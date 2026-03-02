from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import MediaType, Rule, media_type_choices, media_type_label
from app.services.quality_filters import (
    available_filter_profile_choices,
    detect_matching_filter_profile_key,
    preview_quality_taxonomy_update,
    quality_option_choices,
    quality_option_groups,
    quality_profile_choices,
    quality_taxonomy_snapshot,
    read_quality_taxonomy_text,
    recent_quality_taxonomy_audit_entries,
    resolve_quality_profile_rules,
)
from app.services.qbittorrent import QbittorrentClientError
from app.services.qbittorrent import QbittorrentClient
from app.services.settings_service import SettingsService

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _base_context(request: Request, page_title: str) -> dict[str, object]:
    return {
        "request": request,
        "page_title": page_title,
        "message": request.query_params.get("message"),
        "message_level": request.query_params.get("level", "info"),
    }


def _safe_feed_options(session: Session, selected_urls: list[str] | None = None) -> list[dict[str, str]]:
    settings = SettingsService.get_or_create(session)
    connection = SettingsService.resolve_qb_connection(settings)
    selected_urls = selected_urls or []
    feed_options: list[dict[str, str]] = []
    if connection.is_configured:
        try:
            with QbittorrentClient(connection.base_url, connection.username, connection.password) as client:
                feed_options = [item.model_dump() for item in client.get_feeds()]
        except QbittorrentClientError:
            feed_options = []
    seen = {item["url"] for item in feed_options}
    for url in selected_urls:
        if url not in seen:
            feed_options.append({"label": f"Saved feed: {url}", "url": url})
            seen.add(url)
    return feed_options


