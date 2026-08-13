from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import obfuscate_secret
from app.db import get_db_session
from app.models import (
    AppSettings,
    DownloadAccelerationJob,
    MediaType,
    QualityMode,
    QualityProfile,
    Rule,
    SyncStatus,
    media_type_choices,
    media_type_label,
    utcnow,
)
from app.routes.pages import (
    DEFAULT_RULE_LANGUAGE,
    LANGUAGE_FEED_SELECTION_NO_MATCHING_FEEDS,
    LANGUAGE_FEED_SELECTION_QB_FEEDS_UNAVAILABLE,
    _normalize_language_list,
    _resolve_language_feed_urls,
    _safe_feed_options,
    _safe_rule_language_options,
)
from app.schemas import (
    FilterProfileSaveRequest,
    ImportMode,
    JackettSearchRequest,
    JackettSettingsPayload,
    JellyfinSettingsPayload,
    MetadataLookupRequest,
    MetadataSettingsPayload,
    MyJDownloaderSettingsPayload,
    QbSettingsPayload,
    RealDebridSettingsPayload,
    RuleBatchFetchRequest,
    RuleBatchQualityProfileRequest,
    RuleFetchSchedulePayload,
    RuleFormPayload,
    RulesPagePreferencesPayload,
    SearchQueueRequest,
    SearchViewPreferencesPayload,
    SettingsFormPayload,
    StremioSettingsPayload,
)
from app.services.codex_maintenance import (
    maintenance_status_by_job,
    queue_acceleration_maintenance_request,
)
from app.services.hover_debug import (
    clear_hover_events,
    hover_debug_log_path,
    list_hover_events,
    record_hover_event,
)
from app.services.importer import Importer
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    build_search_request_from_rule,
    feed_indexer_slug,
)
from app.services.jellyfin import JellyfinError, JellyfinService
from app.services.jellyfin_sync_ops import JellyfinSyncBusyError, execute_jellyfin_sync
from app.services.metadata import (
    MetadataClient,
    MetadataLookupError,
    default_metadata_lookup_provider,
    metadata_lookup_provider_catalog,
    metadata_lookup_provider_choices,
)
from app.services.myjdownloader import MyJDownloaderClient, MyJDownloaderError
from app.services.operation_status import operations_status_payload
from app.services.qbittorrent import (
    MANAGED_TORRENT_TAG,
    QbittorrentClient,
    QbittorrentClientError,
)
from app.services.quality_filters import (
    add_quality_taxonomy_option,
    apply_quality_taxonomy_update,
    available_filter_profile_choices,
    available_filter_profile_choices_for_media_type,
    build_available_filter_profiles,
    builtin_filter_profile_keys,
    move_quality_taxonomy_option,
    normalize_saved_quality_profiles,
    preview_quality_taxonomy_update,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    quality_profile_label,
    quality_taxonomy_snapshot,
    read_quality_taxonomy_text,
    recent_quality_taxonomy_audit_entries,
    remove_quality_taxonomy_option,
    resolve_quality_profile_rules,
    slugify_profile_key,
)
from app.services.real_debrid import (
    DEVICE_FLOW_REGISTRY,
    RealDebridAuthorizationPendingError,
    RealDebridClient,
    RealDebridError,
)
from app.services.real_debrid_auth import ensure_real_debrid_access_token
from app.services.real_debrid_webseed import WebseedError, fetch_webseed_file
from app.services.rule_builder import RuleBuilder
from app.services.rule_fetch_ops import (
    refresh_snapshot_release_cache,
    run_rules_fetch_batch,
    run_scheduled_fetch_now,
    schedule_payload,
    update_schedule_settings,
)
from app.services.rule_fetch_queue import enqueue_rule_fetch
from app.services.rule_search_snapshots import get_rule_search_snapshot, save_rule_search_snapshot
from app.services.selective_queue import (
    SelectiveQueueError,
    queue_grouped_search_results,
    queue_result_with_optional_file_selection,
)
from app.services.settings_service import SettingsService
from app.services.static_assets import compute_static_asset_version
from app.services.stremio import StremioError, StremioService
from app.services.stremio_sync_ops import StremioSyncBusyError, execute_stremio_sync
from app.services.sync import SyncService, SyncServiceError
from app.services.sync_queue import enqueue_rule_sync
from app.services.watch_progress_sync import sync_watch_progress

router = APIRouter(prefix="/api")
compat_router = APIRouter()


@compat_router.api_route(
    "/webseeds/real-debrid/{token}/{relative_path:path}",
    methods=["GET", "HEAD"],
)
def real_debrid_webseed(
    token: str,
    relative_path: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    settings = SettingsService.get_or_create(session)
    try:
        access_token = ensure_real_debrid_access_token(session, settings)
        with RealDebridClient(access_token) as client:
            result = fetch_webseed_file(
                session,
                token=token,
                relative_path=relative_path,
                range_header=request.headers.get("range"),
                head_only=request.method == "HEAD",
                real_debrid_client=client,
            )
    except WebseedError as exc:
        return Response(str(exc), status_code=404)
    except RealDebridError:
        return Response("Real-Debrid web-seed is temporarily unavailable.", status_code=502)
    return Response(
        content=result.content,
        status_code=result.status_code,
        headers=result.headers,
        media_type=None,
    )


def _template_context(request: Request) -> dict[str, object]:
    return {
        "static_asset_version": compute_static_asset_version(),
        "app_version": getattr(request.app, "version", ""),
    }


templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates"),
    context_processors=[_template_context],
)


def _bool_from_form(form: Any, key: str) -> bool:
    value = form.get(key)
    return str(value).lower() in {"1", "true", "on", "yes"}


def _normalize_result_identity_text(value: object | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _snapshot_queue_rows(snapshot: object | None) -> list[dict[str, Any]]:
    inline_search = cast(dict[str, Any], getattr(snapshot, "inline_search", None) or {})
    rows: list[dict[str, Any]] = []
    for key in ("raw_results", "fallback_results", "raw_fallback_results", "unified_raw_results"):
        for item in cast(list[object], inline_search.get(key) or []):
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _matching_refreshed_queue_link(
    refreshed_rows: Sequence[object],
    *,
    snapshot_row: dict[str, Any],
) -> str | None:
    snapshot_merge_key = str(snapshot_row.get("merge_key") or "").strip()
    snapshot_guid = str(snapshot_row.get("guid") or "").strip()
    snapshot_details_url = str(snapshot_row.get("details_url") or "").strip()
    snapshot_title = _normalize_result_identity_text(snapshot_row.get("title"))
    snapshot_indexer = _normalize_result_identity_text(snapshot_row.get("indexer"))

    def is_match(candidate: object) -> bool:
        merge_key = str(getattr(candidate, "merge_key", "") or "").strip()
        if snapshot_merge_key and merge_key == snapshot_merge_key:
            return True
        guid = str(getattr(candidate, "guid", "") or "").strip()
        if snapshot_guid and guid == snapshot_guid:
            return True
        details_url = str(getattr(candidate, "details_url", "") or "").strip()
        if snapshot_details_url and details_url == snapshot_details_url:
            return True
        candidate_title = _normalize_result_identity_text(getattr(candidate, "title", ""))
        candidate_indexer = _normalize_result_identity_text(getattr(candidate, "indexer", ""))
        return bool(
            snapshot_title
            and snapshot_indexer
            and candidate_title == snapshot_title
            and candidate_indexer == snapshot_indexer
        )

    for item in refreshed_rows:
        if not is_match(item):
            continue
        candidate_link = str(getattr(item, "link", "") or "").strip()
        if candidate_link:
            return candidate_link
    return None


def _broken_jackett_download_error(indexer_label: str | None) -> str:
    label = str(indexer_label or "this Jackett indexer").strip() or "this Jackett indexer"
    return (
        f"{label} returned a search result, but Jackett could not produce a downloadable torrent for it. "
        "This usually means the indexer can search but is not authenticated for downloads in Jackett. "
        "Re-test or reconfigure that indexer in Jackett, then refresh the rule snapshot and queue again."
    )


def _refresh_stale_rule_queue_link(
    *,
    session: Session,
    settings: AppSettings,
    rule: Rule | None,
    stale_link: str,
) -> tuple[str | None, str | None]:
    if rule is None:
        return None, None
    snapshot = get_rule_search_snapshot(session, rule_id=rule.id)
    if snapshot is None:
        return None, None
    snapshot_row = next(
        (
            item
            for item in _snapshot_queue_rows(snapshot)
            if str(item.get("link") or "").strip() == str(stale_link or "").strip()
        ),
        None,
    )
    if snapshot_row is None:
        return None, None
    indexer_label = str(snapshot_row.get("indexer") or "").strip() or None
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.api_url or not jackett.api_key:
        return None, indexer_label
    payload, ignored_full_regex = build_search_request_from_rule(rule)
    client = JackettClient(
        jackett.api_url,
        jackett.api_key,
        language_overrides=jackett.language_overrides,
    )
    refreshed_run = client.search(payload)
    refreshed_rows = [
        *list(refreshed_run.results or []),
        *list(refreshed_run.fallback_results or []),
        *list(refreshed_run.raw_results or []),
        *list(refreshed_run.raw_fallback_results or []),
    ]
    refreshed_link = _matching_refreshed_queue_link(
        refreshed_rows,
        snapshot_row=snapshot_row,
    )
    if not refreshed_link or refreshed_link == str(stale_link or "").strip():
        return None, indexer_label
    refreshed_snapshot = save_rule_search_snapshot(
        session,
        rule_id=rule.id,
        payload=payload,
        run=refreshed_run,
        ignored_full_regex=ignored_full_regex,
    )
    refresh_snapshot_release_cache(refreshed_snapshot, rule=rule)
    session.commit()
    return refreshed_link, indexer_label


def _rule_form_from_posted(form: Any) -> RuleFormPayload:
    return RuleFormPayload.model_validate(_raw_rule_form_data(form))


def _raw_rule_form_data(form: Any) -> dict[str, Any]:
    return {
        "rule_name": form.get("rule_name", ""),
        "content_name": form.get("content_name", ""),
        "imdb_id": form.get("imdb_id") or None,
        "normalized_title": form.get("normalized_title", ""),
        "poster_url": form.get("poster_url") or None,
        "media_type": form.get("media_type", MediaType.SERIES.value),
        "quality_profile": form.get("quality_profile", QualityProfile.PLAIN.value),
        "quality_mode": form.get("quality_mode") or None,
        "filter_profile_key": form.get("filter_profile_key", ""),
        "release_year": form.get("release_year", ""),
        "include_release_year": _bool_from_form(form, "include_release_year"),
        "additional_includes": form.get("additional_includes", ""),
        "quality_include_tokens": form.getlist("quality_include_tokens"),
        "quality_exclude_tokens": form.getlist("quality_exclude_tokens"),
        "use_regex": _bool_from_form(form, "use_regex"),
        "must_contain_override": form.get("must_contain_override") or None,
        "must_not_contain": form.get("must_not_contain", ""),
        "start_season": form.get("start_season") or None,
        "start_episode": form.get("start_episode") or None,
        "jellyfin_search_existing_unseen": _bool_from_form(form, "jellyfin_search_existing_unseen"),
        "episode_filter": form.get("episode_filter", ""),
        "ignore_days": form.get("ignore_days", 0),
        "add_paused": _bool_from_form(form, "add_paused"),
        "enabled": _bool_from_form(form, "enabled"),
        "smart_filter": _bool_from_form(form, "smart_filter"),
        "language": form.getlist("language"),
        "assigned_category": form.get("assigned_category", ""),
        "save_path": form.get("save_path", ""),
        "feed_urls": form.getlist("feed_urls"),
        "search_indexers": form.getlist("search_indexers"),
        "audiobook_title": form.get("audiobook_title", ""),
        "audiobook_author": form.get("audiobook_author", ""),
        "audiobook_publisher": form.get("audiobook_publisher", ""),
        "audiobook_genre": form.get("audiobook_genre", ""),
        "audiobook_isbn": form.get("audiobook_isbn", ""),
        "notes": form.get("notes", ""),
        "remember_feed_defaults": _bool_from_form(form, "remember_feed_defaults"),
    }


def _settings_form_from_posted(form: Any) -> SettingsFormPayload:
    return SettingsFormPayload.model_validate(_raw_settings_form_data(form))


def _raw_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "qb_base_url": form.get("qb_base_url") or None,
        "qb_username": form.get("qb_username") or None,
        "qb_password": form.get("qb_password") or None,
        "jackett_api_url": form.get("jackett_api_url") or None,
        "jackett_qb_url": form.get("jackett_qb_url") or None,
        "jackett_api_key": form.get("jackett_api_key") or None,
        "jackett_language_overrides_text": form.get("jackett_language_overrides_text", ""),
        "real_debrid_enabled": _bool_from_form(form, "real_debrid_enabled"),
        "real_debrid_webseed_base_url": form.get(
            "real_debrid_webseed_base_url", "http://127.0.0.1:8000"
        ),
        "real_debrid_metadata_wait_seconds": form.get(
            "real_debrid_metadata_wait_seconds", 120
        ),
        "myjd_enabled": _bool_from_form(form, "myjd_enabled"),
        "myjd_email": form.get("myjd_email") or None,
        "myjd_password": form.get("myjd_password") or None,
        "myjd_device_id": form.get("myjd_device_id") or None,
        "myjd_device_name": form.get("myjd_device_name") or None,
        "jellyfin_db_path": form.get("jellyfin_db_path") or None,
        "jellyfin_user_name": form.get("jellyfin_user_name") or None,
        "jellyfin_server_url": form.get("jellyfin_server_url") or None,
        "jellyfin_api_key": form.get("jellyfin_api_key") or None,
        "jellyfin_auto_sync_enabled": _bool_from_form(form, "jellyfin_auto_sync_enabled"),
        "jellyfin_auto_sync_interval_seconds": form.get("jellyfin_auto_sync_interval_seconds", 30),
        "stremio_local_storage_path": form.get("stremio_local_storage_path") or None,
        "stremio_auto_sync_enabled": _bool_from_form(form, "stremio_auto_sync_enabled"),
        "stremio_auto_sync_interval_seconds": form.get("stremio_auto_sync_interval_seconds", 30),
        "metadata_provider": form.get("metadata_provider", "omdb"),
        "omdb_api_key": form.get("omdb_api_key") or None,
        "series_category_template": form.get(
            "series_category_template",
            "Series/{title} [imdbid-{imdb_id}]",
        ),
        "movie_category_template": form.get(
            "movie_category_template",
            "Movies/{title} [imdbid-{imdb_id}]",
        ),
        "save_path_template": form.get("save_path_template", ""),
        "default_add_paused": _bool_from_form(form, "default_add_paused"),
        "default_sequential_download": _bool_from_form(form, "default_sequential_download"),
        "default_first_last_piece_prio": _bool_from_form(form, "default_first_last_piece_prio"),
        "default_enabled": _bool_from_form(form, "default_enabled"),
        "profile_1080p_include_tokens": form.getlist("profile_1080p_include_tokens"),
        "profile_1080p_exclude_tokens": form.getlist("profile_1080p_exclude_tokens"),
        "profile_2160p_hdr_include_tokens": form.getlist("profile_2160p_hdr_include_tokens"),
        "profile_2160p_hdr_exclude_tokens": form.getlist("profile_2160p_hdr_exclude_tokens"),
        "default_quality_profile": form.get("default_quality_profile", "plain"),
    }


