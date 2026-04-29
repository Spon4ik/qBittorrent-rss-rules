from __future__ import annotations

import json
import re
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from app.models import AppSettings, MediaType, QualityProfile, Rule

QUALITY_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "quality_taxonomy.json"
QUALITY_TAXONOMY_AUDIT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "taxonomy_audit.jsonl"
)


def _quality_taxonomy_source(source: Path | str | None = None) -> str:
    if source is None:
        return str(QUALITY_TAXONOMY_PATH)
    return str(source)


def _quality_taxonomy_error(problem: str, *, source: Path | str | None = None) -> RuntimeError:
    return RuntimeError(
        f"Invalid quality taxonomy at {_quality_taxonomy_source(source)}: {problem}"
    )


def _parse_quality_taxonomy_json(
    raw_payload: str,
    *,
    source: Path | str | None = None,
) -> dict[str, Any]:
    source_label = _quality_taxonomy_source(source)
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid quality taxonomy at {source_label}: JSON decode error at line "
            f"{exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise _quality_taxonomy_error("top-level JSON value must be an object", source=source)
    return payload


SCOPED_MEDIA_TYPE_ORDER: tuple[str, ...] = (
    MediaType.SERIES.value,
    MediaType.MOVIE.value,
    MediaType.AUDIOBOOK.value,
    MediaType.MUSIC.value,
)
VIDEO_MEDIA_TYPES = {MediaType.SERIES.value, MediaType.MOVIE.value}
AUDIO_MEDIA_TYPES = {MediaType.AUDIOBOOK.value, MediaType.MUSIC.value}
QUALITY_TOKEN_PREFIX_BOUNDARY = r"(?:^|[^A-Za-z0-9])"
QUALITY_TOKEN_SUFFIX_BOUNDARY = r"(?![A-Za-z0-9])"


def _normalize_media_type_scope(
    raw_value: Any,
    *,
    field_name: str,
    source: Path | str | None = None,
    required: bool = False,
) -> tuple[str, ...] | None:
    if raw_value is None:
        if required:
            raise _quality_taxonomy_error(f"{field_name} must be a list", source=source)
        return None
    if not isinstance(raw_value, list):
        raise _quality_taxonomy_error(f"{field_name} must be a list", source=source)

    cleaned: list[str] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_value):
        value = str(raw_item).strip()
        if not value:
            raise _quality_taxonomy_error(
                f"{field_name}[{index}] must be a non-empty string",
                source=source,
            )
        if value not in SCOPED_MEDIA_TYPE_ORDER:
            raise _quality_taxonomy_error(
                f"{field_name}[{index}] must be one of {', '.join(SCOPED_MEDIA_TYPE_ORDER)}",
                source=source,
            )
        if value in seen:
            raise _quality_taxonomy_error(
                f"{field_name}[{index}] duplicates '{value}'",
                source=source,
            )
        seen.add(value)
        cleaned.append(value)

    if not cleaned:
        raise _quality_taxonomy_error(
            f"{field_name} must contain at least one media type",
            source=source,
        )
    return tuple(cleaned)


