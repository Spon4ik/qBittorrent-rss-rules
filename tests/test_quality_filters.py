from __future__ import annotations

from copy import deepcopy

from app.models import AppSettings, QualityProfile
from app.services.quality_filters import (
    AT_LEAST_UHD_PROFILE,
    DEFAULT_QUALITY_PROFILE_RULES,
    LEGACY_DEFAULT_QUALITY_PROFILE_RULES,
    detect_matching_filter_profile_key,
)
from app.services.settings_service import SettingsService


def test_default_resolution_profiles_do_not_exclude_sources() -> None:
    assert DEFAULT_QUALITY_PROFILE_RULES[QualityProfile.HD_1080P.value]["exclude_tokens"] == [
        "480p",
        "360p",
        "sd",
    ]
    assert DEFAULT_QUALITY_PROFILE_RULES[QualityProfile.UHD_2160P_HDR.value]["exclude_tokens"] == [
        "1080p",
        "720p",
        "480p",
        "360p",
        "sd",
    ]
    assert AT_LEAST_UHD_PROFILE["exclude_tokens"] == ["1080p", "720p", "480p", "360p", "sd"]


def test_detect_matching_filter_profile_key_ignores_checkbox_order() -> None:
    assert (
        detect_matching_filter_profile_key(
            ["hd", "720p", "full_hd", "1080p", "ultra_hd", "uhd", "2160p", "4k"],
            ["sd", "360p", "480p"],
            settings=None,
        )
        == "builtin-at-least-hd"
    )


def test_get_or_create_migrates_legacy_default_quality_profile_rules(db_session) -> None:
    settings = AppSettings(
        id="default",
        quality_profile_rules=deepcopy(LEGACY_DEFAULT_QUALITY_PROFILE_RULES),
        saved_quality_profiles={},
        default_quality_profile=QualityProfile.UHD_2160P_HDR,
    )
    db_session.add(settings)
    db_session.commit()

    resolved = SettingsService.get_or_create(db_session)

    assert resolved.quality_profile_rules[QualityProfile.HD_1080P.value]["exclude_tokens"] == [
        "480p",
        "360p",
        "sd",
    ]
    assert resolved.quality_profile_rules[QualityProfile.UHD_2160P_HDR.value]["exclude_tokens"] == [
        "1080p",
        "720p",
        "480p",
        "360p",
        "sd",
    ]


def test_get_or_create_keeps_customized_quality_profile_rules(db_session) -> None:
    customized_rules = deepcopy(LEGACY_DEFAULT_QUALITY_PROFILE_RULES)
    customized_rules[QualityProfile.HD_1080P.value]["exclude_tokens"] = ["480p", "360p", "sd", "bluray"]

    settings = AppSettings(
        id="default",
        quality_profile_rules=customized_rules,
        saved_quality_profiles={},
        default_quality_profile=QualityProfile.UHD_2160P_HDR,
    )
    db_session.add(settings)
    db_session.commit()

    resolved = SettingsService.get_or_create(db_session)

    assert resolved.quality_profile_rules[QualityProfile.HD_1080P.value]["exclude_tokens"] == [
        "480p",
        "360p",
        "sd",
        "bluray",
    ]
