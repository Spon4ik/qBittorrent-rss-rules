from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, load_only

from app.db import get_db_session, get_session_factory
from app.models import (
    MediaType,
    QualityMode,
    QualityProfile,
    Rule,
    RuleSearchSnapshot,
    media_type_choices,
    media_type_label,
)
from app.schemas import JackettSearchRequest
from app.services.category_catalog import (
    resolve_category_labels,
    sync_category_catalog_from_indexer_map,
    sync_category_catalog_from_results,
)
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    build_reduced_search_request_from_rule,
    build_search_request_from_rule,
    clamp_search_query_text,
    expand_grouped_quality_search_terms,
    expand_quality_search_terms,
    feed_indexer_slug,
    quality_pattern_map,
    quality_search_term_map,
)
from app.services.metadata import (
    MetadataClient,
    MetadataLookupError,
    MetadataLookupProvider,
    default_metadata_lookup_provider,
    metadata_lookup_provider_catalog,
    metadata_lookup_provider_choices,
)
from app.services.quality_filters import (
    available_filter_profile_choices,
    available_filter_profile_choices_for_media_type,
    detect_matching_filter_profile_key,
    effective_rule_quality_tokens,
    preview_quality_taxonomy_update,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    quality_profile_label,
    quality_taxonomy_snapshot,
    read_quality_taxonomy_text,
    recent_quality_taxonomy_audit_entries,
    resolve_quality_profile_rules,
)
from app.services.rule_fetch_ops import (
    refresh_snapshot_release_cache,
    release_state_from_snapshot,
    run_due_scheduled_fetch,
    schedule_payload,
)
from app.services.rule_search_snapshots import (
    build_inline_search_payload,
    get_rule_search_snapshot,
    inline_search_from_snapshot,
    save_rule_search_snapshot,
)
from app.services.settings_service import (
    DEFAULT_SEARCH_RESULT_VIEW_MODE,
    DEFAULT_SEARCH_SORT_CRITERIA,
    SettingsService,
    normalize_rules_page_sort_direction,
    normalize_rules_page_sort_field,
    normalize_rules_page_view_mode,
    normalize_search_result_view_mode,
    normalize_search_sort_criteria,
)
from app.services.static_assets import compute_static_asset_version
from app.services.watch_state import format_watch_state_source_labels

router = APIRouter()


def _template_context(_: Request) -> dict[str, object]:
    return {"static_asset_version": compute_static_asset_version()}


templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates"),
    context_processors=[_template_context],
)
SEARCH_FILTER_SPLIT_RE = re.compile(r"[\n,;]+")
PLACEHOLDER_CATEGORY_LABEL_RE = re.compile(r"^(?:Unknown \(#[^)]+\)|Category #.+)$")
UNKNOWN_CATEGORY_LABEL_RE = re.compile(r"^Unknown \(#([^)]+)\)$")
RULE_POSTER_BACKFILL_LIMIT = 2
RULE_POSTER_BACKFILL_COOLDOWN = timedelta(hours=6)
RULE_POSTER_BACKFILL_TIMEOUT_SECONDS = 2.0
_RULE_POSTER_BACKFILL_RETRY_AFTER: dict[str, datetime] = {}
_RULE_POSTER_BACKFILL_LOCK = threading.Lock()
_RULE_POSTER_BACKFILL_IN_FLIGHT: set[str] = set()
SERIES_EPISODE_QUERY_RE = re.compile(
    r"(?i)\b(?:s(?P<season>\d{1,2})[\s._-]*e(?P<episode>\d{1,3})|(?P<season_x>\d{1,2})x(?P<episode_x>\d{1,3}))\b"
)


def _sync_search_form_data_with_payload(
    form_data: dict[str, object],
    payload: JackettSearchRequest,
) -> None:
    form_data["query"] = payload.query
    form_data["media_type"] = payload.media_type.value
    form_data["imdb_id"] = payload.imdb_id or ""
    form_data["include_release_year"] = bool(payload.release_year)
    form_data["release_year"] = payload.release_year or ""


def _base_context(request: Request, page_title: str) -> dict[str, object]:
    return {
        "request": request,
        "page_title": page_title,
        "message": request.query_params.get("message"),
        "message_level": request.query_params.get("level", "info"),
    }


def _safe_feed_options(
    session: Session, selected_urls: list[str] | None = None
) -> list[dict[str, str]]:
    settings = SettingsService.get_or_create(session)
    selected_urls = selected_urls or []
    feed_options: list[dict[str, str]] = []
    jackett = SettingsService.resolve_jackett(settings)
    if jackett.app_ready:
        try:
            feed_options = JackettClient(
                jackett.api_url,
                jackett.api_key,
                language_overrides=jackett.language_overrides,
            ).configured_indexer_options()
        except JackettClientError:
            feed_options = []
    seen = {item["url"] for item in feed_options}
    for url in selected_urls:
        if url not in seen:
            indexer = feed_indexer_slug(url)
            if indexer:
                feed_options.append({"label": f"Jackett/{indexer}", "url": url})
            seen.add(url)
    return feed_options


def _safe_rule_language_options(session: Session) -> list[dict[str, str]]:
    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.app_ready:
        return []
    try:
        client = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        )
        return client.configured_language_options()
    except JackettClientError:
        return []


def _default_rule_language(session: Session) -> str:
    return DEFAULT_RULE_LANGUAGE if _safe_rule_language_options(session) else ""


LANGUAGE_FEED_SELECTION_JACKETT_UNAVAILABLE = (
    "Language-based feed selection needs a working Jackett connection."
)
LANGUAGE_FEED_SELECTION_QB_FEEDS_UNAVAILABLE = (
    "Language-based feed selection needs available qB RSS feeds."
)
LANGUAGE_FEED_SELECTION_NO_MATCHING_FEEDS = (
    "No Jackett-backed qB feeds match the selected language."
)
DEFAULT_RULE_LANGUAGE = "ru"


def _normalize_language_list(language: str | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in str(language or "").split(","):
        candidate = raw_item.strip().casefold()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _resolve_language_feed_urls(
    session: Session,
    *,
    language: str | None,
    selected_urls: list[str] | None = None,
) -> tuple[list[str], str | None]:
    normalized_languages = _normalize_language_list(language)
    if not normalized_languages:
        return _normalize_feed_url_list(selected_urls), None

    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.app_ready:
        return [], LANGUAGE_FEED_SELECTION_JACKETT_UNAVAILABLE

    try:
        client = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        )
        feed_map: dict[str, str] = {}
        for normalized_language in normalized_languages:
            feed_map.update(client.configured_indexer_feed_urls(language=normalized_language))
    except JackettClientError:
        return _normalize_feed_url_list(selected_urls), (
            "Language-based feed selection could not read Jackett indexer metadata."
        )

    resolved_feed_urls = list(feed_map.values())

    if not resolved_feed_urls:
        return [], LANGUAGE_FEED_SELECTION_NO_MATCHING_FEEDS
    return _normalize_feed_url_list(resolved_feed_urls), None


def _resolved_rule_form_feed_urls(
    form_feed_urls: list[str] | None,
    *,
    language: str | None,
    resolved_language_feed_urls: list[str],
    language_resolution_notice: str | None,
) -> list[str]:
    if not _normalize_language_list(language):
        return _normalize_feed_url_list(form_feed_urls)
    if language_resolution_notice is not None:
        return _normalize_feed_url_list(form_feed_urls)
    return _normalize_feed_url_list(resolved_language_feed_urls)