def _validate_quality_taxonomy_payload(
    payload: dict[str, Any],
    *,
    source: Path | str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _quality_taxonomy_error("top-level JSON value must be an object", source=source)

    version = payload.get("version")
    if version not in (1, 2, 3):
        raise _quality_taxonomy_error("version must be 1, 2, or 3", source=source)

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise _quality_taxonomy_error("groups must be a list", source=source)

    groups: list[dict[str, object]] = []
    seen_group_keys: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise _quality_taxonomy_error(f"groups[{index}] must be an object", source=source)
        key = str(raw_group.get("key", "")).strip()
        label = str(raw_group.get("label", "")).strip()
        if not key:
            raise _quality_taxonomy_error(
                f"groups[{index}].key must be a non-empty string",
                source=source,
            )
        if not label:
            raise _quality_taxonomy_error(
                f"groups[{index}].label must be a non-empty string",
                source=source,
            )
        if key in seen_group_keys:
            raise _quality_taxonomy_error(f"duplicate group key '{key}'", source=source)
        seen_group_keys.add(key)
        group: dict[str, object] = {"key": key, "label": label}
        media_types = _normalize_media_type_scope(
            raw_group.get("media_types"),
            field_name=f"groups[{index}].media_types",
            source=source,
        )
        if media_types is not None:
            group["media_types"] = media_types
        groups.append(group)

    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        raise _quality_taxonomy_error("options must be a list", source=source)

    options: list[dict[str, object]] = []
    seen_option_values: set[str] = set()
    for index, raw_option in enumerate(raw_options):
        if not isinstance(raw_option, dict):
            raise _quality_taxonomy_error(f"options[{index}] must be an object", source=source)
        value = str(raw_option.get("value", "")).strip()
        label = str(raw_option.get("label", "")).strip()
        pattern = str(raw_option.get("pattern", "")).strip()
        group_key = str(raw_option.get("group", "")).strip()
        if not value:
            raise _quality_taxonomy_error(
                f"options[{index}].value must be a non-empty string",
                source=source,
            )
        if not label:
            raise _quality_taxonomy_error(
                f"options[{index}].label must be a non-empty string",
                source=source,
            )
        if not pattern:
            raise _quality_taxonomy_error(
                f"options[{index}].pattern must be a non-empty string",
                source=source,
            )
        if not group_key:
            raise _quality_taxonomy_error(
                f"options[{index}].group must be a non-empty string",
                source=source,
            )
        if value in seen_option_values:
            raise _quality_taxonomy_error(f"duplicate option value '{value}'", source=source)
        if group_key not in seen_group_keys:
            raise _quality_taxonomy_error(
                f"options[{index}].group references unknown group '{group_key}'",
                source=source,
            )
        seen_option_values.add(value)
        option: dict[str, object] = {
            "value": value,
            "label": label,
            "pattern": pattern,
            "group": group_key,
        }
        media_types = _normalize_media_type_scope(
            raw_option.get("media_types"),
            field_name=f"options[{index}].media_types",
            source=source,
        )
        if media_types is not None:
            option["media_types"] = media_types
        options.append(option)

    bundles: list[dict[str, object]] = []
    seen_bundle_keys: set[str] = set()
    raw_bundles = payload.get("bundles", [])
    if version in (2, 3):
        if not isinstance(raw_bundles, list):
            raise _quality_taxonomy_error("bundles must be a list", source=source)
        for index, raw_bundle in enumerate(raw_bundles):
            if not isinstance(raw_bundle, dict):
                raise _quality_taxonomy_error(f"bundles[{index}] must be an object", source=source)
            key = str(raw_bundle.get("key", "")).strip()
            label = str(raw_bundle.get("label", "")).strip()
            raw_bundle_tokens = raw_bundle.get("tokens")
            if not key:
                raise _quality_taxonomy_error(
                    f"bundles[{index}].key must be a non-empty string",
                    source=source,
                )
            if not label:
                raise _quality_taxonomy_error(
                    f"bundles[{index}].label must be a non-empty string",
                    source=source,
                )
            if key in seen_bundle_keys:
                raise _quality_taxonomy_error(f"duplicate bundle key '{key}'", source=source)
            if key in seen_option_values:
                raise _quality_taxonomy_error(
                    f"bundles[{index}].key collides with option value '{key}'",
                    source=source,
                )
            if not isinstance(raw_bundle_tokens, list):
                raise _quality_taxonomy_error(
                    f"bundles[{index}].tokens must be a list",
                    source=source,
                )

            bundle_tokens: list[str] = []
            seen_bundle_tokens: set[str] = set()
            for token_index, raw_token in enumerate(raw_bundle_tokens):
                token = str(raw_token).strip()
                if not token:
                    raise _quality_taxonomy_error(
                        f"bundles[{index}].tokens[{token_index}] must be a non-empty string",
                        source=source,
                    )
                if token not in seen_option_values:
                    raise _quality_taxonomy_error(
                        f"bundles[{index}].tokens[{token_index}] references unknown option '{token}'",
                        source=source,
                    )
                if token in seen_bundle_tokens:
                    raise _quality_taxonomy_error(
                        f"bundles[{index}] contains duplicate token '{token}'",
                        source=source,
                    )
                seen_bundle_tokens.add(token)
                bundle_tokens.append(token)

            seen_bundle_keys.add(key)
            bundles.append({"key": key, "label": label, "tokens": tuple(bundle_tokens)})

    aliases: list[dict[str, str]] = []
    raw_aliases = payload.get("aliases", [])
    if version in (2, 3):
        if not isinstance(raw_aliases, list):
            raise _quality_taxonomy_error("aliases must be a list", source=source)
        seen_alias_keys: set[str] = set()
        for index, raw_alias in enumerate(raw_aliases):
            if not isinstance(raw_alias, dict):
                raise _quality_taxonomy_error(f"aliases[{index}] must be an object", source=source)
            alias = str(raw_alias.get("alias", "")).strip()
            label = str(raw_alias.get("label", "")).strip()
            canonical = str(raw_alias.get("canonical", "")).strip()
            if not alias:
                raise _quality_taxonomy_error(
                    f"aliases[{index}].alias must be a non-empty string",
                    source=source,
                )
            if not canonical:
                raise _quality_taxonomy_error(
                    f"aliases[{index}].canonical must be a non-empty string",
                    source=source,
                )
            if alias in seen_alias_keys:
                raise _quality_taxonomy_error(f"duplicate alias '{alias}'", source=source)
            if alias in seen_option_values:
                raise _quality_taxonomy_error(
                    f"aliases[{index}].alias collides with option value '{alias}'",
                    source=source,
                )
            if alias in seen_bundle_keys:
                raise _quality_taxonomy_error(
                    f"aliases[{index}].alias collides with bundle key '{alias}'",
                    source=source,
                )
            if canonical not in seen_option_values:
                raise _quality_taxonomy_error(
                    f"aliases[{index}].canonical references unknown option '{canonical}'",
                    source=source,
                )

            seen_alias_keys.add(alias)
            alias_entry = {"alias": alias, "canonical": canonical}
            if label:
                alias_entry["label"] = label
            aliases.append(alias_entry)

    ranks: list[dict[str, object]] = []
    raw_ranks = payload.get("ranks", [])
    if version in (2, 3):
        if not isinstance(raw_ranks, list):
            raise _quality_taxonomy_error("ranks must be a list", source=source)
        seen_rank_keys: set[str] = set()
        for index, raw_rank in enumerate(raw_ranks):
            if not isinstance(raw_rank, dict):
                raise _quality_taxonomy_error(f"ranks[{index}] must be an object", source=source)
            key = str(raw_rank.get("key", "")).strip()
            label = str(raw_rank.get("label", "")).strip()
            raw_rank_tokens = raw_rank.get("tokens")
            if not key:
                raise _quality_taxonomy_error(
                    f"ranks[{index}].key must be a non-empty string",
                    source=source,
                )
            if key in seen_rank_keys:
                raise _quality_taxonomy_error(f"duplicate rank key '{key}'", source=source)
            if not isinstance(raw_rank_tokens, list):
                raise _quality_taxonomy_error(
                    f"ranks[{index}].tokens must be a list",
                    source=source,
                )

            rank_tokens: list[str] = []
            seen_rank_tokens: set[str] = set()
            for token_index, raw_token in enumerate(raw_rank_tokens):
                token = str(raw_token).strip()
                if not token:
                    raise _quality_taxonomy_error(
                        f"ranks[{index}].tokens[{token_index}] must be a non-empty string",
                        source=source,
                    )
                if token not in seen_option_values:
                    raise _quality_taxonomy_error(
                        f"ranks[{index}].tokens[{token_index}] references unknown option '{token}'",
                        source=source,
                    )
                if token in seen_rank_tokens:
                    raise _quality_taxonomy_error(
                        f"ranks[{index}] contains duplicate token '{token}'",
                        source=source,
                    )
                seen_rank_tokens.add(token)
                rank_tokens.append(token)

            seen_rank_keys.add(key)
            rank: dict[str, object] = {"key": key, "tokens": tuple(rank_tokens)}
            if label:
                rank["label"] = label
            ranks.append(rank)

    return {
        "version": version,
        "groups": tuple(groups),
        "options": tuple(options),
        "bundles": tuple(bundles),
        "aliases": tuple(aliases),
        "ranks": tuple(ranks),
    }


@lru_cache(maxsize=1)
def _load_quality_taxonomy() -> dict[str, Any]:
    try:
        raw_payload = QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to load quality taxonomy from {QUALITY_TAXONOMY_PATH}: {exc}"
        ) from exc

    payload = _parse_quality_taxonomy_json(raw_payload, source=QUALITY_TAXONOMY_PATH)
    return _validate_quality_taxonomy_payload(payload, source=QUALITY_TAXONOMY_PATH)


