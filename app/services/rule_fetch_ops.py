from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.models import MediaType, Rule, RuleSearchSnapshot, utcnow
from app.schemas import JackettSearchRequest
from app.services.category_catalog import (
    sync_category_catalog_from_indexer_map,
    sync_category_catalog_from_results,
)
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    _matches_excluded_keyword,
    _matches_included_keyword,
    _matches_precise_title_identity,
    _matches_query_text,
    _normalize_match_text,
    build_reduced_search_request_from_rule,
    build_search_request_from_rule,
    clamp_search_query_text,
)
from app.services.quality_filters import (
    effective_rule_quality_tokens,
    grouped_tokens_to_regex,
    tokens_to_regex,
)
from app.services.rule_builder import (
    build_episode_progress_fragment,
    build_existing_episode_exclusion_fragment,
    build_lower_episode_exclusion_fragment,
    build_manual_must_contain_fragments,
    looks_like_full_must_contain_override,
    normalize_jellyfin_episode_keys,
    normalize_release_year,
    parse_additional_include_groups,
)
from app.services.rule_search_snapshots import (
    inline_search_from_snapshot,
    save_rule_search_snapshot,
)
from app.services.settings_service import (
    DEFAULT_RULE_FETCH_PARALLELISM,
    SettingsService,
    normalize_rule_fetch_parallelism,
)

JACKETT_FEED_INDEXER_PATH_RE = re.compile(
    r"/api/v2\.0/indexers/(?P<indexer>[^/]+)/results/torznab(?:/api)?/?$",
    re.IGNORECASE,
)
RULE_FETCH_SCHEDULE_SCOPES = frozenset({"enabled", "all"})
DEFAULT_RULE_FETCH_SCHEDULE_SCOPE = "enabled"
DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 360
MIN_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 5
MAX_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 10080
_RULE_FETCH_RUN_LOCK = threading.Lock()
INDEXER_KEY_STRIP_RE = re.compile(r"[^a-z0-9]+")
SEASON_PACK_COMPLETE_MARKER_RE = re.compile(
    r"\b(?:complete|full(?:\s+season)?|season\s+pack|полный)\b",
    re.IGNORECASE | re.UNICODE,
)
SEASON_PACK_CURRENT_SEASON_RE_TEMPLATE = (
    r"(?:s(?:eason)?[\s._:-]*0*{season}(?!\d)|0*{season}x0*\d{{1,3}})"
)


def normalize_schedule_scope(value: object | None) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in RULE_FETCH_SCHEDULE_SCOPES:
        return cleaned
    return DEFAULT_RULE_FETCH_SCHEDULE_SCOPE


def normalize_schedule_interval_minutes(value: object | None) -> int:
    if value is None:
        return DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES
    return max(
        MIN_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
        min(MAX_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES, numeric),
    )


def schedule_next_run_at(*, from_time: datetime | None = None, interval_minutes: int) -> datetime:
    base_time = (from_time or utcnow()).astimezone(UTC)
    return base_time + timedelta(minutes=interval_minutes)


def schedule_payload(settings: Any) -> dict[str, Any]:
    interval_minutes = normalize_schedule_interval_minutes(
        getattr(
            settings,
            "rules_fetch_schedule_interval_minutes",
            DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
        )
    )
    scope = normalize_schedule_scope(
        getattr(settings, "rules_fetch_schedule_scope", DEFAULT_RULE_FETCH_SCHEDULE_SCOPE)
    )
    return {
        "enabled": bool(getattr(settings, "rules_fetch_schedule_enabled", False)),
        "interval_minutes": interval_minutes,
        "scope": scope,
        "last_run_at": _iso_datetime(getattr(settings, "rules_fetch_schedule_last_run_at", None)),
        "next_run_at": _iso_datetime(getattr(settings, "rules_fetch_schedule_next_run_at", None)),
        "last_status": str(getattr(settings, "rules_fetch_schedule_last_status", "idle") or "idle"),
        "last_message": str(getattr(settings, "rules_fetch_schedule_last_message", "") or ""),
    }


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def _rule_search_title(rule: Rule) -> str:
    return (
        str(rule.normalized_title or "").strip()
        or str(rule.content_name or "").strip()
        or str(rule.rule_name or "").strip()
    )


def _normalized_media_type(value: object | None) -> str:
    cleaned = str(value or "").strip()
    valid_values = {item.value for item in MediaType}
    if cleaned in valid_values:
        return cleaned
    return MediaType.SERIES.value


def _rule_search_media_type(rule: Rule) -> str:
    raw_value = getattr(rule.media_type, "value", rule.media_type)
    return _normalized_media_type(raw_value)


def _title_only_search_request_from_rule(rule: Rule) -> JackettSearchRequest | None:
    fallback_title = clamp_search_query_text(_rule_search_title(rule))
    if not fallback_title:
        return None
    try:
        media_type = MediaType(_rule_search_media_type(rule))
        return JackettSearchRequest(
            query=fallback_title,
            media_type=media_type,
            imdb_id=rule.imdb_id or None,
            release_year=(rule.release_year or None) if rule.include_release_year else None,
        )
    except ValidationError:
        return None


def _auto_imdb_first_payload(payload: JackettSearchRequest) -> JackettSearchRequest:
    if payload.imdb_id and payload.media_type in {MediaType.MOVIE, MediaType.SERIES}:
        return payload.model_copy(update={"imdb_id_only": True})
    return payload


