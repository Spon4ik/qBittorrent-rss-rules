from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from app.models import AppSettings, QualityProfile

QUALITY_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "quality_taxonomy.json"


def _quality_taxonomy_error(problem: str) -> RuntimeError:
    return RuntimeError(f"Invalid quality taxonomy at {QUALITY_TAXONOMY_PATH}: {problem}")


@lru_cache(maxsize=1)
def _load_quality_taxonomy() -> dict[str, tuple[dict[str, str], ...]]:
    try:
        raw_payload = QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to load quality taxonomy from {QUALITY_TAXONOMY_PATH}: {exc}"
        ) from exc

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid quality taxonomy at {QUALITY_TAXONOMY_PATH}: JSON decode error at line "
            f"{exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise _quality_taxonomy_error("top-level JSON value must be an object")
    if payload.get("version") != 1:
        raise _quality_taxonomy_error("version must be 1")

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise _quality_taxonomy_error("groups must be a list")

    groups: list[dict[str, str]] = []
    seen_group_keys: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise _quality_taxonomy_error(f"groups[{index}] must be an object")
        key = str(raw_group.get("key", "")).strip()
        label = str(raw_group.get("label", "")).strip()
        if not key:
            raise _quality_taxonomy_error(f"groups[{index}].key must be a non-empty string")
        if not label:
            raise _quality_taxonomy_error(f"groups[{index}].label must be a non-empty string")
        if key in seen_group_keys:
            raise _quality_taxonomy_error(f"duplicate group key '{key}'")
        seen_group_keys.add(key)
        groups.append({"key": key, "label": label})

    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        raise _quality_taxonomy_error("options must be a list")

    options: list[dict[str, str]] = []
    seen_option_values: set[str] = set()
    for index, raw_option in enumerate(raw_options):
        if not isinstance(raw_option, dict):
            raise _quality_taxonomy_error(f"options[{index}] must be an object")
        value = str(raw_option.get("value", "")).strip()
        label = str(raw_option.get("label", "")).strip()
        pattern = str(raw_option.get("pattern", "")).strip()
        group = str(raw_option.get("group", "")).strip()
        if not value:
            raise _quality_taxonomy_error(f"options[{index}].value must be a non-empty string")
        if not label:
            raise _quality_taxonomy_error(f"options[{index}].label must be a non-empty string")
        if not pattern:
            raise _quality_taxonomy_error(f"options[{index}].pattern must be a non-empty string")
        if not group:
            raise _quality_taxonomy_error(f"options[{index}].group must be a non-empty string")
        if value in seen_option_values:
            raise _quality_taxonomy_error(f"duplicate option value '{value}'")
        if group not in seen_group_keys:
            raise _quality_taxonomy_error(
                f"options[{index}].group references unknown group '{group}'"
            )
        seen_option_values.add(value)
        options.append(
            {
                "value": value,
                "label": label,
                "pattern": pattern,
                "group": group,
            }
        )

    return {
        "groups": tuple(groups),
        "options": tuple(options),
    }


@lru_cache(maxsize=1)
def _quality_group_labels() -> dict[str, str]:
    groups = _load_quality_taxonomy()["groups"]
    return {item["key"]: item["label"] for item in groups}


@lru_cache(maxsize=1)
def _quality_options() -> tuple[dict[str, str], ...]:
    return _load_quality_taxonomy()["options"]


@lru_cache(maxsize=1)
def _quality_option_patterns() -> dict[str, str]:
    return {item["value"]: item["pattern"] for item in _quality_options()}


@lru_cache(maxsize=1)
def _quality_option_order() -> dict[str, int]:
    return {item["value"]: index for index, item in enumerate(_quality_options())}


def _clear_quality_taxonomy_cache() -> None:
    _quality_option_order.cache_clear()
    _quality_option_patterns.cache_clear()
    _quality_options.cache_clear()
    _quality_group_labels.cache_clear()
    _load_quality_taxonomy.cache_clear()


QUALITY_PROFILE_LABELS: dict[str, str] = {
    QualityProfile.PLAIN.value: "No preset",
    QualityProfile.HD_1080P.value: "At Least HD",
    QualityProfile.UHD_2160P_HDR.value: "Ultra HD HDR",
    QualityProfile.CUSTOM.value: "Custom (manual tags)",
}

BUILTIN_AT_LEAST_UHD_PROFILE_KEY = "builtin-at-least-uhd"
BUILTIN_AT_LEAST_UHD_PROFILE_LABEL = "At Least UHD"

