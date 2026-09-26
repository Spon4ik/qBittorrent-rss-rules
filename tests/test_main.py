from __future__ import annotations

import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_startup_rule_sync_does_not_block_app_startup(configured_app_env, monkeypatch) -> None:
    monkeypatch.setenv("QB_RULES_SYNC_RULES_ON_STARTUP", "1")

    import app.main as main_module
    from app.config import get_environment_settings
    from app.main import create_app
    from app.services.settings_service import SettingsService
    from app.services.sync import SyncService

    get_environment_settings.cache_clear()
    sync_started = threading.Event()
    release_sync = threading.Event()
    startup_completed = threading.Event()
    startup_errors: list[BaseException] = []
    fake_session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(main_module, "get_session_factory", lambda: lambda: fake_session)
    monkeypatch.setattr(main_module, "start_download_acceleration_scheduler", lambda **_: None)
    monkeypatch.setattr(main_module, "start_qb_recovery_scheduler", lambda **_: None)
    monkeypatch.setattr(SettingsService, "get_or_create", lambda session: object())
    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(is_configured=True),
    )

    def blocking_sync_all(self) -> None:
        sync_started.set()
        release_sync.wait()

    monkeypatch.setattr(SyncService, "sync_all", blocking_sync_all)

    def start_client() -> None:
        try:
            with TestClient(create_app()):
                startup_completed.set()
        except BaseException as error:
            startup_errors.append(error)

    startup_thread = threading.Thread(target=start_client, name="test-startup-client")
    startup_thread.start()
    try:
        assert sync_started.wait(timeout=5.0)
        # Startup must complete while the background sync is still blocked.
        assert startup_completed.wait(timeout=5.0)
    finally:
        release_sync.set()
    startup_thread.join(timeout=5.0)

    assert not startup_thread.is_alive()
    assert startup_errors == []


def test_startup_rule_sync_is_joined_during_app_shutdown(configured_app_env, monkeypatch) -> None:
    import threading

    monkeypatch.setenv("QB_RULES_SYNC_RULES_ON_STARTUP", "1")

    import app.main as main_module
    from app.config import get_environment_settings
    from app.main import create_app
    from app.services.settings_service import SettingsService
    from app.services.sync import SyncService

    get_environment_settings.cache_clear()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    fake_session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(main_module, "get_session_factory", lambda: lambda: fake_session)
    monkeypatch.setattr(main_module, "start_download_acceleration_scheduler", lambda **_: None)
    monkeypatch.setattr(main_module, "start_qb_recovery_scheduler", lambda **_: None)
    monkeypatch.setattr(SettingsService, "get_or_create", lambda session: object())
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