def _normalize_feed_url_list(feed_urls: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_url in list(feed_urls or []):
        candidate = str(raw_url or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _feed_url_to_indexer_slug(feed_url: str) -> str | None:
    cleaned = str(feed_url or "").strip()
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    match = JACKETT_FEED_INDEXER_PATH_RE.search(parsed.path or "")
    if not match:
        return None
    raw_indexer = unquote(match.group("indexer") or "").strip().casefold()
    if not raw_indexer or raw_indexer == "all":
        return None
    return raw_indexer


def _normalize_search_indexers(indexers: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_indexer in list(indexers or []):
        candidate = str(raw_indexer or "").strip().casefold()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _apply_indexer_scope(
    payload: JackettSearchRequest,
    indexers: list[str],
    *,
    singular_notice: str,
    plural_notice: str,
) -> tuple[JackettSearchRequest, str]:
    if len(indexers) == 1:
        scoped_indexer = indexers[0]
        return (
            payload.model_copy(
                update={
                    "indexer": scoped_indexer,
                    "filter_indexers": [scoped_indexer],
                }
            ),
            singular_notice.format(indexer=scoped_indexer),
        )
    merged_filter_indexers = list(payload.filter_indexers or [])
    seen = {item.casefold() for item in merged_filter_indexers}
    for item in indexers:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged_filter_indexers.append(item)
    return (
        payload.model_copy(
            update={
                "indexer": "all",
                "filter_indexers": merged_filter_indexers,
            }
        ),
        plural_notice.format(indexers=", ".join(indexers)),
    )


def _build_indexer_key_variants(value: object | None) -> list[str]:
    raw = str(value or "").strip().casefold()
    if not raw:
        return []
    cleaned = raw[4:] if raw.startswith("www.") else raw
    variants: list[str] = []
    seen: set[str] = set()

    def _push_unique(candidate: object | None) -> None:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        variants.append(normalized)

    _push_unique(cleaned)
    _push_unique(INDEXER_KEY_STRIP_RE.sub("", cleaned))
    if "." in cleaned:
        host_without_tld = cleaned.rsplit(".", 1)[0].strip()
        _push_unique(host_without_tld)
        _push_unique(INDEXER_KEY_STRIP_RE.sub("", host_without_tld))
    return variants


def _normalize_imdb_id(value: object | None) -> str:
    cleaned = str(value or "").strip().casefold()
    if not cleaned:
        return ""
    if cleaned.isdigit():
        return f"tt{cleaned}"
    if re.fullmatch(r"tt\d+", cleaned):
        return cleaned
    return ""


def _compile_pattern(pattern: object | None, *, ignore_case: bool = True) -> re.Pattern[str] | None:
    cleaned = str(pattern or "").strip()
    if not cleaned:
        return None
    flags = re.UNICODE
    if ignore_case:
        flags |= re.IGNORECASE
    try:
        return re.compile(cleaned, flags)
    except re.error:
        return None


def _compile_generated_pattern(pattern: object | None) -> re.Pattern[str] | None:
    cleaned = str(pattern or "").strip()
    if not cleaned:
        return None
    source = cleaned
    flags = re.UNICODE
    if source.startswith("(?i)"):
        source = source[4:]
        flags |= re.IGNORECASE
    try:
        return re.compile(source, flags)
    except re.error:
        try:
            return re.compile(re.escape(source), re.IGNORECASE | re.UNICODE)
        except re.error:
            return None


def _dedupe_terms(terms: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in terms:
        candidate = str(item or "").strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _same_season_complete_pack_allowed(row: dict[str, Any], state: dict[str, Any]) -> bool:
    if not bool(state.get("keep_searching_existing")):
        return False
    start_season = state.get("start_season")
    if start_season is None:
        return False
    regex_surface = str(row.get("title") or row.get("text_surface") or "").strip()
    if not regex_surface or not SEASON_PACK_COMPLETE_MARKER_RE.search(regex_surface):
        return False
    try:
        season_number = int(str(start_season).strip())
    except (TypeError, ValueError):
        return False
    if season_number < 0:
        return False
    season_pattern = re.compile(
        SEASON_PACK_CURRENT_SEASON_RE_TEMPLATE.format(season=season_number),
        re.IGNORECASE | re.UNICODE,
    )
    return season_pattern.search(regex_surface) is not None


def _rule_local_generated_pattern(rule: Rule) -> str:
    manual_must_contain = str(rule.must_contain_override or "").strip()
    has_episode_floor = rule.start_season is not None and rule.start_episode is not None
    lower_episode_exclusion = build_lower_episode_exclusion_fragment(
        rule.start_season,
        rule.start_episode,
    )
    jellyfin_existing_episode_exclusion = ""
    if not bool(getattr(rule, "jellyfin_search_existing_unseen", False)):
        jellyfin_existing_episode_exclusion = build_existing_episode_exclusion_fragment(
            normalize_jellyfin_episode_keys(
                list(getattr(rule, "jellyfin_existing_episode_numbers", []) or [])
            )
        )
    if (
        not manual_must_contain
        and not has_episode_floor
        and not lower_episode_exclusion
        and not jellyfin_existing_episode_exclusion
    ):
        return ""
    if looks_like_full_must_contain_override(manual_must_contain):
        return manual_must_contain
    fragments: list[str] = []
    episode_floor_fragment = build_episode_progress_fragment(rule.start_season, rule.start_episode)
    if episode_floor_fragment:
        fragments.append(episode_floor_fragment)
    fragments.extend(build_manual_must_contain_fragments(manual_must_contain))
    if not fragments:
        pattern = "(?i)^"
        if lower_episode_exclusion:
            pattern += f"(?!.*{lower_episode_exclusion})"
        if jellyfin_existing_episode_exclusion:
            pattern += f"(?!.*{jellyfin_existing_episode_exclusion})"
        return pattern if pattern != "(?i)^" else ""
    pattern = "(?i)^" + "".join(f"(?=.*{fragment})" for fragment in fragments if fragment)
    if lower_episode_exclusion:
        pattern += f"(?!.*{lower_episode_exclusion})"
    if jellyfin_existing_episode_exclusion:
        pattern += f"(?!.*{jellyfin_existing_episode_exclusion})"
    return pattern


def _rule_local_filter_state(rule: Rule) -> dict[str, Any]:
    include_groups = parse_additional_include_groups(rule.additional_includes)
    required_include_terms = [group[0] for group in include_groups if len(group) == 1]
    any_include_groups = [group for group in include_groups if len(group) > 1]
    excluded_terms = _dedupe_terms(
        [item for group in parse_additional_include_groups(rule.must_not_contain) for item in group]
    )

    include_tokens, raw_exclude_tokens = effective_rule_quality_tokens(rule)
    include_token_set = set(include_tokens)
    exclude_tokens = [
        token
        for token in raw_exclude_tokens
        if token not in include_token_set
    ]
    include_quality_patterns = [
        compiled
        for compiled in (
            _compile_pattern(fragment) for fragment in grouped_tokens_to_regex(include_tokens)
        )
        if compiled is not None
    ]
    exclude_quality_pattern = _compile_pattern(tokens_to_regex(exclude_tokens))
    generated_pattern = _compile_generated_pattern(_rule_local_generated_pattern(rule))

    release_year = (
        normalize_release_year(rule.release_year) if bool(rule.include_release_year) else ""
    )
    feed_urls = _normalize_feed_url_list(list(rule.feed_urls or []))
    feed_indexers: list[str] = []
    seen_indexers: set[str] = set()
    for feed_url in feed_urls:
        indexer_slug = _feed_url_to_indexer_slug(feed_url)
        if not indexer_slug or indexer_slug in seen_indexers:
            continue
        seen_indexers.add(indexer_slug)
        feed_indexers.append(indexer_slug)
    feed_scope_blocks_all = bool(feed_urls) and not feed_indexers
    allowed_feed_indexer_keys = {
        key for item in feed_indexers for key in _build_indexer_key_variants(item)
    }

    return {
        "query": _rule_search_title(rule),
        "imdb_id": _normalize_imdb_id(rule.imdb_id),
        "keywords_all": required_include_terms,
        "keywords_any_groups": any_include_groups,
        "keywords_not": excluded_terms,
        "quality_include_patterns": include_quality_patterns,
        "quality_exclude_pattern": exclude_quality_pattern,
        "generated_pattern": generated_pattern,
        "release_year": release_year,
        "feed_scope_blocks_all": feed_scope_blocks_all,
        "allowed_feed_indexer_keys": allowed_feed_indexer_keys,
        "keep_searching_existing": bool(getattr(rule, "jellyfin_search_existing_unseen", False)),
        "start_season": rule.start_season,
    }


def _rule_local_filter_cache_key(rule: Rule) -> str:
    return json.dumps(
        {
            "additional_includes": str(rule.additional_includes or "").strip(),
            "query": _rule_search_title(rule),
            "imdb_id": _normalize_imdb_id(rule.imdb_id),
            "must_not_contain": str(rule.must_not_contain or "").strip(),
            "quality_include_tokens": list(effective_rule_quality_tokens(rule)[0]),
            "quality_exclude_tokens": list(effective_rule_quality_tokens(rule)[1]),
            "must_contain_override": str(rule.must_contain_override or "").strip(),
            "start_season": rule.start_season,
            "start_episode": rule.start_episode,
            "jellyfin_search_existing_unseen": bool(
                getattr(rule, "jellyfin_search_existing_unseen", False)
            ),
            "jellyfin_existing_episode_numbers": normalize_jellyfin_episode_keys(
                list(getattr(rule, "jellyfin_existing_episode_numbers", []) or [])
            ),
            "include_release_year": bool(rule.include_release_year),
            "release_year": normalize_release_year(rule.release_year)
            if bool(rule.include_release_year)
            else "",
            "feed_urls": _normalize_feed_url_list(list(rule.feed_urls or [])),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _snapshot_row_matches_rule_identity(
    row: dict[str, Any],
    *,
    state: dict[str, Any],
    title_surface: str,
) -> bool:
    query = str(state.get("query") or "").strip()
    if not query:
        return True

    expected_imdb_id = _normalize_imdb_id(state.get("imdb_id"))
    result_imdb_id = _normalize_imdb_id(row.get("imdb_id"))
    if expected_imdb_id and result_imdb_id and expected_imdb_id == result_imdb_id:
        return True

    source_keys = _snapshot_row_query_source_keys(row)
    if (
        expected_imdb_id
        and "primary" in source_keys
        and _matches_precise_title_identity(str(row.get("title") or ""), query)
    ):
        return True

    return _matches_query_text(title_surface=title_surface, query=query)


def _snapshot_row_filter_failure(row: dict[str, Any], state: dict[str, Any]) -> str | None:
    if bool(state.get("feed_scope_blocks_all")):
        return "No affected feeds are selected."

    text_surface = str(row.get("text_surface") or "").strip()
    if not text_surface:
        text_surface = _normalize_match_text(str(row.get("title") or ""))
    title_surface = _normalize_match_text(str(row.get("title") or ""))
    regex_surface = str(row.get("title") or row.get("text_surface") or "").strip()

    if not _snapshot_row_matches_rule_identity(row, state=state, title_surface=title_surface):
        query = str(state.get("query") or "").strip()
        if query:
            return f'Title does not match query "{query}".'
        return "Title does not match the rule."

    for keyword in state.get("keywords_all", []):
        if not _matches_included_keyword(text_surface, str(keyword)):
            return f"Missing include keyword: {keyword}."

    for group_index, group in enumerate(state.get("keywords_any_groups", []), start=1):
        if not any(_matches_included_keyword(text_surface, str(keyword)) for keyword in group):
            group_label = " | ".join(str(keyword) for keyword in group if str(keyword).strip())
            return f"Missing any-of group {group_index}: {group_label}."

    for keyword in state.get("keywords_not", []):
        if _matches_excluded_keyword(text_surface, str(keyword)):
            return f"Matched excluded keyword: {keyword}."

    for include_pattern in state.get("quality_include_patterns", []):
        if not include_pattern.search(regex_surface):
            return "Missing required quality tags."

    exclude_pattern = state.get("quality_exclude_pattern")
    if exclude_pattern is not None and exclude_pattern.search(regex_surface):
        return "Matched an excluded quality tag."

    generated_pattern = state.get("generated_pattern")
    if generated_pattern is not None and not generated_pattern.search(regex_surface):
        if _same_season_complete_pack_allowed(row, state):
            pass
        else:
            return "Does not match the generated rule pattern."

    release_year = str(state.get("release_year") or "").strip()
    if release_year:
        result_year = normalize_release_year(str(row.get("year") or row.get("title") or ""))
        if not result_year or result_year != release_year:
            return f"Release year does not match {release_year}."

    allowed_feed_indexer_keys = set(state.get("allowed_feed_indexer_keys", set()) or set())
    if allowed_feed_indexer_keys:
        indexer_keys = set(_build_indexer_key_variants(row.get("indexer") or ""))
        if not indexer_keys.intersection(allowed_feed_indexer_keys):
            return "Indexer is outside the affected-feed scope."

    return None


def _snapshot_unified_raw_rows(snapshot: RuleSearchSnapshot) -> list[dict[str, Any]]:
    inline_search = cast(dict[str, Any], snapshot.inline_search or {})
    raw_rows = inline_search.get("unified_raw_results")
    if isinstance(raw_rows, list):
        return [item for item in raw_rows if isinstance(item, dict)]

    legacy_inline_search = inline_search_from_snapshot(snapshot)
    legacy_rows = legacy_inline_search.get("unified_raw_results")
    if not isinstance(legacy_rows, list):
        return []
    return [item for item in legacy_rows if isinstance(item, dict)]


def _snapshot_row_query_source_keys(row: dict[str, Any]) -> list[str]:
    grouped_sources = row.get("grouped_query_sources")
    if isinstance(grouped_sources, list):
        keys = [
            str(item or "").strip().casefold()
            for item in grouped_sources
            if str(item or "").strip()
        ]
    else:
        source_key = str(row.get("query_source_key") or "").strip().casefold()
        keys = [item.strip() for item in source_key.split("+") if item.strip()]
    return [item for item in keys if item in {"primary", "fallback"}]


def inline_search_from_rule_snapshot(
    snapshot: RuleSearchSnapshot,
    *,
    rule: Rule,
) -> dict[str, object]:
    inline_search = dict(cast(dict[str, Any], inline_search_from_snapshot(snapshot)))
    raw_rows = inline_search.get("unified_raw_results")
    rows = [dict(item) for item in raw_rows or [] if isinstance(item, dict)]
    filter_state = _rule_local_filter_state(rule)
    filtered_count = 0
    hidden_reasons: dict[str, int] = {}
    visible_by_source: dict[str, int] = {}

    for row in rows:
        failure = _snapshot_row_filter_failure(row, filter_state)
        row["visible"] = failure is None
        if failure is None:
            row.pop("rule_local_hidden_reason", None)
            filtered_count += 1
            for source_key in _snapshot_row_query_source_keys(row):
                visible_by_source[source_key] = visible_by_source.get(source_key, 0) + 1
            continue
        row["rule_local_hidden_reason"] = failure
        hidden_reasons[failure] = hidden_reasons.get(failure, 0) + 1

    source_breakdown: list[dict[str, Any]] = []
    for source in inline_search.get("source_breakdown") or []:
        if not isinstance(source, dict):
            continue
        item = dict(source)
        source_key = str(item.get("key") or "").strip().casefold()
        if source_key in {"primary", "fallback"}:
            item["filtered_count"] = visible_by_source.get(source_key, 0)
        source_breakdown.append(item)

    inline_search["unified_raw_results"] = rows
    inline_search["combined_filtered_count"] = filtered_count
    inline_search["combined_fetched_count"] = len(rows)
    inline_search["source_breakdown"] = source_breakdown
    inline_search["rule_local_filter_mode"] = True
    inline_search["rule_local_filter_cache_key"] = _rule_local_filter_cache_key(rule)
    inline_search["rule_local_hidden_reasons"] = hidden_reasons
    return cast(dict[str, object], inline_search)


def _rule_local_filtered_count_from_rows(
    rule: Rule,
    raw_rows: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
) -> int:
    filtered_count, _hidden_reasons = _rule_local_filter_diagnostics_from_rows(
        rule,
        raw_rows,
        state=state,
    )
    return filtered_count


def _rule_local_filter_diagnostics_from_rows(
    rule: Rule,
    raw_rows: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int]]:
    filter_state = state or _rule_local_filter_state(rule)
    filtered_count = 0
    hidden_reasons: dict[str, int] = {}
    for item in raw_rows:
        failure = _snapshot_row_filter_failure(item, filter_state)
        if failure is None:
            filtered_count += 1
            continue
        hidden_reasons[failure] = hidden_reasons.get(failure, 0) + 1
    return filtered_count, hidden_reasons


def refresh_snapshot_release_cache(snapshot: RuleSearchSnapshot, *, rule: Rule) -> bool:
    inline_search = dict(cast(dict[str, Any], snapshot.inline_search or {}))
    raw_rows = inline_search.get("unified_raw_results")
    if not isinstance(raw_rows, list):
        inline_search = dict(cast(dict[str, Any], inline_search_from_snapshot(snapshot)))
        raw_rows = inline_search.get("unified_raw_results")
    typed_rows = [item for item in raw_rows or [] if isinstance(item, dict)]
    state = _rule_local_filter_state(rule)
    filtered_count, hidden_reasons = _rule_local_filter_diagnostics_from_rows(
        rule,
        typed_rows,
        state=state,
    )
    cache_key = _rule_local_filter_cache_key(rule)
    current_key = str(
        snapshot.release_filter_cache_key or inline_search.get("rule_local_filter_cache_key") or ""
    )
    current_count = (
        snapshot.release_filtered_count
        if snapshot.release_filtered_count is not None
        else inline_search.get("rule_local_filtered_count")
    )
    count_matches = (
        current_count is not None and _coerce_int(current_count, default=-1) == filtered_count
    )
    current_hidden_reasons = inline_search.get("rule_local_hidden_reasons")
    hidden_reasons_match = (
        isinstance(current_hidden_reasons, dict)
        and {
            str(reason): _coerce_int(count, default=0)
            for reason, count in current_hidden_reasons.items()
        }
        == hidden_reasons
    )
    fetched_count = len(typed_rows)
    summary_matches = (
        rule.last_snapshot_at == snapshot.fetched_at
        and rule.last_release_filtered_count == filtered_count
        and rule.last_release_fetched_count == fetched_count
        and rule.last_exact_filtered_count == snapshot.exact_filtered_count
        and rule.last_exact_fetched_count == snapshot.exact_fetched_count
    )
    if (
        current_key == cache_key
        and count_matches
        and hidden_reasons_match
        and snapshot.release_fetched_count == fetched_count
        and summary_matches
    ):
        return False
    inline_search["rule_local_filter_cache_key"] = cache_key
    inline_search["rule_local_filtered_count"] = filtered_count
    inline_search["rule_local_hidden_reasons"] = hidden_reasons
    inline_search["combined_fetched_count"] = fetched_count
    snapshot.inline_search = cast(dict[str, object], inline_search)
    snapshot.release_filter_cache_key = cache_key
    snapshot.release_filtered_count = filtered_count
    snapshot.release_fetched_count = fetched_count
    rule.last_snapshot_at = snapshot.fetched_at
    rule.last_release_filtered_count = filtered_count
    rule.last_release_fetched_count = fetched_count
    rule.last_exact_filtered_count = snapshot.exact_filtered_count
    rule.last_exact_fetched_count = snapshot.exact_fetched_count
    return True


def _apply_rule_feed_scope(
    payload: JackettSearchRequest,
    rule: Rule,
    *,
    feed_urls_override: list[str] | None = None,
) -> tuple[JackettSearchRequest, str | None]:
    effective_feed_urls = (
        _normalize_feed_url_list(feed_urls_override)
        if feed_urls_override is not None
        else list(rule.feed_urls or [])
    )
    feed_indexers: list[str] = []
    seen_indexers: set[str] = set()
    for feed_url in effective_feed_urls:
        indexer = _feed_url_to_indexer_slug(feed_url)
        if not indexer or indexer in seen_indexers:
            continue
        seen_indexers.add(indexer)
        feed_indexers.append(indexer)

    if not feed_indexers:
        if effective_feed_urls:
            return (
                payload,
                "Affected feeds could not be mapped to Jackett indexers; using default scope.",
            )
        return payload, None

    if len(feed_indexers) == 1:
        scoped_indexer = feed_indexers[0]
        return (
            payload.model_copy(
                update={
                    "indexer": scoped_indexer,
                    "filter_indexers": [scoped_indexer],
                }
            ),
            f"Scoped to affected feed indexer: {scoped_indexer}.",
        )

    merged_filter_indexers = list(payload.filter_indexers or [])
    seen = {item.casefold() for item in merged_filter_indexers}
    for item in feed_indexers:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged_filter_indexers.append(item)

    return (
        payload.model_copy(
            update={
                "indexer": "all",
                "filter_indexers": merged_filter_indexers,
            }
        ),
        f"Scoped to affected feed indexers: {', '.join(feed_indexers)}.",
    )


def _apply_rule_search_scope(
    payload: JackettSearchRequest,
    rule: Rule,
    *,
    feed_urls_override: list[str] | None = None,
) -> tuple[JackettSearchRequest, str | None]:
    if feed_urls_override is not None:
        return _apply_rule_feed_scope(payload, rule, feed_urls_override=feed_urls_override)

    explicit_indexers = _normalize_search_indexers(
        list(getattr(rule, "search_indexers", []) or [])
    )
    if explicit_indexers:
        return _apply_indexer_scope(
            payload,
            explicit_indexers,
            singular_notice="Scoped to saved Jackett search indexer: {indexer}.",
            plural_notice="Scoped to saved Jackett search indexers: {indexers}.",
        )
    return _apply_rule_feed_scope(payload, rule)


def _unexpected_error_message(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip()
    label = exc.__class__.__name__
    if detail:
        return f"{prefix} ({label}): {detail}"
    return f"{prefix} ({label})."


def _release_state_from_counts(filtered_count: int, fetched_count: int) -> str:
    if filtered_count > 0:
        return "matches"
    if fetched_count > 0:
        return "no_matches"
    return "empty"


def _release_state_rank(state: str) -> int:
    ranking = {
        "matches": 0,
        "no_matches": 1,
        "empty": 2,
        "unknown": 3,
        "error": 4,
    }
    return ranking.get(state, 5)


def _exact_state_rank(state: str) -> int:
    ranking = {
        "exact": 0,
        "fallback_only": 1,
        "none": 2,
        "unknown": 3,
    }
    return ranking.get(state, 4)


def _release_signal_from_counts(
    *,
    filtered_count: int,
    fetched_count: int,
    exact_filtered_count: int,
    exact_fetched_count: int,
) -> tuple[str, str, int]:
    if exact_filtered_count > 0:
        return "exact", "Exact", 0
    if filtered_count > 0:
        return "fallback", "Fallback", 1
    if exact_fetched_count > 0:
        return "no_exact", "No exact", 2
    if fetched_count > 0:
        return "no_matches", "No matches", 3
    return "no_matches", "No matches", 3


def _coerce_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _exact_counts_from_snapshot(snapshot: RuleSearchSnapshot) -> tuple[int, int]:
    if snapshot.exact_filtered_count is not None and snapshot.exact_fetched_count is not None:
        return int(snapshot.exact_filtered_count), int(snapshot.exact_fetched_count)
    inline_search = cast(dict[str, Any], snapshot.inline_search or {})
    exact_filtered_count = _coerce_int(inline_search.get("exact_filtered_count"), default=0)
    exact_fetched_count = _coerce_int(inline_search.get("exact_fetched_count"), default=0)
    if exact_filtered_count or exact_fetched_count:
        return exact_filtered_count, exact_fetched_count
    payload = cast(dict[str, Any], snapshot.payload or {})
    if bool(payload.get("imdb_id_only")):
        filtered_primary = inline_search.get("results")
        raw_primary = inline_search.get("raw_results")
        filtered_count = len(filtered_primary) if isinstance(filtered_primary, list) else 0
        fetched_count = len(raw_primary) if isinstance(raw_primary, list) else 0
        return filtered_count, fetched_count
    return 0, 0


def release_state_from_snapshot(
    snapshot: RuleSearchSnapshot | None,
    *,
    rule: Rule | None = None,
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "state": "unknown",
            "rank": _release_state_rank("unknown"),
            "label": "No snapshot",
            "signal_state": "no_snapshot",
            "signal_rank": 4,
            "signal_label": "No snapshot",
            "combined_filtered_count": 0,
            "combined_fetched_count": 0,
            "exact_state": "unknown",
            "exact_rank": _exact_state_rank("unknown"),
            "exact_label": "No snapshot",
            "exact_filtered_count": 0,
            "exact_fetched_count": 0,
            "snapshot_fetched_at": None,
        }
    if rule is not None:
        cache_key = str(snapshot.release_filter_cache_key or "")
        expected_key = _rule_local_filter_cache_key(rule)
        if cache_key and cache_key == expected_key and snapshot.release_filtered_count is not None:
            filtered_count = int(snapshot.release_filtered_count)
        elif not cache_key and snapshot.release_filtered_count is not None:
            filtered_count = int(snapshot.release_filtered_count)
        else:
            raw_rows = _snapshot_unified_raw_rows(snapshot)
            if snapshot.release_filtered_count is not None and not raw_rows:
                filtered_count = int(snapshot.release_filtered_count)
            else:
                filtered_count = _rule_local_filtered_count_from_rows(rule, raw_rows)
    else:
        if snapshot.release_filtered_count is not None:
            filtered_count = int(snapshot.release_filtered_count)
        else:
            inline_search = cast(dict[str, Any], snapshot.inline_search or {})
            filtered_count = _coerce_int(inline_search.get("combined_filtered_count"), default=0)
            if "combined_filtered_count" not in inline_search:
                filtered_count = sum(
                    1
                    for row in _snapshot_unified_raw_rows(snapshot)
                    if isinstance(row, dict) and row.get("visible") is not False
                )
    if snapshot.release_fetched_count is not None:
        fetched_count = int(snapshot.release_fetched_count)
    else:
        inline_search = cast(dict[str, Any], snapshot.inline_search or {})
        fetched_count = _coerce_int(inline_search.get("combined_fetched_count"), default=-1)
    if fetched_count < 0:
        fetched_count = len(_snapshot_unified_raw_rows(snapshot))
    state = _release_state_from_counts(filtered_count, fetched_count)
    if rule is None:
        exact_filtered_count = int(snapshot.exact_filtered_count or 0)
        if snapshot.exact_fetched_count is not None:
            exact_fetched_count = int(snapshot.exact_fetched_count)
        elif snapshot.release_fetched_count is not None:
            exact_fetched_count = int(snapshot.release_fetched_count)
        else:
            exact_fetched_count = 0
    else:
        exact_filtered_count, exact_fetched_count = _exact_counts_from_snapshot(snapshot)
    if exact_filtered_count > 0:
        exact_state = "exact"
    elif filtered_count > 0:
        exact_state = "fallback_only"
    else:
        exact_state = "none"
    signal_state, signal_label, signal_rank = _release_signal_from_counts(
        filtered_count=filtered_count,
        fetched_count=fetched_count,
        exact_filtered_count=exact_filtered_count,
        exact_fetched_count=exact_fetched_count,
    )
    label = {
        "matches": "Matches found",
        "no_matches": "No matches",
        "empty": "No fetched rows",
    }.get(state, "Unknown")
    exact_label = {
        "exact": "Exact found",
        "fallback_only": "Fallback only",
        "none": "No exact",
        "unknown": "No snapshot",
    }.get(exact_state, "Unknown")
    return {
        "state": state,
        "rank": _release_state_rank(state),
        "label": label,
        "signal_state": signal_state,
        "signal_rank": signal_rank,
        "signal_label": signal_label,
        "combined_filtered_count": filtered_count,
        "combined_fetched_count": fetched_count,
        "exact_state": exact_state,
        "exact_rank": _exact_state_rank(exact_state),
        "exact_label": exact_label,
        "exact_filtered_count": exact_filtered_count,
        "exact_fetched_count": exact_fetched_count,
        "snapshot_fetched_at": snapshot.fetched_at,
    }


def release_state_from_cached_counts(
    *,
    filtered_count: int | None,
    fetched_count: int | None,
    exact_filtered_count: int | None,
    exact_fetched_count: int | None,
    snapshot_fetched_at: datetime | None,
) -> dict[str, Any]:
    if snapshot_fetched_at is None:
        return release_state_from_snapshot(None)

    normalized_filtered_count = int(filtered_count or 0)
    normalized_fetched_count = int(fetched_count or 0)
    normalized_exact_filtered_count = int(exact_filtered_count or 0)
    normalized_exact_fetched_count = int(exact_fetched_count or 0)
    state = _release_state_from_counts(normalized_filtered_count, normalized_fetched_count)
    exact_state = (
        "exact"
        if normalized_exact_filtered_count > 0
        else "fallback_only"
        if normalized_filtered_count > 0
        else "none"
    )
    signal_state, signal_label, signal_rank = _release_signal_from_counts(
        filtered_count=normalized_filtered_count,
        fetched_count=normalized_fetched_count,
        exact_filtered_count=normalized_exact_filtered_count,
        exact_fetched_count=normalized_exact_fetched_count,
    )
    return {
        "state": state,
        "rank": _release_state_rank(state),
        "label": {
            "matches": "Matches found",
            "no_matches": "No matches",
            "empty": "No fetched rows",
        }.get(state, "Unknown"),
        "signal_state": signal_state,
        "signal_rank": signal_rank,
        "signal_label": signal_label,
        "combined_filtered_count": normalized_filtered_count,
        "combined_fetched_count": normalized_fetched_count,
        "exact_state": exact_state,
        "exact_rank": _exact_state_rank(exact_state),
        "exact_label": {
            "exact": "Exact found",
            "fallback_only": "Fallback only",
            "none": "No exact",
            "unknown": "No snapshot",
        }.get(exact_state, "Unknown"),
        "exact_filtered_count": normalized_exact_filtered_count,
        "exact_fetched_count": normalized_exact_fetched_count,
        "snapshot_fetched_at": snapshot_fetched_at,
    }


def execute_rule_fetch(
    session: Session,
    *,
    rule: Rule,
    feed_urls_override: list[str] | None = None,
) -> dict[str, Any]:
    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.app_ready:
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": False,
            "state": "error",
            "rank": _release_state_rank("error"),
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": [],
            "error": "Jackett app search is not configured in Settings.",
        }

    payload_from_rule: JackettSearchRequest | None = None
    ignored_full_regex = False
    notices: list[str] = []

    try:
        payload_from_rule, ignored_full_regex = build_search_request_from_rule(rule)
    except ValidationError:
        ignored_full_regex = True
        try:
            payload_from_rule, _ = build_reduced_search_request_from_rule(rule)
            notices.append("Rule keywords were reduced to stay within structured-search limits.")
        except Exception:
            payload_from_rule = _title_only_search_request_from_rule(rule)
            if payload_from_rule is not None:
                notices.append("Rule search fell back to title-only compatibility mode.")
    except Exception:
        ignored_full_regex = True
        payload_from_rule = _title_only_search_request_from_rule(rule)
        if payload_from_rule is not None:
            notices.append("Rule search needed compatibility fallback and used title-only mode.")

    if payload_from_rule is None:
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": False,
            "state": "error",
            "rank": _release_state_rank("error"),
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": notices,
            "error": "Rule could not be converted into a Jackett search payload.",
        }

    payload_from_rule, feed_scope_notice = _apply_rule_search_scope(
        payload_from_rule,
        rule,
        feed_urls_override=feed_urls_override,
    )
    if feed_scope_notice:
        notices.append(feed_scope_notice)

    try:
        payload_from_rule = _auto_imdb_first_payload(payload_from_rule)
        client = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        )
        run = client.search(payload_from_rule)
        all_results = [
            *list(run.raw_results or []),
            *list(run.results or []),
            *list(run.raw_fallback_results or []),
            *list(run.fallback_results or []),
        ]
        client.enrich_result_category_labels(all_results)
        sync_category_catalog_from_results(session, all_results)
        sync_category_catalog_from_indexer_map(
            session,
            client.configured_indexer_category_labels(),
        )
        snapshot = save_rule_search_snapshot(
            session,
            rule_id=rule.id,
            payload=payload_from_rule,
            run=run,
            ignored_full_regex=ignored_full_regex,
        )
        refresh_snapshot_release_cache(snapshot, rule=rule)
        session.commit()
        release = release_state_from_snapshot(snapshot, rule=rule)
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": True,
            "state": str(release.get("state") or "unknown"),
            "rank": int(release.get("rank") or _release_state_rank("unknown")),
            "filtered_count": int(release.get("combined_filtered_count") or 0),
            "fetched_count": int(release.get("combined_fetched_count") or 0),
            "warnings": list(run.warning_messages or []),
            "notices": notices,
            "error": "",
            "request_variants": list(run.request_variants or run.query_variants),
            "fallback_request_variants": list(run.fallback_request_variants or []),
            "snapshot_fetched_at": _iso_datetime(snapshot.fetched_at),
        }
    except JackettClientError as exc:
        session.rollback()
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": False,
            "state": "error",
            "rank": _release_state_rank("error"),
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": notices,
            "error": str(exc),
        }
    except Exception as exc:  # pragma: no cover - defensive fallback
        session.rollback()
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": False,
            "state": "error",
            "rank": _release_state_rank("error"),
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": notices,
            "error": _unexpected_error_message("Rule fetch failed unexpectedly", exc),
        }


