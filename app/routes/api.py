from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import (
    AppSettings,
    MediaType,
    QualityProfile,
    Rule,
    media_type_choices,
    media_type_label,
)
from app.schemas import (
    FilterProfileSaveRequest,
    ImportMode,
    JackettSearchRequest,
    MetadataLookupRequest,
    RuleBatchFetchRequest,
    RuleFetchSchedulePayload,
    RuleFormPayload,
    RulesPagePreferencesPayload,
    SearchQueueRequest,
    SearchViewPreferencesPayload,
    SettingsFormPayload,
    StremioQueueRequest,
)
from app.services.hover_debug import (
    clear_hover_events,
    hover_debug_log_path,
    list_hover_events,
    record_hover_event,
)
from app.services.importer import Importer
from app.services.jackett import JackettClient, JackettClientError
from app.services.jellyfin import JellyfinError, JellyfinService
from app.services.jellyfin_sync_ops import JellyfinSyncBusyError, execute_jellyfin_sync
from app.services.metadata import (
    MetadataClient,
    MetadataLookupError,
    default_metadata_lookup_provider,
    metadata_lookup_provider_catalog,
    metadata_lookup_provider_choices,
)
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.quality_filters import (
    apply_quality_taxonomy_update,
    available_filter_profile_choices,
    available_filter_profile_choices_for_media_type,
    build_available_filter_profiles,
    builtin_filter_profile_keys,
    normalize_saved_quality_profiles,
    preview_quality_taxonomy_update,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    quality_profile_label,
    quality_taxonomy_snapshot,
    read_quality_taxonomy_text,
    recent_quality_taxonomy_audit_entries,
    resolve_quality_profile_rules,
    slugify_profile_key,
)
from app.services.rule_builder import RuleBuilder
from app.services.rule_fetch_ops import (
    run_rules_fetch_batch,
    run_scheduled_fetch_now,
    schedule_payload,
    update_schedule_settings,
)
from app.services.selective_queue import (
    SelectiveQueueError,
    StremioQueueSelection,
    queue_result_with_optional_file_selection,
    queue_stremio_stream_selection,
)
from app.services.settings_service import SettingsService
from app.services.static_assets import compute_static_asset_version
from app.services.stremio import StremioError, StremioService
from app.services.stremio_sync_ops import StremioSyncBusyError, execute_stremio_sync
from app.services.sync import SyncService, SyncServiceError

router = APIRouter(prefix="/api")
compat_router = APIRouter()


def _template_context(_: Request) -> dict[str, object]:
    return {"static_asset_version": compute_static_asset_version()}


templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates"),
    context_processors=[_template_context],
)


