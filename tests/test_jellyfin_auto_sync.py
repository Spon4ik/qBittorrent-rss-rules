from __future__ import annotations

import os
import time
from types import SimpleNamespace

from app.db import get_session_factory, init_db
from app.models import AppSettings
from app.services.jellyfin_auto_sync import JellyfinAutoSyncService
from tests.jellyfin_test_utils import create_jellyfin_test_db


def test_jellyfin_auto_sync_runs_on_start_and_on_db_changes(
    configured_app_env,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    init_db()
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    settings = AppSettings(
        id="default",
        jellyfin_db_path=str(db_path),
        jellyfin_user_name="Spon4ik",
        jellyfin_auto_sync_enabled=True,
        jellyfin_auto_sync_interval_seconds=5,
    )
    db_session.add(settings)
    db_session.commit()

    calls: list[str] = []

    def fake_execute(session, *, settings):
        calls.append(str(settings.jellyfin_db_path))
        return SimpleNamespace(
            message_level="success",
            render_message=lambda prefix="Jellyfin sync completed for": (
                f'{prefix} "Spon4ik" (0 updated, 1 unchanged, 0 skipped, 0 errors).'
            ),
        )

    monkeypatch.setattr("app.services.jellyfin_auto_sync.execute_jellyfin_sync", fake_execute)

    service = JellyfinAutoSyncService(
        session_factory=get_session_factory(), poll_interval_seconds=5
    )

    service.run_once(force=True)
    db_session.expire_all()
    refreshed = db_session.get(AppSettings, "default")
    assert refreshed is not None
    assert calls == [str(db_path)]
    assert refreshed.jellyfin_auto_sync_last_run_at is not None
    assert refreshed.jellyfin_auto_sync_last_status == "success"
    assert refreshed.jellyfin_auto_sync_last_message.startswith(
        'Automatic Jellyfin sync completed for "Spon4ik"'
    )

    service.run_once(force=False)
    assert calls == [str(db_path)]

    time.sleep(0.02)
    os.utime(db_path, None)
    service.run_once(force=False)
    assert calls == [str(db_path), str(db_path)]