@lru_cache(maxsize=1)
def _quality_group_definitions() -> tuple[dict[str, object], ...]:
    groups = _load_quality_taxonomy()["groups"]
    return cast(tuple[dict[str, object], ...], groups)


@lru_cache(maxsize=1)
def _quality_group_labels() -> dict[str, str]:
    groups = _quality_group_definitions()
    return {str(item["key"]): str(item["label"]) for item in groups}


@lru_cache(maxsize=1)
def _quality_options() -> tuple[dict[str, object], ...]:
    options = _load_quality_taxonomy()["options"]
    return cast(tuple[dict[str, object], ...], options)


@lru_cache(maxsize=1)
def _quality_bundle_definitions() -> tuple[dict[str, object], ...]:
    bundles = _load_quality_taxonomy()["bundles"]
    return cast(tuple[dict[str, object], ...], bundles)


@lru_cache(maxsize=1)
def _quality_bundle_labels() -> dict[str, str]:
    return {str(item["key"]): str(item["label"]) for item in _quality_bundle_definitions()}


@lru_cache(maxsize=1)
def _quality_bundle_tokens() -> dict[str, tuple[str, ...]]:
    return {
        str(item["key"]): tuple(str(token) for token in _coerce_token_values(item.get("tokens")))
        for item in _quality_bundle_definitions()
    }


@lru_cache(maxsize=1)
def _quality_alias_map() -> dict[str, str]:
    return {
        str(item["alias"]): str(item["canonical"])
        for item in cast(tuple[dict[str, str], ...], _load_quality_taxonomy()["aliases"])
    }


@lru_cache(maxsize=1)
def _quality_option_patterns() -> dict[str, str]:
    return {str(item["value"]): str(item["pattern"]) for item in _quality_options()}


@lru_cache(maxsize=1)
def _quality_option_media_types() -> dict[str, tuple[str, ...] | None]:
    return {
        str(item["value"]): (
            tuple(
                str(media_type) for media_type in _coerce_media_type_values(item.get("media_types"))
            )
            if _coerce_media_type_values(item.get("media_types"))
            else None
        )
        for item in _quality_options()
    }


@lru_cache(maxsize=1)
def _quality_option_order() -> dict[str, int]:
    return {str(item["value"]): index for index, item in enumerate(_quality_options())}


def _clear_quality_taxonomy_cache() -> None:
    _quality_option_order.cache_clear()
    _quality_option_patterns.cache_clear()
    _quality_option_media_types.cache_clear()
    _quality_alias_map.cache_clear()
    _quality_bundle_tokens.cache_clear()
    _quality_bundle_labels.cache_clear()
    _quality_bundle_definitions.cache_clear()
    _quality_options.cache_clear()
    _quality_group_labels.cache_clear()
    _quality_group_definitions.cache_clear()
    _load_quality_taxonomy.cache_clear()