def _bool_from_form(form: Any, key: str) -> bool:
    value = form.get(key)
    return str(value).lower() in {"1", "true", "on", "yes"}


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
        "assigned_category": form.get("assigned_category", ""),
        "save_path": form.get("save_path", ""),
        "feed_urls": form.getlist("feed_urls"),
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
        "jellyfin_db_path": form.get("jellyfin_db_path") or None,
        "jellyfin_user_name": form.get("jellyfin_user_name") or None,
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

    connection = SettingsService.resolve_qb_connection(settings)
    if connection.is_configured:
        try:
            with QbittorrentClient(
                connection.base_url, connection.username, connection.password
            ) as client:
                context["feed_options"] = [item.model_dump() for item in client.get_feeds()]
        except QbittorrentClientError:
            pass
    seen = {item["url"] for item in context["feed_options"]}
    for url in selected_feed_urls:
        if url not in seen:
            context["feed_options"].append({"label": f"Saved feed: {url}", "url": url})
            seen.add(url)

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
            "stremio_addon_manifest_url": str(request.url_for("stremio_manifest")),
            "errors": errors,
            "profile_1080p_label": quality_profile_label(QualityProfile.HD_1080P),
            "profile_2160p_hdr_label": quality_profile_label(QualityProfile.UHD_2160P_HDR),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "metadata_choices": ["omdb", "disabled"],
            "message": message,
            "message_level": message_level,
        },
        status_code=status_code,
    )


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
) -> None:
    rule.rule_name = payload.rule_name
    rule.content_name = payload.content_name
    rule.imdb_id = payload.imdb_id
    rule.normalized_title = payload.normalized_title or payload.content_name
    rule.poster_url = payload.poster_url
    rule.media_type = payload.media_type
    rule.quality_profile = payload.quality_profile
    rule.release_year = payload.release_year
    rule.include_release_year = payload.include_release_year
    rule.additional_includes = payload.additional_includes
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
    rule.feed_urls = payload.feed_urls
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
        jellyfin_db_path=getattr(settings, "jellyfin_db_path", None),
        jellyfin_user_name=getattr(settings, "jellyfin_user_name", None),
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
    client = JackettClient(jackett.api_url, jackett.api_key)
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
    if not connection.is_configured:
        return JSONResponse({"error": "qBittorrent connection is not configured."}, status_code=400)

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
        add_paused = settings.default_add_paused

    try:
        queue_result = queue_result_with_optional_file_selection(
            qb_base_url=connection.base_url or "",
            qb_username=connection.username or "",
            qb_password=connection.password or "",
            link=payload.link,
            category=category,
            save_path=save_path,
            paused=bool(add_paused),
            sequential_download=payload.sequential_download,
            first_last_piece_prio=payload.first_last_piece_prio,
            rule=rule,
        )
    except SelectiveQueueError as exc:
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


@router.post("/stremio/queue")
def queue_stremio_stream(
    payload: StremioQueueRequest,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    connection = SettingsService.resolve_qb_connection(settings)
    if not connection.is_configured:
        return JSONResponse({"error": "qBittorrent connection is not configured."}, status_code=400)

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
        add_paused = settings.default_add_paused

    try:
        queue_result, magnet_link = queue_stremio_stream_selection(
            qb_base_url=connection.base_url or "",
            qb_username=connection.username or "",
            qb_password=connection.password or "",
            selection=StremioQueueSelection(
                info_hash=payload.info_hash,
                tracker_urls=payload.tracker_urls,
                display_name=payload.display_name,
                file_idx=payload.file_idx,
            ),
            category=category,
            save_path=save_path,
            paused=bool(add_paused),
            sequential_download=payload.sequential_download,
            first_last_piece_prio=payload.first_last_piece_prio,
        )
    except SelectiveQueueError as exc:
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
            "magnet_link": magnet_link,
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
    connection = SettingsService.resolve_qb_connection(settings)
    if not connection.is_configured:
        return JSONResponse({"error": "qBittorrent connection is not configured."}, status_code=400)

    try:
        with QbittorrentClient(
            connection.base_url, connection.username, connection.password
        ) as client:
            feeds = [item.model_dump() for item in client.get_feeds()]
    except QbittorrentClientError as exc:
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
    remember_feed_defaults = bool(raw_form.get("remember_feed_defaults"))
    rule = Rule()
    _apply_rule_payload_to_model(rule, payload, settings=settings)
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

    sync_result = SyncService(session, settings).sync_rule(rule.id)
    message = sync_result.message
    level = "success" if sync_result.success else "warning"
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
    remember_feed_defaults = bool(raw_form.get("remember_feed_defaults"))
    _apply_rule_payload_to_model(rule, payload, settings=settings)
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

    sync_result = SyncService(session, settings).sync_rule(rule.id)
    level = "success" if sync_result.success else "warning"
    return RedirectResponse(
        url=f"/rules/{rule.id}?message={sync_result.message}&level={level}",
        status_code=303,
    )


@router.post("/rules/{rule_id}/sync")
def sync_rule(
    rule_id: str,
    session: Session = Depends(get_db_session),
) -> RedirectResponse:
    settings = SettingsService.get_or_create(session)
    try:
        result = SyncService(session, settings).sync_rule(rule_id)
    except SyncServiceError as exc:
        return RedirectResponse(url=f"/?message={exc}&level=error", status_code=303)
    level = "success" if result.success else "warning"
    return RedirectResponse(
        url=f"/rules/{rule_id}?message={result.message}&level={level}", status_code=303
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
    settings = SettingsService.get_or_create(session)
    result = SyncService(session, settings).sync_all()
    level = "success" if result.error_count == 0 else "warning"
    message = (
        f"Synced {result.success_count} rule(s), "
        f"{result.error_count} failed, drift detected on {result.drift_detected}."
    )
    return RedirectResponse(url=f"/?message={message}&level={level}", status_code=303)


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


@router.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> Response:
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
        url="/settings?message=Settings saved.&level=success",
        status_code=303,
    )


@router.post("/settings/test-qb", response_class=HTMLResponse)
async def test_qb_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
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
    temp_settings = _clone_settings(settings)
    SettingsService.apply_payload(temp_settings, payload)
    connection = SettingsService.resolve_qb_connection(temp_settings)
    if not connection.is_configured:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["qBittorrent connection is not fully configured."],
        )
    try:
        with QbittorrentClient(
            connection.base_url, connection.username, connection.password
        ) as client:
            client.test_connection()
    except QbittorrentClientError as exc:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )
    return _render_settings_page(
        request,
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message="qBittorrent connection test succeeded.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-jackett", response_class=HTMLResponse)
async def test_jackett_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
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
    temp_settings = _clone_settings(settings)
    SettingsService.apply_payload(temp_settings, payload)
    jackett = SettingsService.resolve_jackett(temp_settings)
    if not jackett.app_ready:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=["Jackett app URL and API key are both required."],
        )

    try:
        client = JackettClient(jackett.api_url, jackett.api_key)
        client.test_connection()
    except JackettClientError as exc:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    return _render_settings_page(
        request,
        form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
        errors=[],
        message="Jackett connection test succeeded.",
        message_level="success",
        status_code=200,
    )


