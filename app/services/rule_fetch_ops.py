from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    _normalize_match_text,
    build_reduced_search_request_from_rule,
    build_search_request_from_rule,
    clamp_search_query_text,
)
from app.services.quality_filters import (
    grouped_tokens_to_regex,
    normalize_quality_tokens,
    tokens_to_regex,
)
from app.services.rule_builder import (
    build_episode_progress_fragment,
    build_manual_must_contain_fragments,
    looks_like_full_must_contain_override,
    normalize_release_year,
    parse_additional_include_groups,
)
from app.services.rule_search_snapshots import (
    inline_search_from_snapshot,
    save_rule_search_snapshot,
)
from app.services.settings_service import SettingsService

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
        getattr(settings, "rules_fetch_schedule_interval_minutes", DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES)
    )
    scope = normalize_schedule_scope(getattr(settings, "rules_fetch_schedule_scope", DEFAULT_RULE_FETCH_SCHEDULE_SCOPE))
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


def _rule_local_generated_pattern(rule: Rule) -> str:
    manual_must_contain = str(rule.must_contain_override or "").strip()
    has_episode_floor = rule.start_season is not None and rule.start_episode is not None
    if not manual_must_contain and not has_episode_floor:
        return ""
    if looks_like_full_must_contain_override(manual_must_contain):
        return manual_must_contain
    fragments: list[str] = []
    episode_floor_fragment = build_episode_progress_fragment(rule.start_season, rule.start_episode)
    if episode_floor_fragment:
        fragments.append(episode_floor_fragment)
    fragments.extend(build_manual_must_contain_fragments(manual_must_contain))
    if not fragments:
        return ""
    return "(?i)" + "".join(f"(?=.*{fragment})" for fragment in fragments if fragment)


def _rule_local_filter_state(rule: Rule) -> dict[str, Any]:
    include_groups = parse_additional_include_groups(rule.additional_includes)
    required_include_terms = [group[0] for group in include_groups if len(group) == 1]
    any_include_groups = [group for group in include_groups if len(group) > 1]
    excluded_terms = _dedupe_terms(
        [item for group in parse_additional_include_groups(rule.must_not_contain) for item in group]
    )

    include_tokens = normalize_quality_tokens(rule.quality_include_tokens)
    include_token_set = set(include_tokens)
    exclude_tokens = [
        token
        for token in normalize_quality_tokens(rule.quality_exclude_tokens)
        if token not in include_token_set
    ]
    include_quality_patterns = [
        compiled
        for compiled in (
            _compile_pattern(fragment)
            for fragment in grouped_tokens_to_regex(include_tokens)
        )
        if compiled is not None
    ]
    exclude_quality_pattern = _compile_pattern(tokens_to_regex(exclude_tokens))
    generated_pattern = _compile_generated_pattern(_rule_local_generated_pattern(rule))

    release_year = normalize_release_year(rule.release_year) if bool(rule.include_release_year) else ""
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
        key
        for item in feed_indexers
        for key in _build_indexer_key_variants(item)
    }

    return {
        "keywords_all": required_include_terms,
        "keywords_any_groups": any_include_groups,
        "keywords_not": excluded_terms,
        "quality_include_patterns": include_quality_patterns,
        "quality_exclude_pattern": exclude_quality_pattern,
        "generated_pattern": generated_pattern,
        "release_year": release_year,
        "feed_scope_blocks_all": feed_scope_blocks_all,
        "allowed_feed_indexer_keys": allowed_feed_indexer_keys,
    }


