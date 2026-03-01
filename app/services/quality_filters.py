from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.models import AppSettings, QualityProfile

QUALITY_GROUP_LABELS: dict[str, str] = {
    "resolution": "Resolution",
    "definition": "Video Definition",
    "source": "Source",
}

QUALITY_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "sd", "label": "SD", "pattern": r"sd", "group": "resolution"},
    {"value": "360p", "label": "360p", "pattern": r"360p", "group": "resolution"},
    {"value": "480p", "label": "480p", "pattern": r"480p", "group": "resolution"},
    {"value": "hd", "label": "HD", "pattern": r"hd", "group": "resolution"},
    {"value": "720p", "label": "720p", "pattern": r"720p", "group": "resolution"},
    {"value": "full_hd", "label": "Full HD", "pattern": r"full[\s._-]*hd", "group": "resolution"},
    {"value": "1080p", "label": "1080p", "pattern": r"1080p", "group": "resolution"},
    {"value": "ultra_hd", "label": "Ultra HD", "pattern": r"ultra[\s._-]*hd", "group": "resolution"},
    {"value": "uhd", "label": "UHD", "pattern": r"uhd", "group": "resolution"},
    {"value": "2160p", "label": "2160p", "pattern": r"2160p", "group": "resolution"},
    {"value": "4k", "label": "4K", "pattern": r"4k", "group": "resolution"},
    {"value": "hdr", "label": "HDR", "pattern": r"hdr10\+?|hdr", "group": "definition"},
    {"value": "dolby_vision", "label": "Dolby Vision", "pattern": r"dolby[\s._-]*vision|dv", "group": "definition"},
    {"value": "hevc", "label": "HEVC", "pattern": r"hevc|x265|h265", "group": "definition"},
    {"value": "av1", "label": "AV1", "pattern": r"av1", "group": "definition"},
    {"value": "bdremux", "label": "bdremux", "pattern": r"bdremux", "group": "source"},
    {"value": "bluray", "label": "BluRay", "pattern": r"blu[\s._-]*ray|bluray|b[dr]rip", "group": "source"},
    {"value": "web_dl", "label": "WEB-DL", "pattern": r"web[\s._-]*dl", "group": "source"},
    {"value": "web_rip", "label": "WEBRip", "pattern": r"web[\s._-]*rip", "group": "source"},
    {"value": "tv_sync", "label": "TV Sync", "pattern": r"tv[\s._-]*sync|tele[\s._-]*sync|telesync", "group": "source"},
    {"value": "dvd", "label": "DVD", "pattern": r"dvd(?:rip|scr)?|dvd[\s._-]*rip", "group": "source"},
    {"value": "ts", "label": "TS", "pattern": r"(?:hd)?ts", "group": "source"},
    {"value": "cam", "label": "CAM", "pattern": r"cam", "group": "source"},
)

QUALITY_OPTION_PATTERNS: dict[str, str] = {item["value"]: item["pattern"] for item in QUALITY_OPTIONS}
QUALITY_OPTION_ORDER: dict[str, int] = {
    item["value"]: index for index, item in enumerate(QUALITY_OPTIONS)
}

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
        for item in QUALITY_OPTIONS
    ]


def quality_option_groups() -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = {key: [] for key in QUALITY_GROUP_LABELS}
    for item in quality_option_choices():
        grouped[item["group"]].append(item)
    return [
        {"key": key, "label": QUALITY_GROUP_LABELS[key], "options": grouped[key]}
        for key in QUALITY_GROUP_LABELS
    ]


def quality_profile_choices() -> list[dict[str, str]]:
    return [{"value": item.value, "label": QUALITY_PROFILE_LABELS[item.value]} for item in QualityProfile]


def normalize_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    tokens = raw_tokens or []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_token in tokens:
        token = str(raw_token).strip()
        if not token or token not in QUALITY_OPTION_PATTERNS or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def canonicalize_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    return sorted(
        normalize_quality_tokens(raw_tokens),
        key=lambda token: QUALITY_OPTION_ORDER.get(token, len(QUALITY_OPTION_ORDER)),
    )


def tokens_to_regex(tokens: list[str] | tuple[str, ...] | None) -> str:
    ordered_patterns: list[str] = []
    seen_patterns: set[str] = set()
    for token in normalize_quality_tokens(tokens):
        pattern = QUALITY_OPTION_PATTERNS[token]
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
