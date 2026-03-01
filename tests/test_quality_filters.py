from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
import json

import pytest

from app.models import AppSettings, QualityProfile
from app.services import quality_filters
from app.services.quality_filters import (
    AT_LEAST_UHD_PROFILE,
    DEFAULT_QUALITY_PROFILE_RULES,
    LEGACY_DEFAULT_QUALITY_PROFILE_RULES,
    _clear_quality_taxonomy_cache,
    detect_matching_filter_profile_key,
    normalize_quality_tokens,
    quality_option_choices,
    quality_option_groups,
    tokens_to_regex,
)
from app.services.settings_service import SettingsService

DEFAULT_QUALITY_TAXONOMY_PATH = quality_filters.QUALITY_TAXONOMY_PATH


@pytest.fixture(autouse=True)
def clear_quality_taxonomy_cache() -> Iterator[None]:
    _clear_quality_taxonomy_cache()
    yield
    _clear_quality_taxonomy_cache()


def _read_default_quality_taxonomy() -> dict[str, object]:
    return json.loads(DEFAULT_QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8"))


def _write_quality_taxonomy(tmp_path, payload: dict[str, object]):
    path = tmp_path / "quality_taxonomy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def test_quality_option_choices_preserve_current_order_and_groups() -> None:
    choices = quality_option_choices()

    assert [item["value"] for item in choices[:5]] == ["sd", "360p", "480p", "hd", "720p"]
    assert [item["value"] for item in choices[-4:]] == ["tv_sync", "dvd", "ts", "cam"]
    assert [item["key"] for item in quality_option_groups()] == [
        "resolution",
        "definition",
        "source",
    ]


def test_normalize_quality_tokens_filters_invalid_and_duplicate_values() -> None:
    assert normalize_quality_tokens(["2160p", "unknown", "hdr", "2160p", "", "hdr"]) == [
        "2160p",
        "hdr",
    ]


def test_tokens_to_regex_preserves_current_patterns() -> None:
    assert tokens_to_regex(["2160p", "hdr"]) == r"(?:2160p|hdr10\+?|hdr)"
    assert tokens_to_regex(["tv_sync", "ts"]) == (
        r"(?:tv[\s._-]*sync|tele[\s._-]*sync|telesync|(?:hd)?ts)"
    )


def test_quality_taxonomy_rejects_unsupported_version(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    payload["version"] = 2
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="version must be 1"):
        quality_option_choices()


def test_quality_taxonomy_rejects_duplicate_option_values(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    options = payload["options"]
    assert isinstance(options, list)
    options.append(
        {
            "value": "sd",
            "label": "Duplicate SD",
            "pattern": "duplicate",
            "group": "resolution",
        }
    )
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="duplicate option value 'sd'"):
        quality_option_choices()


def test_quality_taxonomy_rejects_unknown_group_reference(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    options = payload["options"]
    assert isinstance(options, list)
    options[0]["group"] = "missing-group"
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="unknown group 'missing-group'"):
        quality_option_choices()


def test_quality_taxonomy_cache_uses_cached_data_until_cleared(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    taxonomy_path = _write_quality_taxonomy(tmp_path, payload)
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_PATH", taxonomy_path)

    assert quality_option_choices()[0]["label"] == "SD"

    options = payload["options"]
    assert isinstance(options, list)
    options[0]["label"] = "SD Modified"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")

    assert quality_option_choices()[0]["label"] == "SD"

    _clear_quality_taxonomy_cache()

    assert quality_option_choices()[0]["label"] == "SD Modified"


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