def _rule_snapshot_fetch_sort_value(
    rule: Rule,
    snapshot_by_rule_id: dict[str, RuleSearchSnapshot],
) -> tuple[int, datetime, str]:
    snapshot = snapshot_by_rule_id.get(rule.id)
    if snapshot is None:
        return (0, datetime.min.replace(tzinfo=UTC), rule.rule_name.casefold())
    fetched_at = snapshot.fetched_at or datetime.min.replace(tzinfo=UTC)
    return (1, fetched_at, rule.rule_name.casefold())


def _prioritize_fetch_rules(session: Session, rules: list[Rule]) -> list[Rule]:
    if not rules:
        return []
    snapshots = session.scalars(
        select(RuleSearchSnapshot).where(
            RuleSearchSnapshot.rule_id.in_([rule.id for rule in rules])
        )
    ).all()
    snapshot_by_rule_id = {snapshot.rule_id: snapshot for snapshot in snapshots}
    return sorted(
        rules,
        key=lambda rule: _rule_snapshot_fetch_sort_value(rule, snapshot_by_rule_id),
    )


def _execute_rule_fetch_for_rule_id(rule_id: str) -> dict[str, Any]:
    session_factory = get_session_factory()
    worker_session = session_factory()
    try:
        rule = worker_session.get(Rule, rule_id)
        if rule is None:
            return {
                "rule_id": rule_id,
                "rule_name": "",
                "success": False,
                "state": "error",
                "rank": _release_state_rank("error"),
                "filtered_count": 0,
                "fetched_count": 0,
                "warnings": [],
                "notices": [],
                "error": "Rule not found.",
            }
        return execute_rule_fetch(worker_session, rule=rule)
    finally:
        worker_session.close()


