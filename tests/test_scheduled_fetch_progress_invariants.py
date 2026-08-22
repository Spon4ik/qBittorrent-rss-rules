from __future__ import annotations

from datetime import UTC, datetime

from app.services import operation_status, runtime_diagnostics
from app.services.functional_invariants import (
    MAX_ACTIVE_TICK_NO_PROGRESS_SECONDS,
    evaluate_scheduled_fetch_effectiveness,
    evaluate_scheduled_fetch_liveness,
)

NOW = datetime(2026, 8, 22, 19, 31, tzinfo=UTC)


def _progressing_payload(*, updated_at: str) -> dict[str, object]:
    return {
        "diagnostic_capabilities": [
            "scheduled_snapshot_freshness",
            "scheduled_fetch_progress",
        ],
        "runtime": {
            "instance_id": "runtime-progress",
            "started_at": "2026-08-22T18:50:00+00:00",
        },
        "components": {
            "scheduled_rule_fetch": {
                "runtime_enabled": True,
                "overdue_seconds": 14800.0,
                "schedule": {
                    "enabled": True,
                    "interval_minutes": 1440,
                    "scope": "enabled",
                    "last_run_at": "2026-08-21T15:23:07+00:00",
                    "next_run_at": "2026-08-22T15:23:07+00:00",
                    "last_status": "error",
                    "last_message": "historical failure",
                },
                "scheduler": {
                    "created": True,
                    "running": True,
                    "started_at": "2026-08-22T18:50:00+00:00",
                    "poll_interval_seconds": 30,
                    "tick_in_progress": True,
                    "last_tick_started_at": "2026-08-22T18:50:00+00:00",
                    "last_tick_completed_at": None,
                    "last_tick_result": "never",
                    "last_tick_error_type": None,
                },
                "operation_progress": {
                    "current": 70,
                    "total": 276,
                    "percent": 25,
                    "started_at": "2026-08-22T18:50:01+00:00",
                    "updated_at": updated_at,
                },
                "readiness": {
                    "jackett_app_ready": True,
                    "error_type": None,
                },
                "snapshot_freshness": {
                    "scope": "enabled",
                    "total_rules": 276,
                    "fresh_snapshots": 70,
                    "stale_snapshots": 206,
                    "missing_snapshots": 0,
                    "pending_snapshots": 0,
                    "freshness_limit_seconds": 172800.0,
                    "oldest_snapshot_at": "2026-08-13T20:17:36+00:00",
                    "newest_snapshot_at": "2026-08-22T19:30:51+00:00",
                    "oldest_snapshot_age_seconds": 774806.0,
                },
            }
        },
    }


def test_long_scheduled_tick_stays_pending_while_rule_progress_is_recent() -> None:
    payload = _progressing_payload(updated_at="2026-08-22T19:30:51+00:00")

    liveness = evaluate_scheduled_fetch_liveness(payload, NOW)
    effectiveness = evaluate_scheduled_fetch_effectiveness(payload, NOW)

    assert liveness.status == "pending"
    assert liveness.metrics["active_tick_age_seconds"] > 1800
    assert liveness.metrics["progress_current"] == 70
    assert liveness.metrics["progress_total"] == 276
    assert "70/276" in liveness.summary

    assert effectiveness.status == "pending"
    assert effectiveness.metrics["effectiveness_state"] == "refresh_in_progress"
    assert "70 fresh, 206 stale" in effectiveness.summary


def test_scheduled_tick_fails_when_rule_progress_stops_advancing() -> None:
    stale_age = int(MAX_ACTIVE_TICK_NO_PROGRESS_SECONDS) + 1
    payload = _progressing_payload(updated_at="2026-08-22T19:25:59+00:00")

    liveness = evaluate_scheduled_fetch_liveness(payload, NOW)
    effectiveness = evaluate_scheduled_fetch_effectiveness(payload, NOW)

    assert liveness.status == "fail"
    assert liveness.metrics["progress_age_seconds"] == stale_age
    assert "no rule-level progress" in liveness.summary

    assert effectiveness.status == "fail"
    assert effectiveness.metrics["effectiveness_state"] == "stale_snapshots"


def test_runtime_diagnostics_exposes_active_rule_fetch_operation_progress() -> None:
    operation_status.reset_operations_for_tests()
    try:
        handle = operation_status.start_operation(
            operation_type="jackett_fetch",
            label="Fetching Jackett releases",
            total=276,
        )
        operation_status.update_operation(handle.operation_id, current=70)

        progress = runtime_diagnostics._scheduled_fetch_operation_progress()

        assert progress is not None
        assert progress["current"] == 70
        assert progress["total"] == 276
        assert progress["percent"] == 25
        assert progress["updated_at"] is not None
    finally:
        operation_status.reset_operations_for_tests()
