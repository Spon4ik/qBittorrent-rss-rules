from __future__ import annotations

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_startup_rule_sync_does_not_block_app_startup(configured_app_env, monkeypatch) -> None:
    monkeypatch.setenv("QB_RULES_SYNC_RULES_ON_STARTUP", "1")

    from app.config import get_environment_settings
    from app.main import create_app
    from app.services.settings_service import SettingsService
    from app.services.sync import SyncService

    get_environment_settings.cache_clear()
    sync_started = threading.Event()
    release_sync = threading.Event()
    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(is_configured=True),
    )

    def blocking_sync_all(self) -> None:
        sync_started.set()
        release_sync.wait()

    monkeypatch.setattr(SyncService, "sync_all", blocking_sync_all)

    with TestClient(create_app()):
        # Entering the lifespan while sync_all is still blocked proves startup
        # does not wait for the asynchronous qB sync.  Avoid a wall-clock
        # threshold here: host load is unrelated to the behavioral contract.
        assert sync_started.wait(timeout=1.0)
        assert release_sync.is_set() is False
        release_sync.set()


def test_startup_rule_sync_is_joined_during_app_shutdown(configured_app_env, monkeypatch) -> None:
    monkeypatch.setenv("QB_RULES_SYNC_RULES_ON_STARTUP", "1")

    from app.config import get_environment_settings
    from app.main import create_app
    from app.services.settings_service import SettingsService
    from app.services.sync import SyncService

    get_environment_settings.cache_clear()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(is_configured=True),
    )

    def blocking_sync_all(self) -> None:
        started.set()
        release.wait()
        finished.set()

    monkeypatch.setattr(SyncService, "sync_all", blocking_sync_all)

    with TestClient(create_app()):
        assert started.wait(timeout=1.0)
        release.set()

    assert finished.is_set()
    assert not any(thread.name == "startup-rule-sync" for thread in threading.enumerate())