def read_quality_taxonomy_text() -> str:
    try:
        return QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to load quality taxonomy from {QUALITY_TAXONOMY_PATH}: {exc}"
        ) from exc


def quality_taxonomy_snapshot() -> dict[str, object]:
    taxonomy = _load_quality_taxonomy()
    return {
        "version": taxonomy["version"],
        "groups": [
            {
                "key": item["key"],
                "label": item["label"],
                "media_types": list(item.get("media_types", ())),
            }
            for item in taxonomy["groups"]
        ],
        "options": quality_option_choices(),
        "bundles": quality_bundle_choices(),
        "aliases": [dict(item) for item in taxonomy["aliases"]],
        "ranks": [
            {
                "key": item["key"],
                "label": item.get("label", ""),
                "tokens": list(item["tokens"]),
            }
            for item in taxonomy["ranks"]
        ],
    }


def _quality_taxonomy_summary(taxonomy: dict[str, Any]) -> dict[str, int]:
    return {
        "group_count": len(taxonomy["groups"]),
        "option_count": len(taxonomy["options"]),
        "bundle_count": len(taxonomy["bundles"]),
        "alias_count": len(taxonomy["aliases"]),
        "rank_count": len(taxonomy["ranks"]),
    }


def _dedupe_stored_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    tokens = raw_tokens or []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_token in tokens:
        token = str(raw_token).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _coerce_token_values(raw_value: object | None) -> list[str]:
    if isinstance(raw_value, (list, tuple)):
        return [str(item) for item in raw_value]
    return []


def _coerce_media_type_values(raw_value: object | None) -> list[str]:
    if isinstance(raw_value, (list, tuple)):
        return [str(item) for item in raw_value]
    return []


def _quality_taxonomy_references(
    settings: AppSettings | None,
    rules: Sequence[Rule] | None,
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for profile in available_filter_profile_choices(settings):
        tokens = _dedupe_stored_tokens(
            _coerce_token_values(profile.get("include_tokens"))
            + _coerce_token_values(profile.get("exclude_tokens"))
        )
        if not tokens:
            continue
        references.append(
            {
                "kind": "filter_profile",
                "label": str(profile.get("label", profile.get("key", "Profile"))),
                "tokens": tokens,
            }
        )

    for rule in rules or []:
        tokens = _dedupe_stored_tokens(
            list(rule.quality_include_tokens or []) + list(rule.quality_exclude_tokens or [])
        )
        if not tokens:
            continue
        references.append(
            {
                "kind": "rule",
                "label": rule.rule_name,
                "tokens": tokens,
            }
        )

    return references


def preview_quality_taxonomy_update(
    raw_payload: str,
    *,
    settings: AppSettings | None,
    rules: Sequence[Rule] | None,
) -> dict[str, object]:
    payload = _parse_quality_taxonomy_json(raw_payload, source="submitted taxonomy")
    validated = _validate_quality_taxonomy_payload(payload, source="submitted taxonomy")

    current_tokens = [item["value"] for item in _quality_options()]
    candidate_tokens = [str(item["value"]) for item in validated["options"]]
    current_token_set = set(current_tokens)
    candidate_token_set = set(candidate_tokens)

    added_tokens = [token for token in candidate_tokens if token not in current_token_set]
    removed_tokens = [token for token in current_tokens if token not in candidate_token_set]
    removed_token_set = set(removed_tokens)

    existing_invalid_references: list[dict[str, object]] = []
    blocking_references: list[dict[str, object]] = []
    for reference in _quality_taxonomy_references(settings, rules):
        reference_tokens = _coerce_token_values(reference.get("tokens"))
        existing_invalid_tokens = [
            token for token in reference_tokens if token not in current_token_set
        ]
        if existing_invalid_tokens:
            existing_invalid_references.append(
                {
                    "kind": reference["kind"],
                    "label": reference["label"],
                    "missing_tokens": existing_invalid_tokens,
                }
            )

        newly_orphaned_tokens = [token for token in reference_tokens if token in removed_token_set]
        if newly_orphaned_tokens:
            blocking_references.append(
                {
                    "kind": reference["kind"],
                    "label": reference["label"],
                    "missing_tokens": newly_orphaned_tokens,
                }
            )

    return {
        "formatted_text": json.dumps(payload, indent=2) + "\n",
        "version": int(validated["version"]),
        "summary": _quality_taxonomy_summary(validated),
        "added_tokens": added_tokens,
        "removed_tokens": removed_tokens,
        "existing_invalid_references": existing_invalid_references,
        "blocking_references": blocking_references,
        "safe_to_apply": not blocking_references,
    }


def _append_quality_taxonomy_audit_entry(entry: dict[str, object]) -> str | None:
    try:
        QUALITY_TAXONOMY_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUALITY_TAXONOMY_AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True))
            handle.write("\n")
    except OSError as exc:
        return str(exc)
    return None