def _raw_jellyfin_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "jellyfin_db_path": form.get("jellyfin_db_path") or None,
        "jellyfin_user_name": form.get("jellyfin_user_name") or None,
        "jellyfin_server_url": form.get("jellyfin_server_url") or None,
        "jellyfin_api_key": form.get("jellyfin_api_key") or None,
        "jellyfin_auto_sync_enabled": _bool_from_form(form, "jellyfin_auto_sync_enabled"),
        "jellyfin_auto_sync_interval_seconds": form.get(
            "jellyfin_auto_sync_interval_seconds", 30
        ),
    }


def _raw_stremio_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "stremio_local_storage_path": form.get("stremio_local_storage_path") or None,
        "stremio_auto_sync_enabled": _bool_from_form(form, "stremio_auto_sync_enabled"),
        "stremio_auto_sync_interval_seconds": form.get(
            "stremio_auto_sync_interval_seconds", 30
        ),
    }


def _raw_myjd_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "myjd_enabled": _bool_from_form(form, "myjd_enabled"),
        "myjd_email": form.get("myjd_email") or None,
        "myjd_password": form.get("myjd_password") or None,
        "myjd_device_id": form.get("myjd_device_id") or None,
        "myjd_device_name": form.get("myjd_device_name") or None,
    }


def _raw_qb_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "qb_base_url": form.get("qb_base_url") or None,
        "qb_username": form.get("qb_username") or None,
        "qb_password": form.get("qb_password") or None,
    }


def _raw_jackett_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "jackett_api_url": form.get("jackett_api_url") or None,
        "jackett_qb_url": form.get("jackett_qb_url") or None,
        "jackett_api_key": form.get("jackett_api_key") or None,
        "jackett_language_overrides_text": form.get("jackett_language_overrides_text", ""),
    }


def _raw_real_debrid_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "real_debrid_enabled": _bool_from_form(form, "real_debrid_enabled"),
        "real_debrid_webseed_base_url": form.get(
            "real_debrid_webseed_base_url", "http://127.0.0.1:8000"
        ),
        "real_debrid_metadata_wait_seconds": form.get(
            "real_debrid_metadata_wait_seconds", 120
        ),
    }


def _raw_metadata_settings_form_data(form: Any) -> dict[str, Any]:
    return {
        "metadata_provider": form.get("metadata_provider", "omdb"),
        "omdb_api_key": form.get("omdb_api_key") or None,
    }


def _raw_taxonomy_form_data(form: Any) -> dict[str, str]:
    return {
        "taxonomy_json": str(form.get("taxonomy_json", "")),
        "change_note": str(form.get("taxonomy_change_note", "")).strip(),
    }


def _render_rule_form(
    request: Request,
    *,
    mode: str,
    session: Session,
    form_data: dict[str, Any],
    errors: list[str],
    rule_id: str | None = None,
    status_code: int = 400,
) -> HTMLResponse:
    form_data.setdefault("jellyfin_search_existing_unseen", False)
    form_data.setdefault("jellyfin_auto_disabled", False)
    form_data.setdefault("movie_completion_sources", [])
    form_data.setdefault("movie_completion_sources_display", "")
    form_data.setdefault("movie_completion_auto_disabled", False)
    form_data.setdefault(
        "movie_auto_disabled",
        bool(form_data.get("movie_completion_auto_disabled", False))
        or bool(form_data.get("jellyfin_auto_disabled", False)),
    )
    form_data.setdefault("jellyfin_existing_episode_numbers", [])
    form_data.setdefault("audiobook_title", "")
    form_data.setdefault("audiobook_author", "")
    form_data.setdefault("audiobook_publisher", "")
    form_data.setdefault("audiobook_genre", "")
    form_data.setdefault("audiobook_isbn", "")
    if "jellyfin_existing_episode_count" not in form_data:
        existing_episode_numbers = form_data.get("jellyfin_existing_episode_numbers", []) or []
        if isinstance(existing_episode_numbers, list):
            form_data["jellyfin_existing_episode_count"] = len(existing_episode_numbers)
        else:
            form_data["jellyfin_existing_episode_count"] = 0
    settings = SettingsService.get_or_create(session)
    profile_rules = resolve_quality_profile_rules(settings)
    current_media_type = str(
        form_data.get("media_type", MediaType.SERIES.value) or MediaType.SERIES.value
    )
    resolved_language_feed_urls, language_resolution_notice = _resolve_language_feed_urls(
        session,
        language=str(form_data.get("language", "") or ""),
        selected_urls=cast(list[str], form_data.get("feed_urls", []) or []),
    )
    if str(form_data.get("language", "") or "").strip():
        form_data["feed_urls"] = resolved_language_feed_urls
    form_data.setdefault(
        "metadata_lookup_provider", default_metadata_lookup_provider(current_media_type)
    )
    available_filter_profiles = available_filter_profile_choices(settings)
    raw_selected_feed_urls = form_data.get("feed_urls", []) or []
    if isinstance(raw_selected_feed_urls, list):
        selected_feed_urls = raw_selected_feed_urls
    else:
        selected_feed_urls = [str(raw_selected_feed_urls)]
    context: dict[str, Any] = {
        "request": request,
        "page_title": "New Rule"
        if mode == "create"
        else f"Edit {form_data.get('rule_name', 'Rule')}",
        "mode": mode,
        "rule_id": rule_id,
        "form_data": form_data,
        "errors": errors,
        "feed_options": [],
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
            current_media_type,
        ),
        "media_choices": media_type_choices(),
        "metadata_lookup_providers": metadata_lookup_provider_catalog(),
        "visible_metadata_lookup_providers": metadata_lookup_provider_choices(current_media_type),
        "metadata_lookup_disabled": settings.metadata_provider.value == "disabled",
        "message": None,
        "message_level": "error",
        "shell_layout": "wide",
        "content_layout": "wide",
    }

    context["feed_options"] = _safe_feed_options(session, selected_feed_urls)

    return templates.TemplateResponse(request, "rule_form.html", context, status_code=status_code)


def _render_settings_page(
    request: Request,
    *,
    form_data: dict[str, Any],
    errors: list[str],
    message: str | None = None,
    message_level: str = "info",
    status_code: int = 400,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "page_title": "Settings",
            "form_data": form_data,
            "errors": errors,
            "profile_1080p_label": quality_profile_label(QualityProfile.HD_1080P),
            "profile_2160p_hdr_label": quality_profile_label(QualityProfile.UHD_2160P_HDR),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "metadata_choices": ["omdb", "disabled"],
            "app_version": getattr(request.app, "version", ""),
            "desktop_backend_contract": getattr(
                request.app.state, "desktop_backend_contract", ""
            ),
            "desktop_capabilities": list(
                getattr(request.app.state, "desktop_capabilities", []) or []
            ),
            "message": message,
            "message_level": message_level,
        },
        status_code=status_code,
    )


def _resolve_rule_payload_feeds(
    session: Session,
    payload: RuleFormPayload,
    *,
    existing_rule: Rule | None = None,
) -> tuple[RuleFormPayload, str | None, str | None]:
    had_language = bool(_normalize_language_list(payload.language))
    if not payload.language and list(payload.feed_urls or []):
        return payload, None, None
    if not payload.language:
        payload = payload.model_copy(update={"language": DEFAULT_RULE_LANGUAGE})
    resolved_feed_urls, resolution_error = _resolve_language_feed_urls(
        session,
        language=payload.language,
        selected_urls=list(payload.feed_urls or []),
    )
    if resolution_error:
        if (
            existing_rule is not None
            and _normalize_language_list(getattr(existing_rule, "language", ""))
            == _normalize_language_list(payload.language)
            and list(getattr(existing_rule, "feed_urls", []) or [])
        ):
            return (
                payload.model_copy(
                    update={"feed_urls": list(getattr(existing_rule, "feed_urls", []) or [])}
                ),
                None,
                resolution_error,
            )
        if had_language and resolution_error == LANGUAGE_FEED_SELECTION_NO_MATCHING_FEEDS:
            if _search_indexers_from_language(session, payload.language):
                return (
                    payload.model_copy(update={"feed_urls": []}),
                    None,
                    LANGUAGE_FEED_SELECTION_QB_FEEDS_UNAVAILABLE,
                )
            return payload, resolution_error, None
        if resolution_error == LANGUAGE_FEED_SELECTION_QB_FEEDS_UNAVAILABLE:
            return payload.model_copy(update={"feed_urls": []}), None, resolution_error
        return payload.model_copy(update={"feed_urls": []}), None, resolution_error
    return payload.model_copy(update={"feed_urls": resolved_feed_urls}), None, None


