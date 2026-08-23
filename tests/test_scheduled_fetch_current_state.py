from __future__ import annotations

from app.services.scheduled_fetch_status import current_scheduled_fetch_state


def _schedule(last_status: str = "ok", *, enabled: bool = True) -> dict[str, object]:
    return {
        "enabled": enabled,
        "last_status": last_status,
        "last_message": "historical detail",
    }


def _freshness(
    *,
    total: int = 3,
    fresh: int = 3,
    stale: int = 0,
    missing: int = 0,
    pending: int = 0,
) -> dict[str, object]:
    return {
        "total_rules": total,
        "fresh_snapshots": fresh,
        "stale_snapshots": stale,
        "missing_snapshots": missing,
        "pending_snapshots": pending,
    }


def test_historical_partial_becomes_recovered_when_current_scope_is_fresh() -> None:
    state = current_scheduled_fetch_state(
        schedule=_schedule("partial"),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(total=276, fresh=276),
    )

    assert state["status"] == "healthy"
    assert state["recovered_from_last_run"] is True
    assert state["historical_status"] == "partial"
    assert state["summary"] == "All 276/276 scheduled-scope rule snapshots are fresh."


def test_historical_error_becomes_recovered_only_after_current_scope_is_fresh() -> None:
    degraded = current_scheduled_fetch_state(
        schedule=_schedule("error"),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(total=3, fresh=2, stale=1),
    )
    healthy = current_scheduled_fetch_state(
        schedule=_schedule("error"),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(),
    )

    assert degraded["status"] == "degraded"
    assert degraded["recovered_from_last_run"] is False
    assert healthy["status"] == "healthy"
    assert healthy["recovered_from_last_run"] is True


def test_pending_new_rules_do_not_clear_historical_failure() -> None:
    state = current_scheduled_fetch_state(
        schedule=_schedule("partial"),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(total=3, fresh=2, pending=1),
    )

    assert state["status"] == "pending"
    assert state["recovered_from_last_run"] is False


def test_active_refresh_reports_running_before_stale_state() -> None:
    state = current_scheduled_fetch_state(
        schedule=_schedule("partial"),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(total=3, fresh=2, stale=1),
        scheduler={"tick_in_progress": True},
        operation_progress={"current": 2, "total": 3},
    )

    assert state["status"] == "running"
    assert state["summary"] == "Scheduled refresh is running (2/3 rule(s))."
    assert state["recovered_from_last_run"] is False


def test_readiness_and_runtime_failures_take_precedence_over_fresh_snapshots() -> None:
    no_runtime = current_scheduled_fetch_state(
        schedule=_schedule("partial"),
        runtime_enabled=False,
        jackett_ready=True,
        snapshot_freshness=_freshness(),
    )
    no_jackett = current_scheduled_fetch_state(
        schedule=_schedule("partial"),
        runtime_enabled=True,
        jackett_ready=False,
        snapshot_freshness=_freshness(),
    )

    assert no_runtime["status"] == "unavailable"
    assert no_runtime["recovered_from_last_run"] is False
    assert no_jackett["status"] == "blocked"
    assert no_jackett["recovered_from_last_run"] is False


def test_disabled_schedule_is_not_reported_as_recovered() -> None:
    state = current_scheduled_fetch_state(
        schedule=_schedule("partial", enabled=False),
        runtime_enabled=True,
        jackett_ready=True,
        snapshot_freshness=_freshness(),
    )

    assert state["status"] == "disabled"
    assert state["recovered_from_last_run"] is False