def recent_quality_taxonomy_audit_entries(limit: int = 10) -> list[dict[str, object]]:
    if limit <= 0:
        return []

    try:
        raw_lines = QUALITY_TAXONOMY_AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        return []

    entries: list[dict[str, object]] = []
    for raw_line in reversed(raw_lines):
        if len(entries) >= limit:
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def apply_quality_taxonomy_update(
    raw_payload: str,
    *,
    change_note: str = "",
) -> str | None:
    payload = _parse_quality_taxonomy_json(raw_payload, source="submitted taxonomy")
    validated = _validate_quality_taxonomy_payload(payload, source="submitted taxonomy")
    formatted_text = json.dumps(payload, indent=2) + "\n"

    try:
        QUALITY_TAXONOMY_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUALITY_TAXONOMY_PATH.write_text(formatted_text, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Unable to write quality taxonomy to {QUALITY_TAXONOMY_PATH}: {exc}"
        ) from exc

    _clear_quality_taxonomy_cache()

    audit_error = _append_quality_taxonomy_audit_entry(
        {
            "created_at": datetime.now(UTC).isoformat(),
            "action": "apply",
            "note": change_note.strip(),
            "version": int(validated["version"]),
            **_quality_taxonomy_summary(validated),
        }
    )
    return audit_error


QUALITY_PROFILE_FALLBACK_LABELS: dict[str, str] = {
    QualityProfile.PLAIN.value: "No preset",
    QualityProfile.HD_1080P.value: "At Least Full HD",
    QualityProfile.UHD_2160P_HDR.value: "Ultra HD HDR",
    QualityProfile.CUSTOM.value: "Custom (manual tags)",
}

QUALITY_PROFILE_BUNDLE_KEYS: dict[str, str] = {
    QualityProfile.HD_1080P.value: "at_least_hd",
    QualityProfile.UHD_2160P_HDR.value: "ultra_hd_hdr",
}

BUILTIN_AT_LEAST_UHD_PROFILE_KEY = "builtin-at-least-uhd"
BUILTIN_AT_LEAST_UHD_PROFILE_LABEL = "At Least UHD"
BUILTIN_AUDIOBOOK_PORTABLE_PROFILE_KEY = "builtin-audiobook-portable"
BUILTIN_AUDIOBOOK_HIGH_BITRATE_PROFILE_KEY = "builtin-audiobook-high-bitrate"
BUILTIN_MUSIC_LOSSLESS_PROFILE_KEY = "builtin-music-lossless"
BUILTIN_MUSIC_LOSSY_PROFILE_KEY = "builtin-music-lossy"

