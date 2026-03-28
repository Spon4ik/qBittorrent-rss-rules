from __future__ import annotations

from types import SimpleNamespace

from app.db import get_session_factory, init_db
from app.models import AppSettings
from app.services.stremio_auto_sync import StremioAutoSyncService


def test_stremio_auto_sync_runs_on_start_and_on_library_changes(
    configured_app_env,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    init_db()
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(tmp_path / "stremio"),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=5,
    )
    db_session.add(settings)
    db_session.commit()

    signature_values = iter(["sig-a", "sig-a", "sig-b"])
    calls: list[str] = []

    monkeypatch.setattr(
        "app.services.stremio_auto_sync.StremioService.fetch_library_signature",
        lambda self: next(signature_values),
    )
    monkeypatch.setattr(
        "app.services.stremio_auto_sync.StremioService.can_resolve_auth",
        lambda self: True,
    )

    def fake_execute(session, *, settings):
        calls.append(str(settings.stremio_local_storage_path))
        return SimpleNamespace(
            message_level="success",
            render_message=lambda prefix="Stremio sync completed": (
                f"{prefix} for 1 active title(s) (1 created, 0 linked, 0 updated, 0 disabled, 0 re-enabled, 0 unchanged, 0 skipped, 0 errors)."
            ),
        )

    monkeypatch.setattr("app.services.stremio_auto_sync.execute_stremio_sync", fake_execute)

    service = StremioAutoSyncService(
        session_factory=get_session_factory(),
        poll_interval_seconds=5,
    )

    service.run_once(force=True)
    db_session.expire_all()
    refreshed = db_session.get(AppSettings, "default")
    assert refreshed is not None
    assert calls == [str(tmp_path / "stremio")]
    assert refreshed.stremio_auto_sync_last_run_at is not None
    assert refreshed.stremio_auto_sync_last_status == "success"
    assert refreshed.stremio_auto_sync_last_message.startswith(
        "Automatic Stremio sync completed"
    )

    service.run_once(force=False)
    assert calls == [str(tmp_path / "stremio")]

    service.run_once(force=False)
    assert calls == [str(tmp_path / "stremio"), str(tmp_path / "stremio")]