def _normalize_search_indexers(indexers: Sequence[object] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_indexer in list(indexers or []):
        candidate = str(raw_indexer or "").strip().casefold()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _search_indexers_from_feed_urls(feed_urls: Sequence[object] | None) -> list[str]:
    indexers: list[str] = []
    seen: set[str] = set()
    for raw_feed_url in list(feed_urls or []):
        indexer = feed_indexer_slug(str(raw_feed_url or ""))
        if not indexer or indexer in seen:
            continue
        seen.add(indexer)
        indexers.append(indexer)
    return indexers


def _search_indexers_from_language(session: Session, language: str) -> list[str]:
    normalized_languages = _normalize_language_list(language)
    if not normalized_languages:
        return []
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
        language_map = client.configured_indexer_languages()
    except JackettClientError:
        return []
    selected: list[str] = []
    seen: set[str] = set()
    for indexer in sorted(language_map):
        languages = {str(code).strip().casefold() for code in language_map.get(indexer, [])}
        if set(normalized_languages).isdisjoint(languages):
            continue
        if indexer in seen:
            continue
        seen.add(indexer)
        selected.append(indexer)
    return selected


def _resolve_rule_payload_search_indexers(
    session: Session,
    payload: RuleFormPayload,
    *,
    existing_rule: Rule | None = None,
) -> list[str]:
    explicit_indexers = _normalize_search_indexers(payload.search_indexers)
    if explicit_indexers:
        return explicit_indexers
    feed_indexers = _search_indexers_from_feed_urls(payload.feed_urls)
    if feed_indexers:
        return feed_indexers
    language_indexers = _search_indexers_from_language(session, payload.language)
    if language_indexers:
        return language_indexers
    if existing_rule is not None:
        existing_language = _normalize_language_list(getattr(existing_rule, "language", ""))
        if existing_language == _normalize_language_list(payload.language):
            return _normalize_search_indexers(getattr(existing_rule, "search_indexers", []) or [])
    return []


def _normalize_search_metadata_value(value: object | None) -> str:
    return str(value or "").strip()


def _search_metadata_from_rule_payload(payload: RuleFormPayload) -> dict[str, object]:
    if payload.media_type != MediaType.AUDIOBOOK:
        return {}

    fields = {
        "title": payload.audiobook_title,
        "author": payload.audiobook_author,
        "publisher": payload.audiobook_publisher,
        "genre": payload.audiobook_genre,
        "isbn": payload.audiobook_isbn,
    }
    return {
        key: cleaned
        for key, value in fields.items()
        if (cleaned := _normalize_search_metadata_value(value))
    }


def _render_taxonomy_page(
    request: Request,
    *,
    session: Session,
    form_data: dict[str, str],
    errors: list[str],
    preview: dict[str, object] | None = None,
    message: str | None = None,
    message_level: str = "info",
    status_code: int = 400,
) -> HTMLResponse:
    current_errors = list(errors)
    current_snapshot: dict[str, object] | None = None
    current_preview: dict[str, object] | None = None

    settings = SettingsService.get_or_create(session)
    rules = session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
    try:
        raw_taxonomy = read_quality_taxonomy_text()
        current_snapshot = quality_taxonomy_snapshot()
        current_preview = preview_quality_taxonomy_update(
            raw_taxonomy,
            settings=settings,
            rules=rules,
        )
    except RuntimeError as exc:
        if not current_errors:
            current_errors.append(str(exc))

    return templates.TemplateResponse(
        request,
        "taxonomy.html",
        {
            "request": request,
            "page_title": "Taxonomy",
            "taxonomy_form": form_data,
            "taxonomy_preview": preview,
            "taxonomy_snapshot": current_snapshot,
            "current_taxonomy_preview": current_preview,
            "taxonomy_audit_entries": recent_quality_taxonomy_audit_entries(),
            "taxonomy_media_types": [choice["value"] for choice in media_type_choices()],
            "errors": current_errors,
            "message": message,
            "message_level": message_level,
        },
        status_code=status_code,
    )


def _render_import_page(
    request: Request,
    *,
    preview_entries: list[dict[str, Any]],
    errors: list[str],
    result_summary: dict[str, Any] | None = None,
    status_code: int = 400,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "request": request,
            "page_title": "Import",
            "preview_entries": preview_entries,
            "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
            "errors": errors,
            "result_summary": result_summary,
            "message": None,
            "message_level": "error",
        },
        status_code=status_code,
    )


def _apply_rule_payload_to_model(
    rule: Rule,
    payload: RuleFormPayload,
    *,
    settings: AppSettings,
    feed_resolution_notice: str | None = None,
    search_indexers: list[str] | None = None,
) -> None:
    rule.rule_name = payload.rule_name
    rule.content_name = payload.content_name
    rule.imdb_id = payload.imdb_id
    rule.normalized_title = payload.normalized_title or payload.content_name
    rule.poster_url = payload.poster_url
    rule.media_type = payload.media_type
    rule.quality_profile = payload.quality_profile
    rule.quality_mode = payload.quality_mode
    rule.release_year = payload.release_year
    rule.include_release_year = payload.include_release_year
    rule.additional_includes = payload.additional_includes
    if payload.quality_mode == QualityMode.MANAGED:
        existing_include_tokens = list(getattr(rule, "quality_include_tokens", []) or [])
        existing_exclude_tokens = list(getattr(rule, "quality_exclude_tokens", []) or [])
        rule.quality_include_tokens = existing_include_tokens or payload.quality_include_tokens
        rule.quality_exclude_tokens = existing_exclude_tokens or payload.quality_exclude_tokens
    else:
        rule.quality_include_tokens = payload.quality_include_tokens
        rule.quality_exclude_tokens = payload.quality_exclude_tokens
    rule.use_regex = payload.use_regex
    rule.must_contain_override = payload.must_contain_override
    rule.must_not_contain = payload.must_not_contain
    rule.start_season = payload.start_season
    rule.start_episode = payload.start_episode
    rule.jellyfin_search_existing_unseen = payload.jellyfin_search_existing_unseen
    rule.episode_filter = payload.episode_filter
    rule.ignore_days = payload.ignore_days
    rule.add_paused = payload.add_paused
    rule.enabled = payload.enabled
    rule.smart_filter = payload.smart_filter
    rule.language = payload.language
    rule.feed_urls = payload.feed_urls
    rule.search_indexers = _normalize_search_indexers(
        search_indexers if search_indexers is not None else payload.search_indexers
    )
    rule.search_metadata = _search_metadata_from_rule_payload(payload)
    if _normalize_language_list(payload.language):
        rule.feed_resolution_status = "unavailable" if feed_resolution_notice else "resolved"
        rule.feed_resolution_message = feed_resolution_notice or ""
    else:
        rule.feed_resolution_status = "manual"
        rule.feed_resolution_message = ""
    rule.notes = payload.notes
    rule.assigned_category = payload.assigned_category
    rule.save_path = payload.save_path

    builder = RuleBuilder(settings)
    if not rule.assigned_category.strip():
        rule.assigned_category = builder.render_category(rule)
    if not rule.save_path.strip():
        rule.save_path = builder.render_save_path(rule)


def _clone_settings(settings: AppSettings) -> AppSettings:
    return AppSettings(
        id=settings.id,
        qb_base_url=settings.qb_base_url,
        qb_username=settings.qb_username,
        qb_password_encrypted=settings.qb_password_encrypted,
        jackett_api_url=settings.jackett_api_url,
        jackett_qb_url=settings.jackett_qb_url,
        jackett_api_key_encrypted=settings.jackett_api_key_encrypted,
        real_debrid_enabled=bool(getattr(settings, "real_debrid_enabled", False)),
        real_debrid_client_id_encrypted=getattr(
            settings, "real_debrid_client_id_encrypted", None
        ),
        real_debrid_client_secret_encrypted=getattr(
            settings, "real_debrid_client_secret_encrypted", None
        ),
        real_debrid_access_token_encrypted=getattr(
            settings, "real_debrid_access_token_encrypted", None
        ),
        real_debrid_refresh_token_encrypted=getattr(
            settings, "real_debrid_refresh_token_encrypted", None
        ),
        real_debrid_token_expires_at=getattr(settings, "real_debrid_token_expires_at", None),
        real_debrid_account_username=getattr(
            settings, "real_debrid_account_username", None
        ),
        real_debrid_account_premium_until=getattr(
            settings, "real_debrid_account_premium_until", None
        ),
        real_debrid_connection_status=str(
            getattr(settings, "real_debrid_connection_status", "disconnected")
        ),
        real_debrid_connection_message=str(
            getattr(settings, "real_debrid_connection_message", "")
        ),
        real_debrid_webseed_base_url=str(
            getattr(settings, "real_debrid_webseed_base_url", "http://127.0.0.1:8000")
        ),
        real_debrid_metadata_wait_seconds=int(
            getattr(settings, "real_debrid_metadata_wait_seconds", 120)
        ),
        myjd_enabled=bool(getattr(settings, "myjd_enabled", False)),
        myjd_email=getattr(settings, "myjd_email", None),
        myjd_password_encrypted=getattr(settings, "myjd_password_encrypted", None),
        myjd_device_id=getattr(settings, "myjd_device_id", None),
        myjd_device_name=getattr(settings, "myjd_device_name", None),
        myjd_connection_status=str(
            getattr(settings, "myjd_connection_status", "disconnected")
        ),
        myjd_connection_message=str(getattr(settings, "myjd_connection_message", "")),
        jellyfin_db_path=getattr(settings, "jellyfin_db_path", None),
        jellyfin_user_name=getattr(settings, "jellyfin_user_name", None),
        jellyfin_server_url=getattr(settings, "jellyfin_server_url", None),
        jellyfin_api_key_encrypted=getattr(settings, "jellyfin_api_key_encrypted", None),
        jellyfin_auto_sync_enabled=bool(getattr(settings, "jellyfin_auto_sync_enabled", True)),
        jellyfin_auto_sync_interval_seconds=int(
            getattr(settings, "jellyfin_auto_sync_interval_seconds", 30)
        ),
        jellyfin_auto_sync_last_run_at=getattr(settings, "jellyfin_auto_sync_last_run_at", None),
        jellyfin_auto_sync_last_status=str(
            getattr(settings, "jellyfin_auto_sync_last_status", "idle")
        ),
        jellyfin_auto_sync_last_message=str(
            getattr(settings, "jellyfin_auto_sync_last_message", "")
        ),
        stremio_local_storage_path=getattr(settings, "stremio_local_storage_path", None),
        stremio_auto_sync_enabled=bool(getattr(settings, "stremio_auto_sync_enabled", True)),
        stremio_auto_sync_interval_seconds=int(
            getattr(settings, "stremio_auto_sync_interval_seconds", 30)
        ),
        stremio_auto_sync_last_run_at=getattr(settings, "stremio_auto_sync_last_run_at", None),
        stremio_auto_sync_last_status=str(
            getattr(settings, "stremio_auto_sync_last_status", "idle")
        ),
        stremio_auto_sync_last_message=str(getattr(settings, "stremio_auto_sync_last_message", "")),
        metadata_provider=settings.metadata_provider,
        omdb_api_key_encrypted=settings.omdb_api_key_encrypted,
        series_category_template=settings.series_category_template,
        movie_category_template=settings.movie_category_template,
        save_path_template=settings.save_path_template,
        default_add_paused=settings.default_add_paused,
        default_sequential_download=bool(getattr(settings, "default_sequential_download", True)),
        default_first_last_piece_prio=bool(
            getattr(settings, "default_first_last_piece_prio", True)
        ),
        default_enabled=settings.default_enabled,
        quality_profile_rules=settings.quality_profile_rules,
        saved_quality_profiles=settings.saved_quality_profiles,
        default_feed_urls=settings.default_feed_urls,
        search_result_view_mode=settings.search_result_view_mode,
        search_sort_criteria=settings.search_sort_criteria,
        rules_fetch_schedule_enabled=bool(getattr(settings, "rules_fetch_schedule_enabled", False)),
        rules_fetch_schedule_interval_minutes=int(
            getattr(settings, "rules_fetch_schedule_interval_minutes", 360)
        ),
        rules_fetch_schedule_scope=str(getattr(settings, "rules_fetch_schedule_scope", "enabled")),
        rules_fetch_schedule_last_run_at=getattr(
            settings, "rules_fetch_schedule_last_run_at", None
        ),
        rules_fetch_schedule_next_run_at=getattr(
            settings, "rules_fetch_schedule_next_run_at", None
        ),
        rules_fetch_schedule_last_status=str(
            getattr(settings, "rules_fetch_schedule_last_status", "idle")
        ),
        rules_fetch_schedule_last_message=str(
            getattr(settings, "rules_fetch_schedule_last_message", "")
        ),
        rules_fetch_parallelism=int(getattr(settings, "rules_fetch_parallelism", 3)),
        rules_page_view_mode=str(getattr(settings, "rules_page_view_mode", "table")),
        rules_page_sort_field=str(getattr(settings, "rules_page_sort_field", "updated_at")),
        rules_page_sort_direction=str(getattr(settings, "rules_page_sort_direction", "desc")),
        default_quality_profile=settings.default_quality_profile,
    )