def _rule_to_form_data(rule: Rule) -> dict[str, object]:
    include_tokens = list(rule.quality_include_tokens or [])
    exclude_tokens = list(rule.quality_exclude_tokens or [])
    return {
        "rule_name": rule.rule_name,
        "content_name": rule.content_name,
        "imdb_id": rule.imdb_id or "",
        "normalized_title": rule.normalized_title,
        "media_type": rule.media_type.value,
        "quality_profile": rule.quality_profile.value,
        "filter_profile_key": "",
        "release_year": rule.release_year,
        "include_release_year": rule.include_release_year,
        "additional_includes": rule.additional_includes,
        "quality_include_tokens": include_tokens,
        "quality_exclude_tokens": exclude_tokens,
        "use_regex": rule.use_regex,
        "must_contain_override": rule.must_contain_override or "",
        "must_not_contain": rule.must_not_contain,
        "episode_filter": rule.episode_filter,
        "ignore_days": rule.ignore_days,
        "add_paused": rule.add_paused,
        "enabled": rule.enabled,
        "smart_filter": rule.smart_filter,
        "assigned_category": rule.assigned_category,
        "save_path": rule.save_path,
        "feed_urls": rule.feed_urls,
        "notes": rule.notes,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    rules = session.scalars(select(Rule).order_by(Rule.updated_at.desc())).all()
    search = request.query_params.get("search", "").strip().lower()
    media_filter = request.query_params.get("media", "").strip()
    sync_filter = request.query_params.get("sync", "").strip()
    enabled_filter = request.query_params.get("enabled", "").strip()

    filtered = []
    for rule in rules:
        if search and search not in rule.rule_name.lower() and search not in (rule.imdb_id or "").lower():
            continue
        if media_filter and rule.media_type.value != media_filter:
            continue
        if sync_filter and rule.last_sync_status.value != sync_filter:
            continue
        if enabled_filter:
            expected = enabled_filter == "true"
            if rule.enabled != expected:
                continue
        filtered.append(rule)

    context = _base_context(request, "Rules")
    context.update(
        {
            "rules": filtered,
            "filters": {
                "search": request.query_params.get("search", ""),
                "media": media_filter,
                "sync": sync_filter,
                "enabled": enabled_filter,
            },
            "media_choices": media_type_choices(),
            "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
            "sync_choices": ["never", "ok", "error", "drift"],
        }
    )
    return templates.TemplateResponse("index.html", context)


@router.get("/rules/new", response_class=HTMLResponse)
def new_rule(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    default_quality = settings.default_quality_profile
    profile_rules = resolve_quality_profile_rules(settings)
    default_profile_rule = profile_rules.get(default_quality.value, {"include_tokens": [], "exclude_tokens": []})
    default_filter_profile_key = detect_matching_filter_profile_key(
        default_profile_rule.get("include_tokens", []),
        default_profile_rule.get("exclude_tokens", []),
        settings,
    )
    context = _base_context(request, "New Rule")
    context.update(
        {
            "mode": "create",
            "rule_id": None,
            "form_data": {
                "rule_name": "",
                "content_name": "",
                "imdb_id": "",
                "normalized_title": "",
                "media_type": MediaType.SERIES.value,
                "quality_profile": default_quality.value,
                "filter_profile_key": default_filter_profile_key,
                "release_year": "",
                "include_release_year": False,
                "additional_includes": "",
                "quality_include_tokens": list(default_profile_rule.get("include_tokens", [])),
                "quality_exclude_tokens": list(default_profile_rule.get("exclude_tokens", [])),
                "use_regex": True,
                "must_contain_override": "",
                "must_not_contain": "",
                "episode_filter": "",
                "ignore_days": 0,
                "add_paused": settings.default_add_paused,
                "enabled": settings.default_enabled,
                "smart_filter": False,
                "assigned_category": "",
                "save_path": "",
                "feed_urls": [],
                "notes": "",
            },
            "errors": [],
            "feed_options": _safe_feed_options(session, []),
            "settings_form": SettingsService.to_form_dict(settings),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "quality_profile_rules": profile_rules,
            "available_filter_profiles": available_filter_profile_choices(settings),
            "media_choices": media_type_choices(),
        }
    )
    return templates.TemplateResponse("rule_form.html", context)


@router.get("/rules/{rule_id}", response_class=HTMLResponse)
def edit_rule(
    rule_id: str,
    request: Request,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    rule = session.get(Rule, rule_id)
    if rule is None:
        return templates.TemplateResponse(
            "index.html",
            {
                **_base_context(request, "Rules"),
                "rules": [],
                "filters": {"search": "", "media": "", "sync": "", "enabled": ""},
                "media_choices": media_type_choices(),
                "media_type_labels": {item.value: media_type_label(item) for item in MediaType},
                "sync_choices": ["never", "ok", "error", "drift"],
                "message": "Rule not found.",
                "message_level": "error",
            },
            status_code=404,
        )

    settings = SettingsService.get_or_create(session)
    profile_rules = resolve_quality_profile_rules(settings)
    form_data = _rule_to_form_data(rule)
    form_data["filter_profile_key"] = detect_matching_filter_profile_key(
        form_data["quality_include_tokens"],
        form_data["quality_exclude_tokens"],
        settings,
    )
    context = _base_context(request, f"Edit {rule.rule_name}")
    context.update(
        {
            "mode": "edit",
            "rule_id": rule.id,
            "form_data": form_data,
            "errors": [],
            "feed_options": _safe_feed_options(session, rule.feed_urls),
            "settings_form": SettingsService.to_form_dict(settings),
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "quality_profile_rules": profile_rules,
            "available_filter_profiles": available_filter_profile_choices(settings),
            "media_choices": media_type_choices(),
        }
    )
    return templates.TemplateResponse("rule_form.html", context)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    context = _base_context(request, "Settings")
    context.update(
        {
            "form_data": SettingsService.to_form_dict(settings),
            "errors": [],
            "quality_choices": quality_profile_choices(),
            "quality_options": quality_option_choices(),
            "quality_option_groups": quality_option_groups(),
            "metadata_choices": ["omdb", "disabled"],
        }
    )
    return templates.TemplateResponse("settings.html", context)


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

    return templates.TemplateResponse("taxonomy.html", context)


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
    return templates.TemplateResponse("import.html", context)


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
