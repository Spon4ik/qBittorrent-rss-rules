from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ensure_runtime_dirs
from app.db import init_db
from app.routes.api import router as api_router
from app.routes.pages import router as pages_router


def create_app() -> FastAPI:
    ensure_runtime_dirs()
    init_db()

    app = FastAPI(
        title="qBittorrent RSS Rule Manager",
        version="0.2.0",
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )
    app.include_router(pages_router)
    app.include_router(api_router)
    return app
