from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_FERNET_KEY = "fn-lMUENe1LpVWmq1cTkZSIQshpSWnwYjvAnHo55JlQ="


@pytest.fixture(autouse=True)
def configured_secret_store(monkeypatch: pytest.MonkeyPatch):
    from app.services.secret_store import reset_secret_store_cache

    monkeypatch.setenv("QB_RULES_SECRET_KEY", TEST_FERNET_KEY)
    reset_secret_store_cache()
    yield
    reset_secret_store_cache()


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
    monkeypatch.setenv("QB_RULES_ENABLE_FUNCTIONAL_WATCHDOG", "0")
    monkeypatch.setenv("QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER", "0")
    monkeypatch.setenv("QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER", "0")

    from app.config import get_environment_settings
    from app.db import reset_db_caches
    from app.services.api_error_registry import reset_api_error_registry_for_tests

    get_environment_settings.cache_clear()
    reset_db_caches()
    reset_api_error_registry_for_tests()
    yield database_path

    reset_api_error_registry_for_tests()
    get_environment_settings.cache_clear()
    reset_db_caches()


@pytest.fixture()
def app_client(configured_app_env: Path) -> TestClient:
    from app.main import create_app
    from app.services.rule_fetch_queue import start_rule_fetch_queue, stop_rule_fetch_queue
    from app.services.sync_queue import start_rule_sync_queue, stop_rule_sync_queue

    start_rule_sync_queue()
    start_rule_fetch_queue()
    client = TestClient(create_app())
    try:
        yield client
    finally:
        client.close()
        stop_rule_fetch_queue()
        stop_rule_sync_queue()


@pytest.fixture()
def db_session(configured_app_env: Path):
    from app.db import get_session_factory, init_db

    init_db()

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
