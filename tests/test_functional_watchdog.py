from __future__ import annotations

from app.services import functional_watchdog


class _FakeSession:
    def close(self) -> None:
        return None


def _payload(*, jackett_ready: bool) -> dict[str, object]:
    return {
        "runtime": {
            "instance_id": "runtime-watchdog",
            "started_at": "2026-08-21T12:30:00+00:00",
        },
        "components": {
            "api": {
                "unhandled_errors": {
                    "count": 0,
                    "last": None,
                }
            },
            "scheduled_rule_fetch": {
                "runtime_enabled": True,
                "overdue_seconds": 0.0,
                "readiness": {
                    "jackett_app_ready": jackett_ready,
                    "error_type": None,
                },
                "schedule": {
                    "enabled": True,
                    "interval_minutes": 1440,
                    "last_run_at": "2026-08-21T12:45:00+00:00",
                    "next_run_at": "2099-08-22T12:00:00+00:00",
                    "last_status": "ok",
                    "last_message": "",
                },
                "scheduler": {
                    "created": True,
                    "running": True,
                    "started_at": "2026-08-21T12:30:00+00:00",
                    "poll_interval_seconds": 30,
                    "tick_in_progress": False,
                    "last_tick_started_at": "2099-08-21T12:59:29+00:00",
                    "last_tick_completed_at": "2099-08-21T12:59:30+00:00",
                    "last_tick_result": "not_due",
                    "last_tick_error_type": None,
                },
            },
        },
    }


def test_watchdog_promotes_repeated_failure_to_incident_and_records_recovery(monkeypatch) -> None:
    payload = _payload(jackett_ready=False)
    monkeypatch.setattr(
        functional_watchdog,
        "runtime_diagnostics_payload",
        lambda session: payload,
    )
    watchdog = functional_watchdog.FunctionalWatchdog(
        session_factory=_FakeSession,
        interval_seconds=30,
    )

    for _ in range(functional_watchdog.FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD):
        watchdog.run_once()

    failed = watchdog.status()
    f02 = failed["checks"]["F-02"]
    assert f02["consecutive_failures"] == functional_watchdog.FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD
    assert f02["incident_active"] is True
    assert failed["incident_count"] == 1
    assert failed["overall_state"] == "unhealthy"

    payload = _payload(jackett_ready=True)
    watchdog.run_once()

    recovered = watchdog.status()
    f02 = recovered["checks"]["F-02"]
    assert f02["status"] == "pass"
    assert f02["consecutive_failures"] == 0
    assert f02["incident_active"] is False
    assert f02["recovered_at"] is not None
    assert recovered["overall_state"] == "healthy"
