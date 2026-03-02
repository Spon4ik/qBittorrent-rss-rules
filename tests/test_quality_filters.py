from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
import json

import pytest

from app.models import AppSettings, QualityProfile, Rule
from app.services import quality_filters
from app.services.quality_filters import (
    AT_LEAST_UHD_PROFILE,
    DEFAULT_QUALITY_PROFILE_RULES,
    LEGACY_DEFAULT_QUALITY_PROFILE_RULES,
    _clear_quality_taxonomy_cache,
    apply_quality_taxonomy_update,
    available_filter_profile_choices,
    detect_matching_filter_profile_key,
    expand_quality_tokens,
    normalize_quality_tokens,
    preview_quality_taxonomy_update,
    quality_bundle_choices,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    recent_quality_taxonomy_audit_entries,
    resolve_quality_token,
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


def test_quality_bundle_choices_preserve_schema_order() -> None:
    assert [item["key"] for item in quality_bundle_choices()] == [
        "at_least_hd",
        "at_least_uhd",
        "ultra_hd_hdr",
    ]


def test_normalize_quality_tokens_filters_invalid_and_duplicate_values() -> None:
    assert normalize_quality_tokens(["2160p", "unknown", "hdr", "2160p", "", "hdr"]) == [
        "2160p",
        "hdr",
    ]


def test_expand_quality_tokens_resolves_bundles_and_aliases_to_leaf_tokens() -> None:
    assert expand_quality_tokens(["at_least_uhd", "x265", "dv", "hdr10_plus", "4k"]) == [
        "ultra_hd",
        "uhd",
        "2160p",
        "4k",
        "hevc",
        "dolby_vision",
        "hdr",
    ]
    assert resolve_quality_token("webrip") == ["web_rip"]


def test_tokens_to_regex_preserves_current_patterns() -> None:
    assert tokens_to_regex(["2160p", "hdr"]) == r"(?:2160p|hdr10\+?|hdr)"
    assert tokens_to_regex(["tv_sync", "ts"]) == (
        r"(?:tv[\s._-]*sync|tele[\s._-]*sync|telesync|(?:hd)?ts)"
    )


def test_quality_taxonomy_rejects_unsupported_version(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    payload["version"] = 99
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="version must be 1 or 2"):
        quality_option_choices()


def test_quality_taxonomy_supports_version_1_payloads(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    payload["version"] = 1
    payload.pop("bundles", None)
    payload.pop("aliases", None)
    payload.pop("ranks", None)
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    assert quality_option_choices()[0]["value"] == "sd"
    assert quality_bundle_choices() == []


def test_quality_taxonomy_rejects_bundle_with_unknown_option(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["tokens"].append("missing-option")
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="unknown option 'missing-option'"):
        quality_bundle_choices()


def test_quality_taxonomy_rejects_alias_with_unknown_canonical_option(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    aliases = payload["aliases"]
    assert isinstance(aliases, list)
    aliases[0]["canonical"] = "missing-option"
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="unknown option 'missing-option'"):
        normalize_quality_tokens(["hdr10_plus"])


def test_quality_taxonomy_rejects_rank_with_unknown_option(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    ranks = payload["ranks"]
    assert isinstance(ranks, list)
    ranks[0]["tokens"].append("missing-option")
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    with pytest.raises(RuntimeError, match="unknown option 'missing-option'"):
        quality_option_choices()


def test_preview_quality_taxonomy_update_flags_orphaned_rule_tokens() -> None:
    payload = _read_default_quality_taxonomy()
    options = payload["options"]
    aliases = payload["aliases"]
    assert isinstance(options, list)
    assert isinstance(aliases, list)
    payload["options"] = [item for item in options if item["value"] != "hevc"]
    payload["aliases"] = [item for item in aliases if item["canonical"] != "hevc"]

    rule = Rule(
        rule_name="Rule Alpha",
        content_name="Rule Alpha",
        normalized_title="Rule Alpha",
    )
    rule.quality_include_tokens = ["hevc"]
    rule.quality_exclude_tokens = []

    preview = preview_quality_taxonomy_update(
        json.dumps(payload),
        settings=None,
        rules=[rule],
    )

    assert preview["safe_to_apply"] is False
    assert preview["removed_tokens"] == ["hevc"]
    assert preview["blocking_references"] == [
        {
            "kind": "rule",
            "label": "Rule Alpha",
            "missing_tokens": ["hevc"],
        }
    ]
    assert preview["existing_invalid_references"] == []


def test_preview_quality_taxonomy_update_allows_label_changes_when_invalid_tokens_already_exist() -> None:
    payload = _read_default_quality_taxonomy()
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"

    rule = Rule(
        rule_name="Rule Beta",
        content_name="Rule Beta",
        normalized_title="Rule Beta",
    )
    rule.quality_include_tokens = ["legacy_missing"]
    rule.quality_exclude_tokens = []

    preview = preview_quality_taxonomy_update(
        json.dumps(payload),
        settings=None,
        rules=[rule],
    )

    assert preview["safe_to_apply"] is True
    assert preview["removed_tokens"] == []
    assert preview["blocking_references"] == []
    assert preview["existing_invalid_references"] == [
        {
            "kind": "rule",
            "label": "Rule Beta",
            "missing_tokens": ["legacy_missing"],
        }
    ]


def test_quality_profile_labels_follow_matching_taxonomy_bundle_labels(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"
    bundles[1]["label"] = "At Least Ultra HD"
    bundles[2]["label"] = "Ultra HD + HDR"
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        _write_quality_taxonomy(tmp_path, payload),
    )

    quality_choices = {item["value"]: item["label"] for item in quality_profile_choices()}
    filter_profiles = {item["key"]: item["label"] for item in available_filter_profile_choices(None)}

    assert quality_choices["1080p"] == "At Least Full HD"
    assert quality_choices["2160p_hdr"] == "Ultra HD + HDR"
    assert filter_profiles["builtin-at-least-hd"] == "At Least Full HD"
    assert filter_profiles["builtin-at-least-uhd"] == "At Least Ultra HD"
    assert filter_profiles["builtin-ultra-hd-hdr"] == "Ultra HD + HDR"


def test_apply_quality_taxonomy_update_writes_file_and_audit_entry(tmp_path, monkeypatch) -> None:
    payload = _read_default_quality_taxonomy()
    aliases = payload["aliases"]
    assert isinstance(aliases, list)
    aliases.append(
        {
            "alias": "web_rip_alt",
            "label": "Web Rip Alt",
            "canonical": "web_rip",
        }
    )
    taxonomy_path = _write_quality_taxonomy(tmp_path, _read_default_quality_taxonomy())
    audit_path = tmp_path / "taxonomy_audit.jsonl"
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_PATH", taxonomy_path)
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_AUDIT_PATH", audit_path)
    _clear_quality_taxonomy_cache()

    audit_error = apply_quality_taxonomy_update(
        json.dumps(payload),
        change_note="service test",
    )

    assert audit_error is None
    assert json.loads(taxonomy_path.read_text(encoding="utf-8"))["aliases"][-1]["alias"] == "web_rip_alt"
    assert recent_quality_taxonomy_audit_entries(limit=1)[0]["note"] == "service test"


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