@router.post("/metadata/lookup")
def metadata_lookup(
    payload: MetadataLookupRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    metadata_config = SettingsService.resolve_metadata(settings)
    client = MetadataClient(metadata_config.provider, metadata_config.api_key)
    try:
        result = client.lookup(payload.provider, payload.lookup_value, payload.media_type)
    except MetadataLookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result.model_dump(mode="json"))


@router.post("/search/jackett")
def jackett_search(
    payload: JackettSearchRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    client = JackettClient(
        jackett.api_url,
        jackett.api_key,
        language_overrides=jackett.language_overrides,
    )
    try:
        result = client.search(payload)
    except JackettClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result.model_dump(mode="json"))


@router.post("/search/queue")
def queue_search_result(
    payload: SearchQueueRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    connection = SettingsService.resolve_qb_connection(settings)
    jackett = SettingsService.resolve_jackett(settings)

    category = ""
    save_path = ""
    add_paused = payload.add_paused
    rule: Rule | None = None
    if payload.rule_id:
        rule = session.get(Rule, payload.rule_id)
        if rule is None:
            return JSONResponse({"error": "Rule not found for queue defaults."}, status_code=404)
        builder = RuleBuilder(settings)
        category = builder.render_category(rule)
        save_path = builder.render_save_path(rule)
        if add_paused is None:
            add_paused = rule.add_paused
    if add_paused is None:
        # Queueing without a rule is always paused unless this individual
        # request explicitly opts out. Saved rule exceptions are handled above.
        add_paused = True

    if payload.source_kind.value == "real_debrid_download":
        return _queue_real_debrid_history_download(
            session=session,
            settings=settings,
            payload=payload,
            save_path=save_path,
        )
    if not connection.is_configured:
        return JSONResponse({"error": "qBittorrent connection is not configured."}, status_code=400)
    if payload.source_kind.value == "real_debrid_torrent":
        try:
            access_token = ensure_real_debrid_access_token(session, settings)
            with RealDebridClient(access_token) as rd_client:
                provider = rd_client.get_torrent(str(payload.provider_id or ""))
            info_hash = str(provider.get("hash") or payload.info_hash or "").strip().casefold()
            if len(info_hash) != 40:
                raise RealDebridError("Real-Debrid torrent has no supported v1 infohash.")
            payload.link = f"magnet:?xt=urn:btih:{info_hash}"
            payload.links = [payload.link]
            payload.info_hash = info_hash
        except RealDebridError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    retryable_stale_link = str(payload.link or "").strip()
    try:
        if len(payload.links or []) > 1:
            queue_result = queue_grouped_search_results(
                qb_base_url=connection.base_url or "",
                qb_username=connection.username or "",
                qb_password=connection.password or "",
                links=list(payload.links or []),
                jackett_api_url=jackett.api_url,
                jackett_qb_url=jackett.qb_url,
                info_hash=payload.info_hash,
                tracker_urls=list(payload.tracker_urls or []),
                category=category,
                save_path=save_path,
                paused=bool(add_paused),
                sequential_download=payload.sequential_download,
                first_last_piece_prio=payload.first_last_piece_prio,
                rule=rule,
            )
        else:
            queue_result = queue_result_with_optional_file_selection(
                qb_base_url=connection.base_url or "",
                qb_username=connection.username or "",
                qb_password=connection.password or "",
                link=payload.link,
                jackett_api_url=jackett.api_url,
                jackett_qb_url=jackett.qb_url,
                category=category,
                save_path=save_path,
                paused=bool(add_paused),
                sequential_download=payload.sequential_download,
                first_last_piece_prio=payload.first_last_piece_prio,
                rule=rule,
            )
    except SelectiveQueueError as exc:
        refreshed_link, _refreshed_indexer_label = _refresh_stale_rule_queue_link(
            session=session,
            settings=settings,
            rule=rule,
            stale_link=retryable_stale_link,
        )
        if refreshed_link:
            try:
                queue_result = queue_result_with_optional_file_selection(
                    qb_base_url=connection.base_url or "",
                    qb_username=connection.username or "",
                    qb_password=connection.password or "",
                    link=refreshed_link,
                    jackett_api_url=jackett.api_url,
                    jackett_qb_url=jackett.qb_url,
                    category=category,
                    save_path=save_path,
                    paused=bool(add_paused),
                    sequential_download=payload.sequential_download,
                    first_last_piece_prio=payload.first_last_piece_prio,
                    rule=rule,
                )
            except (SelectiveQueueError, QbittorrentClientError) as retry_exc:
                return JSONResponse({"error": str(retry_exc)}, status_code=400)
        else:
            return JSONResponse({"error": str(exc)}, status_code=400)
    except QbittorrentClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse(
        {
            "status": "queued",
            "category": category,
            "save_path": save_path,
            "add_paused": add_paused,
            "sequential_download": payload.sequential_download,
            "first_last_piece_prio": payload.first_last_piece_prio,
            "message": queue_result.message,
            "selected_file_count": queue_result.selected_file_count,
            "skipped_file_count": queue_result.skipped_file_count,
            "deferred_file_selection": queue_result.deferred_file_selection,
            "queued_via_torrent_file": queue_result.queued_via_torrent_file,
        }
    )


@router.post("/search/preferences")
def save_search_preferences(
    payload: SearchViewPreferencesPayload,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    settings.search_result_view_mode = payload.view_mode
    settings.search_sort_criteria = [item.model_dump(mode="json") for item in payload.sort_criteria]
    if payload.default_sequential_download is not None:
        settings.default_sequential_download = payload.default_sequential_download
    if payload.default_first_last_piece_prio is not None:
        settings.default_first_last_piece_prio = payload.default_first_last_piece_prio
    session.add(settings)
    session.commit()
    return JSONResponse(
        {
            "view_mode": settings.search_result_view_mode,
            "sort_criteria": list(settings.search_sort_criteria or []),
            "default_sequential_download": bool(
                getattr(settings, "default_sequential_download", True)
            ),
            "default_first_last_piece_prio": bool(
                getattr(settings, "default_first_last_piece_prio", True)
            ),
        }
    )


@router.post("/debug/hover-telemetry")
async def record_debug_hover_telemetry(request: Request) -> JSONResponse:
    payload = await request.json()
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Hover telemetry payload must be a JSON object."}, status_code=400
        )
    event = record_hover_event(payload)
    return JSONResponse({"status": "ok", "event": event})


@router.get("/debug/hover-telemetry")
def read_debug_hover_telemetry(
    limit: int = 50,
    session_id: str | None = None,
    clear: bool = False,
) -> JSONResponse:
    cleared_count = 0
    if clear:
        cleared_count = clear_hover_events(session_id=session_id)
    events = list_hover_events(limit=limit, session_id=session_id)
    return JSONResponse(
        {
            "events": events,
            "count": len(events),
            "cleared_count": cleared_count,
            "log_path": str(hover_debug_log_path()),
        }
    )


@router.get("/operations/status")
def read_operations_status(
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    payload = operations_status_payload()
    active_operations = [
        operation
        for operation in cast(list[dict[str, object]], payload["operations"])
        if str(operation.get("status") or "") in {"queued", "running"}
    ]
    payload["operations"] = active_operations
    total = sum(
        int(value) if isinstance(value, (int, float, str)) else 0
        for operation in active_operations
        for value in [operation.get("total") or 0]
    )
    current = sum(
        int(value) if isinstance(value, (int, float, str)) else 0
        for operation in active_operations
        for value in [operation.get("current") or 0]
    )
    payload["summary"] = {
        "is_running": bool(active_operations),
        "operation_count": len(active_operations),
        "active_count": len(active_operations),
        "current": current,
        "total": total,
        "percent": round((current / total) * 100) if total else None,
    }
    problem_states = {"terminal_error", "retry_wait", "metadata_unavailable"}
    problem_count = int(
        session.scalar(
            select(func.count()).select_from(DownloadAccelerationJob).where(
                DownloadAccelerationJob.state.in_(problem_states),
                DownloadAccelerationJob.notification_dismissed_at.is_(None),
            )
        ) or 0
    )
    payload["acceleration_problem_count"] = problem_count
    payload["acceleration_console_url"] = "/acceleration"
    return JSONResponse(payload)


def _acceleration_job_payload(
    job: DownloadAccelerationJob,
    *,
    rules_by_id: dict[str, Rule],
    maintenance_by_job: dict[str, dict[str, object]],
) -> dict[str, object]:
    error_states = {"terminal_error", "retry_wait", "metadata_unavailable"}
    success_states = {"completed", "webseed_attached"}
    return {
        "id": job.id,
        "type": "download_acceleration",
        "label": (
            f"{rules_by_id[job.rule_id].rule_name} - Real-Debrid acceleration"
            if job.rule_id in rules_by_id
            else "Real-Debrid acceleration"
        ),
        "info_hash": job.info_hash,
        "reference": str(job.info_hash or job.provider_download_id or job.id)[:12],
        "subject": job.torrent_name,
        "rule_id": job.rule_id,
        "rule_name": rules_by_id[job.rule_id].rule_name
        if job.rule_id in rules_by_id
        else None,
        "context_url": f"/rules/{job.rule_id}" if job.rule_id in rules_by_id else None,
        "codex_request_status": str(maintenance_by_job.get(job.id, {}).get("status") or ""),
        "codex_request_result": str(maintenance_by_job.get(job.id, {}).get("result") or ""),
        "status": "error" if job.state in error_states else "success" if job.state in success_states else "running",
        "state": job.state,
        "message": job.last_error or job.state.replace("_", " ").title(),
        "updated_at": job.updated_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "dismissed": job.notification_dismissed_at is not None,
    }


@router.get("/acceleration/jobs")
def read_acceleration_jobs(
    status: str = "all",
    limit: int = 500,
    include_dismissed: bool = False,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    limit = max(1, min(limit, 1000))
    query = select(DownloadAccelerationJob)
    if not include_dismissed:
        query = query.where(DownloadAccelerationJob.notification_dismissed_at.is_(None))
    error_states = {"terminal_error", "retry_wait", "metadata_unavailable"}
    success_states = {"completed", "webseed_attached"}
    if status == "problems":
        query = query.where(DownloadAccelerationJob.state.in_(error_states))
    elif status == "active":
        query = query.where(DownloadAccelerationJob.state.not_in(error_states | success_states))
    elif status == "finished":
        query = query.where(DownloadAccelerationJob.state.in_(success_states))
    jobs = list(session.scalars(query.order_by(DownloadAccelerationJob.updated_at.desc()).limit(limit)))
    rules_by_id = {
        rule.id: rule
        for rule in session.scalars(
            select(Rule).where(
                Rule.id.in_({job.rule_id for job in jobs if job.rule_id})
            )
        )
    }
    maintenance_by_job = maintenance_status_by_job()
    items = [
        _acceleration_job_payload(job, rules_by_id=rules_by_id, maintenance_by_job=maintenance_by_job)
        for job in jobs
    ]
    return JSONResponse({"items": items, "count": len(items), "status": status})


@router.post("/acceleration/jobs/{job_id}/dismiss")
def dismiss_acceleration_job_notification(
    job_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    job = session.get(DownloadAccelerationJob, job_id)
    if job is None:
        return JSONResponse({"error": "Acceleration job not found."}, status_code=404)
    job.notification_dismissed_at = utcnow()
    session.add(job)
    session.commit()
    return JSONResponse({"status": "dismissed", "job_id": job.id})


@router.post("/acceleration/jobs/{job_id}/ask-codex")
def ask_codex_to_investigate_acceleration_job(
    job_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    job = session.get(DownloadAccelerationJob, job_id)
    if job is None:
        return JSONResponse({"error": "Acceleration job not found."}, status_code=404)
    rule = session.get(Rule, job.rule_id) if job.rule_id else None
    request_payload = queue_acceleration_maintenance_request(job, rule=rule)
    return JSONResponse(
        {
            "status": "queued",
            "request_id": request_payload["id"],
            "message": (
                "Codex maintenance task queued. "
                "It will inspect this issue within five minutes."
            ),
        }
    )


@router.post("/acceleration/jobs/dismiss-finished")
def dismiss_finished_acceleration_notifications(
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    jobs = list(
        session.scalars(
            select(DownloadAccelerationJob).where(
                DownloadAccelerationJob.state.in_({"completed", "webseed_attached"}),
                DownloadAccelerationJob.notification_dismissed_at.is_(None),
            )
        )
    )
    dismissed_at = utcnow()
    for job in jobs:
        job.notification_dismissed_at = dismissed_at
        session.add(job)
    session.commit()
    return JSONResponse({"status": "dismissed", "dismissed_count": len(jobs)})


@router.post("/acceleration/adopt")
def adopt_existing_rule_torrents(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    settings = SettingsService.get_or_create(session)
    config = SettingsService.resolve_qb_connection(settings)
    if not config.is_configured:
        return JSONResponse({"error": "qBittorrent is not configured."}, status_code=400)
    categories = sorted(
        {
            str(rule.assigned_category or "").strip()
            for rule in session.scalars(select(Rule).where(Rule.enabled.is_(True)))
            if str(rule.assigned_category or "").strip()
        }
    )
    adopted: list[str] = []
    with QbittorrentClient(config.base_url, config.username, config.password) as client:
        for category in categories:
            for torrent in client.get_torrents(category=category):
                info_hash = str(torrent.get("hash") or "").strip().casefold()
                tags = {item.strip() for item in str(torrent.get("tags") or "").split(",")}
                try:
                    progress = float(str(torrent.get("progress") or 0))
                except ValueError:
                    progress = 0.0
                if info_hash and progress < 1 and MANAGED_TORRENT_TAG not in tags:
                    client.add_tags(info_hash, [MANAGED_TORRENT_TAG])
                    adopted.append(info_hash)
    if "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
        return RedirectResponse(
            url=f"/?message=Adopted%20{len(adopted)}%20existing%20torrent(s).&level=success",
            status_code=303,
        )
    return JSONResponse({"status": "ok", "adopted_count": len(adopted)})


@router.post("/acceleration/jobs/{job_id}/retry")
def retry_acceleration_job(
    job_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    job = session.get(DownloadAccelerationJob, job_id)
    if job is None:
        return JSONResponse({"error": "Acceleration job not found."}, status_code=404)
    job.state = "discovered" if not job.provider_torrent_id else "provider_submitted"
    job.retry_count = 0
    job.next_retry_at = None
    job.last_error = ""
    job.notification_dismissed_at = None
    session.add(job)
    session.commit()
    return JSONResponse({"status": "queued", "job_id": job.id})


@router.post("/acceleration/jobs/{job_id}/cleanup")
def cleanup_acceleration_job(
    job_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    job = session.get(DownloadAccelerationJob, job_id)
    if job is None:
        return JSONResponse({"error": "Acceleration job not found."}, status_code=404)
    settings = SettingsService.get_or_create(session)
    config = SettingsService.resolve_qb_connection(settings)
    if config.is_configured and job.info_hash and job.app_webseed_urls:
        with QbittorrentClient(config.base_url, config.username, config.password) as client:
            client.remove_webseeds(job.info_hash, list(job.app_webseed_urls))
    session.delete(job)
    session.commit()
    return JSONResponse({"status": "cleaned", "delete_files": False})


@router.post("/rules/page-preferences")
def save_rules_page_preferences(
    payload: RulesPagePreferencesPayload,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    settings.rules_page_view_mode = payload.view_mode
    settings.rules_page_sort_field = payload.sort_field
    settings.rules_page_sort_direction = payload.sort_direction
    session.add(settings)
    session.commit()
    return JSONResponse(
        {
            "view_mode": settings.rules_page_view_mode,
            "sort_field": settings.rules_page_sort_field,
            "sort_direction": settings.rules_page_sort_direction,
        }
    )


@router.post("/rules/batch-quality-profile")
def batch_update_rule_quality_profile(
    payload: RuleBatchQualityProfileRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    target_profile = QualityProfile(payload.quality_profile)
    selected_rules = session.scalars(select(Rule).where(Rule.id.in_(payload.rule_ids))).all()
    rules_by_id = {rule.id: rule for rule in selected_rules}
    results: list[dict[str, object]] = []
    changed_rule_ids: list[str] = []

    for rule_id in payload.rule_ids:
        rule = rules_by_id.get(rule_id)
        if rule is None:
            results.append(
                {
                    "rule_id": rule_id,
                    "status": "skipped",
                    "reason": "Rule not found.",
                }
            )
            continue
        if rule.quality_profile == target_profile and rule.quality_mode == QualityMode.MANAGED:
            results.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.rule_name,
                    "status": "skipped",
                    "reason": "Rule already uses that managed profile.",
                }
            )
            continue
        rule.quality_profile = target_profile
        rule.quality_mode = QualityMode.MANAGED
        rule.last_sync_status = SyncStatus.PENDING
        rule.last_sync_error = None
        session.add(rule)
        changed_rule_ids.append(rule.id)
        results.append(
            {
                "rule_id": rule.id,
                "rule_name": rule.rule_name,
                "status": "changed",
                "quality_profile": target_profile.value,
                "quality_mode": QualityMode.MANAGED.value,
            }
        )

    if changed_rule_ids:
        session.commit()
    else:
        session.rollback()

    sync_enqueued_count = 0
    sync_results: list[dict[str, object]] = []
    for rule_id in changed_rule_ids:
        summary = enqueue_rule_sync(rule_id)
        if isinstance(summary, dict):
            sync_results.append({"rule_id": rule_id, **summary})
            sync_enqueued_count += 1 if summary.get("enqueued") or summary.get("duplicate") else 0
        else:
            sync_results.append({"rule_id": rule_id, "enqueued": True})
            sync_enqueued_count += 1

    return JSONResponse(
        {
            "changed_count": len(changed_rule_ids),
            "skipped_count": len(results) - len(changed_rule_ids),
            "results": results,
            "sync_enqueued_count": sync_enqueued_count,
            "sync": sync_results,
        }
    )


@router.post("/rules/fetch")
def run_rules_fetch(
    payload: RuleBatchFetchRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    batch = run_rules_fetch_batch(
        session,
        run_all=payload.run_all,
        rule_ids=payload.rule_ids,
        include_disabled=payload.include_disabled,
    )
    status_code = 200
    if batch.get("status") == "error":
        status_code = 400
    elif batch.get("status") == "busy":
        status_code = 409
    return JSONResponse(batch, status_code=status_code)


@router.post("/rules/fetch-schedule")
def save_rules_fetch_schedule(
    payload: RuleFetchSchedulePayload,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    schedule = update_schedule_settings(
        session,
        enabled=payload.enabled,
        interval_minutes=payload.interval_minutes,
        scope=payload.scope,
    )
    return JSONResponse({"status": "ok", "schedule": schedule})


@router.post("/rules/fetch-schedule/run-now")
def run_rules_fetch_schedule_now(session: Session = Depends(get_db_session)) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    if not bool(getattr(settings, "rules_fetch_schedule_enabled", False)):
        return JSONResponse(
            {
                "error": "Rule fetch schedule is disabled. Enable and save schedule first.",
                "schedule": schedule_payload(settings),
            },
            status_code=400,
        )
    batch = run_scheduled_fetch_now(session)
    status_code = 200
    if batch.get("status") == "error":
        status_code = 400
    elif batch.get("status") == "busy":
        status_code = 409
    return JSONResponse(batch, status_code=status_code)


@router.post("/feeds/refresh")
def feeds_refresh(session: Session = Depends(get_db_session)) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    jackett = SettingsService.resolve_jackett(settings)
    if not jackett.app_ready:
        return JSONResponse({"error": "Jackett app URL and API key are both required."}, status_code=400)
    try:
        feeds = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        ).configured_indexer_options()
    except JackettClientError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"feeds": feeds})


@router.post("/filter-profiles")
def save_filter_profile(
    payload: FilterProfileSaveRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    saved_profiles = normalize_saved_quality_profiles(settings.saved_quality_profiles)
    all_profiles = build_available_filter_profiles(settings)
    scoped_media_types = (
        [payload.media_type.value]
        if payload.media_type
        in {
            MediaType.SERIES,
            MediaType.MOVIE,
            MediaType.AUDIOBOOK,
            MediaType.MUSIC,
        }
        else None
    )

    if payload.mode == "create":
        profile_key = slugify_profile_key(payload.profile_name)
        if not profile_key:
            return JSONResponse({"error": "A profile name is required."}, status_code=400)
        if profile_key in all_profiles:
            return JSONResponse(
                {"error": "A profile with that name already exists."}, status_code=400
            )
        new_profile: dict[str, object] = {
            "label": payload.profile_name,
            "include_tokens": payload.include_tokens,
            "exclude_tokens": payload.exclude_tokens,
        }
        if scoped_media_types:
            new_profile["media_types"] = scoped_media_types
        saved_profiles[profile_key] = new_profile
    else:
        if payload.target_key == "builtin-at-least-hd":
            profile_rules = resolve_quality_profile_rules(settings)
            profile_rules[QualityProfile.HD_1080P.value] = {
                "include_tokens": payload.include_tokens,
                "exclude_tokens": payload.exclude_tokens,
            }
            settings.quality_profile_rules = profile_rules
            profile_key = payload.target_key
        elif payload.target_key == "builtin-ultra-hd-hdr":
            profile_rules = resolve_quality_profile_rules(settings)
            profile_rules[QualityProfile.UHD_2160P_HDR.value] = {
                "include_tokens": payload.include_tokens,
                "exclude_tokens": payload.exclude_tokens,
            }
            settings.quality_profile_rules = profile_rules
            profile_key = payload.target_key
        elif payload.target_key not in all_profiles:
            return JSONResponse(
                {"error": "Select an existing saved profile or preset to overwrite."},
                status_code=400,
            )
        else:
            existing = all_profiles[payload.target_key]
            updated_profile: dict[str, object] = {
                "label": str(existing.get("label", payload.target_key)),
                "include_tokens": payload.include_tokens,
                "exclude_tokens": payload.exclude_tokens,
            }
            if payload.target_key in builtin_filter_profile_keys():
                raw_existing_media_types = existing.get("media_types")
                existing_media_types = (
                    [str(item) for item in raw_existing_media_types]
                    if isinstance(raw_existing_media_types, list)
                    else []
                )
                if existing_media_types:
                    updated_profile["media_types"] = existing_media_types
            elif scoped_media_types:
                updated_profile["media_types"] = scoped_media_types
            saved_profiles[payload.target_key] = updated_profile
            profile_key = payload.target_key

    settings.saved_quality_profiles = saved_profiles
    session.add(settings)
    session.commit()
    session.refresh(settings)

    return JSONResponse(
        {
            "profile_key": profile_key,
            "profiles": available_filter_profile_choices(settings),
        }
    )


@router.post("/import/qb-json", response_class=HTMLResponse)
async def import_qb_json(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    upload_candidate = form.get("rules_file")
    if upload_candidate is None:
        return _render_import_page(
            request,
            preview_entries=[],
            errors=["Choose a JSON export file first."],
        )
    upload_filename = str(getattr(upload_candidate, "filename", "") or "").strip()
    upload_reader = getattr(upload_candidate, "read", None)
    if not upload_filename or not callable(upload_reader):
        return _render_import_page(
            request,
            preview_entries=[],
            errors=["Choose a JSON export file first."],
        )
    upload = cast(UploadFile, upload_candidate)

    mode_raw = form.get("mode", ImportMode.SKIP.value)
    preview_only = str(form.get("preview_only", "0")) == "1"

    try:
        mode = ImportMode(mode_raw)
    except ValueError:
        mode = ImportMode.SKIP

    raw_bytes = await upload.read()
    if not raw_bytes:
        return _render_import_page(
            request,
            preview_entries=[],
            errors=["The selected file is empty."],
        )
    importer = Importer(session)
    try:
        if preview_only:
            entries = importer.preview_import_from_bytes(raw_bytes, mode=mode)
            return _render_import_page(
                request,
                preview_entries=[entry.model_dump(mode="json") for entry in entries],
                errors=[],
                result_summary=None,
                status_code=200,
            )
        result = importer.apply_import_from_bytes(
            raw_bytes,
            mode=mode,
            source_name=upload_filename or "uploaded-rules.json",
        )
    except ValueError as exc:
        return _render_import_page(
            request,
            preview_entries=[],
            errors=[str(exc)],
        )

    return _render_import_page(
        request,
        preview_entries=[entry.model_dump(mode="json") for entry in result.entries],
        errors=[],
        result_summary={
            "imported_count": result.imported_count,
            "skipped_count": result.skipped_count,
            "batch_id": result.batch_id,
        },
        status_code=200,
    )


@router.post("/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    raw_form = _raw_rule_form_data(form)
    try:
        payload = RuleFormPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_rule_form(
            request,
            mode="create",
            session=session,
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    payload, resolution_error, feed_resolution_notice = _resolve_rule_payload_feeds(
        session,
        payload,
    )
    search_indexers = _resolve_rule_payload_search_indexers(session, payload)
    if resolution_error:
        return _render_rule_form(
            request,
            mode="create",
            session=session,
            form_data={
                **raw_form,
                "feed_urls": list(payload.feed_urls or []),
            },
            errors=[resolution_error],
        )
    remember_feed_defaults = bool(raw_form.get("remember_feed_defaults"))
    rule = Rule()
    _apply_rule_payload_to_model(
        rule,
        payload,
        settings=settings,
        feed_resolution_notice=feed_resolution_notice,
        search_indexers=search_indexers,
    )
    rule.last_sync_status = SyncStatus.PENDING
    rule.last_sync_error = None
    session.add(rule)
    if remember_feed_defaults:
        settings.default_feed_urls = list(payload.feed_urls)

    try:
        session.commit()
        session.refresh(rule)
    except IntegrityError:
        session.rollback()
        return _render_rule_form(
            request,
            mode="create",
            session=session,
            form_data={
                **payload.model_dump(mode="json"),
                "remember_feed_defaults": remember_feed_defaults,
            },
            errors=["Rule name already exists."],
        )

    enqueue_rule_sync(rule.id)
    enqueue_rule_fetch(rule.id)
    message = "Rule saved locally. qB sync and initial snapshot fetch are queued."
    level = "success"
    return RedirectResponse(
        url=f"/rules/{rule.id}?message={message}&level={level}",
        status_code=303,
    )


@router.post("/rules/{rule_id}", response_class=HTMLResponse)
async def update_rule(
    rule_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    rule = session.get(Rule, rule_id)
    if rule is None:
        return RedirectResponse(url="/?message=Rule not found.&level=error", status_code=303)

    form = await request.form()
    raw_form = _raw_rule_form_data(form)
    try:
        payload = RuleFormPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_rule_form(
            request,
            mode="edit",
            session=session,
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
            rule_id=rule_id,
        )

    settings = SettingsService.get_or_create(session)
    payload, resolution_error, feed_resolution_notice = _resolve_rule_payload_feeds(
        session,
        payload,
        existing_rule=rule,
    )
    search_indexers = _resolve_rule_payload_search_indexers(
        session,
        payload,
        existing_rule=rule,
    )
    if resolution_error:
        return _render_rule_form(
            request,
            mode="edit",
            session=session,
            form_data={
                **raw_form,
                "feed_urls": list(payload.feed_urls or []),
            },
            errors=[resolution_error],
            rule_id=rule_id,
        )
    remember_feed_defaults = bool(raw_form.get("remember_feed_defaults"))
    _apply_rule_payload_to_model(
        rule,
        payload,
        settings=settings,
        feed_resolution_notice=feed_resolution_notice,
        search_indexers=search_indexers,
    )
    rule.last_sync_status = SyncStatus.PENDING
    rule.last_sync_error = None
    if remember_feed_defaults:
        settings.default_feed_urls = list(payload.feed_urls)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return _render_rule_form(
            request,
            mode="edit",
            session=session,
            form_data={
                **payload.model_dump(mode="json"),
                "remember_feed_defaults": remember_feed_defaults,
            },
            errors=["Rule name already exists."],
            rule_id=rule_id,
        )

    enqueue_rule_sync(rule.id)
    message = "Rule saved locally. qB sync is queued in the background."
    level = "success"
    return RedirectResponse(
        url=f"/rules/{rule.id}?message={message}&level={level}",
        status_code=303,
    )


@router.post("/rules/{rule_id}/sync")
def sync_rule(
    rule_id: str,
    return_to: str = "",
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    rule = session.get(Rule, rule_id)
    if rule is None:
        return RedirectResponse(url="/?message=Rule%20not%20found.&level=error", status_code=303)
    rule.last_sync_status = SyncStatus.PENDING
    rule.last_sync_error = None
    session.add(rule)
    session.commit()
    enqueue_rule_sync(rule.id)
    target = f"/rules/{rule.id}" if return_to.strip().casefold() == "rule" else "/"
    return RedirectResponse(
        url=f"{target}?message=qB%20sync%20queued%20for%201%20rule.&level=success",
        status_code=303,
    )


@router.post("/rules/{rule_id}/delete")
def delete_rule(
    rule_id: str,
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    settings = SettingsService.get_or_create(session)
    try:
        result = SyncService(session, settings).delete_rule(rule_id)
    except SyncServiceError as exc:
        return RedirectResponse(url=f"/?message={exc}&level=error", status_code=303)
    level = "success" if result.success else "warning"
    target = "/" if result.success else f"/rules/{rule_id}"
    return RedirectResponse(url=f"{target}?message={result.message}&level={level}", status_code=303)


@router.post("/sync/all")
def sync_all(session: Session = Depends(get_db_session)) -> RedirectResponse:
    rules = list(session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all())
    for rule in rules:
        rule.last_sync_status = SyncStatus.PENDING
        rule.last_sync_error = None
        session.add(rule)
    if rules:
        session.commit()
    else:
        session.rollback()
    for rule in rules:
        enqueue_rule_sync(rule.id)
    message = f"qB sync queued for {len(rules)} rule(s)."
    return RedirectResponse(url=f"/?message={message}&level=success", status_code=303)


@router.post("/taxonomy/validate", response_class=HTMLResponse)
async def validate_taxonomy(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    form_data = _raw_taxonomy_form_data(form)
    raw_taxonomy = form_data["taxonomy_json"]
    if not raw_taxonomy.strip():
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=form_data,
            errors=["Taxonomy JSON is required."],
        )

    settings = SettingsService.get_or_create(session)
    rules = session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
    try:
        preview = preview_quality_taxonomy_update(
            raw_taxonomy,
            settings=settings,
            rules=rules,
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=form_data,
            errors=[str(exc)],
        )

    message = "Draft validation passed."
    level = "success"
    if not bool(preview["safe_to_apply"]):
        message = "Draft parsed, but applying it would orphan persisted tokens."
        level = "warning"

    return _render_taxonomy_page(
        request,
        session=session,
        form_data={
            "taxonomy_json": str(preview["formatted_text"]),
            "change_note": form_data["change_note"],
        },
        errors=[],
        preview=preview,
        message=message,
        message_level=level,
        status_code=200,
    )


@router.post("/taxonomy/apply", response_class=HTMLResponse)
async def apply_taxonomy(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    form_data = _raw_taxonomy_form_data(form)
    raw_taxonomy = form_data["taxonomy_json"]
    if not raw_taxonomy.strip():
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=form_data,
            errors=["Taxonomy JSON is required."],
        )

    settings = SettingsService.get_or_create(session)
    rules = session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
    try:
        preview = preview_quality_taxonomy_update(
            raw_taxonomy,
            settings=settings,
            rules=rules,
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=form_data,
            errors=[str(exc)],
        )

    normalized_form_data = {
        "taxonomy_json": str(preview["formatted_text"]),
        "change_note": form_data["change_note"],
    }
    if not bool(preview["safe_to_apply"]):
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=normalized_form_data,
            errors=["Cannot apply a taxonomy update that would orphan persisted tokens."],
            preview=preview,
            message="Resolve the blocking references before applying this draft.",
            message_level="warning",
        )

    try:
        audit_error = apply_quality_taxonomy_update(
            normalized_form_data["taxonomy_json"],
            change_note=normalized_form_data["change_note"],
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data=normalized_form_data,
            errors=[str(exc)],
            preview=preview,
        )

    message = "Taxonomy updated."
    level = "success"
    if audit_error:
        message = f"Taxonomy updated, but the audit log could not be written: {audit_error}"
        level = "warning"

    return RedirectResponse(
        url=f"/taxonomy?message={message}&level={level}",
        status_code=303,
    )


@router.post("/taxonomy/options/add", response_class=HTMLResponse)
async def add_taxonomy_option(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    try:
        add_quality_taxonomy_option(
            group=str(form.get("option_group", "")).strip(),
            value=str(form.get("option_value", "")).strip(),
            label=str(form.get("option_label", "")).strip(),
            pattern=str(form.get("option_pattern", "")).strip(),
            media_types=[str(item) for item in form.getlist("option_media_types")],
            change_note=str(form.get("taxonomy_change_note", "")).strip(),
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data={"taxonomy_json": read_quality_taxonomy_text(), "change_note": ""},
            errors=[str(exc)],
        )
    return RedirectResponse(
        url="/taxonomy?message=Taxonomy%20value%20added.&level=success",
        status_code=303,
    )


@router.post("/taxonomy/options/remove", response_class=HTMLResponse)
async def remove_taxonomy_option_route(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    try:
        remove_quality_taxonomy_option(
            value=str(form.get("option_value", "")).strip(),
            change_note=str(form.get("taxonomy_change_note", "")).strip(),
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data={"taxonomy_json": read_quality_taxonomy_text(), "change_note": ""},
            errors=[str(exc)],
        )
    return RedirectResponse(
        url="/taxonomy?message=Taxonomy%20value%20removed.&level=success",
        status_code=303,
    )


@router.post("/taxonomy/options/move", response_class=HTMLResponse)
async def move_taxonomy_option_route(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    try:
        move_quality_taxonomy_option(
            value=str(form.get("option_value", "")).strip(),
            direction=str(form.get("direction", "")).strip(),
            change_note=str(form.get("taxonomy_change_note", "")).strip(),
        )
    except RuntimeError as exc:
        return _render_taxonomy_page(
            request,
            session=session,
            form_data={"taxonomy_json": read_quality_taxonomy_text(), "change_note": ""},
            errors=[str(exc)],
        )
    return RedirectResponse(
        url="/taxonomy?message=Taxonomy%20value%20moved.&level=success",
        status_code=303,
    )


@router.post("/settings/defaults", response_class=HTMLResponse)
async def save_default_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    settings = SettingsService.get_or_create(session)
    raw_form = SettingsService.to_form_dict(settings)
    raw_form.update(
        {
            "series_category_template": form.get("series_category_template"),
            "movie_category_template": form.get("movie_category_template"),
            "save_path_template": form.get("save_path_template", ""),
            "default_add_paused": True,
            "default_sequential_download": _bool_from_form(form, "default_sequential_download"),
            "default_first_last_piece_prio": _bool_from_form(
                form, "default_first_last_piece_prio"
            ),
            "default_enabled": _bool_from_form(form, "default_enabled"),
            "profile_1080p_include_tokens": form.getlist("profile_1080p_include_tokens"),
            "profile_1080p_exclude_tokens": form.getlist("profile_1080p_exclude_tokens"),
            "profile_2160p_hdr_include_tokens": form.getlist(
                "profile_2160p_hdr_include_tokens"
            ),
            "profile_2160p_hdr_exclude_tokens": form.getlist(
                "profile_2160p_hdr_exclude_tokens"
            ),
            "default_quality_profile": form.get("default_quality_profile", "plain"),
        }
    )
    try:
        payload = SettingsFormPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_settings_page(
            request,
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings.series_category_template = payload.series_category_template
    settings.movie_category_template = payload.movie_category_template
    settings.save_path_template = payload.save_path_template
    # Retain the persisted field for backward compatibility, but the global
    # unpaused default is no longer a supported semantic state. Unpaused adds
    # must be explicit on a saved rule or on one Queue request.
    settings.default_add_paused = True
    settings.default_sequential_download = payload.default_sequential_download
    settings.default_first_last_piece_prio = payload.default_first_last_piece_prio
    settings.default_enabled = payload.default_enabled
    settings.quality_profile_rules = {
        QualityProfile.HD_1080P.value: {
            "include_tokens": payload.profile_1080p_include_tokens,
            "exclude_tokens": payload.profile_1080p_exclude_tokens,
        },
        QualityProfile.UHD_2160P_HDR.value: {
            "include_tokens": payload.profile_2160p_hdr_include_tokens,
            "exclude_tokens": payload.profile_2160p_hdr_exclude_tokens,
        },
    }
    settings.default_quality_profile = payload.default_quality_profile
    session.add(settings)
    session.commit()
    return RedirectResponse(
        url="/settings/defaults?message=Defaults%20and%20quality%20profiles%20saved.&level=success",
        status_code=303,
    )


@router.post("/settings", response_class=HTMLResponse)
async def save_legacy_combined_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    """Keep API compatibility for older desktop builds without linking this form in the UI."""
    form = await request.form()
    raw_form = _raw_settings_form_data(form)
    try:
        payload = SettingsFormPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_settings_page(
            request,
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )
    settings = SettingsService.get_or_create(session)
    SettingsService.apply_payload(settings, payload)
    session.add(settings)
    session.commit()
    return RedirectResponse(
        url="/settings/defaults?message=Settings%20saved.&level=success",
        status_code=303,
    )


def _render_provider_settings_page(
    request: Request,
    *,
    provider: str,
    form_data: dict[str, Any],
    errors: list[str],
    message: str | None = None,
    message_level: str = "info",
    status_code: int = 400,
) -> HTMLResponse:
    provider_titles = {
        "qbittorrent": "qBittorrent",
        "jackett": "Jackett",
        "real-debrid": "Real-Debrid",
        "myjdownloader": "MyJDownloader",
        "jellyfin": "Jellyfin",
        "stremio": "Stremio",
        "metadata": "Metadata",
    }
    return templates.TemplateResponse(
        request,
        "settings_provider.html",
        {
            "request": request,
            "page_title": f"{provider_titles[provider]} settings",
            "provider": provider,
            "provider_title": provider_titles[provider],
            "form_data": form_data,
            "errors": errors,
            "metadata_choices": ["omdb", "disabled"],
            "message": message,
            "message_level": message_level,
        },
        status_code=status_code,
    )


@router.post("/settings/{provider}/save", response_class=HTMLResponse)
async def save_provider_settings(
    provider: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
    form = await request.form()
    settings = SettingsService.get_or_create(session)
    try:
        if provider == "qbittorrent":
            qb_payload = QbSettingsPayload.model_validate(_raw_qb_settings_form_data(form))
            SettingsService.apply_qb_payload(settings, qb_payload)
        elif provider == "jackett":
            jackett_payload = JackettSettingsPayload.model_validate(
                _raw_jackett_settings_form_data(form)
            )
            SettingsService.apply_jackett_payload(settings, jackett_payload)
        elif provider == "real-debrid":
            real_debrid_payload = RealDebridSettingsPayload.model_validate(
                _raw_real_debrid_settings_form_data(form)
            )
            SettingsService.apply_real_debrid_payload(settings, real_debrid_payload)
        elif provider == "myjdownloader":
            myjd_payload = MyJDownloaderSettingsPayload.model_validate(
                _raw_myjd_settings_form_data(form)
            )
            SettingsService.apply_myjd_payload(settings, myjd_payload)
        elif provider == "jellyfin":
            jellyfin_payload = JellyfinSettingsPayload.model_validate(
                _raw_jellyfin_settings_form_data(form)
            )
            SettingsService.apply_jellyfin_payload(settings, jellyfin_payload)
        elif provider == "stremio":
            stremio_payload = StremioSettingsPayload.model_validate(
                _raw_stremio_settings_form_data(form)
            )
            SettingsService.apply_stremio_payload(settings, stremio_payload)
        elif provider == "metadata":
            metadata_payload = MetadataSettingsPayload.model_validate(
                _raw_metadata_settings_form_data(form)
            )
            SettingsService.apply_metadata_payload(settings, metadata_payload)
        else:
            return JSONResponse({"error": "Unknown settings provider."}, status_code=404)
    except ValidationError as exc:
        return JSONResponse(
            {"errors": [error["msg"] for error in exc.errors()]}, status_code=422
        )
    session.add(settings)
    session.commit()
    return RedirectResponse(
        url=f"/settings/{provider}?message=Settings%20saved.&level=success",
        status_code=303,
    )


@router.post("/settings/real-debrid/connect", response_class=HTMLResponse)
async def connect_real_debrid_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_real_debrid_settings_form_data(form)
    try:
        payload = RealDebridSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="real-debrid",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    SettingsService.apply_real_debrid_payload(settings, payload)
    settings.real_debrid_connection_status = "authorizing"
    settings.real_debrid_connection_message = "Waiting for device authorization."
    session.add(settings)
    session.commit()

    try:
        with RealDebridClient() as client:
            flow = client.start_device_flow()
    except RealDebridError as exc:
        settings.real_debrid_connection_status = "error"
        settings.real_debrid_connection_message = str(exc)
        session.add(settings)
        session.commit()
        return _render_provider_settings_page(
            request,
            provider="real-debrid",
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    form_data = SettingsService.to_form_dict(settings)
    form_data["real_debrid_device_flow"] = {
        "flow_id": flow.flow_id,
        "user_code": flow.user_code,
        "verification_url": flow.verification_url,
        "direct_verification_url": flow.direct_verification_url or flow.verification_url,
        "poll_url": f"/api/settings/real-debrid/device/{flow.flow_id}",
        "interval_seconds": flow.interval_seconds,
    }
    return _render_provider_settings_page(
        request,
        provider="real-debrid",
        form_data=form_data,
        errors=[],
        message="Authorize this device in Real-Debrid; this page will finish connecting automatically.",
        message_level="info",
        status_code=200,
    )


@router.get("/settings/real-debrid/device/{flow_id}")
def poll_real_debrid_device(
    flow_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    flow = DEVICE_FLOW_REGISTRY.get(flow_id)
    if flow is None:
        return JSONResponse(
            {"status": "expired", "message": "Real-Debrid device authorization expired."},
            status_code=404,
        )
    settings = SettingsService.get_or_create(session)
    try:
        with RealDebridClient() as client:
            credentials = client.poll_device_credentials(flow)
            token = client.exchange_device_code(flow, credentials)
        with RealDebridClient(token.access_token) as authenticated_client:
            account = authenticated_client.get_account()
    except RealDebridAuthorizationPendingError:
        return JSONResponse(
            {"status": "pending", "message": "Waiting for Real-Debrid authorization."}
        )
    except RealDebridError as exc:
        settings.real_debrid_connection_status = "error"
        settings.real_debrid_connection_message = str(exc)
        session.add(settings)
        session.commit()
        DEVICE_FLOW_REGISTRY.remove(flow_id)
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    settings.real_debrid_client_id_encrypted = obfuscate_secret(credentials.client_id)
    settings.real_debrid_client_secret_encrypted = obfuscate_secret(credentials.client_secret)
    settings.real_debrid_access_token_encrypted = obfuscate_secret(token.access_token)
    settings.real_debrid_refresh_token_encrypted = obfuscate_secret(token.refresh_token)
    settings.real_debrid_token_expires_at = token.expires_at
    settings.real_debrid_account_username = account.username
    settings.real_debrid_account_premium_until = account.premium_until
    settings.real_debrid_connection_status = "connected" if account.is_premium else "account_error"
    settings.real_debrid_connection_message = (
        "Real-Debrid Premium connection is ready."
        if account.is_premium
        else "Real-Debrid connected, but a Premium account is required for acceleration."
    )
    settings.real_debrid_enabled = bool(account.is_premium)
    session.add(settings)
    session.commit()
    DEVICE_FLOW_REGISTRY.remove(flow_id)
    return JSONResponse(
        {
            "status": "connected" if account.is_premium else "account_error",
            "message": settings.real_debrid_connection_message,
            "premium": account.is_premium,
        }
    )


def _queue_real_debrid_history_download(
    *,
    session: Session,
    settings: AppSettings,
    payload: SearchQueueRequest,
    save_path: str,
) -> JSONResponse:
    config = SettingsService.resolve_myjd(settings)
    if not (config.enabled and config.is_configured):
        return JSONResponse(
            {"error": "This Real-Debrid history item requires configured MyJDownloader."},
            status_code=400,
        )
    provider_id = str(payload.provider_id or "").strip()
    if not provider_id:
        return JSONResponse({"error": "Missing Real-Debrid download ID."}, status_code=400)
    try:
        access_token = ensure_real_debrid_access_token(session, settings)
        with RealDebridClient(access_token) as rd_client:
            provider: dict[str, Any] | None = None
            for page in range(1, 101):
                rows = rd_client.list_downloads(page=page, limit=100)
                provider = next(
                    (row for row in rows if str(row.get("id") or "") == provider_id),
                    None,
                )
                if provider is not None or len(rows) < 100:
                    break
            if provider is None:
                raise RealDebridError("Real-Debrid download history item was not found.")
            restricted_link = str(provider.get("link") or "").strip()
            download_link = str(
                rd_client.unrestrict_link(restricted_link).get("download") or ""
            ).strip()
        if not download_link:
            raise RealDebridError("Real-Debrid history item has no downloadable link.")
        existing = session.scalar(
            select(DownloadAccelerationJob).where(
                DownloadAccelerationJob.identity_key == f"rd-download:{provider_id}"
            )
        )
        if existing is not None and existing.myjd_job_ids:
            return JSONResponse(
                {"status": "already_queued", "job_id": existing.id, "message": "Already queued."}
            )
        jd_job_id = MyJDownloaderClient().add_links(
            email=str(config.email),
            password=str(config.password),
            device_id=str(config.device_id),
            links=[download_link],
            package_name=str(provider.get("filename") or "Real-Debrid download"),
            destination_folder=save_path,
            autostart=True,
        )
    except (RealDebridError, MyJDownloaderError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    job = existing or DownloadAccelerationJob(
        identity_key=f"rd-download:{provider_id}",
        source_kind="real_debrid_download",
        provider_download_id=provider_id,
    )
    job.myjd_job_ids = [jd_job_id]
    job.state = "fallback_progress"
    job.last_error = ""
    session.add(job)
    session.commit()
    return JSONResponse(
        {
            "status": "queued",
            "job_id": job.id,
            "message": "Queued in MyJDownloader.",
            "category": "",
            "save_path": save_path,
        }
    )


@router.post("/settings/real-debrid/disconnect")
def disconnect_real_debrid_settings(
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    settings = SettingsService.get_or_create(session)
    for attribute in (
        "real_debrid_client_id_encrypted",
        "real_debrid_client_secret_encrypted",
        "real_debrid_access_token_encrypted",
        "real_debrid_refresh_token_encrypted",
        "real_debrid_token_expires_at",
        "real_debrid_account_username",
        "real_debrid_account_premium_until",
    ):
        setattr(settings, attribute, None)
    settings.real_debrid_enabled = False
    settings.real_debrid_connection_status = "disconnected"
    settings.real_debrid_connection_message = "Real-Debrid connection removed."
    session.add(settings)
    session.commit()
    return RedirectResponse(
        url="/settings?message=Real-Debrid%20disconnected.&level=success", status_code=303
    )


@router.post("/settings/test-qb", response_class=HTMLResponse)
async def test_qb_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_qb_settings_form_data(form)
    try:
        payload = QbSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="qbittorrent",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_qb_payload(temp_settings, payload)
    connection = SettingsService.resolve_qb_connection(temp_settings)
    if not connection.is_configured:
        return _render_provider_settings_page(
            request,
            provider="qbittorrent",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["qBittorrent connection is not fully configured."],
        )
    try:
        with QbittorrentClient(
            connection.base_url, connection.username, connection.password
        ) as client:
            client.test_connection()
    except QbittorrentClientError as exc:
        return _render_provider_settings_page(
            request,
            provider="qbittorrent",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )
    return _render_provider_settings_page(
        request,
        provider="qbittorrent",
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message="qBittorrent connection test succeeded. Test actions do not save settings; use Save Settings before syncing rules.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-myjdownloader", response_class=HTMLResponse)
async def test_myjdownloader_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_myjd_settings_form_data(form)
    try:
        payload = MyJDownloaderSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="myjdownloader",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_myjd_payload(temp_settings, payload)
    config = SettingsService.resolve_myjd(temp_settings)
    if not (config.email and config.password):
        return _render_provider_settings_page(
            request,
            provider="myjdownloader",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["MyJDownloader email and password are required."],
        )
    try:
        devices = MyJDownloaderClient().list_devices(
            email=config.email,
            password=config.password,
        )
    except MyJDownloaderError as exc:
        return _render_provider_settings_page(
            request,
            provider="myjdownloader",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )
    if not devices:
        return _render_provider_settings_page(
            request,
            provider="myjdownloader",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["MyJDownloader connected, but no online devices were found."],
        )
    selected = next(
        (device for device in devices if device.id == config.device_id),
        devices[0],
    )
    form_data = {**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")}
    form_data["myjd_device_id"] = selected.id
    form_data["myjd_device_name"] = selected.name
    form_data["myjd_devices"] = [
        {"id": device.id, "name": device.name, "type": device.type} for device in devices
    ]
    return _render_provider_settings_page(
        request,
        provider="myjdownloader",
        form_data=form_data,
        errors=[],
        message=f"MyJDownloader connection succeeded; selected {selected.name}.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-jackett", response_class=HTMLResponse)
async def test_jackett_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_jackett_settings_form_data(form)
    try:
        payload = JackettSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="jackett",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_jackett_payload(temp_settings, payload)
    jackett = SettingsService.resolve_jackett(temp_settings)
    if not jackett.app_ready:
        return _render_provider_settings_page(
            request,
            provider="jackett",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["Jackett app URL and API key are both required."],
        )

    try:
        client = JackettClient(
            jackett.api_url,
            jackett.api_key,
            language_overrides=jackett.language_overrides,
        )
        client.test_connection()
    except JackettClientError as exc:
        return _render_provider_settings_page(
            request,
            provider="jackett",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    return _render_provider_settings_page(
        request,
        provider="jackett",
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message="Jackett connection test succeeded. Test actions do not save settings; use Save Settings before syncing rules.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-metadata", response_class=HTMLResponse)
async def test_metadata_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_metadata_settings_form_data(form)
    try:
        payload = MetadataSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="metadata",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_metadata_payload(temp_settings, payload)
    metadata = SettingsService.resolve_metadata(temp_settings)

    try:
        client = MetadataClient(metadata.provider, metadata.api_key)
        client.lookup_by_imdb_id("tt0944947")
    except MetadataLookupError as exc:
        return _render_provider_settings_page(
            request,
            provider="metadata",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    return _render_provider_settings_page(
        request,
        provider="metadata",
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message="Metadata lookup test succeeded.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-jellyfin", response_class=HTMLResponse)
async def test_jellyfin_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_jellyfin_settings_form_data(form)
    try:
        payload = JellyfinSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="jellyfin",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_jellyfin_payload(temp_settings, payload)

    try:
        result = JellyfinService(temp_settings).test_connection()
    except JellyfinError as exc:
        return _render_provider_settings_page(
            request,
            provider="jellyfin",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    discovered_users = ", ".join(user.username for user in result.users) or "none"
    return _render_provider_settings_page(
        request,
        provider="jellyfin",
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message=(
            "Jellyfin read-only connection test succeeded. "
            f'Selected user "{result.selected_user.username}". '
            f"Users found: {discovered_users}."
        ),
        message_level="success",
        status_code=200,
    )


@router.post("/settings/sync-jellyfin", response_class=HTMLResponse)
async def sync_jellyfin_rule_progress(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_jellyfin_settings_form_data(form)
    try:
        payload = JellyfinSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="jellyfin",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    SettingsService.apply_jellyfin_payload(settings, payload)
    session.add(settings)
    session.commit()

    try:
        execution = execute_jellyfin_sync(session, settings=settings)
    except (JellyfinError, JellyfinSyncBusyError) as exc:
        return _render_provider_settings_page(
            request,
            provider="jellyfin",
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    return _render_provider_settings_page(
        request,
        provider="jellyfin",
        form_data=SettingsService.to_form_dict(settings),
        errors=execution.top_errors(),
        message=execution.render_message(),
        message_level=execution.message_level,
        status_code=200,
    )


@router.post("/settings/test-stremio", response_class=HTMLResponse)
@compat_router.post("/settings/test-stremio", response_class=HTMLResponse)
async def test_stremio_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_stremio_settings_form_data(form)
    try:
        payload = StremioSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="stremio",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    temp_settings = _clone_settings(settings)
    SettingsService.apply_stremio_payload(temp_settings, payload)

    try:
        result = StremioService(temp_settings).test_connection()
    except StremioError as exc:
        return _render_provider_settings_page(
            request,
            provider="stremio",
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    storage_detail = f" Storage: {result.local_storage_path}." if result.local_storage_path else ""
    return _render_provider_settings_page(
        request,
        provider="stremio",
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message=(
            "Stremio connection test succeeded. "
            f"Auth source: {result.auth_source}."
            f"{storage_detail} "
            f"Active movie/series library items: {result.active_item_count} of {result.total_item_count}."
        ).strip(),
        message_level="success",
        status_code=200,
    )


@router.post("/settings/sync-stremio", response_class=HTMLResponse)
@compat_router.post("/settings/sync-stremio", response_class=HTMLResponse)
async def sync_stremio_library_rules(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    form = await request.form()
    raw_form = _raw_stremio_settings_form_data(form)
    try:
        payload = StremioSettingsPayload.model_validate(raw_form)
    except ValidationError as exc:
        return _render_provider_settings_page(
            request,
            provider="stremio",
            form_data=raw_form,
            errors=[error["msg"] for error in exc.errors()],
        )

    settings = SettingsService.get_or_create(session)
    SettingsService.apply_stremio_payload(settings, payload)
    session.add(settings)
    session.commit()

    try:
        execution = execute_stremio_sync(session, settings=settings)
    except (StremioError, StremioSyncBusyError) as exc:
        return _render_provider_settings_page(
            request,
            provider="stremio",
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    return _render_provider_settings_page(
        request,
        provider="stremio",
        form_data=SettingsService.to_form_dict(settings),
        errors=execution.top_errors(),
        message=execution.render_message(),
        message_level=execution.message_level,
        status_code=200,
    )


@router.post("/settings/sync-watch-progress", response_class=HTMLResponse)
async def sync_provider_watch_progress(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)

    try:
        summary = sync_watch_progress(session, settings=settings)
    except (JellyfinError, StremioError) as exc:
        return _render_settings_page(
            request,
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    message = (
        "Watch progress sync complete. "
        f"Jellyfin read: {summary.jellyfin_read_count}; "
        f"Stremio read: {summary.stremio_read_count}; "
        f"matched: {summary.matched_count}; "
        f"Jellyfin writes: {summary.jellyfin_write_count}; "
        f"Stremio writes: {summary.stremio_write_count}; "
        f"skipped: {summary.skipped_count}; "
        f"errors: {summary.error_count}."
    )
    return _render_settings_page(
        request,
        form_data=SettingsService.to_form_dict(settings),
        errors=summary.messages[-3:] if summary.error_count else [],
        message=message,
        message_level="warning" if summary.error_count else "success",
        status_code=200,
    )