def _backfill_missing_rule_posters(
    session: Session,
    *,
    rules: Sequence[Rule],
    settings: Any,
) -> None:
    metadata_config = SettingsService.resolve_metadata(settings)
    if not metadata_config.enabled or not metadata_config.api_key:
        return

    now = datetime.now(UTC)
    candidates: list[Rule] = []
    for rule in rules:
        if rule.media_type not in {MediaType.MOVIE, MediaType.SERIES}:
            continue
        if str(rule.poster_url or "").strip():
            with _RULE_POSTER_BACKFILL_LOCK:
                _RULE_POSTER_BACKFILL_RETRY_AFTER.pop(rule.id, None)
            continue
        with _RULE_POSTER_BACKFILL_LOCK:
            retry_after = _RULE_POSTER_BACKFILL_RETRY_AFTER.get(rule.id)
        if retry_after is not None and retry_after > now:
            continue
        candidates.append(rule)
        if len(candidates) >= RULE_POSTER_BACKFILL_LIMIT:
            break
    if not candidates:
        return

    client = MetadataClient(
        metadata_config.provider,
        metadata_config.api_key,
        timeout=RULE_POSTER_BACKFILL_TIMEOUT_SECONDS,
    )
    updated = False
    for rule in candidates:
        lookup_title = (
            str(rule.normalized_title or "").strip()
            or str(rule.content_name or "").strip()
            or str(rule.rule_name or "").strip()
        )
        if not lookup_title and not str(rule.imdb_id or "").strip():
            with _RULE_POSTER_BACKFILL_LOCK:
                _RULE_POSTER_BACKFILL_RETRY_AFTER[rule.id] = now + RULE_POSTER_BACKFILL_COOLDOWN
            continue
        try:
            if str(rule.imdb_id or "").strip():
                metadata_result = client.lookup_by_imdb_id(str(rule.imdb_id))
            else:
                metadata_result = client.lookup(
                    MetadataLookupProvider.OMDB,
                    lookup_title,
                    rule.media_type
                    if rule.media_type in {MediaType.MOVIE, MediaType.SERIES}
                    else MediaType.SERIES,
                )
        except MetadataLookupError:
            with _RULE_POSTER_BACKFILL_LOCK:
                _RULE_POSTER_BACKFILL_RETRY_AFTER[rule.id] = now + RULE_POSTER_BACKFILL_COOLDOWN
            continue
        poster_url = str(metadata_result.poster_url or "").strip()
        if not poster_url:
            with _RULE_POSTER_BACKFILL_LOCK:
                _RULE_POSTER_BACKFILL_RETRY_AFTER[rule.id] = now + RULE_POSTER_BACKFILL_COOLDOWN
            continue
        with _RULE_POSTER_BACKFILL_LOCK:
            _RULE_POSTER_BACKFILL_RETRY_AFTER.pop(rule.id, None)
        rule.poster_url = poster_url
        updated = True

    if not updated:
        return
    try:
        session.commit()
    except Exception:
        session.rollback()


def _select_rule_poster_backfill_candidate_ids(rules: Sequence[Rule]) -> list[str]:
    now = datetime.now(UTC)
    candidate_ids: list[str] = []
    with _RULE_POSTER_BACKFILL_LOCK:
        for rule in rules:
            if rule.media_type not in {MediaType.MOVIE, MediaType.SERIES}:
                continue
            if str(rule.poster_url or "").strip():
                _RULE_POSTER_BACKFILL_RETRY_AFTER.pop(rule.id, None)
                _RULE_POSTER_BACKFILL_IN_FLIGHT.discard(rule.id)
                continue
            retry_after = _RULE_POSTER_BACKFILL_RETRY_AFTER.get(rule.id)
            if retry_after is not None and retry_after > now:
                continue
            if rule.id in _RULE_POSTER_BACKFILL_IN_FLIGHT:
                continue
            _RULE_POSTER_BACKFILL_IN_FLIGHT.add(rule.id)
            candidate_ids.append(rule.id)
            if len(candidate_ids) >= RULE_POSTER_BACKFILL_LIMIT:
                break
    return candidate_ids


def _clear_rule_poster_backfill_in_flight(rule_ids: Sequence[str]) -> None:
    with _RULE_POSTER_BACKFILL_LOCK:
        for rule_id in rule_ids:
            _RULE_POSTER_BACKFILL_IN_FLIGHT.discard(rule_id)


def _run_rule_poster_backfill(rule_ids: Sequence[str]) -> None:
    session = get_session_factory()()
    try:
        normalized_rule_ids = [
            candidate
            for candidate in (str(rule_id or "").strip() for rule_id in rule_ids)
            if candidate
        ]
        if not normalized_rule_ids:
            return
        settings = SettingsService.get_or_create(session)
        rules_by_id = {
            rule.id: rule
            for rule in session.scalars(select(Rule).where(Rule.id.in_(normalized_rule_ids))).all()
        }
        ordered_rules = [
            rules_by_id[rule_id] for rule_id in normalized_rule_ids if rule_id in rules_by_id
        ]
        if ordered_rules:
            _backfill_missing_rule_posters(session, rules=ordered_rules, settings=settings)
    finally:
        session.close()
        _clear_rule_poster_backfill_in_flight(rule_ids)


def _queue_rule_poster_backfill(rules: Sequence[Rule]) -> None:
    candidate_ids = _select_rule_poster_backfill_candidate_ids(rules)
    if not candidate_ids:
        return
    worker = threading.Thread(
        target=_run_rule_poster_backfill,
        args=(candidate_ids,),
        daemon=True,
        name="rule-poster-backfill",
    )
    try:
        worker.start()
    except Exception:
        _clear_rule_poster_backfill_in_flight(candidate_ids)


def _rule_to_form_data(rule: Rule) -> dict[str, object]:
    include_tokens = list(rule.quality_include_tokens or [])
    exclude_tokens = list(rule.quality_exclude_tokens or [])
    movie_completion_sources = list(getattr(rule, "movie_completion_sources", []) or [])
    movie_completion_auto_disabled = bool(getattr(rule, "movie_completion_auto_disabled", False))
    legacy_jellyfin_auto_disabled = bool(getattr(rule, "jellyfin_auto_disabled", False))
    quality_mode = rule.quality_mode
    if quality_mode is None:
        quality_mode = (
            QualityMode.MANUAL
            if rule.quality_profile in {QualityProfile.PLAIN, QualityProfile.CUSTOM}
            else QualityMode.MANAGED
        )
    return {
        "rule_name": rule.rule_name,
        "content_name": rule.content_name,
        "imdb_id": rule.imdb_id or "",
        "normalized_title": rule.normalized_title,
        "poster_url": rule.poster_url or "",
        "media_type": rule.media_type.value,
        "quality_profile": rule.quality_profile.value,
        "quality_mode": quality_mode.value,
        "filter_profile_key": "",
        "release_year": rule.release_year,
        "include_release_year": rule.include_release_year,
        "additional_includes": rule.additional_includes,
        "quality_include_tokens": include_tokens,
        "quality_exclude_tokens": exclude_tokens,
        "use_regex": rule.use_regex,
        "must_contain_override": rule.must_contain_override or "",
        "must_not_contain": rule.must_not_contain,
        "start_season": rule.start_season if rule.start_season is not None else "",
        "start_episode": rule.start_episode if rule.start_episode is not None else "",
        "jellyfin_search_existing_unseen": bool(
            getattr(rule, "jellyfin_search_existing_unseen", False)
        ),
        "jellyfin_auto_disabled": bool(getattr(rule, "jellyfin_auto_disabled", False)),
        "movie_completion_sources": movie_completion_sources,
        "movie_completion_sources_display": format_watch_state_source_labels(
            movie_completion_sources
        ),
        "movie_completion_auto_disabled": movie_completion_auto_disabled,
        "movie_auto_disabled": movie_completion_auto_disabled or legacy_jellyfin_auto_disabled,
        "jellyfin_existing_episode_numbers": list(
            getattr(rule, "jellyfin_existing_episode_numbers", []) or []
        ),
        "jellyfin_existing_episode_count": len(
            list(getattr(rule, "jellyfin_existing_episode_numbers", []) or [])
        ),
        "episode_filter": rule.episode_filter,
        "ignore_days": rule.ignore_days,
        "add_paused": rule.add_paused,
        "enabled": rule.enabled,
        "smart_filter": rule.smart_filter,
        "language": str(getattr(rule, "language", "") or ""),
        "assigned_category": rule.assigned_category,
        "save_path": rule.save_path,
        "feed_urls": rule.feed_urls,
        "notes": rule.notes,
        "remember_feed_defaults": True,
        "metadata_lookup_provider": default_metadata_lookup_provider(rule.media_type),
    }


def _normalized_media_type(value: str | None) -> str:
    raw_value = str(value or "").strip()
    valid_values = {item.value for item in MediaType}
    if raw_value in valid_values:
        return raw_value
    return MediaType.SERIES.value


def _optional_keyword_regex_fragment(keywords: list[str]) -> str:
    if not keywords:
        return ""
    fragments = []
    for item in keywords:
        candidate = str(item).strip()
        if not candidate:
            continue
        tokens = [re.escape(part) for part in candidate.split()]
        fragments.append(r"[\s._-]*".join(tokens) if tokens else re.escape(candidate))
    return "|".join(fragments)


