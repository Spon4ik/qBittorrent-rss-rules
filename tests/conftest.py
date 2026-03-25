from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def configured_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "test.db"
    monkeypatch.setenv("QB_RULES_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.delenv("QB_RULES_QB_BASE_URL", raising=False)
    monkeypatch.delenv("QB_RULES_QB_USERNAME", raising=False)
    monkeypatch.delenv("QB_RULES_QB_PASSWORD", raising=False)
    monkeypatch.delenv("QB_RULES_JACKETT_API_URL", raising=False)
    monkeypatch.delenv("QB_RULES_JACKETT_QB_URL", raising=False)
    monkeypatch.delenv("QB_RULES_JACKETT_API_KEY", raising=False)
    monkeypatch.delenv("QB_RULES_JELLYFIN_DB_PATH", raising=False)
    monkeypatch.delenv("QB_RULES_JELLYFIN_USER_NAME", raising=False)
    monkeypatch.delenv("QB_RULES_OMDB_API_KEY", raising=False)
    monkeypatch.setenv("QB_RULES_ENABLE_RULE_FETCH_SCHEDULER", "0")
    monkeypatch.setenv("QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER", "0")

    from app.config import get_environment_settings
    from app.db import reset_db_caches

    get_environment_settings.cache_clear()
    reset_db_caches()
    yield database_path

    get_environment_settings.cache_clear()
    reset_db_caches()


@pytest.fixture()
def app_client(configured_app_env: Path) -> TestClient:
    from app.main import create_app

    client = TestClient(create_app())
    yield client
    client.close()


@pytest.fixture()
def db_session(configured_app_env: Path):
    from app.db import get_session_factory, init_db

    init_db()

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