LEGACY_DEFAULT_QUALITY_PROFILE_RULES: dict[str, dict[str, list[str]]] = {
    QualityProfile.PLAIN.value: {"include_tokens": [], "exclude_tokens": []},
    QualityProfile.HD_1080P.value: {
        "include_tokens": ["hd", "720p", "full_hd", "1080p", "ultra_hd", "uhd", "2160p", "4k"],
        "exclude_tokens": ["480p", "360p", "sd", "bdremux", "remux", "bluray", "tv_sync", "dvd", "ts", "cam"],
    },
    QualityProfile.UHD_2160P_HDR.value: {
        "include_tokens": ["ultra_hd", "uhd", "4k", "2160p", "hdr", "dolby_vision"],
        "exclude_tokens": ["1080p", "720p", "480p", "360p", "sd", "bdremux", "remux", "bluray", "tv_sync", "dvd", "ts", "cam"],
    },
    QualityProfile.CUSTOM.value: {"include_tokens": [], "exclude_tokens": []},
}

DEFAULT_QUALITY_PROFILE_RULES: dict[str, dict[str, list[str]]] = {
    QualityProfile.PLAIN.value: {"include_tokens": [], "exclude_tokens": []},
    QualityProfile.HD_1080P.value: {
        "include_tokens": ["hd", "720p", "full_hd", "1080p", "ultra_hd", "uhd", "2160p", "4k"],
        "exclude_tokens": ["480p", "360p", "sd"],
    },
    QualityProfile.UHD_2160P_HDR.value: {
        "include_tokens": ["ultra_hd", "uhd", "4k", "2160p", "hdr", "dolby_vision"],
        "exclude_tokens": ["1080p", "720p", "480p", "360p", "sd"],
    },
    QualityProfile.CUSTOM.value: {"include_tokens": [], "exclude_tokens": []},
}

AT_LEAST_UHD_PROFILE: dict[str, object] = {
    "label": BUILTIN_AT_LEAST_UHD_PROFILE_LABEL,
    "include_tokens": ["ultra_hd", "uhd", "2160p", "4k"],
    "exclude_tokens": ["1080p", "720p", "480p", "360p", "sd"],
    "quality_profile_value": QualityProfile.CUSTOM.value,
    "built_in": True,
}

PROFILE_KEY_RE = re.compile(r"[^a-z0-9]+")


def quality_option_choices() -> list[dict[str, str]]:
    return [
        {
            "value": item["value"],
            "label": item["label"],
            "pattern": item["pattern"],
            "group": item["group"],
        }
        for item in _quality_options()
    ]


def quality_option_groups() -> list[dict[str, object]]:
    group_labels = _quality_group_labels()
    grouped: dict[str, list[dict[str, str]]] = {key: [] for key in group_labels}
    for item in quality_option_choices():
        grouped[item["group"]].append(item)
    return [
        {"key": key, "label": group_labels[key], "options": grouped[key]}
        for key in group_labels
    ]


def quality_profile_choices() -> list[dict[str, str]]:
    return [{"value": item.value, "label": QUALITY_PROFILE_LABELS[item.value]} for item in QualityProfile]


def normalize_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    tokens = raw_tokens or []
    valid_patterns = _quality_option_patterns()
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_token in tokens:
        token = str(raw_token).strip()
        if not token or token not in valid_patterns or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def canonicalize_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    option_order = _quality_option_order()
    return sorted(
        normalize_quality_tokens(raw_tokens),
        key=lambda token: option_order.get(token, len(option_order)),
    )


def tokens_to_regex(tokens: list[str] | tuple[str, ...] | None) -> str:
    option_patterns = _quality_option_patterns()
    ordered_patterns: list[str] = []
    seen_patterns: set[str] = set()
    for token in normalize_quality_tokens(tokens):
        pattern = option_patterns[token]
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        ordered_patterns.append(pattern)
    if not ordered_patterns:
        return ""
    return f"(?:{'|'.join(ordered_patterns)})"


def normalize_profile_rules(raw_value: Any) -> dict[str, dict[str, list[str]]]:
    normalized = deepcopy(DEFAULT_QUALITY_PROFILE_RULES)
    if not isinstance(raw_value, dict):
        return normalized

    for profile in (QualityProfile.HD_1080P.value, QualityProfile.UHD_2160P_HDR.value):
        candidate = raw_value.get(profile)
        if not isinstance(candidate, dict):
            continue
        include_tokens = normalize_quality_tokens(candidate.get("include_tokens"))
        include_set = set(include_tokens)
        exclude_tokens = [
            token
            for token in normalize_quality_tokens(candidate.get("exclude_tokens"))
            if token not in include_set
        ]
        normalized[profile] = {
            "include_tokens": include_tokens,
            "exclude_tokens": exclude_tokens,
        }
    return normalized