def _rule_local_filter_cache_key(rule: Rule) -> str:
    return json.dumps(
        {
            "additional_includes": str(rule.additional_includes or "").strip(),
            "must_not_contain": str(rule.must_not_contain or "").strip(),
            "quality_include_tokens": normalize_quality_tokens(rule.quality_include_tokens),
            "quality_exclude_tokens": normalize_quality_tokens(rule.quality_exclude_tokens),
            "must_contain_override": str(rule.must_contain_override or "").strip(),
            "start_season": rule.start_season,
            "start_episode": rule.start_episode,
            "include_release_year": bool(rule.include_release_year),
            "release_year": normalize_release_year(rule.release_year) if bool(rule.include_release_year) else "",
            "feed_urls": _normalize_feed_url_list(list(rule.feed_urls or [])),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _snapshot_row_matches_rule_filters(row: dict[str, Any], state: dict[str, Any]) -> bool:
    if bool(state.get("feed_scope_blocks_all")):
        return False

    text_surface = str(row.get("text_surface") or "").strip()
    if not text_surface:
        text_surface = _normalize_match_text(str(row.get("title") or ""))
    regex_surface = str(row.get("title") or row.get("text_surface") or "").strip()

    for keyword in state.get("keywords_all", []):
        if not _matches_included_keyword(text_surface, str(keyword)):
            return False

    for group in state.get("keywords_any_groups", []):
        if not any(_matches_included_keyword(text_surface, str(keyword)) for keyword in group):
            return False

    for keyword in state.get("keywords_not", []):
        if _matches_excluded_keyword(text_surface, str(keyword)):
            return False

    for include_pattern in state.get("quality_include_patterns", []):
        if not include_pattern.search(regex_surface):
            return False

    exclude_pattern = state.get("quality_exclude_pattern")
    if exclude_pattern is not None and exclude_pattern.search(regex_surface):
        return False

    generated_pattern = state.get("generated_pattern")
    if generated_pattern is not None and not generated_pattern.search(regex_surface):
        return False

    release_year = str(state.get("release_year") or "").strip()
    if release_year:
        result_year = normalize_release_year(str(row.get("year") or row.get("title") or ""))
        if not result_year or result_year != release_year:
            return False

    allowed_feed_indexer_keys = set(state.get("allowed_feed_indexer_keys", set()) or set())
    if allowed_feed_indexer_keys:
        indexer_keys = set(_build_indexer_key_variants(row.get("indexer") or ""))
        if not indexer_keys.intersection(allowed_feed_indexer_keys):
            return False

    return True


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


def _rule_local_filtered_count_from_rows(
    rule: Rule,
    raw_rows: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
) -> int:
    filter_state = state or _rule_local_filter_state(rule)
    filtered_count = 0
    for item in raw_rows:
        if _snapshot_row_matches_rule_filters(item, filter_state):
            filtered_count += 1
    return filtered_count


def _rule_local_filtered_count(rule: Rule, inline_search: dict[str, Any]) -> int:
    raw_rows = inline_search.get("unified_raw_results")
    if not isinstance(raw_rows, list):
        return 0
    typed_rows = [item for item in raw_rows if isinstance(item, dict)]
    return _rule_local_filtered_count_from_rows(rule, typed_rows)


def refresh_snapshot_release_cache(snapshot: RuleSearchSnapshot, *, rule: Rule) -> bool:
    inline_search = dict(cast(dict[str, Any], snapshot.inline_search or {}))
    raw_rows = inline_search.get("unified_raw_results")
    if not isinstance(raw_rows, list):
        inline_search = dict(cast(dict[str, Any], inline_search_from_snapshot(snapshot)))
        raw_rows = inline_search.get("unified_raw_results")
    typed_rows = [item for item in raw_rows or [] if isinstance(item, dict)]
    state = _rule_local_filter_state(rule)
    filtered_count = _rule_local_filtered_count_from_rows(rule, typed_rows, state=state)
    cache_key = _rule_local_filter_cache_key(rule)
    current_key = str(snapshot.release_filter_cache_key or inline_search.get("rule_local_filter_cache_key") or "")
    current_count = (
        snapshot.release_filtered_count
        if snapshot.release_filtered_count is not None
        else inline_search.get("rule_local_filtered_count")
    )
    count_matches = current_count is not None and _coerce_int(current_count, default=-1) == filtered_count
    fetched_count = len(typed_rows)
    if (
        current_key == cache_key
        and count_matches
        and snapshot.release_fetched_count == fetched_count
    ):
        return False
    inline_search["rule_local_filter_cache_key"] = cache_key
    inline_search["rule_local_filtered_count"] = filtered_count
    inline_search["combined_fetched_count"] = fetched_count
    snapshot.inline_search = cast(dict[str, object], inline_search)
    snapshot.release_filter_cache_key = cache_key
    snapshot.release_filtered_count = filtered_count
    snapshot.release_fetched_count = fetched_count
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
            return payload, "Affected feeds could not be mapped to Jackett indexers; using default scope."
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


def _coerce_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


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
            "combined_filtered_count": 0,
            "combined_fetched_count": 0,
            "snapshot_fetched_at": None,
        }
    if rule is not None:
        cache_key = str(snapshot.release_filter_cache_key or "")
        expected_key = _rule_local_filter_cache_key(rule)
        if cache_key and cache_key == expected_key and snapshot.release_filtered_count is not None:
            filtered_count = int(snapshot.release_filtered_count)
        else:
            filtered_count = _rule_local_filtered_count_from_rows(
                rule,
                _snapshot_unified_raw_rows(snapshot),
            )
    else:
        if snapshot.release_filtered_count is not None:
            filtered_count = int(snapshot.release_filtered_count)
        else:
            inline_search = cast(dict[str, Any], snapshot.inline_search or {})
            filtered_count = _coerce_int(inline_search.get("combined_filtered_count"), default=0)
    if snapshot.release_fetched_count is not None:
        fetched_count = int(snapshot.release_fetched_count)
    else:
        inline_search = cast(dict[str, Any], snapshot.inline_search or {})
        fetched_count = _coerce_int(inline_search.get("combined_fetched_count"), default=-1)
    if fetched_count < 0:
        fetched_count = len(_snapshot_unified_raw_rows(snapshot))
    state = _release_state_from_counts(filtered_count, fetched_count)
    label = {
        "matches": "Matches found",
        "no_matches": "No matches",
        "empty": "No fetched rows",
    }.get(state, "Unknown")
    return {
        "state": state,
        "rank": _release_state_rank(state),
        "label": label,
        "combined_filtered_count": filtered_count,
        "combined_fetched_count": fetched_count,
        "snapshot_fetched_at": snapshot.fetched_at,
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

    payload_from_rule, feed_scope_notice = _apply_rule_feed_scope(
        payload_from_rule,
        rule,
        feed_urls_override=feed_urls_override,
    )
    if feed_scope_notice:
        notices.append(feed_scope_notice)

    try:
        payload_from_rule = _auto_imdb_first_payload(payload_from_rule)
        client = JackettClient(jackett.api_url, jackett.api_key)
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
            selected_rules = session.scalars(select(Rule).where(Rule.id.in_(normalized_rule_ids))).all()
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

        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for rule in rules:
            run_result = execute_rule_fetch(session, rule=rule)
            results.append(run_result)
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
        getattr(settings, "rules_fetch_schedule_interval_minutes", DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES)
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
        getattr(settings, "rules_fetch_schedule_interval_minutes", DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES)
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
