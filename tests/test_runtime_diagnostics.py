from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from app.models import AppSettings
from app.services import rule_fetch_scheduler, runtime_diagnostics


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_called = False
        self.closed = False

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        self.closed = True


def test_rule_fetch_scheduler_telemetry_records_tick_success_and_failure(monkeypatch) -> None:
    sessions: list[_FakeSession] = []

    def session_factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(
        rule_fetch_scheduler,
        "run_due_scheduled_fetch",
        lambda session: {"status": "partial"},
    )
    scheduler = rule_fetch_scheduler.RuleFetchScheduler(
        session_factory=session_factory,
        poll_interval_seconds=30,
    )
    scheduler.run_once()

    healthy = scheduler.status()
    assert healthy["last_tick_result"] == "run:partial"
    assert healthy["last_tick_error_type"] is None
    assert healthy["last_tick_completed_at"] is not None
    assert sessions[-1].closed is True

    def fail_tick(session):
        raise RuntimeError("provider detail should not be exposed")

    monkeypatch.setattr(rule_fetch_scheduler, "run_due_scheduled_fetch", fail_tick)
    scheduler.run_once()

    failed = scheduler.status()
    assert failed["last_tick_result"] == "error"
    assert failed["last_tick_error_type"] == "RuntimeError"
    assert sessions[-1].rollback_called is True
    assert sessions[-1].closed is True


def test_rule_fetch_scheduler_reports_thread_liveness(monkeypatch) -> None:
    tick_seen = threading.Event()

    def fake_tick(session):
        tick_seen.set()
        return None

    monkeypatch.setattr(rule_fetch_scheduler, "run_due_scheduled_fetch", fake_tick)
    scheduler = rule_fetch_scheduler.RuleFetchScheduler(
        session_factory=_FakeSession,
        poll_interval_seconds=5,
    )
    scheduler.start()
    try:
        assert tick_seen.wait(timeout=1.0)
        assert scheduler.status()["running"] is True
    finally:
        scheduler.stop()

    assert scheduler.status()["running"] is False


def test_runtime_diagnostics_endpoint_exposes_schedule_overdue_and_runtime_switch(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    now = datetime.now(UTC)
    settings = db_session.get(AppSettings, "default") or AppSettings(id="default")
    settings.rules_fetch_schedule_enabled = True
    settings.rules_fetch_schedule_interval_minutes = 1440
    settings.rules_fetch_schedule_last_run_at = now - timedelta(days=8)
    settings.rules_fetch_schedule_next_run_at = now - timedelta(days=7)
    db_session.add(settings)
    db_session.commit()

    monkeypatch.setattr(
        runtime_diagnostics,
        "rule_fetch_scheduler_status",
        lambda: {
            "created": False,
            "running": False,
            "poll_interval_seconds": None,
            "tick_in_progress": False,
            "last_tick_started_at": None,
            "last_tick_completed_at": None,
            "last_tick_result": "never",
            "last_tick_error_type": None,
        },
    )

    response = app_client.get("/api/diagnostics/runtime")

    assert response.status_code == 200
    component = response.json()["components"]["scheduled_rule_fetch"]
    assert component["runtime_enabled"] is False
    assert component["schedule"]["enabled"] is True
    assert component["overdue_seconds"] > 6 * 24 * 60 * 60
    assert component["scheduler"]["running"] is False