LEGACY_DEFAULT_QUALITY_PROFILE_RULES: dict[str, dict[str, list[str]]] = {
    QualityProfile.PLAIN.value: {"include_tokens": [], "exclude_tokens": []},
    QualityProfile.HD_1080P.value: {
        "include_tokens": ["hd", "720p", "full_hd", "1080p", "ultra_hd", "uhd", "2160p", "4k"],
        "exclude_tokens": [
            "480p",
            "360p",
            "sd",
            "bdremux",
            "remux",
            "bluray",
            "tv_sync",
            "dvd",
            "ts",
            "cam",
        ],
    },
    QualityProfile.UHD_2160P_HDR.value: {
        "include_tokens": ["ultra_hd", "uhd", "4k", "2160p", "hdr", "dolby_vision"],
        "exclude_tokens": [
            "1080p",
            "720p",
            "480p",
            "360p",
            "sd",
            "bdremux",
            "remux",
            "bluray",
            "tv_sync",
            "dvd",
            "ts",
            "cam",
        ],
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
    "media_types": [MediaType.SERIES.value, MediaType.MOVIE.value],
}

BUILTIN_FILTER_PROFILE_ORDER: tuple[str, ...] = (
    "builtin-ultra-hd-hdr",
    "builtin-at-least-hd",
    BUILTIN_AT_LEAST_UHD_PROFILE_KEY,
    BUILTIN_AUDIOBOOK_PORTABLE_PROFILE_KEY,
    BUILTIN_AUDIOBOOK_HIGH_BITRATE_PROFILE_KEY,
    BUILTIN_MUSIC_LOSSLESS_PROFILE_KEY,
    BUILTIN_MUSIC_LOSSY_PROFILE_KEY,
)

BUILTIN_FILTER_PROFILE_SPECS: tuple[dict[str, object], ...] = (
    {
        "key": "builtin-ultra-hd-hdr",
        "label_mode": "quality_profile",
        "quality_profile_key": QualityProfile.UHD_2160P_HDR.value,
        "quality_profile_value": QualityProfile.UHD_2160P_HDR.value,
        "media_types": tuple(SCOPED_MEDIA_TYPE_ORDER[:2]),
        "override_mode": "profile_rule",
    },
    {
        "key": "builtin-at-least-hd",
        "label_mode": "quality_profile",
        "quality_profile_key": QualityProfile.HD_1080P.value,
        "quality_profile_value": QualityProfile.HD_1080P.value,
        "media_types": tuple(SCOPED_MEDIA_TYPE_ORDER[:2]),
        "override_mode": "profile_rule",
    },
    {
        "key": BUILTIN_AT_LEAST_UHD_PROFILE_KEY,
        "label_mode": "bundle",
        "bundle_key": "at_least_uhd",
        "fallback_label": BUILTIN_AT_LEAST_UHD_PROFILE_LABEL,
        "quality_profile_value": QualityProfile.CUSTOM.value,
        "media_types": tuple(SCOPED_MEDIA_TYPE_ORDER[:2]),
        "override_mode": "saved_profile",
        "include_tokens": tuple(cast(list[str], AT_LEAST_UHD_PROFILE["include_tokens"])),
        "exclude_tokens": tuple(cast(list[str], AT_LEAST_UHD_PROFILE["exclude_tokens"])),
    },
    {
        "key": BUILTIN_AUDIOBOOK_PORTABLE_PROFILE_KEY,
        "label_mode": "static",
        "fallback_label": "Audiobook Portable (AAC/M4B/MP3)",
        "quality_profile_value": QualityProfile.CUSTOM.value,
        "media_types": (MediaType.AUDIOBOOK.value,),
        "override_mode": "saved_profile",
        "include_tokens": ("aac", "m4b", "mp3"),
        "exclude_tokens": ("lossless", "flac", "alac", "wav"),
    },
    {
        "key": BUILTIN_AUDIOBOOK_HIGH_BITRATE_PROFILE_KEY,
        "label_mode": "static",
        "fallback_label": "Audiobook High Bitrate (192k+)",
        "quality_profile_value": QualityProfile.CUSTOM.value,
        "media_types": (MediaType.AUDIOBOOK.value,),
        "override_mode": "saved_profile",
        "include_tokens": ("192kbps", "256kbps", "320kbps", "aac", "m4b", "mp3", "opus"),
        "exclude_tokens": ("64kbps", "128kbps"),
    },
    {
        "key": BUILTIN_MUSIC_LOSSLESS_PROFILE_KEY,
        "label_mode": "static",
        "fallback_label": "Music Lossless",
        "quality_profile_value": QualityProfile.CUSTOM.value,
        "media_types": (MediaType.MUSIC.value,),
        "override_mode": "saved_profile",
        "include_tokens": ("lossless", "flac", "alac", "wav"),
        "exclude_tokens": ("64kbps", "128kbps", "192kbps", "mp3", "aac", "opus"),
    },
    {
        "key": BUILTIN_MUSIC_LOSSY_PROFILE_KEY,
        "label_mode": "static",
        "fallback_label": "Music Lossy (256/320/VBR)",
        "quality_profile_value": QualityProfile.CUSTOM.value,
        "media_types": (MediaType.MUSIC.value,),
        "override_mode": "saved_profile",
        "include_tokens": ("256kbps", "320kbps", "vbr", "mp3", "aac", "opus", "m4a"),
        "exclude_tokens": ("64kbps", "128kbps", "lossless", "flac", "alac", "wav"),
    },
)

PROFILE_KEY_RE = re.compile(r"[^a-z0-9]+")


def _ordered_media_types(raw_media_types: tuple[str, ...] | list[str] | None) -> list[str]:
    if not raw_media_types:
        return []
    available = {str(item) for item in raw_media_types}
    return [item for item in SCOPED_MEDIA_TYPE_ORDER if item in available]


def _media_type_is_other(media_type: MediaType | str | None) -> bool:
    raw_value = media_type.value if isinstance(media_type, MediaType) else str(media_type or "")
    return raw_value == MediaType.OTHER.value


def _media_type_matches_scope(
    media_type: MediaType | str | None,
    scope: tuple[str, ...] | list[str] | None,
) -> bool:
    if _media_type_is_other(media_type):
        return True
    raw_value = media_type.value if isinstance(media_type, MediaType) else str(media_type or "")
    if not raw_value:
        return True
    return not scope or raw_value in scope


def _bundle_label_or_default(bundle_key: str, fallback: str) -> str:
    return _quality_bundle_labels().get(bundle_key, fallback)


def quality_profile_label(value: QualityProfile | str) -> str:
    raw_value = value.value if isinstance(value, QualityProfile) else str(value)
    bundle_key = QUALITY_PROFILE_BUNDLE_KEYS.get(raw_value)
    if bundle_key:
        return _bundle_label_or_default(
            bundle_key,
            QUALITY_PROFILE_FALLBACK_LABELS.get(raw_value, raw_value),
        )
    return QUALITY_PROFILE_FALLBACK_LABELS.get(raw_value, raw_value)


def quality_option_choices() -> list[dict[str, object]]:
    return [
        {
            "value": str(item["value"]),
            "label": str(item["label"]),
            "pattern": str(item["pattern"]),
            "group": str(item["group"]),
            "media_types": _ordered_media_types(_coerce_media_type_values(item.get("media_types"))),
        }
        for item in _quality_options()
    ]


def quality_option_groups() -> list[dict[str, object]]:
    group_definitions = _quality_group_definitions()
    grouped: dict[str, list[dict[str, object]]] = {
        str(item["key"]): [] for item in group_definitions
    }
    for item in quality_option_choices():
        grouped[str(item["group"])].append(item)
    return [
        {
            "key": str(group["key"]),
            "label": str(group["label"]),
            "media_types": _ordered_media_types(
                _coerce_media_type_values(group.get("media_types"))
            ),
            "options": grouped[str(group["key"])],
        }
        for group in group_definitions
    ]


def quality_option_groups_for_media_type(
    media_type: MediaType | str | None,
) -> list[dict[str, object]]:
    if _media_type_is_other(media_type):
        return quality_option_groups()

    filtered_groups: list[dict[str, object]] = []
    for group in quality_option_groups():
        if not _media_type_matches_scope(
            media_type, _coerce_media_type_values(group.get("media_types"))
        ):
            continue
        visible_options = [
            option
            for option in cast(list[dict[str, object]], group["options"])
            if _media_type_matches_scope(
                media_type, _coerce_media_type_values(option.get("media_types"))
            )
        ]
        if not visible_options:
            continue
        filtered_groups.append({**group, "options": visible_options})
    return filtered_groups


def quality_bundle_choices() -> list[dict[str, object]]:
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "tokens": _coerce_token_values(item.get("tokens")),
        }
        for item in _quality_bundle_definitions()
    ]


