from __future__ import annotations

import time
from types import SimpleNamespace


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

    app = create_app()
    startup_sync = next(
        handler for handler in app.router.on_startup if handler.__name__ == "_sync_rules_on_startup"
    )

    started = time.perf_counter()
    startup_sync()

    assert time.perf_counter() - started < 0.1
