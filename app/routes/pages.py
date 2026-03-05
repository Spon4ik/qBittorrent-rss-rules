from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import MediaType, QualityProfile, Rule, media_type_choices, media_type_label
from app.schemas import JackettSearchRequest
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    build_reduced_search_request_from_rule,
    build_search_request_from_rule,
    clamp_search_query_text,
)
from app.services.metadata import (
    default_metadata_lookup_provider,
    metadata_lookup_provider_catalog,
    metadata_lookup_provider_choices,
)
from app.services.quality_filters import (
    available_filter_profile_choices,
    available_filter_profile_choices_for_media_type,
    detect_matching_filter_profile_key,
    preview_quality_taxonomy_update,
    quality_profile_label,
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
        return JackettSearchRequest(
            query=fallback_title,
            media_type=_rule_search_media_type(rule),
            imdb_id=rule.imdb_id or None,
            release_year=rule.release_year or None,
        )
    except ValidationError:
        return None


def _auto_imdb_first_payload(payload: JackettSearchRequest) -> JackettSearchRequest:
    if payload.imdb_id and payload.media_type in {MediaType.MOVIE, MediaType.SERIES}:
        return payload.model_copy(update={"imdb_id_only": True})
    return payload


def _prefill_rule_search_form_data(form_data: dict[str, str], rule: Rule) -> None:
    if form_data["query"]:
        return
    fallback_title = clamp_search_query_text(_rule_search_title(rule))
    if not fallback_title:
        return
    form_data["query"] = fallback_title
    form_data["media_type"] = _rule_search_media_type(rule)
    form_data["imdb_id"] = str(rule.imdb_id or "").strip()
    form_data["release_year"] = str(rule.release_year or "").strip()


def _unexpected_error_message(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip()
    label = exc.__class__.__name__
    if detail:
        return f"{prefix} ({label}): {detail}"
    return f"{prefix} ({label})."


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


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    source_rule: Rule | None = None
    source_rule_id = request.query_params.get("rule_id", "").strip()
    form_data = {
        "query": request.query_params.get("query", "").strip(),
        "media_type": _normalized_media_type(request.query_params.get("media_type")),
        "indexer": request.query_params.get("indexer", "all").strip() or "all",
        "imdb_id": request.query_params.get("imdb_id", "").strip(),
        "release_year": request.query_params.get("release_year", "").strip(),
        "keywords_all": request.query_params.get("keywords_all", "").strip(),
        "keywords_any": request.query_params.get("keywords_any", "").strip(),
        "keywords_not": request.query_params.get("keywords_not", "").strip(),
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

    try:
        settings = SettingsService.get_or_create(session)
        jackett = SettingsService.resolve_jackett(settings)
        jackett_ready = jackett.app_ready
        jackett_rule_ready = jackett.rule_ready
        jackett_api_url = jackett.api_url or ""
        jackett_qb_url = jackett.qb_url or ""
        jackett_api_key = jackett.api_key
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
            if payload_from_rule is not None and not form_data["query"]:
                active_payload = payload_from_rule
                form_data.update(
                    {
                        "query": payload_from_rule.query,
                        "media_type": payload_from_rule.media_type.value,
                        "imdb_id": payload_from_rule.imdb_id or "",
                        "release_year": payload_from_rule.release_year or "",
                        "keywords_all": ", ".join(payload_from_rule.keywords_all),
                        "keywords_any": ", ".join(payload_from_rule.keywords_any),
                        "keywords_not": ", ".join(payload_from_rule.keywords_not),
                    }
                )

    if form_data["query"] and not errors:
        if active_payload is None:
            try:
                active_payload = JackettSearchRequest.model_validate(
                    {
                        "query": form_data["query"],
                        "media_type": form_data["media_type"],
                        "indexer": form_data["indexer"],
                        "imdb_id": form_data["imdb_id"],
                        "release_year": form_data["release_year"],
                        "keywords_all": form_data["keywords_all"],
                        "keywords_any": form_data["keywords_any"],
                        "keywords_not": form_data["keywords_not"],
                    }
                )
            except ValidationError as exc:
                errors = [error["msg"] for error in exc.errors()]
        if active_payload is not None and not errors:
            try:
                active_payload = _auto_imdb_first_payload(active_payload)
                client = JackettClient(jackett_api_url, jackett_api_key)
                result = client.search(active_payload)
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
                summary_parts = ["Title"]
                if active_payload.imdb_id_only:
                    summary_parts.append("IMDb-enforced Jackett lookup")
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
                search_run = {
                    **result.model_dump(mode="json"),
                    "source_label": "Saved rule search" if source_rule else "Jackett active search",
                    "primary_label": (
                        "IMDb-first results"
                        if active_payload.imdb_id_only
                        else ("Saved rule search" if source_rule else "Jackett active search")
                    ),
                    "fallback_label": "Title fallback" if result.fallback_request_variants else "",
                    "results": [
                        {
                            **item.model_dump(mode="json"),
                            "new_rule_href": new_rule_href,
                        }
                        for item in result.results
                    ],
                    "fallback_results": [
                        {
                            **item.model_dump(mode="json"),
                            "new_rule_href": new_rule_href,
                        }
                        for item in result.fallback_results
                    ],
                    "rule_prefill_summary": f"{', '.join(summary_parts)}.",
                    "source_rule_name": source_rule.rule_name if source_rule else "",
                    "ignored_full_regex": ignored_full_regex,
                }
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
        }
    )
    return templates.TemplateResponse("search.html", context)


@router.get("/rules/{rule_id}/search")
def run_rule_search(rule_id: str) -> RedirectResponse:
    return RedirectResponse(url=f"/search?rule_id={rule_id}", status_code=303)


@router.get("/rules/new", response_class=HTMLResponse)
def new_rule(request: Request, session: Session = Depends(get_db_session)) -> HTMLResponse:
    settings = SettingsService.get_or_create(session)
    requested_media_type = _normalized_media_type(request.query_params.get("media_type"))
    default_quality = settings.default_quality_profile
    profile_rules = resolve_quality_profile_rules(settings)
    default_profile_rule = profile_rules.get(default_quality.value, {"include_tokens": [], "exclude_tokens": []})
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
        "media_type": requested_media_type,
        "quality_profile": (
            default_quality.value
            if requested_media_type in {MediaType.SERIES.value, MediaType.MOVIE.value}
            else QualityProfile.CUSTOM.value
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
        "episode_filter": "",
        "ignore_days": 0,
        "add_paused": settings.default_add_paused,
        "enabled": settings.default_enabled,
        "smart_filter": False,
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
    context.update(
        {
            "mode": "create",
            "rule_id": None,
            "form_data": form_data,
            "errors": [],
            "feed_options": _safe_feed_options(session, list(settings.default_feed_urls or [])),
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
            "visible_metadata_lookup_providers": metadata_lookup_provider_choices(requested_media_type),
            "metadata_lookup_disabled": settings.metadata_provider.value == "disabled",
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
        media_type=form_data["media_type"],
    )
    context = _base_context(request, f"Edit {rule.rule_name}")
    available_filter_profiles = available_filter_profile_choices(settings)
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
            "available_filter_profiles": available_filter_profiles,
            "visible_filter_profiles": available_filter_profile_choices_for_media_type(
                settings,
                form_data["media_type"],
            ),
            "media_choices": media_type_choices(),
            "metadata_lookup_providers": metadata_lookup_provider_catalog(),
            "visible_metadata_lookup_providers": metadata_lookup_provider_choices(
                form_data["media_type"],
            ),
            "metadata_lookup_disabled": settings.metadata_provider.value == "disabled",
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
            "profile_1080p_label": quality_profile_label(QualityProfile.HD_1080P),
            "profile_2160p_hdr_label": quality_profile_label(QualityProfile.UHD_2160P_HDR),
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