def resolve_quality_token(raw_token: str) -> list[str]:
    token = str(raw_token).strip()
    if not token:
        return []

    bundle_tokens = _quality_bundle_tokens().get(token)
    if bundle_tokens is not None:
        return list(bundle_tokens)

    canonical = _quality_alias_map().get(token, token)
    if canonical not in _quality_option_patterns():
        return []
    return [canonical]


def expand_quality_tokens(raw_tokens: object | None) -> list[str]:
    tokens = _coerce_token_values(raw_tokens)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_token in tokens:
        for token in resolve_quality_token(str(raw_token)):
            if token in seen:
                continue
            seen.add(token)
            cleaned.append(token)
    return cleaned


def quality_profile_choices() -> list[dict[str, str]]:
    return [{"value": item.value, "label": quality_profile_label(item)} for item in QualityProfile]


def normalize_quality_tokens(raw_tokens: object | None) -> list[str]:
    return expand_quality_tokens(raw_tokens)


def canonicalize_quality_tokens(raw_tokens: object | None) -> list[str]:
    option_order = _quality_option_order()
    return sorted(
        normalize_quality_tokens(raw_tokens),
        key=lambda token: option_order.get(token, len(option_order)),
    )


def quality_token_group_map() -> dict[str, str]:
    return {str(item["value"]): str(item["group"]) for item in quality_option_choices()}


def grouped_quality_tokens(raw_tokens: object | None) -> list[list[str]]:
    token_group_map = quality_token_group_map()
    grouped: dict[str, list[str]] = {}
    ordered_groups: list[str] = []
    for token in normalize_quality_tokens(raw_tokens):
        group_key = token_group_map.get(token, "__ungrouped__")
        if group_key not in grouped:
            grouped[group_key] = []
            ordered_groups.append(group_key)
        grouped[group_key].append(token)
    return [grouped[group_key] for group_key in ordered_groups if grouped[group_key]]


def tokens_to_regex(tokens: object | None) -> str:
    option_patterns = _quality_option_patterns()
    ordered_patterns: list[str] = []
    seen_patterns: set[str] = set()
    for token in normalize_quality_tokens(tokens):
        pattern = (
            f"{QUALITY_TOKEN_PREFIX_BOUNDARY}(?:{option_patterns[token]})"
            f"{QUALITY_TOKEN_SUFFIX_BOUNDARY}"
        )
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        ordered_patterns.append(pattern)
    if not ordered_patterns:
        return ""
    return f"(?:{'|'.join(ordered_patterns)})"


def grouped_tokens_to_regex(tokens: object | None) -> list[str]:
    fragments: list[str] = []
    for group_tokens in grouped_quality_tokens(tokens):
        fragment = tokens_to_regex(group_tokens)
        if fragment:
            fragments.append(fragment)
    return fragments


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


def quality_token_media_types(token: str) -> list[str]:
    return _ordered_media_types(_quality_option_media_types().get(token))


def _scope_domain(media_types: list[str]) -> str | None:
    if not media_types:
        return None
    media_type_set = set(media_types)
    if media_type_set.issubset(VIDEO_MEDIA_TYPES):
        return "video"
    if media_type_set.issubset(AUDIO_MEDIA_TYPES):
        return "audio"
    return None


def infer_filter_profile_media_types(
    include_tokens: object | None,
    exclude_tokens: object | None,
) -> list[str] | None:
    tokens = canonicalize_quality_tokens(
        list(normalize_quality_tokens(include_tokens))
        + list(normalize_quality_tokens(exclude_tokens))
    )
    if not tokens:
        return None

    domain: str | None = None
    intersection: set[str] | None = None
    for token in tokens:
        token_media_types = quality_token_media_types(token)
        if not token_media_types:
            return None
        token_domain = _scope_domain(token_media_types)
        if token_domain is None:
            return None
        if domain is None:
            domain = token_domain
        elif domain != token_domain:
            return None

        token_scope = set(token_media_types)
        if intersection is None:
            intersection = token_scope
        else:
            intersection &= token_scope

    if not intersection:
        return None
    return [item for item in SCOPED_MEDIA_TYPE_ORDER if item in intersection]