def run_rules_fetch_batch(
    session: Session,
    *,
    run_all: bool,
    rule_ids: list[str] | None = None,
    include_disabled: bool = False,
) -> dict[str, Any]:
    if not _RULE_FETCH_RUN_LOCK.acquire(blocking=False):
        return {
            "status": "busy",
            "message": "Another rule fetch run is already in progress.",
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "results": [],
        }

    started_at = utcnow()
    try:
        settings = SettingsService.get_or_create(session)
        jackett = SettingsService.resolve_jackett(settings)
        if not jackett.app_ready:
            return {
                "status": "error",
                "message": "Jackett app search is not configured in Settings.",
                "attempted": 0,
                "succeeded": 0,
                "failed": 0,
                "results": [],
            }

        if run_all:
            statement = select(Rule)
            if not include_disabled:
                statement = statement.where(Rule.enabled.is_(True))
            rules = session.scalars(statement.order_by(Rule.rule_name.asc())).all()
        else:
            normalized_rule_ids: list[str] = []
            seen_rule_ids: set[str] = set()
            for raw_rule_id in list(rule_ids or []):
                candidate = str(raw_rule_id or "").strip()
                if not candidate or candidate in seen_rule_ids:
                    continue
                seen_rule_ids.add(candidate)
                normalized_rule_ids.append(candidate)
            if not normalized_rule_ids:
                return {
                    "status": "error",
                    "message": "Select one or more rules to run.",
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "results": [],
                }
            selected_rules = session.scalars(
                select(Rule).where(Rule.id.in_(normalized_rule_ids))
            ).all()
            by_id = {rule.id: rule for rule in selected_rules}
            rules = [by_id[rule_id] for rule_id in normalized_rule_ids if rule_id in by_id]
            if not include_disabled:
                rules = [rule for rule in rules if rule.enabled]

        if not rules:
            return {
                "status": "ok",
                "message": "No rules matched the selected scope.",
                "attempted": 0,
                "succeeded": 0,
                "failed": 0,
                "results": [],
            }

        rules = _prioritize_fetch_rules(session, list(rules))
        parallelism = normalize_rule_fetch_parallelism(
            getattr(settings, "rules_fetch_parallelism", DEFAULT_RULE_FETCH_PARALLELISM)
        )
        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        if parallelism <= 1 or len(rules) <= 1:
            for rule in rules:
                run_result = execute_rule_fetch(session, rule=rule)
                results.append(run_result)
        else:
            rule_ids = [rule.id for rule in rules]
            with ThreadPoolExecutor(max_workers=parallelism) as executor:
                results.extend(executor.map(_execute_rule_fetch_for_rule_id, rule_ids))

        for run_result in results:
            if run_result.get("success"):
                succeeded += 1
            else:
                failed += 1

        attempted = len(rules)
        if failed == 0:
            message = f"Completed Jackett fetch for {succeeded}/{attempted} rule(s)."
            status = "ok"
        elif succeeded == 0:
            message = f"All {failed}/{attempted} rule fetches failed."
            status = "error"
        else:
            message = f"Completed with failures: {succeeded} succeeded, {failed} failed."
            status = "partial"

        return {
            "status": status,
            "message": message,
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
            "started_at": _iso_datetime(started_at),
            "completed_at": _iso_datetime(utcnow()),
        }
    finally:
        _RULE_FETCH_RUN_LOCK.release()