def _optional_keyword_group_regex(keyword_groups: list[list[str]]) -> str:
    if not keyword_groups:
        return ""
    lines = []
    for group in keyword_groups:
        fragment = _optional_keyword_regex_fragment(group)
        if fragment:
            lines.append(f"(?:{fragment})")
    return "\n".join(lines)


def _parse_search_filter_terms(value: str | None) -> list[str]:
    parts = SEARCH_FILTER_SPLIT_RE.split(str(value or ""))
    terms: list[str] = []
    seen: set[str] = set()
    for raw_part in parts:
        candidate = raw_part.strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(candidate)
    return terms


def _parse_keywords_any_groups(value: str | None) -> list[list[str]]:
    cleaned = str(value or "").strip()
    if not cleaned or "|" not in cleaned:
        return []
    groups: list[list[str]] = []
    for raw_group in cleaned.split("|"):
        normalized_group = _parse_search_filter_terms(raw_group)
        if normalized_group:
            groups.append(normalized_group)
    return groups


def _format_keywords_any_groups(keyword_groups: list[list[str]]) -> str:
    segments: list[str] = []
    for group in keyword_groups:
        normalized_group = _parse_search_filter_terms(", ".join(group))
        if normalized_group:
            segments.append(", ".join(normalized_group))
    return " | ".join(segments)


def _merge_search_terms(*term_lists: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for term_list in term_lists:
        for raw_term in term_list:
            candidate = str(raw_term or "").strip()
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
    return merged


def _normalize_quality_token_selection(
    include_tokens: list[str], exclude_tokens: list[str]
) -> tuple[list[str], list[str]]:
    normalized_include = _merge_search_terms(include_tokens)
    include_keys = {item.casefold() for item in normalized_include}
    normalized_exclude = [
        token
        for token in _merge_search_terms(exclude_tokens)
        if token.casefold() not in include_keys
    ]
    return normalized_include, normalized_exclude


def _query_bool_values(values: list[str]) -> bool:
    return any(
        str(value or "").strip().casefold() in {"1", "true", "on", "yes"} for value in values
    )


def _rule_search_title(rule: Rule) -> str:
    return (
        str(rule.normalized_title or "").strip()
        or str(rule.content_name or "").strip()
        or str(rule.rule_name or "").strip()
    )


def _rule_search_media_type(rule: Rule) -> str:
    raw_value = getattr(rule.media_type, "value", rule.media_type)
    return _normalized_media_type(str(raw_value or ""))


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
            season_number=(
                int(rule.start_season)
                if media_type == MediaType.SERIES and rule.start_season is not None
                else None
            ),
            episode_number=(
                int(rule.start_episode)
                if media_type == MediaType.SERIES and rule.start_episode is not None
                else None
            ),
            release_year=(rule.release_year or None) if rule.include_release_year else None,
        )
    except ValidationError:
        return None


def _auto_imdb_first_payload(payload: JackettSearchRequest) -> JackettSearchRequest:
    if not payload.imdb_id or payload.media_type not in {MediaType.MOVIE, MediaType.SERIES}:
        return payload

    updates: dict[str, object] = {"imdb_id_only": True}
    if payload.media_type == MediaType.SERIES:
        if payload.season_number is not None or payload.episode_number is not None:
            # Series floor-targeted searches should not inherit the parent series year.
            updates["release_year"] = None
        elif payload.season_number is None and payload.episode_number is None:
            match = SERIES_EPISODE_QUERY_RE.search(str(payload.query or ""))
            if match is not None:
                season_value = match.group("season") or match.group("season_x")
                episode_value = match.group("episode") or match.group("episode_x")
                if season_value and episode_value:
                    updates["season_number"] = int(season_value)
                    updates["episode_number"] = int(episode_value)
                    # Series episode queries should not inherit a year floor from the
                    # broader series entry; it over-constrains long-running titles.
                    updates["release_year"] = None

    if updates:
        return payload.model_copy(update=updates)
    return payload


def _prefill_rule_search_form_data(form_data: dict[str, object], rule: Rule) -> None:
    if form_data["query"]:
        return
    fallback_title = clamp_search_query_text(_rule_search_title(rule))
    if not fallback_title:
        return
    form_data["query"] = fallback_title
    form_data["media_type"] = _rule_search_media_type(rule)
    form_data["imdb_id"] = str(rule.imdb_id or "").strip()
    form_data["release_year"] = str(rule.release_year or "").strip()
    form_data["include_release_year"] = bool(rule.include_release_year)
    form_data["additional_includes"] = str(rule.additional_includes or "").strip()
    form_data["must_not_contain"] = str(rule.must_not_contain or "").strip()


def _unexpected_error_message(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip()
    label = exc.__class__.__name__
    if detail:
        return f"{prefix} ({label}): {detail}"
    return f"{prefix} ({label})."


def _format_snapshot_fetched_at(value: datetime | None) -> str:
    if value is None:
        return "unknown time"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _search_result_key(item: object) -> str:
    merge_key = str(getattr(item, "merge_key", "") or "").strip()
    if merge_key:
        return merge_key
    info_hash = str(getattr(item, "info_hash", "") or "").strip().casefold()
    guid = str(getattr(item, "guid", "") or "").strip().casefold()
    title = str(getattr(item, "title", "") or "").strip().casefold()
    size_bytes = getattr(item, "size_bytes", None)
    return f"{info_hash}|{guid}|{title}|{size_bytes}"


def _feed_url_to_indexer_slug(feed_url: str) -> str | None:
    return feed_indexer_slug(feed_url)


def _rule_feed_indexers(rule: Rule) -> list[str]:
    indexers: list[str] = []
    seen: set[str] = set()
    for feed_url in list(rule.feed_urls or []):
        indexer = _feed_url_to_indexer_slug(feed_url)
        if not indexer or indexer in seen:
            continue
        seen.add(indexer)
        indexers.append(indexer)
    return indexers


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


def _apply_rule_feed_scope(
    payload: JackettSearchRequest,
    rule: Rule,
    *,
    feed_urls_override: list[str] | None = None,
) -> tuple[JackettSearchRequest, str | None]:
    if feed_urls_override is None:
        effective_feed_urls = list(rule.feed_urls or [])
    else:
        effective_feed_urls = _normalize_feed_url_list(feed_urls_override)
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
                "Affected feeds could not be mapped to Jackett indexers; using default indexer scope.",
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
            f"Search scoped to affected feed indexer: {scoped_indexer}.",
        )

    merged_filter_indexers = _merge_search_terms(
        list(payload.filter_indexers or []),
        feed_indexers,
    )
    return (
        payload.model_copy(
            update={
                "indexer": "all",
                "filter_indexers": merged_filter_indexers,
            }
        ),
        f"Search scoped to affected feed indexers: {', '.join(feed_indexers)}.",
    )


def _apply_rule_search_scope(
    session: Session,
    payload: JackettSearchRequest,
    rule: Rule,
    *,
    feed_urls_override: list[str] | None = None,
) -> tuple[JackettSearchRequest, str | None]:
    scoped_payload, feed_scope_notice = _apply_rule_feed_scope(
        payload,
        rule,
        feed_urls_override=feed_urls_override,
    )

    notices: list[str] = []
    if feed_scope_notice:
        notices.append(feed_scope_notice)

    normalized_languages = _normalize_language_list(getattr(rule, "language", ""))
    if not normalized_languages:
        return scoped_payload, " ".join(notices) if notices else None

    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.app_ready:
        return scoped_payload, " ".join(notices) if notices else None

    try:
        client = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        )
        language_map = client.configured_indexer_languages()
    except JackettClientError:
        return scoped_payload, " ".join(notices) if notices else None

    matching_indexers = sorted(
        indexer
        for indexer, languages in language_map.items()
        if not set(normalized_languages).isdisjoint(
            {str(code).strip().casefold() for code in languages}
        )
    )
    if not matching_indexers:
        return scoped_payload, " ".join(notices) if notices else None

    if len(matching_indexers) == 1:
        scoped_indexer = matching_indexers[0]
        notices.append(
            "Search scoped to Jackett indexer from the saved rule language "
            f"({', '.join(normalized_languages)}): {scoped_indexer}."
        )
        return (
            scoped_payload.model_copy(
                update={
                    "indexer": scoped_indexer,
                    "filter_indexers": [scoped_indexer],
                }
            ),
            " ".join(notices),
        )

    merged_filter_indexers = _merge_search_terms(
        list(scoped_payload.filter_indexers or []),
        matching_indexers,
    )
    notices.append(
        "Search scoped to Jackett indexers from the saved rule language "
        f"({', '.join(normalized_languages)}): {', '.join(matching_indexers)}."
    )
    return (
        scoped_payload.model_copy(
            update={
                "indexer": "all",
                "filter_indexers": merged_filter_indexers,
            }
        ),
        " ".join(notices),
    )