def resolve_quality_profile_rules(settings: AppSettings | None) -> dict[str, dict[str, list[str]]]:
    if settings is None:
        return deepcopy(DEFAULT_QUALITY_PROFILE_RULES)
    return normalize_profile_rules(settings.quality_profile_rules)


def normalize_saved_quality_profiles(raw_value: Any) -> dict[str, dict[str, object]]:
    if not isinstance(raw_value, dict):
        return {}

    normalized: dict[str, dict[str, object]] = {}
    for raw_key, raw_profile in raw_value.items():
        key = str(raw_key).strip()
        if not key or not isinstance(raw_profile, dict):
            continue
        label = str(raw_profile.get("label", "")).strip()
        if not label:
            continue
        include_tokens = normalize_quality_tokens(raw_profile.get("include_tokens"))
        include_set = set(include_tokens)
        exclude_tokens = [
            token
            for token in normalize_quality_tokens(raw_profile.get("exclude_tokens"))
            if token not in include_set
        ]
        normalized[key] = {
            "label": label,
            "include_tokens": include_tokens,
            "exclude_tokens": exclude_tokens,
            "quality_profile_value": QualityProfile.CUSTOM.value,
            "built_in": False,
        }
    return normalized


def slugify_profile_key(value: str) -> str:
    cleaned = PROFILE_KEY_RE.sub("-", value.strip().casefold()).strip("-")
    return cleaned


def build_available_filter_profiles(settings: AppSettings | None) -> dict[str, dict[str, object]]:
    profile_rules = resolve_quality_profile_rules(settings)
    saved_profiles = normalize_saved_quality_profiles(settings.saved_quality_profiles if settings else {})
    at_least_uhd_override = saved_profiles.pop(BUILTIN_AT_LEAST_UHD_PROFILE_KEY, None)
    at_least_uhd_profile = deepcopy(AT_LEAST_UHD_PROFILE)
    if at_least_uhd_override:
        at_least_uhd_profile["include_tokens"] = list(at_least_uhd_override.get("include_tokens", []))
        at_least_uhd_profile["exclude_tokens"] = list(at_least_uhd_override.get("exclude_tokens", []))
    available = {
        "builtin-ultra-hd-hdr": {
            "label": "Ultra HD HDR",
            "include_tokens": list(profile_rules[QualityProfile.UHD_2160P_HDR.value]["include_tokens"]),
            "exclude_tokens": list(profile_rules[QualityProfile.UHD_2160P_HDR.value]["exclude_tokens"]),
            "quality_profile_value": QualityProfile.UHD_2160P_HDR.value,
            "built_in": True,
        },
        "builtin-at-least-hd": {
            "label": "At Least HD",
            "include_tokens": list(profile_rules[QualityProfile.HD_1080P.value]["include_tokens"]),
            "exclude_tokens": list(profile_rules[QualityProfile.HD_1080P.value]["exclude_tokens"]),
            "quality_profile_value": QualityProfile.HD_1080P.value,
            "built_in": True,
        },
        BUILTIN_AT_LEAST_UHD_PROFILE_KEY: at_least_uhd_profile,
    }
    available.update(saved_profiles)
    return available


def available_filter_profile_choices(settings: AppSettings | None) -> list[dict[str, object]]:
    profiles = build_available_filter_profiles(settings)
    ordered_keys = ["builtin-ultra-hd-hdr", "builtin-at-least-hd", BUILTIN_AT_LEAST_UHD_PROFILE_KEY]
    custom_keys = sorted(
        (key for key, profile in profiles.items() if not bool(profile.get("built_in"))),
        key=lambda key: str(profiles[key]["label"]).casefold(),
    )
    return [
        {"key": key, **profiles[key]}
        for key in [*ordered_keys, *custom_keys]
        if key in profiles
    ]


def detect_matching_filter_profile_key(
    include_tokens: list[str] | tuple[str, ...] | None,
    exclude_tokens: list[str] | tuple[str, ...] | None,
    settings: AppSettings | None,
) -> str:
    normalized_include = canonicalize_quality_tokens(include_tokens)
    normalized_exclude = canonicalize_quality_tokens(exclude_tokens)
    for item in available_filter_profile_choices(settings):
        if (
            normalized_include == canonicalize_quality_tokens(item.get("include_tokens"))
            and normalized_exclude == canonicalize_quality_tokens(item.get("exclude_tokens"))
        ):
            return str(item["key"])
    return ""