def _normalize_saved_profile_media_types(raw_value: Any) -> list[str] | None:
    if not isinstance(raw_value, list):
        return None

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_value:
        value = str(raw_item).strip()
        if not value or value not in SCOPED_MEDIA_TYPE_ORDER or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned or None


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
        media_types = _normalize_saved_profile_media_types(raw_profile.get("media_types"))
        if "media_types" not in raw_profile:
            media_types = infer_filter_profile_media_types(include_tokens, exclude_tokens)

        profile: dict[str, object] = {
            "label": label,
            "include_tokens": include_tokens,
            "exclude_tokens": exclude_tokens,
            "quality_profile_value": QualityProfile.CUSTOM.value,
            "built_in": False,
        }
        if media_types:
            profile["media_types"] = media_types
        normalized[key] = profile
    return normalized


def slugify_profile_key(value: str) -> str:
    cleaned = PROFILE_KEY_RE.sub("-", value.strip().casefold()).strip("-")
    return cleaned


def builtin_filter_profile_keys() -> set[str]:
    return {str(spec["key"]) for spec in BUILTIN_FILTER_PROFILE_SPECS}


def filter_profile_matches_media_type(
    profile: dict[str, object],
    media_type: MediaType | str | None,
) -> bool:
    return _media_type_matches_scope(
        media_type, _coerce_media_type_values(profile.get("media_types"))
    )


def _build_builtin_filter_profile(
    spec: dict[str, object],
    *,
    profile_rules: dict[str, dict[str, list[str]]],
    saved_profiles: dict[str, dict[str, object]],
) -> dict[str, object]:
    key = str(spec["key"])
    override = saved_profiles.pop(key, None)
    label_mode = str(spec.get("label_mode", "static"))
    if label_mode == "quality_profile":
        label = quality_profile_label(str(spec["quality_profile_key"]))
    elif label_mode == "bundle":
        label = _bundle_label_or_default(
            str(spec["bundle_key"]),
            str(spec.get("fallback_label", key)),
        )
    else:
        label = str(spec.get("fallback_label", key))

    override_mode = str(spec.get("override_mode", "saved_profile"))
    if override_mode == "profile_rule":
        profile_key = str(spec["quality_profile_key"])
        include_tokens = list(profile_rules[profile_key]["include_tokens"])
        exclude_tokens = list(profile_rules[profile_key]["exclude_tokens"])
    else:
        include_tokens = _coerce_token_values(spec.get("include_tokens"))
        exclude_tokens = _coerce_token_values(spec.get("exclude_tokens"))
        if override:
            include_tokens = _coerce_token_values(override.get("include_tokens")) or include_tokens
            exclude_tokens = _coerce_token_values(override.get("exclude_tokens")) or exclude_tokens

    return {
        "label": label,
        "include_tokens": include_tokens,
        "exclude_tokens": exclude_tokens,
        "quality_profile_value": str(
            spec.get("quality_profile_value", QualityProfile.CUSTOM.value)
        ),
        "built_in": True,
        "media_types": _ordered_media_types(_coerce_media_type_values(spec.get("media_types"))),
    }


def build_available_filter_profiles(settings: AppSettings | None) -> dict[str, dict[str, object]]:
    profile_rules = resolve_quality_profile_rules(settings)
    saved_profiles = normalize_saved_quality_profiles(
        settings.saved_quality_profiles if settings else {}
    )
    available = {
        str(spec["key"]): _build_builtin_filter_profile(
            spec,
            profile_rules=profile_rules,
            saved_profiles=saved_profiles,
        )
        for spec in BUILTIN_FILTER_PROFILE_SPECS
    }
    available.update(saved_profiles)
    return available


def available_filter_profile_choices(settings: AppSettings | None) -> list[dict[str, object]]:
    profiles = build_available_filter_profiles(settings)
    custom_keys = sorted(
        (key for key, profile in profiles.items() if not bool(profile.get("built_in"))),
        key=lambda key: str(profiles[key]["label"]).casefold(),
    )
    return [
        {"key": key, **profiles[key]}
        for key in [*BUILTIN_FILTER_PROFILE_ORDER, *custom_keys]
        if key in profiles
    ]


def available_filter_profile_choices_for_media_type(
    settings: AppSettings | None,
    media_type: MediaType | str | None,
) -> list[dict[str, object]]:
    return [
        profile
        for profile in available_filter_profile_choices(settings)
        if filter_profile_matches_media_type(profile, media_type)
    ]


def detect_matching_filter_profile_key(
    include_tokens: object | None,
    exclude_tokens: object | None,
    settings: AppSettings | None,
    *,
    media_type: MediaType | str | None = None,
) -> str:
    normalized_include = canonicalize_quality_tokens(include_tokens)
    normalized_exclude = canonicalize_quality_tokens(exclude_tokens)
    for item in available_filter_profile_choices(settings):
        if media_type is not None and not filter_profile_matches_media_type(item, media_type):
            continue
        if normalized_include == canonicalize_quality_tokens(
            _coerce_token_values(item.get("include_tokens"))
        ) and normalized_exclude == canonicalize_quality_tokens(
            _coerce_token_values(item.get("exclude_tokens"))
        ):
            return str(item["key"])
    return ""
