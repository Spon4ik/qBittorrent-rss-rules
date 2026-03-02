from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import AppSettings, MediaType, QualityProfile, Rule, media_type_choices, media_type_label
from app.schemas import (
    FilterProfileSaveRequest,
    ImportMode,
    MetadataLookupRequest,
    RuleFormPayload,
    SettingsFormPayload,
)
from app.services.importer import Importer
from app.services.metadata import MetadataClient, MetadataLookupError
from app.services.quality_filters import (
    AT_LEAST_UHD_PROFILE,
    BUILTIN_AT_LEAST_UHD_PROFILE_KEY,
    apply_quality_taxonomy_update,
    available_filter_profile_choices,
    build_available_filter_profiles,
    normalize_saved_quality_profiles,
    preview_quality_taxonomy_update,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    quality_taxonomy_snapshot,
    read_quality_taxonomy_text,
    recent_quality_taxonomy_audit_entries,
    resolve_quality_profile_rules,
    slugify_profile_key,
)
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.rule_builder import RuleBuilder
from app.services.settings_service import SettingsService
from app.services.sync import SyncService, SyncServiceError

router = APIRouter(prefix="/api")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


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
    settings = SettingsService.get_or_create(session)
    profile_rules = resolve_quality_profile_rules(settings)
    raw_selected_feed_urls = form_data.get("feed_urls", []) or []
    if isinstance(raw_selected_feed_urls, list):
        selected_feed_urls = raw_selected_feed_urls
    else:
        selected_feed_urls = [str(raw_selected_feed_urls)]
    context = {
        "request": request,
        "page_title": "New Rule" if mode == "create" else f"Edit {form_data.get('rule_name', 'Rule')}",
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
        "available_filter_profiles": available_filter_profile_choices(settings),
        "media_choices": media_type_choices(),
        "message": None,
        "message_level": "error",
    }

    connection = SettingsService.resolve_qb_connection(settings)
    if connection.is_configured:
        try:
            with QbittorrentClient(connection.base_url, connection.username, connection.password) as client:
                context["feed_options"] = [item.model_dump() for item in client.get_feeds()]
        except QbittorrentClientError:
            pass
    seen = {item["url"] for item in context["feed_options"]}
    for url in selected_feed_urls:
        if url not in seen:
            context["feed_options"].append({"label": f"Saved feed: {url}", "url": url})
            seen.add(url)

    return templates.TemplateResponse("rule_form.html", context, status_code=status_code)


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
        "settings.html",
        {
            "request": request,
            "page_title": "Settings",
            "form_data": form_data,
            "errors": errors,
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
        metadata_provider=settings.metadata_provider,
        omdb_api_key_encrypted=settings.omdb_api_key_encrypted,
        series_category_template=settings.series_category_template,
        movie_category_template=settings.movie_category_template,
        save_path_template=settings.save_path_template,
        default_add_paused=settings.default_add_paused,
        default_enabled=settings.default_enabled,
        quality_profile_rules=settings.quality_profile_rules,
        saved_quality_profiles=settings.saved_quality_profiles,
        default_feed_urls=settings.default_feed_urls,
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
        result = client.lookup_by_imdb_id(payload.imdb_id)
    except MetadataLookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result.model_dump(mode="json"))


@router.post("/feeds/refresh")
def feeds_refresh(session: Session = Depends(get_db_session)) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    connection = SettingsService.resolve_qb_connection(settings)
    if not connection.is_configured:
        return JSONResponse({"error": "qBittorrent connection is not configured."}, status_code=400)

    try:
        with QbittorrentClient(connection.base_url, connection.username, connection.password) as client:
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

    if payload.mode == "create":
        profile_key = slugify_profile_key(payload.profile_name)
        if not profile_key:
            return JSONResponse({"error": "A profile name is required."}, status_code=400)
        if profile_key in all_profiles or profile_key in saved_profiles:
            return JSONResponse({"error": "A profile with that name already exists."}, status_code=400)
        saved_profiles[profile_key] = {
            "label": payload.profile_name,
            "include_tokens": payload.include_tokens,
            "exclude_tokens": payload.exclude_tokens,
        }
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
        elif payload.target_key == BUILTIN_AT_LEAST_UHD_PROFILE_KEY:
            saved_profiles[payload.target_key] = {
                "label": str(AT_LEAST_UHD_PROFILE["label"]),
                "include_tokens": payload.include_tokens,
                "exclude_tokens": payload.exclude_tokens,
            }
            profile_key = payload.target_key
        elif payload.target_key not in saved_profiles:
            return JSONResponse(
                {"error": "Select an existing saved profile or preset to overwrite."},
                status_code=400,
            )
        else:
            existing = saved_profiles[payload.target_key]
            saved_profiles[payload.target_key] = {
                "label": str(existing.get("label", payload.target_key)),
                "include_tokens": payload.include_tokens,
                "exclude_tokens": payload.exclude_tokens,
            }
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
    upload = form.get("rules_file")
    if upload is None or not hasattr(upload, "read") or not getattr(upload, "filename", ""):
        return _render_import_page(
            request,
            preview_entries=[],
            errors=["Choose a JSON export file first."],
        )

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
            source_name=upload.filename or "uploaded-rules.json",
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
    remember_feed_defaults = _bool_from_form(form, "remember_feed_defaults")
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
            form_data=payload.model_dump(mode="json"),
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
    _apply_rule_payload_to_model(rule, payload, settings=settings)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return _render_rule_form(
            request,
            mode="edit",
            session=session,
            form_data=payload.model_dump(mode="json"),
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
    return RedirectResponse(url=f"/rules/{rule_id}?message={result.message}&level={level}", status_code=303)


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
        form_data={"taxonomy_json": str(preview["formatted_text"]), "change_note": form_data["change_note"]},
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
        with QbittorrentClient(connection.base_url, connection.username, connection.password) as client:
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
