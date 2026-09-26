from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_FERNET_KEY = "fn-lMUENe1LpVWmq1cTkZSIQshpSWnwYjvAnHo55JlQ="
_TEST_RUNTIME_ROOT: tempfile.TemporaryDirectory[str] | None = None
_ORIGINAL_DATA_DIR: Path | None = None
_ORIGINAL_TEST_ENV: dict[str, str | None] = {}
_TEST_ENV_KEYS = (
    "QB_RULES_DATABASE_URL",
    "QB_RULES_QB_BASE_URL",
    "QB_RULES_QB_USERNAME",
    "QB_RULES_QB_PASSWORD",
    "QB_RULES_JACKETT_API_URL",
    "QB_RULES_JACKETT_QB_URL",
    "QB_RULES_JACKETT_API_KEY",
    "QB_RULES_JELLYFIN_DB_PATH",
    "QB_RULES_JELLYFIN_USER_NAME",
    "QB_RULES_JELLYFIN_SERVER_URL",
    "QB_RULES_JELLYFIN_API_KEY",
    "QB_RULES_OMDB_API_KEY",
    "QB_RULES_STREMIO_LOCAL_STORAGE_PATH",
    "QB_RULES_STREMIO_AUTH_KEY",
    "QB_RULES_SYNC_RULES_ON_STARTUP",
    "QB_RULES_ENABLE_RULE_FETCH_SCHEDULER",
    "QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER",
    "QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER",
    "QB_RULES_ENABLE_DOWNLOAD_ACCELERATION_SCHEDULER",
    "QB_RULES_ENABLE_QB_RECOVERY_SCHEDULER",
)


def pytest_configure(config: pytest.Config) -> None:
    del config
    global _ORIGINAL_DATA_DIR, _ORIGINAL_TEST_ENV, _TEST_RUNTIME_ROOT

    from app import config as app_config

    _ORIGINAL_DATA_DIR = app_config.DATA_DIR
    _ORIGINAL_TEST_ENV = {key: os.environ.get(key) for key in _TEST_ENV_KEYS}
    _TEST_RUNTIME_ROOT = tempfile.TemporaryDirectory(prefix="qb-rss-pytest-")
    test_data_dir = Path(_TEST_RUNTIME_ROOT.name) / "data"
    test_data_dir.mkdir(parents=True)

    app_config.DATA_DIR = test_data_dir
    os.environ["QB_RULES_DATABASE_URL"] = (
        f"sqlite:///{(test_data_dir / 'qb_rules.db').as_posix()}"
    )
    for key in _TEST_ENV_KEYS[1:]:
        os.environ.pop(key, None)
    for key in (
        "QB_RULES_SYNC_RULES_ON_STARTUP",
        "QB_RULES_ENABLE_RULE_FETCH_SCHEDULER",
        "QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER",
        "QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER",
        "QB_RULES_ENABLE_DOWNLOAD_ACCELERATION_SCHEDULER",
        "QB_RULES_ENABLE_QB_RECOVERY_SCHEDULER",
    ):
        os.environ[key] = "0"

    app_config.get_environment_settings.cache_clear()
    from app.services import quality_filters

    quality_filters._clear_quality_taxonomy_cache()
    quality_filters._load_quality_taxonomy()


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    global _ORIGINAL_DATA_DIR, _ORIGINAL_TEST_ENV, _TEST_RUNTIME_ROOT

    from app import config as app_config
    from app.services import quality_filters

    quality_filters._clear_quality_taxonomy_cache()
    if _ORIGINAL_DATA_DIR is not None:
        app_config.DATA_DIR = _ORIGINAL_DATA_DIR
        quality_filters.QUALITY_TAXONOMY_PATH = _ORIGINAL_DATA_DIR / "quality_taxonomy.json"
        quality_filters.QUALITY_TAXONOMY_AUDIT_PATH = (
            app_config.ROOT_DIR / "data" / "taxonomy_audit.jsonl"
        )
    for key, value in _ORIGINAL_TEST_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    app_config.get_environment_settings.cache_clear()
    if _TEST_RUNTIME_ROOT is not None:
        _TEST_RUNTIME_ROOT.cleanup()
        _TEST_RUNTIME_ROOT = None


@pytest.fixture(autouse=True)
def isolated_quality_taxonomy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.services import quality_filters

    test_data_dir = tmp_path / "quality-taxonomy-data"
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_PATH",
        test_data_dir / "quality_taxonomy.json",
    )
    monkeypatch.setattr(
        quality_filters,
        "QUALITY_TAXONOMY_AUDIT_PATH",
        test_data_dir / "taxonomy_audit.jsonl",
    )
    quality_filters._clear_quality_taxonomy_cache()
    quality_filters._load_quality_taxonomy()
    yield
    quality_filters._clear_quality_taxonomy_cache()


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
    monkeypatch.setenv("QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER", "0")
    monkeypatch.setenv("QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER", "0")

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
