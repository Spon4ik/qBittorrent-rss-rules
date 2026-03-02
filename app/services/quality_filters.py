from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from app.models import AppSettings, QualityProfile, Rule

QUALITY_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "quality_taxonomy.json"
QUALITY_TAXONOMY_AUDIT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "taxonomy_audit.jsonl"
)


def _quality_taxonomy_source(source: Path | str | None = None) -> str:
    if source is None:
        return str(QUALITY_TAXONOMY_PATH)
    return str(source)


def _quality_taxonomy_error(problem: str, *, source: Path | str | None = None) -> RuntimeError:
    return RuntimeError(f"Invalid quality taxonomy at {_quality_taxonomy_source(source)}: {problem}")


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


def _validate_quality_taxonomy_payload(
    payload: dict[str, Any],
    *,
    source: Path | str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _quality_taxonomy_error("top-level JSON value must be an object", source=source)

    version = payload.get("version")
    if version not in (1, 2):
        raise _quality_taxonomy_error("version must be 1 or 2", source=source)

    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise _quality_taxonomy_error("groups must be a list", source=source)

    groups: list[dict[str, str]] = []
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
        groups.append({"key": key, "label": label})

    raw_options = payload.get("options")
    if not isinstance(raw_options, list):
        raise _quality_taxonomy_error("options must be a list", source=source)

    options: list[dict[str, str]] = []
    seen_option_values: set[str] = set()
    for index, raw_option in enumerate(raw_options):
        if not isinstance(raw_option, dict):
            raise _quality_taxonomy_error(f"options[{index}] must be an object", source=source)
        value = str(raw_option.get("value", "")).strip()
        label = str(raw_option.get("label", "")).strip()
        pattern = str(raw_option.get("pattern", "")).strip()
        group = str(raw_option.get("group", "")).strip()
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
        if not group:
            raise _quality_taxonomy_error(
                f"options[{index}].group must be a non-empty string",
                source=source,
            )
        if value in seen_option_values:
            raise _quality_taxonomy_error(f"duplicate option value '{value}'", source=source)
        if group not in seen_group_keys:
            raise _quality_taxonomy_error(
                f"options[{index}].group references unknown group '{group}'",
                source=source,
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

    bundles: list[dict[str, object]] = []
    seen_bundle_keys: set[str] = set()
    raw_bundles = payload.get("bundles", [])
    if version == 2:
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
    if version == 2:
        if not isinstance(raw_aliases, list):
            raise _quality_taxonomy_error("aliases must be a list", source=source)
        seen_alias_keys: set[str] = set()
        for index, raw_alias in enumerate(raw_aliases):
            if not isinstance(raw_alias, dict):
                raise _quality_taxonomy_error(f"aliases[{index}] must be an object", source=source)
            alias = str(raw_alias.get("alias", "")).strip()
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
            aliases.append({"alias": alias, "canonical": canonical})

    ranks: list[dict[str, object]] = []
    raw_ranks = payload.get("ranks", [])
    if version == 2:
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
def _quality_group_labels() -> dict[str, str]:
    groups = _load_quality_taxonomy()["groups"]
    return {item["key"]: item["label"] for item in groups}


@lru_cache(maxsize=1)
def _quality_options() -> tuple[dict[str, str], ...]:
    return _load_quality_taxonomy()["options"]


@lru_cache(maxsize=1)
def _quality_bundle_definitions() -> tuple[dict[str, object], ...]:
    return _load_quality_taxonomy()["bundles"]


@lru_cache(maxsize=1)
def _quality_bundle_labels() -> dict[str, str]:
    return {
        str(item["key"]): str(item["label"])
        for item in _quality_bundle_definitions()
    }


@lru_cache(maxsize=1)
def _quality_bundle_tokens() -> dict[str, tuple[str, ...]]:
    return {
        str(item["key"]): tuple(str(token) for token in item["tokens"])
        for item in _quality_bundle_definitions()
    }


@lru_cache(maxsize=1)
def _quality_alias_map() -> dict[str, str]:
    return {
        str(item["alias"]): str(item["canonical"])
        for item in _load_quality_taxonomy()["aliases"]
    }


@lru_cache(maxsize=1)
def _quality_option_patterns() -> dict[str, str]:
    return {item["value"]: item["pattern"] for item in _quality_options()}


@lru_cache(maxsize=1)
def _quality_option_order() -> dict[str, int]:
    return {item["value"]: index for index, item in enumerate(_quality_options())}


def _clear_quality_taxonomy_cache() -> None:
    _quality_option_order.cache_clear()
    _quality_option_patterns.cache_clear()
    _quality_alias_map.cache_clear()
    _quality_bundle_tokens.cache_clear()
    _quality_bundle_labels.cache_clear()
    _quality_bundle_definitions.cache_clear()
    _quality_options.cache_clear()
    _quality_group_labels.cache_clear()
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
        "groups": [dict(item) for item in taxonomy["groups"]],
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


def _quality_taxonomy_references(
    settings: AppSettings | None,
    rules: list[Rule] | tuple[Rule, ...] | None,
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for profile in available_filter_profile_choices(settings):
        tokens = _dedupe_stored_tokens(
            list(profile.get("include_tokens", [])) + list(profile.get("exclude_tokens", []))
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
    rules: list[Rule] | tuple[Rule, ...] | None,
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
        existing_invalid_tokens = [token for token in reference["tokens"] if token not in current_token_set]
        if existing_invalid_tokens:
            existing_invalid_references.append(
                {
                    "kind": reference["kind"],
                    "label": reference["label"],
                    "missing_tokens": existing_invalid_tokens,
                }
            )

        newly_orphaned_tokens = [token for token in reference["tokens"] if token in removed_token_set]
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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


def quality_bundle_choices() -> list[dict[str, object]]:
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "tokens": list(item["tokens"]),
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


def expand_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    tokens = raw_tokens or []
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


def normalize_quality_tokens(raw_tokens: list[str] | tuple[str, ...] | None) -> list[str]:
    return expand_quality_tokens(raw_tokens)


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
    at_least_uhd_profile["label"] = _bundle_label_or_default(
        "at_least_uhd",
        BUILTIN_AT_LEAST_UHD_PROFILE_LABEL,
    )
    if at_least_uhd_override:
        at_least_uhd_profile["include_tokens"] = list(at_least_uhd_override.get("include_tokens", []))
        at_least_uhd_profile["exclude_tokens"] = list(at_least_uhd_override.get("exclude_tokens", []))
    available = {
        "builtin-ultra-hd-hdr": {
            "label": quality_profile_label(QualityProfile.UHD_2160P_HDR),
            "include_tokens": list(profile_rules[QualityProfile.UHD_2160P_HDR.value]["include_tokens"]),
            "exclude_tokens": list(profile_rules[QualityProfile.UHD_2160P_HDR.value]["exclude_tokens"]),
            "quality_profile_value": QualityProfile.UHD_2160P_HDR.value,
            "built_in": True,
        },
        "builtin-at-least-hd": {
            "label": quality_profile_label(QualityProfile.HD_1080P),
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
