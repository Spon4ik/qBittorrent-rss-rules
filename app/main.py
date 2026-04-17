from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.config import ensure_runtime_dirs, get_environment_settings
from app.db import get_session_factory, init_db
from app.routes.api import compat_router as api_compat_router
from app.routes.api import router as api_router
from app.routes.pages import router as pages_router
from app.routes.stremio_addon import router as stremio_addon_router
from app.services.jellyfin_auto_sync import (
    start_jellyfin_auto_sync_service,
    stop_jellyfin_auto_sync_service,
)
from app.services.rule_fetch_scheduler import (
    start_rule_fetch_scheduler,
    stop_rule_fetch_scheduler,
)
from app.services.static_assets import compute_static_asset_version
from app.services.stremio_auto_sync import (
    start_stremio_auto_sync_service,
    stop_stremio_auto_sync_service,
)

DESKTOP_BACKEND_CONTRACT = "2026-03-22"
DESKTOP_BACKEND_CAPABILITIES = (
    "hover_debug_telemetry",
    "search_hidden_result_diagnostics",
    "jellyfin_auto_sync",
    "stremio_library_sync",
    "stremio_native_addon",
)


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    init_db()
    env_settings = get_environment_settings()

    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(
        title="qBittorrent RSS Rule Manager",
        version="0.9.2",
    )
    app.state.static_asset_version = compute_static_asset_version(static_dir) or app.version
    app.state.desktop_backend_contract = DESKTOP_BACKEND_CONTRACT
    app.state.desktop_capabilities = DESKTOP_BACKEND_CAPABILITIES

    @app.middleware("http")
    async def _apply_stremio_addon_cors(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/stremio/") and request.method.upper() == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)
        if request.url.path.startswith("/stremio/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        return response

    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )
    app.include_router(pages_router)
    app.include_router(stremio_addon_router)
    app.include_router(api_compat_router)
    app.include_router(api_router)

    if env_settings.enable_rule_fetch_scheduler:

        @app.on_event("startup")
        def _start_background_rule_fetch_scheduler() -> None:  # pragma: no cover - startup hook
            start_rule_fetch_scheduler(
                session_factory=get_session_factory(),
                poll_interval_seconds=env_settings.rule_fetch_scheduler_poll_seconds,
            )

        @app.on_event("shutdown")
        def _stop_background_rule_fetch_scheduler() -> None:  # pragma: no cover - shutdown hook
            stop_rule_fetch_scheduler()

    if env_settings.enable_jellyfin_auto_sync_scheduler:

        @app.on_event("startup")
        def _start_jellyfin_auto_sync() -> None:  # pragma: no cover - startup hook
            start_jellyfin_auto_sync_service(
                session_factory=get_session_factory(),
            )

        @app.on_event("shutdown")
        def _stop_jellyfin_auto_sync() -> None:  # pragma: no cover - shutdown hook
            stop_jellyfin_auto_sync_service()

    if env_settings.enable_stremio_auto_sync_scheduler:

        @app.on_event("startup")
        def _start_stremio_auto_sync() -> None:  # pragma: no cover - startup hook
            start_stremio_auto_sync_service(
                session_factory=get_session_factory(),
            )

        @app.on_event("shutdown")
        def _stop_stremio_auto_sync() -> None:  # pragma: no cover - shutdown hook
            stop_stremio_auto_sync_service()

    return app