def _is_placeholder_category_label(value: object | None) -> bool:
    return bool(PLACEHOLDER_CATEGORY_LABEL_RE.match(str(value or "").strip()))


def _canonical_category_label(value: object | None, fallback_category_id: str = "") -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        if fallback_category_id:
            return f"Category #{fallback_category_id}"
        return ""
    unknown_match = UNKNOWN_CATEGORY_LABEL_RE.match(cleaned)
    if unknown_match:
        category_id = unknown_match.group(1).strip() or fallback_category_id
        if category_id:
            return f"Category #{category_id}"
    return cleaned


def _dedupe_labels(labels: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        candidate = str(label or "").strip()
        key = candidate.casefold()
        if not candidate or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _apply_catalog_category_labels(session: Session, results: list[Any]) -> None:
    for result in results:
        result_record = cast(Any, result)
        category_ids = list(getattr(result, "category_ids", []) or [])
        if not category_ids:
            continue
        fallback_category_id = str(category_ids[0] or "").strip() if category_ids else ""
        resolved_labels = _dedupe_labels(
            [
                _canonical_category_label(item, fallback_category_id)
                for item in resolve_category_labels(
                    session,
                    indexer=getattr(result, "indexer", None),
                    category_ids=category_ids,
                )
            ]
        )
        if any(not _is_placeholder_category_label(item) for item in resolved_labels):
            result_record.category_labels = resolved_labels
            continue
        existing_labels = _dedupe_labels(
            [
                _canonical_category_label(item, fallback_category_id)
                for item in list(getattr(result, "category_labels", []) or [])
            ]
        )
        existing_real_labels = [
            item for item in existing_labels if not _is_placeholder_category_label(item)
        ]
        if existing_real_labels:
            result_record.category_labels = existing_real_labels
            continue
        if resolved_labels:
            result_record.category_labels = resolved_labels
            continue
        fallback_labels = _dedupe_labels(
            [_canonical_category_label(item, fallback_category_id) for item in category_ids]
        )
        if fallback_labels:
            result_record.category_labels = fallback_labels
            continue
        existing_raw_labels = [
            str(item).strip()
            for item in list(getattr(result, "category_labels", []) or [])
            if str(item or "").strip()
        ]
        if existing_raw_labels:
            result_record.category_labels = existing_raw_labels
            continue
        result_record.category_labels = []


SYNC_STATUS_SORT_RANK = {
    "ok": 0,
    "never": 1,
    "drift": 2,
    "error": 3,
}


def _safe_datetime_for_sort(value: datetime | None) -> datetime:
    if value is None:
        return datetime.fromtimestamp(0, tz=UTC)
    return value.astimezone(UTC)


def _rule_list_sort_value(item: dict[str, Any], field: str) -> Any:
    rule = cast(Rule, item["rule"])
    if field == "rule_name":
        return rule.rule_name.casefold()
    if field == "media_type":
        return rule.media_type.value
    if field == "last_sync_status":
        return SYNC_STATUS_SORT_RANK.get(rule.last_sync_status.value, 9)
    if field == "enabled":
        return 1 if rule.enabled else 0
    if field == "release_state":
        release = cast(dict[str, Any], item.get("release") or {})
        return int(release.get("rank") or 99)
    if field == "combined_filtered_count":
        release = cast(dict[str, Any], item.get("release") or {})
        return int(release.get("combined_filtered_count") or 0)
    if field == "combined_fetched_count":
        release = cast(dict[str, Any], item.get("release") or {})
        return int(release.get("combined_fetched_count") or 0)
    if field == "exact_filtered_count":
        release = cast(dict[str, Any], item.get("release") or {})
        return int(release.get("exact_filtered_count") or 0)
    if field == "last_snapshot_at":
        release = cast(dict[str, Any], item.get("release") or {})
        snapshot_fetched_at = cast(datetime | None, release.get("snapshot_fetched_at"))
        return _safe_datetime_for_sort(snapshot_fetched_at)
    return _safe_datetime_for_sort(rule.updated_at)


def _sorted_rule_rows(
    rows: list[dict[str, Any]],
    *,
    sort_field: str,
    sort_direction: str,
) -> list[dict[str, Any]]:
    reverse = sort_direction == "desc"
    sorted_rows = sorted(
        rows,
        key=lambda item: _rule_list_sort_value(item, sort_field),
        reverse=reverse,
    )
    return sorted_rows


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    try:
        run_due_scheduled_fetch(session)
        settings = SettingsService.get_or_create(session)
    except Exception:
        session.rollback()
        settings = SettingsService.get_or_create(session)

    default_sort_field = normalize_rules_page_sort_field(
        getattr(settings, "rules_page_sort_field", "updated_at")
    )
    default_sort_direction = normalize_rules_page_sort_direction(
        getattr(settings, "rules_page_sort_direction", "desc")
    )
    default_view_mode = normalize_rules_page_view_mode(
        getattr(settings, "rules_page_view_mode", "table")
    )

    search = request.query_params.get("search", "").strip()
    search_lower = search.lower()
    media_filter = request.query_params.get("media", "").strip()
    sync_filter = request.query_params.get("sync", "").strip()
    enabled_filter = request.query_params.get("enabled", "").strip()
    release_filter = request.query_params.get("release", "").strip()
    exact_filter = request.query_params.get("exact", "").strip()
    sort_field = normalize_rules_page_sort_field(
        request.query_params.get("sort", "").strip() or default_sort_field
    )
    sort_direction = normalize_rules_page_sort_direction(
        request.query_params.get("direction", "").strip() or default_sort_direction
    )
    view_mode = normalize_rules_page_view_mode(
        request.query_params.get("view", "").strip() or default_view_mode
    )

    rules_query = select(Rule).order_by(Rule.updated_at.desc())
    if search_lower:
        rules_query = rules_query.where(
            or_(
                func.lower(Rule.rule_name).contains(search_lower),
                func.lower(func.coalesce(Rule.imdb_id, "")).contains(search_lower),
            )
        )
    valid_media_values = {item.value for item in MediaType}
    if media_filter in valid_media_values:
        rules_query = rules_query.where(Rule.media_type == MediaType(media_filter))
    if sync_filter in {"never", "ok", "error", "drift"}:
        rules_query = rules_query.where(func.lower(Rule.last_sync_status) == sync_filter.lower())
    if enabled_filter in {"true", "false"}:
        rules_query = rules_query.where(Rule.enabled.is_(enabled_filter == "true"))

    rules = session.scalars(rules_query).all()

    snapshot_by_rule_id: dict[str, RuleSearchSnapshot] = {}
    if rules:
        snapshot_query = (
            select(RuleSearchSnapshot)
            .options(
                load_only(
                    RuleSearchSnapshot.rule_id,
                    RuleSearchSnapshot.fetched_at,
                    RuleSearchSnapshot.release_filter_cache_key,
                    RuleSearchSnapshot.release_filtered_count,
                    RuleSearchSnapshot.release_fetched_count,
                    RuleSearchSnapshot.exact_filtered_count,
                    RuleSearchSnapshot.exact_fetched_count,
                )
            )
            .where(RuleSearchSnapshot.rule_id.in_([rule.id for rule in rules]))
        )
        snapshot_by_rule_id = {item.rule_id: item for item in session.scalars(snapshot_query).all()}

    rows: list[dict[str, Any]] = []
    for rule in rules:
        snapshot = snapshot_by_rule_id.get(rule.id)
        release = release_state_from_snapshot(snapshot, rule=rule)
        if release_filter and str(release.get("state")) != release_filter:
            continue
        if exact_filter and str(release.get("exact_state")) != exact_filter:
            continue
        rows.append(
            {
                "rule": rule,
                "release": release,
                "snapshot": snapshot,
            }
        )
    filtered = _sorted_rule_rows(
        rows,
        sort_field=sort_field,
        sort_direction=sort_direction,
    )

    context = _base_context(request, "Rules")
    context.update(
        {
            "rules": filtered,
            "filters": {
                "search": search,
                "media": media_filter,
                "sync": sync_filter,
                "enabled": enabled_filter,
                "release": release_filter,
                "exact": exact_filter,
                "sort": sort_field,
                "direction": sort_direction,
                "view": view_mode,
            },
            "media_choices": media_type_choices(),
            "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
            "sync_choices": ["never", "ok", "error", "drift"],
            "release_choices": [
                {"value": "matches", "label": "Matches found"},
                {"value": "no_matches", "label": "No matches"},
                {"value": "empty", "label": "No fetched rows"},
                {"value": "unknown", "label": "No snapshot"},
            ],
            "exact_choices": [
                {"value": "exact", "label": "Exact found"},
                {"value": "fallback_only", "label": "Fallback only"},
                {"value": "none", "label": "No exact"},
                {"value": "unknown", "label": "No snapshot"},
            ],
            "rules_page_defaults": {
                "view_mode": default_view_mode,
                "sort_field": default_sort_field,
                "sort_direction": default_sort_direction,
            },
            "schedule": schedule_payload(settings),
            "shell_layout": "wide",
            "content_layout": "wide",
        }
    )
    return templates.TemplateResponse(request, "index.html", context)


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    source_rule: Rule | None = None
    source_rule_id = request.query_params.get("rule_id", "").strip()
    query_params = request.query_params
    additional_includes = query_params.get("additional_includes")
    if additional_includes is None:
        additional_includes = query_params.get("keywords_all", "")
    must_not_contain = query_params.get("must_not_contain")
    if must_not_contain is None:
        must_not_contain = query_params.get("keywords_not", "")
    quality_include_tokens = _parse_search_filter_terms(
        ", ".join(query_params.getlist("quality_include_tokens"))
    )
    quality_exclude_tokens = _parse_search_filter_terms(
        ", ".join(query_params.getlist("quality_exclude_tokens"))
    )
    quality_include_tokens, quality_exclude_tokens = _normalize_quality_token_selection(
        quality_include_tokens,
        quality_exclude_tokens,
    )
    filter_indexers = _parse_search_filter_terms(", ".join(query_params.getlist("filter_indexers")))
    filter_category_ids = _parse_search_filter_terms(
        ", ".join(query_params.getlist("filter_category_ids"))
    )
    form_data = {
        "query": query_params.get("query", "").strip(),
        "media_type": _normalized_media_type(query_params.get("media_type")),
        "indexer": query_params.get("indexer", "all").strip() or "all",
        "imdb_id": query_params.get("imdb_id", "").strip(),
        "include_release_year": (
            _query_bool_values(query_params.getlist("include_release_year"))
            or (
                not query_params.getlist("include_release_year")
                and bool(query_params.get("release_year", "").strip())
            )
        ),
        "release_year": query_params.get("release_year", "").strip(),
        "additional_includes": str(additional_includes or "").strip(),
        "keywords_any": query_params.get("keywords_any", "").strip(),
        "must_not_contain": str(must_not_contain or "").strip(),
        "quality_include_tokens": quality_include_tokens,
        "quality_exclude_tokens": quality_exclude_tokens,
        "size_min_mb": query_params.get("size_min_mb", "").strip(),
        "size_max_mb": query_params.get("size_max_mb", "").strip(),
        "filter_indexers": ", ".join(filter_indexers),
        "filter_category_ids": ", ".join(filter_category_ids),
    }
    errors: list[str] = []
    search_run: dict[str, object] | None = None
    ignored_full_regex = False
    active_payload: JackettSearchRequest | None = None
    derivation_notice: str | None = None
    jackett_ready = False
    jackett_rule_ready = False
    jackett_api_url = ""
    jackett_qb_url = ""
    jackett_api_key: str | None = None
    jackett_language_overrides: dict[str, list[str]] = {}
    search_view_defaults = {
        "view_mode": DEFAULT_SEARCH_RESULT_VIEW_MODE,
        "sort_criteria": [dict(item) for item in DEFAULT_SEARCH_SORT_CRITERIA],
    }
    queue_defaults = {
        "rule_id": "",
        "add_paused": True,
        "sequential_download": True,
        "first_last_piece_prio": True,
    }

    try:
        settings = SettingsService.get_or_create(session)
        jackett = SettingsService.resolve_jackett(settings)
        jackett_ready = jackett.app_ready
        jackett_rule_ready = jackett.rule_ready
        jackett_api_url = jackett.api_url or ""
        jackett_qb_url = jackett.qb_url or ""
        jackett_api_key = jackett.api_key
        jackett_language_overrides = jackett.language_overrides
        search_view_defaults = {
            "view_mode": normalize_search_result_view_mode(settings.search_result_view_mode),
            "sort_criteria": normalize_search_sort_criteria(settings.search_sort_criteria),
        }
        queue_defaults["add_paused"] = bool(settings.default_add_paused)
        queue_defaults["sequential_download"] = bool(
            getattr(settings, "default_sequential_download", True)
        )
        queue_defaults["first_last_piece_prio"] = bool(
            getattr(settings, "default_first_last_piece_prio", True)
        )
    except Exception as exc:
        errors = [_unexpected_error_message("Search setup failed unexpectedly", exc)]

    if source_rule_id and not errors:
        try:
            source_rule = session.get(Rule, source_rule_id)
        except Exception as exc:
            derivation_notice = (
                "The saved rule could not be loaded for search. "
                "Adjust the title and keywords manually."
            )
            errors = [_unexpected_error_message("Saved rule search failed unexpectedly", exc)]
            source_rule = None
        if source_rule is None:
            if not errors:
                errors = ["Rule not found for search."]
        else:
            queue_defaults["rule_id"] = source_rule.id
            queue_defaults["add_paused"] = bool(source_rule.add_paused)
            payload_from_rule: JackettSearchRequest | None = None
            try:
                payload_from_rule, ignored_full_regex = build_search_request_from_rule(source_rule)
            except ValidationError:
                ignored_full_regex = True
                try:
                    payload_from_rule, _ = build_reduced_search_request_from_rule(source_rule)
                    derivation_notice = (
                        "The saved rule expanded into too many structured terms. "
                        "Search kept a reduced subset of inherited keywords."
                    )
                except Exception:
                    payload_from_rule = _title_only_search_request_from_rule(source_rule)
                    if payload_from_rule is not None:
                        derivation_notice = (
                            "The saved rule expanded into too many structured terms. "
                            "Search fell back to the saved title only."
                        )
                if payload_from_rule is None:
                    derivation_notice = (
                        "The saved rule could not be reduced into a safe structured search. "
                        "Adjust the title and keywords manually."
                    )
                    if not form_data["query"]:
                        _prefill_rule_search_form_data(form_data, source_rule)
                        errors = ["Saved rule could not be converted into a Jackett search."]
            except Exception:
                ignored_full_regex = True
                try:
                    payload_from_rule, _ = build_reduced_search_request_from_rule(source_rule)
                    derivation_notice = (
                        "The saved rule needed a compatibility fallback. "
                        "Search kept the safe title and keywords the app could extract."
                    )
                except Exception:
                    payload_from_rule = _title_only_search_request_from_rule(source_rule)
                    if payload_from_rule is not None:
                        derivation_notice = (
                            "The saved rule needed a compatibility fallback. "
                            "Search fell back to the saved title only."
                        )
                    else:
                        derivation_notice = (
                            "The saved rule could not be reduced into a safe structured search. "
                            "Adjust the title and keywords manually."
                        )
                        if not form_data["query"]:
                            _prefill_rule_search_form_data(form_data, source_rule)
                            errors = ["Saved rule could not be converted into a Jackett search."]
            if payload_from_rule is not None:
                payload_from_rule, feed_scope_notice = _apply_rule_search_scope(
                    session,
                    payload_from_rule, source_rule
                )
                if feed_scope_notice:
                    derivation_notice = (
                        f"{derivation_notice} {feed_scope_notice}".strip()
                        if derivation_notice
                        else feed_scope_notice
                    )

            if payload_from_rule is not None and not form_data["query"]:
                active_payload = payload_from_rule
                form_data.update(
                    {
                        "query": payload_from_rule.query,
                        "media_type": payload_from_rule.media_type.value,
                        "imdb_id": payload_from_rule.imdb_id or "",
                        "include_release_year": bool(source_rule.include_release_year),
                        "release_year": payload_from_rule.release_year or "",
                        "additional_includes": str(source_rule.additional_includes or "").strip(),
                        "keywords_any": "",
                        "must_not_contain": str(source_rule.must_not_contain or "").strip(),
                        "quality_include_tokens": list(source_rule.quality_include_tokens or []),
                        "quality_exclude_tokens": list(source_rule.quality_exclude_tokens or []),
                        "size_min_mb": "",
                        "size_max_mb": "",
                        "filter_indexers": ", ".join(payload_from_rule.filter_indexers),
                        "filter_category_ids": "",
                    }
                )

    if form_data["query"] and not errors:
        if active_payload is None:
            try:
                quality_include_tokens, quality_exclude_tokens = _normalize_quality_token_selection(
                    cast(list[str], form_data.get("quality_include_tokens", [])),
                    cast(list[str], form_data.get("quality_exclude_tokens", [])),
                )
                form_data["quality_include_tokens"] = quality_include_tokens
                form_data["quality_exclude_tokens"] = quality_exclude_tokens
                keywords_any_groups = _parse_keywords_any_groups(str(form_data["keywords_any"]))
                quality_include_term_groups = expand_grouped_quality_search_terms(
                    quality_include_tokens
                )
                for group in quality_include_term_groups:
                    keywords_any_groups.append(group)
                quality_include_terms = [
                    term for group in quality_include_term_groups for term in group
                ]
                merged_keywords_any = _merge_search_terms(
                    _parse_search_filter_terms(str(form_data["keywords_any"])),
                    quality_include_terms,
                )
                quality_exclude_terms = expand_quality_search_terms(quality_exclude_tokens)
                merged_keywords_not = _merge_search_terms(
                    _parse_search_filter_terms(str(form_data["must_not_contain"])),
                    quality_exclude_terms,
                )
                active_payload = JackettSearchRequest.model_validate(
                    {
                        "query": form_data["query"],
                        "media_type": form_data["media_type"],
                        "indexer": form_data["indexer"],
                        "imdb_id": form_data["imdb_id"],
                        "release_year": (
                            form_data["release_year"]
                            if cast(bool, form_data["include_release_year"])
                            else ""
                        ),
                        "keywords_all": form_data["additional_includes"],
                        "keywords_any": merged_keywords_any,
                        "keywords_any_groups": keywords_any_groups,
                        "keywords_not": merged_keywords_not,
                        "primary_keywords_any": quality_include_terms,
                        "primary_keywords_any_groups": quality_include_term_groups,
                        "primary_keywords_not": quality_exclude_terms,
                        "size_min_mb": form_data["size_min_mb"],
                        "size_max_mb": form_data["size_max_mb"],
                        "filter_indexers": filter_indexers,
                        "filter_category_ids": filter_category_ids,
                    }
                )
            except ValidationError as exc:
                errors = [error["msg"] for error in exc.errors()]
        if active_payload is not None and not errors:
            try:
                active_payload = _auto_imdb_first_payload(active_payload)
                _sync_search_form_data_with_payload(form_data, active_payload)
                client = JackettClient(
                    jackett_api_url,
                    jackett_api_key,
                    language_overrides=jackett_language_overrides,
                )
                result = client.search(active_payload)
                all_results = [
                    *list(result.raw_results or []),
                    *list(result.results or []),
                    *list(result.raw_fallback_results or []),
                    *list(result.fallback_results or []),
                ]
                client.enrich_result_category_labels(all_results)
                sync_category_catalog_from_results(session, all_results)
                sync_category_catalog_from_indexer_map(
                    session,
                    client.configured_indexer_category_labels(),
                )
                _apply_catalog_category_labels(session, all_results)
                session.commit()
                rule_prefill = {
                    "rule_name": active_payload.query,
                    "content_name": active_payload.query,
                    "normalized_title": active_payload.query,
                    "media_type": active_payload.media_type.value,
                }
                if active_payload.imdb_id:
                    rule_prefill["imdb_id"] = active_payload.imdb_id
                if active_payload.release_year:
                    rule_prefill["release_year"] = active_payload.release_year
                if active_payload.keywords_all:
                    rule_prefill["additional_includes"] = ", ".join(active_payload.keywords_all)
                keyword_fragment = _optional_keyword_group_regex(
                    active_payload.keywords_any_groups
                    or ([active_payload.keywords_any] if active_payload.keywords_any else [])
                )
                if keyword_fragment:
                    rule_prefill["must_contain_override"] = keyword_fragment
                new_rule_href = f"/rules/new?{urlencode(rule_prefill)}"

                primary_label = (
                    "Precise results"
                    if active_payload.imdb_id_only
                    else ("Saved rule search" if source_rule else "Jackett active search")
                )
                fallback_label = "Title fallback" if result.fallback_request_variants else ""
                summary_parts = ["Title"]
                if active_payload.imdb_id_only:
                    summary_parts.append("IMDb-enforced Jackett lookup")
                if active_payload.season_number is not None:
                    if active_payload.episode_number is not None:
                        summary_parts.append(
                            f"series floor S{int(active_payload.season_number):02d}E{int(active_payload.episode_number):02d}"
                        )
                    else:
                        summary_parts.append(
                            f"season floor S{int(active_payload.season_number):02d}"
                        )
                if active_payload.keywords_all:
                    summary_parts.append("required keywords")
                if keyword_fragment:
                    keyword_group_count = len(
                        active_payload.keywords_any_groups
                        or ([active_payload.keywords_any] if active_payload.keywords_any else [])
                    )
                    if keyword_group_count > 1:
                        summary_parts.append(f"{keyword_group_count} any-of mustContain groups")
                    else:
                        summary_parts.append("an any-of mustContain regex fragment")
                search_run = build_inline_search_payload(
                    payload=active_payload,
                    run=result,
                    ignored_full_regex=ignored_full_regex,
                    primary_label_override=primary_label,
                    fallback_label_override=fallback_label,
                )
                for key in (
                    "raw_results",
                    "results",
                    "raw_fallback_results",
                    "fallback_results",
                    "unified_raw_results",
                ):
                    raw_items = cast(list[dict[str, Any]], search_run.get(key, []))
                    search_run[key] = [
                        {**item, "new_rule_href": new_rule_href} for item in raw_items
                    ]
                search_run.update(
                    {
                        "source_label": "Saved rule search"
                        if source_rule
                        else "Jackett active search",
                        "rule_prefill_summary": f"{', '.join(summary_parts)}.",
                        "source_rule_name": source_rule.rule_name if source_rule else "",
                        "ignored_full_regex": ignored_full_regex,
                    }
                )
            except JackettClientError as exc:
                errors = [str(exc)]
            except Exception as exc:
                errors = [_unexpected_error_message("Jackett search failed unexpectedly", exc)]

    context = _base_context(request, "Search")
    context.update(
        {
            "form_data": form_data,
            "errors": errors,
            "media_choices": media_type_choices(),
            "jackett_ready": jackett_ready,
            "jackett_rule_ready": jackett_rule_ready,
            "jackett_api_url": jackett_api_url,
            "jackett_qb_url": jackett_qb_url,
            "source_rule": source_rule,
            "derivation_notice": derivation_notice,
            "search_run": search_run,
            "quality_option_groups": quality_option_groups(),
            "quality_search_term_map": quality_search_term_map(),
            "quality_pattern_map": quality_pattern_map(),
            "search_view_defaults": search_view_defaults,
            "queue_defaults": queue_defaults,
            "shell_layout": "wide",
            "content_layout": "wide",
        }
    )
    return templates.TemplateResponse(request, "search.html", context)


@router.get("/rules/{rule_id}/search")
def run_rule_search(rule_id: str, request: Request) -> RedirectResponse:
    feed_urls = _normalize_feed_url_list(request.query_params.getlist("feed_urls"))
    feed_scope_override = request.query_params.get(
        "feed_scope_override", ""
    ).strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    refresh_snapshot = request.query_params.get("refresh_snapshot", "").strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    query_params: list[tuple[str, str]] = [("run_search", "1")]
    if feed_scope_override:
        query_params.append(("feed_scope_override", "1"))
        query_params.extend(("feed_urls", item) for item in feed_urls)
    if refresh_snapshot:
        query_params.append(("refresh_snapshot", "1"))
    query = urlencode(query_params, doseq=True)
    return RedirectResponse(url=f"/rules/{rule_id}?{query}#inline-search-results", status_code=303)


@router.get("/rules/new", response_class=HTMLResponse)
def new_rule(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    requested_media_type = _normalized_media_type(request.query_params.get("media_type"))
    default_quality = settings.default_quality_profile
    profile_rules = resolve_quality_profile_rules(settings)
    default_profile_rule = profile_rules.get(
        default_quality.value, {"include_tokens": [], "exclude_tokens": []}
    )
    default_filter_profile_key = detect_matching_filter_profile_key(
        default_profile_rule.get("include_tokens", []),
        default_profile_rule.get("exclude_tokens", []),
        settings,
        media_type=requested_media_type,
    )
    default_include_tokens = list(default_profile_rule.get("include_tokens", []))
    default_exclude_tokens = list(default_profile_rule.get("exclude_tokens", []))
    if requested_media_type not in {MediaType.SERIES.value, MediaType.MOVIE.value}:
        default_include_tokens = []
        default_exclude_tokens = []
        default_filter_profile_key = ""

    form_data: dict[str, object] = {
        "rule_name": "",
        "content_name": "",
        "imdb_id": "",
        "normalized_title": "",
        "poster_url": "",
        "media_type": requested_media_type,
        "quality_profile": (
            default_quality.value
            if requested_media_type in {MediaType.SERIES.value, MediaType.MOVIE.value}
            else QualityProfile.CUSTOM.value
        ),
        "quality_mode": (
            QualityMode.MANAGED.value
            if requested_media_type in {MediaType.SERIES.value, MediaType.MOVIE.value}
            else QualityMode.MANUAL.value
        ),
        "filter_profile_key": default_filter_profile_key,
        "release_year": "",
        "include_release_year": False,
        "additional_includes": "",
        "quality_include_tokens": default_include_tokens,
        "quality_exclude_tokens": default_exclude_tokens,
        "use_regex": True,
        "must_contain_override": "",
        "must_not_contain": "",
        "start_season": "",
        "start_episode": "",
        "jellyfin_search_existing_unseen": False,
        "jellyfin_auto_disabled": False,
        "movie_completion_sources": [],
        "movie_completion_sources_display": "",
        "movie_completion_auto_disabled": False,
        "movie_auto_disabled": False,
        "jellyfin_existing_episode_numbers": [],
        "jellyfin_existing_episode_count": 0,
        "episode_filter": "",
        "ignore_days": 0,
        "add_paused": settings.default_add_paused,
        "enabled": settings.default_enabled,
        "smart_filter": False,
        "language": _default_rule_language(session),
        "assigned_category": "",
        "save_path": "",
        "feed_urls": list(settings.default_feed_urls or []),
        "notes": "",
        "remember_feed_defaults": True,
        "metadata_lookup_provider": default_metadata_lookup_provider(requested_media_type),
    }

    for key in (
        "rule_name",
        "content_name",
        "imdb_id",
        "normalized_title",
        "release_year",
        "additional_includes",
        "must_contain_override",
    ):
        value = request.query_params.get(key, "").strip()
        if value:
            form_data[key] = value

    context = _base_context(request, "New Rule")
    available_filter_profiles = available_filter_profile_choices(settings)
    resolved_language_feed_urls, language_resolution_notice = _resolve_language_feed_urls(
        session,
        language=str(form_data.get("language", "") or ""),
        selected_urls=list(cast(list[str], form_data.get("feed_urls", []) or [])),
    )
    form_data["feed_urls"] = _resolved_rule_form_feed_urls(
        cast(list[str], form_data.get("feed_urls", []) or []),
        language=str(form_data.get("language", "") or ""),
        resolved_language_feed_urls=resolved_language_feed_urls,
        language_resolution_notice=language_resolution_notice,
    )
    context.update(
        {
            "mode": "create",
            "rule_id": None,
            "form_data": form_data,
            "errors": [],
            "feed_options": _safe_feed_options(
                session,
                cast(list[str], form_data.get("feed_urls", []) or []),
            ),
            "language_options": _safe_rule_language_options(session),
            "language_resolution_notice": language_resolution_notice,
            "settings_form": SettingsService.to_form_dict(settings),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "quality_profile_rules": profile_rules,
            "available_filter_profiles": available_filter_profiles,
            "visible_filter_profiles": available_filter_profile_choices_for_media_type(
                settings,
                requested_media_type,
            ),
            "media_choices": media_type_choices(),
            "metadata_lookup_providers": metadata_lookup_provider_catalog(),
            "visible_metadata_lookup_providers": metadata_lookup_provider_choices(
                requested_media_type
            ),
            "metadata_lookup_disabled": settings.metadata_provider.value == "disabled",
            "shell_layout": "wide",
            "content_layout": "wide",
        }
    )
    return templates.TemplateResponse(request, "rule_form.html", context)


@router.get("/rules/{rule_id}", response_class=HTMLResponse)
def edit_rule(
    rule_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    rule = session.get(Rule, rule_id)
    if rule is None:
        settings = SettingsService.get_or_create(session)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                **_base_context(request, "Rules"),
                "rules": [],
                "filters": {
                    "search": "",
                    "media": "",
                    "sync": "",
                    "enabled": "",
                    "release": "",
                    "sort": normalize_rules_page_sort_field(
                        getattr(settings, "rules_page_sort_field", "updated_at")
                    ),
                    "direction": normalize_rules_page_sort_direction(
                        getattr(settings, "rules_page_sort_direction", "desc")
                    ),
                    "view": normalize_rules_page_view_mode(
                        getattr(settings, "rules_page_view_mode", "table")
                    ),
                },
                "media_choices": media_type_choices(),
                "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
                "sync_choices": ["never", "ok", "error", "drift"],
                "release_choices": [
                    {"value": "matches", "label": "Matches found"},
                    {"value": "no_matches", "label": "No matches"},
                    {"value": "empty", "label": "No fetched rows"},
                    {"value": "unknown", "label": "No snapshot"},
                ],
                "rules_page_defaults": {
                    "view_mode": normalize_rules_page_view_mode(
                        getattr(settings, "rules_page_view_mode", "table")
                    ),
                    "sort_field": normalize_rules_page_sort_field(
                        getattr(settings, "rules_page_sort_field", "updated_at")
                    ),
                    "sort_direction": normalize_rules_page_sort_direction(
                        getattr(settings, "rules_page_sort_direction", "desc")
                    ),
                },
                "schedule": schedule_payload(settings),
                "message": "Rule not found.",
                "message_level": "error",
                "shell_layout": "wide",
                "content_layout": "wide",
            },
            status_code=404,
        )

    settings = SettingsService.get_or_create(session)
    profile_rules = resolve_quality_profile_rules(settings)
    form_data = _rule_to_form_data(rule)
    effective_include_tokens, effective_exclude_tokens = effective_rule_quality_tokens(rule, settings)
    form_data["quality_include_tokens"] = effective_include_tokens
    form_data["quality_exclude_tokens"] = effective_exclude_tokens
    form_media_type = str(
        form_data.get("media_type", MediaType.SERIES.value) or MediaType.SERIES.value
    )
    form_data["filter_profile_key"] = detect_matching_filter_profile_key(
        form_data["quality_include_tokens"],
        form_data["quality_exclude_tokens"],
        settings,
        media_type=form_media_type,
    )
    resolved_language_feed_urls, language_resolution_notice = _resolve_language_feed_urls(
        session,
        language=str(form_data.get("language", "") or ""),
        selected_urls=list(cast(list[str], form_data.get("feed_urls", []) or [])),
    )
    form_data["feed_urls"] = _resolved_rule_form_feed_urls(
        cast(list[str], form_data.get("feed_urls", []) or []),
        language=str(form_data.get("language", "") or ""),
        resolved_language_feed_urls=resolved_language_feed_urls,
        language_resolution_notice=language_resolution_notice,
    )
    inline_search_view_defaults = {
        "view_mode": "table",
        "sort_criteria": normalize_search_sort_criteria(settings.search_sort_criteria),
    }
    inline_search: dict[str, object] | None = None
    inline_search_errors: list[str] = []
    inline_search_notices: list[str] = []
    run_inline_search_requested = request.query_params.get("run_search", "").strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    refresh_inline_snapshot = request.query_params.get(
        "refresh_snapshot", ""
    ).strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    clear_inline_results = request.query_params.get("clear_results", "").strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    feed_scope_override_requested = request.query_params.get(
        "feed_scope_override", ""
    ).strip().casefold() in {
        "1",
        "true",
        "on",
        "yes",
    }
    feed_urls_override = _normalize_feed_url_list(request.query_params.getlist("feed_urls"))
    feed_urls_from_rule = _normalize_feed_url_list(list(rule.feed_urls or []))
    effective_feed_scope_override = feed_scope_override_requested and sorted(
        feed_urls_override
    ) != sorted(feed_urls_from_rule)
    auto_replay_inline_snapshot = (
        not run_inline_search_requested
        and not clear_inline_results
        and not refresh_inline_snapshot
        and not effective_feed_scope_override
    )
    if run_inline_search_requested or auto_replay_inline_snapshot:
        replay_saved_snapshot = not refresh_inline_snapshot and not effective_feed_scope_override
        if replay_saved_snapshot:
            snapshot = get_rule_search_snapshot(session, rule_id=rule.id)
            if snapshot is not None:
                inline_search = inline_search_from_snapshot(snapshot)
                inline_search_notices.append(
                    "Showing saved search snapshot from "
                    f"{_format_snapshot_fetched_at(snapshot.fetched_at)}."
                )
        if inline_search is None and run_inline_search_requested:
            payload_from_rule: JackettSearchRequest | None = None
            ignored_full_regex = False
            try:
                payload_from_rule, ignored_full_regex = build_search_request_from_rule(rule)
            except ValidationError:
                ignored_full_regex = True
                try:
                    payload_from_rule, _ = build_reduced_search_request_from_rule(rule)
                    inline_search_notices.append(
                        "Rule keywords were reduced to stay within structured-search limits."
                    )
                except Exception:
                    payload_from_rule = _title_only_search_request_from_rule(rule)
                    if payload_from_rule is not None:
                        inline_search_notices.append(
                            "Rule search fell back to title-only compatibility mode."
                        )
            except Exception:
                ignored_full_regex = True
                payload_from_rule = _title_only_search_request_from_rule(rule)
                if payload_from_rule is not None:
                    inline_search_notices.append(
                        "Rule search needed compatibility fallback and used title-only mode."
                    )

            if payload_from_rule is None:
                inline_search_errors = [
                    "Rule could not be converted into a Jackett search payload."
                ]
            else:
                payload_from_rule, feed_scope_notice = _apply_rule_search_scope(
                    session,
                    payload_from_rule,
                    rule,
                    feed_urls_override=(
                        feed_urls_override if effective_feed_scope_override else None
                    ),
                )
                if feed_scope_notice:
                    inline_search_notices.append(feed_scope_notice)
                if effective_feed_scope_override:
                    inline_search_notices.append(
                        "Inline search used current affected-feed selection from the form (not yet saved)."
                    )
                jackett = SettingsService.resolve_jackett(settings)
                if not jackett.app_ready:
                    inline_search_errors = ["Jackett app search is not configured in Settings."]
                else:
                    try:
                        payload_from_rule = _auto_imdb_first_payload(payload_from_rule)
                        client = JackettClient(
                            jackett.api_url,
                            jackett.api_key,
                            language_overrides=jackett.language_overrides,
                        )
                        result = client.search(payload_from_rule)
                        all_results = [
                            *list(result.raw_results or []),
                            *list(result.results or []),
                            *list(result.raw_fallback_results or []),
                            *list(result.fallback_results or []),
                        ]
                        client.enrich_result_category_labels(all_results)
                        sync_category_catalog_from_results(session, all_results)
                        sync_category_catalog_from_indexer_map(
                            session,
                            client.configured_indexer_category_labels(),
                        )
                        _apply_catalog_category_labels(session, all_results)
                        snapshot = save_rule_search_snapshot(
                            session,
                            rule_id=rule.id,
                            payload=payload_from_rule,
                            run=result,
                            ignored_full_regex=ignored_full_regex,
                        )
                        if not effective_feed_scope_override:
                            refresh_snapshot_release_cache(snapshot, rule=rule)
                        inline_search = inline_search_from_snapshot(snapshot)
                        session.commit()
                        if refresh_inline_snapshot:
                            inline_search_notices.append(
                                "Search snapshot refreshed from Jackett and saved for future runs."
                            )
                    except JackettClientError as exc:
                        inline_search_errors = [str(exc)]
                    except Exception as exc:
                        inline_search_errors = [
                            _unexpected_error_message("Inline rule search failed unexpectedly", exc)
                        ]

    context = _base_context(request, f"Edit {rule.rule_name}")
    available_filter_profiles = available_filter_profile_choices(settings)
    context.update(
        {
            "mode": "edit",
            "rule_id": rule.id,
            "form_data": form_data,
            "errors": [],
            "feed_options": _safe_feed_options(
                session,
                cast(list[str], form_data.get("feed_urls", []) or []),
            ),
            "language_options": _safe_rule_language_options(session),
            "language_resolution_notice": language_resolution_notice,
            "settings_form": SettingsService.to_form_dict(settings),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "quality_profile_rules": profile_rules,
            "available_filter_profiles": available_filter_profiles,
            "visible_filter_profiles": available_filter_profile_choices_for_media_type(
                settings,
                form_media_type,
            ),
            "media_choices": media_type_choices(),
            "metadata_lookup_providers": metadata_lookup_provider_catalog(),
            "visible_metadata_lookup_providers": metadata_lookup_provider_choices(
                form_media_type,
            ),
            "metadata_lookup_disabled": settings.metadata_provider.value == "disabled",
            "quality_search_term_map": quality_search_term_map(),
            "quality_pattern_map": quality_pattern_map(),
            "inline_search_view_defaults": inline_search_view_defaults,
            "inline_search": inline_search,
            "inline_search_errors": inline_search_errors,
            "inline_search_notices": inline_search_notices,
            "inline_queue_defaults": {
                "rule_id": rule.id,
                "add_paused": bool(rule.add_paused),
                "sequential_download": bool(getattr(settings, "default_sequential_download", True)),
                "first_last_piece_prio": bool(
                    getattr(settings, "default_first_last_piece_prio", True)
                ),
            },
            "shell_layout": "wide",
            "content_layout": "wide",
        }
    )
    return templates.TemplateResponse(request, "rule_form.html", context)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    context = _base_context(request, "Settings")
    context.update(
        {
            "form_data": SettingsService.to_form_dict(settings),
            "errors": [],
            "profile_1080p_label": quality_profile_label(QualityProfile.HD_1080P),
            "profile_2160p_hdr_label": quality_profile_label(QualityProfile.UHD_2160P_HDR),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "metadata_choices": ["omdb", "disabled"],
        }
    )
    return templates.TemplateResponse(request, "settings.html", context)


@router.get("/taxonomy", response_class=HTMLResponse)
def taxonomy_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    rules = session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
    context = _base_context(request, "Taxonomy")
    context.update(
        {
            "taxonomy_form": {"taxonomy_json": "", "change_note": ""},
            "taxonomy_preview": None,
            "taxonomy_snapshot": None,
            "current_taxonomy_preview": None,
            "taxonomy_audit_entries": recent_quality_taxonomy_audit_entries(),
            "taxonomy_media_types": [choice["value"] for choice in media_type_choices()],
            "errors": [],
        }
    )

    try:
        raw_taxonomy = read_quality_taxonomy_text()
        context["taxonomy_form"] = {"taxonomy_json": raw_taxonomy, "change_note": ""}
        context["taxonomy_snapshot"] = quality_taxonomy_snapshot()
        context["current_taxonomy_preview"] = preview_quality_taxonomy_update(
            raw_taxonomy,
            settings=settings,
            rules=rules,
        )
    except RuntimeError as exc:
        context["errors"] = [str(exc)]

    return templates.TemplateResponse(request, "taxonomy.html", context)


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    SettingsService.get_or_create(session)
    context = _base_context(request, "Import")
    context.update(
        {
            "preview_entries": [],
            "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
            "errors": [],
            "result_summary": None,
        }
    )
    return templates.TemplateResponse(request, "import.html", context)


@router.get("/health")
def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "app_version": request.app.version,
            "static_asset_version": compute_static_asset_version()
            or getattr(
                request.app.state,
                "static_asset_version",
                request.app.version,
            ),
            "desktop_backend_contract": getattr(request.app.state, "desktop_backend_contract", ""),
            "capabilities": list(getattr(request.app.state, "desktop_capabilities", ())),
        }
    )
