from __future__ import annotations

import json
from datetime import UTC, datetime
from time import monotonic
from typing import cast
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import ROOT_DIR
from app.db import get_db_session
from app.services.local_playback import resolve_local_playback_token
from app.services.settings_service import SettingsService
from app.services.stremio_addon import StremioAddonService

router = APIRouter()
STREMIO_ADDON_DEBUG_LOG_PATH = ROOT_DIR / "logs" / "stremio-addon-debug.log"


def _payload_objects(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    raw_items = payload.get(key)
    if not isinstance(raw_items, list):
        return []
    return [cast(dict[str, object], item) for item in raw_items if isinstance(item, dict)]


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_skip(value: str | None) -> int:
    try:
        return max(0, int(str(value or "0").strip()))
    except ValueError:
        return 0


def _extra_params_from_request(request: Request, extra_path: str | None = None) -> dict[str, str]:
    extras: dict[str, str] = {}
    raw_extra_path = str(extra_path or "").strip()
    if raw_extra_path:
        path_text = raw_extra_path[:-5] if raw_extra_path.endswith(".json") else raw_extra_path
        for segment in [item for item in path_text.split("/") if item]:
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            cleaned_key = unquote(str(key or "").strip())
            if not cleaned_key:
                continue
            extras[cleaned_key] = unquote(str(value or "").strip())
    for key, value in request.query_params.items():
        extras.setdefault(str(key).strip(), str(value).strip())
    return extras


def _append_stremio_addon_debug_event(event: dict[str, object]) -> None:
    try:
        STREMIO_ADDON_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STREMIO_ADDON_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True))
            handle.write("\n")
    except OSError:
        return


def _request_debug_context(request: Request) -> dict[str, object]:
    client_host = request.client.host if request.client is not None else None
    return {
        "at": datetime.now(UTC).isoformat(),
        "path": request.url.path,
        "query": str(request.url.query or ""),
        "client_host": client_host,
        "user_agent": str(request.headers.get("user-agent") or "").strip(),
    }


@router.get("/stremio/manifest.json")
def stremio_manifest(request: Request, session: Session = Depends(get_db_session)) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    payload = StremioAddonService(settings).manifest(version=request.app.version)
    _append_stremio_addon_debug_event(
        {
            **_request_debug_context(request),
            "route": "manifest",
        }
    )
    return JSONResponse(payload)


@router.get("/stremio/catalog/{item_type}/{catalog_id}.json")
def stremio_catalog(
    request: Request,
    item_type: str,
    catalog_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    extras = _extra_params_from_request(request)
    settings = SettingsService.get_or_create(session)
    payload = StremioAddonService(settings).catalog_search(
        item_type=item_type,
        catalog_id=catalog_id,
        search_text=extras.get("search"),
        skip=_coerce_skip(extras.get("skip")),
    )
    _append_stremio_addon_debug_event(
        {
            **_request_debug_context(request),
            "route": "catalog",
            "item_type": item_type,
            "catalog_id": catalog_id,
            "search_text": extras.get("search"),
            "skip": _coerce_skip(extras.get("skip")),
            "metas_count": len(_payload_objects(payload, "metas")),
        }
    )
    return JSONResponse(payload)


@router.get("/stremio/catalog/{item_type}/{catalog_id}/{extra_path:path}")
def stremio_catalog_with_extra_path(
    request: Request,
    item_type: str,
    catalog_id: str,
    extra_path: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    extras = _extra_params_from_request(request, extra_path)
    settings = SettingsService.get_or_create(session)
    payload = StremioAddonService(settings).catalog_search(
        item_type=item_type,
        catalog_id=catalog_id,
        search_text=extras.get("search"),
        skip=_coerce_skip(extras.get("skip")),
    )
    _append_stremio_addon_debug_event(
        {
            **_request_debug_context(request),
            "route": "catalog",
            "item_type": item_type,
            "catalog_id": catalog_id,
            "search_text": extras.get("search"),
            "skip": _coerce_skip(extras.get("skip")),
            "metas_count": len(_payload_objects(payload, "metas")),
        }
    )
    return JSONResponse(payload)


@router.get("/stremio/stream/{item_type}/{item_id}.json")
def stremio_stream(
    request: Request,
    item_type: str,
    item_id: str,
    session: Session = Depends(get_db_session),
) -> JSONResponse:
    settings = SettingsService.get_or_create(session)
    started_at = monotonic()
    payload = StremioAddonService(settings).stream_lookup(
        item_type=item_type,
        item_id=item_id,
        base_url=str(request.base_url),
    )
    streams = _payload_objects(payload, "streams")
    _append_stremio_addon_debug_event(
        {
            **_request_debug_context(request),
            "route": "stream",
            "item_type": item_type,
            "item_id": item_id,
            "elapsed_ms": round((monotonic() - started_at) * 1000, 3),
            "streams_count": len(streams),
            "info_hashes": [
                str(item.get("infoHash") or "").strip()
                for item in streams[:5]
                if str(item.get("infoHash") or "").strip()
            ],
            "file_idxs": [
                file_idx
                for item in streams[:5]
                if (file_idx := _coerce_optional_int(item.get("fileIdx"))) is not None
            ],
        }
    )
    return JSONResponse(payload)


@router.get("/stremio/local-playback/{token}")
def stremio_local_playback(token: str) -> FileResponse:
    playback_file = resolve_local_playback_token(token)
    if playback_file is None:
        raise HTTPException(status_code=404, detail="Not Found")
    headers = {
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(
        path=playback_file.file_path,
        media_type=playback_file.media_type,
        filename=playback_file.filename,
        content_disposition_type="inline",
        headers=headers,
    )
