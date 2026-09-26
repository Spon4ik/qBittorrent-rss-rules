from __future__ import annotations

from pathlib import Path

import pytest


def test_app_db_engine_refuses_checkout_database_and_preserves_sentinel(
    configured_app_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import config, db

    sentinel_path = config.ROOT_DIR / "data" / f".pytest-denied-{tmp_path.name}.db"
    assert not sentinel_path.exists()
    monkeypatch.setenv("QB_RULES_DATABASE_URL", f"sqlite:///{sentinel_path.as_posix()}")
    config.get_environment_settings.cache_clear()
    db.reset_db_caches()

    try:
        with pytest.raises(RuntimeError, match="temporary directory"):
            db.get_engine()
        assert not sentinel_path.exists()
    finally:
        config.get_environment_settings.cache_clear()
        db.reset_db_caches()


def test_pytest_defaults_each_test_to_its_own_temporary_database(tmp_path: Path) -> None:
    from sqlalchemy.engine import make_url

    from app.config import get_environment_settings

    database_path = Path(make_url(get_environment_settings().database_url).database or "")
    assert database_path == tmp_path / "pytest.db"


def test_pytest_runtime_clears_inherited_provider_settings() -> None:
    import os

    from app.config import get_environment_settings

    get_environment_settings.cache_clear()
    settings = get_environment_settings()
    provider_values = (
        settings.qb_base_url,
        settings.qb_username,
        settings.qb_password,
        settings.jackett_api_url,
        settings.jackett_qb_url,
        settings.jackett_api_key,
        settings.jellyfin_db_path,
        settings.jellyfin_user_name,
        settings.jellyfin_server_url,
        settings.jellyfin_api_key,
        settings.stremio_local_storage_path,
        settings.stremio_auth_key,
        settings.omdb_api_key,
    )
    assert provider_values == (None,) * len(provider_values)
    assert settings.enable_jellyfin_auto_sync_scheduler is False
    assert settings.enable_stremio_auto_sync_scheduler is False
    assert settings.enable_rule_fetch_scheduler is False
    assert settings.sync_rules_on_startup is False
    assert os.environ["QB_RULES_DATABASE_URL"].startswith("sqlite:///")


def test_app_client_fixture_stops_queues_if_app_creation_fails(
    configured_app_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    import app.main
    import app.services.rule_fetch_queue as fetch_queue
    import app.services.sync_queue as sync_queue

    events: list[str] = []

    monkeypatch.setattr(sync_queue, "start_rule_sync_queue", lambda: events.append("start-sync"))
    monkeypatch.setattr(sync_queue, "stop_rule_sync_queue", lambda: events.append("stop-sync"))
    monkeypatch.setattr(fetch_queue, "start_rule_fetch_queue", lambda: events.append("start-fetch"))
    monkeypatch.setattr(fetch_queue, "stop_rule_fetch_queue", lambda: events.append("stop-fetch"))

    def fail_app_creation():
        raise RuntimeError("synthetic app construction failure")

    monkeypatch.setattr(app.main, "create_app", fail_app_creation)

    with pytest.raises(RuntimeError, match="synthetic app construction failure"):
        request.getfixturevalue("app_client")

    assert events == ["start-sync", "start-fetch", "stop-fetch", "stop-sync"]
