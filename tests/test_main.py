from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_startup_rule_sync_does_not_block_app_startup(configured_app_env, monkeypatch) -> None:
    monkeypatch.setenv("QB_RULES_SYNC_RULES_ON_STARTUP", "1")

    from app.config import get_environment_settings
    from app.main import create_app
    from app.services.settings_service import SettingsService
    from app.services.sync import SyncService

    get_environment_settings.cache_clear()
    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(is_configured=True),
    )
    monkeypatch.setattr(SyncService, "sync_all", lambda self: time.sleep(0.2))

    started = time.perf_counter()
    with TestClient(create_app()):
        # Lifespan startup must not wait for the asynchronous qB sync.
        assert time.perf_counter() - started < 0.1


def test_startup_rule_sync_is_joined_during_app_shutdown(configured_app_env, monkeypatch) -> None:
    import threading

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