def update_schedule_settings(
    session: Session,
    *,
    enabled: bool,
    interval_minutes: int,
    scope: str,
) -> dict[str, Any]:
    settings = SettingsService.get_or_create(session)
    normalized_interval = normalize_schedule_interval_minutes(interval_minutes)
    normalized_scope = normalize_schedule_scope(scope)
    settings.rules_fetch_schedule_enabled = bool(enabled)
    settings.rules_fetch_schedule_interval_minutes = normalized_interval
    settings.rules_fetch_schedule_scope = normalized_scope
    if enabled:
        settings.rules_fetch_schedule_next_run_at = schedule_next_run_at(
            interval_minutes=normalized_interval
        )
        if not str(getattr(settings, "rules_fetch_schedule_last_status", "")).strip():
            settings.rules_fetch_schedule_last_status = "idle"
    else:
        settings.rules_fetch_schedule_next_run_at = None
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return schedule_payload(settings)


def run_scheduled_fetch_now(session: Session) -> dict[str, Any]:
    settings = SettingsService.get_or_create(session)
    scope = normalize_schedule_scope(getattr(settings, "rules_fetch_schedule_scope", None))
    include_disabled = scope == "all"
    batch = run_rules_fetch_batch(
        session,
        run_all=True,
        include_disabled=include_disabled,
    )
    completed_at = utcnow()
    interval_minutes = normalize_schedule_interval_minutes(
        getattr(
            settings,
            "rules_fetch_schedule_interval_minutes",
            DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
        )
    )
    settings.rules_fetch_schedule_last_run_at = completed_at
    settings.rules_fetch_schedule_next_run_at = (
        schedule_next_run_at(from_time=completed_at, interval_minutes=interval_minutes)
        if bool(getattr(settings, "rules_fetch_schedule_enabled", False))
        else None
    )
    settings.rules_fetch_schedule_last_status = str(batch.get("status") or "idle")
    settings.rules_fetch_schedule_last_message = str(batch.get("message") or "")
    session.add(settings)
    session.commit()
    batch["schedule"] = schedule_payload(settings)
    return batch


def run_due_scheduled_fetch(session: Session) -> dict[str, Any] | None:
    settings = SettingsService.get_or_create(session)
    if not bool(getattr(settings, "rules_fetch_schedule_enabled", False)):
        return None

    now = utcnow()
    next_run_at = getattr(settings, "rules_fetch_schedule_next_run_at", None)
    interval_minutes = normalize_schedule_interval_minutes(
        getattr(
            settings,
            "rules_fetch_schedule_interval_minutes",
            DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
        )
    )
    if next_run_at is None:
        settings.rules_fetch_schedule_next_run_at = schedule_next_run_at(
            from_time=now,
            interval_minutes=interval_minutes,
        )
        session.add(settings)
        session.commit()
        return None

    if next_run_at.astimezone(UTC) > now.astimezone(UTC):
        return None

    return run_scheduled_fetch_now(session)
