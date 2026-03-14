from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ensure_runtime_dirs
from app.db import init_db
from app.routes.api import router as api_router
from app.routes.pages import router as pages_router


def _static_asset_version(static_dir: Path) -> str:
    parts: list[str] = []
    for filename in ("app.css", "app.js"):
        file_path = static_dir / filename
        if not file_path.exists():
            continue
        parts.append(str(file_path.stat().st_mtime_ns))
    return "-".join(parts)


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    init_db()

    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(
        title="qBittorrent RSS Rule Manager",
        version="0.4.0",
    )
    app.state.static_asset_version = _static_asset_version(static_dir) or app.version
    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )
    app.include_router(pages_router)
    app.include_router(api_router)
    return app