@router.post("/settings/test-metadata", response_class=HTMLResponse)
async def test_metadata_settings(
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
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
    temp_settings = _clone_settings(settings)
    SettingsService.apply_payload(temp_settings, payload)
    metadata = SettingsService.resolve_metadata(temp_settings)

    try:
        client = MetadataClient(metadata.provider, metadata.api_key)
        client.lookup_by_imdb_id("tt0944947")
    except MetadataLookupError as exc:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    return _render_settings_page(
        request,
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
    temp_settings = _clone_settings(settings)
    SettingsService.apply_payload(temp_settings, payload)

    try:
        result = JellyfinService(temp_settings).test_connection()
    except JellyfinError as exc:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    discovered_users = ", ".join(user.username for user in result.users) or "none"
    return _render_settings_page(
        request,
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

    try:
        execution = execute_jellyfin_sync(session, settings=settings)
    except (JellyfinError, JellyfinSyncBusyError) as exc:
        return _render_settings_page(
            request,
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    return _render_settings_page(
        request,
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
    temp_settings = _clone_settings(settings)
    SettingsService.apply_payload(temp_settings, payload)

    try:
        result = StremioService(temp_settings).test_connection()
    except StremioError as exc:
        return _render_settings_page(
            request,
            form_data={**SettingsService.to_form_dict(settings), **payload.model_dump(mode="json")},
            errors=[str(exc)],
        )

    storage_detail = f" Storage: {result.local_storage_path}." if result.local_storage_path else ""
    return _render_settings_page(
        request,
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

    try:
        execution = execute_stremio_sync(session, settings=settings)
    except (StremioError, StremioSyncBusyError) as exc:
        return _render_settings_page(
            request,
            form_data=SettingsService.to_form_dict(settings),
            errors=[str(exc)],
        )

    return _render_settings_page(
        request,
        form_data=SettingsService.to_form_dict(settings),
        errors=execution.top_errors(),
        message=execution.render_message(),
        message_level=execution.message_level,
        status_code=200,
    )
