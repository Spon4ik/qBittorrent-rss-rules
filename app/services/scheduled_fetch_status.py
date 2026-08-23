from __future__ import annotations

from typing import Any

_HISTORICAL_FAILURE_STATUSES = frozenset({"partial", "error"})


def _count(mapping: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(mapping.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def current_scheduled_fetch_state(
    *,
    schedule: dict[str, Any],
    runtime_enabled: bool,
    jackett_ready: bool,
    snapshot_freshness: dict[str, Any],
    scheduler: dict[str, Any] | None = None,
    operation_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive current operational health without rewriting historical run evidence."""
    historical_status = str(schedule.get("last_status") or "idle").strip().casefold() or "idle"
    total = _count(snapshot_freshness, "total_rules")
    fresh = _count(snapshot_freshness, "fresh_snapshots")
    stale = _count(snapshot_freshness, "stale_snapshots")
    missing = _count(snapshot_freshness, "missing_snapshots")
    pending = _count(snapshot_freshness, "pending_snapshots")
    scheduler = scheduler or {}
    operation_progress = operation_progress or {}

    status: str
    summary: str
    if not bool(schedule.get("enabled")):
        status = "disabled"
        summary = "Scheduled fetch is disabled."
    elif not runtime_enabled:
        status = "unavailable"
        summary = "Scheduled fetch is enabled, but the runtime scheduler is disabled."
    elif not jackett_ready:
        status = "blocked"
        summary = "Scheduled fetch is enabled, but Jackett search is not currently ready."
    elif bool(scheduler.get("tick_in_progress")):
        status = "running"
        current = _count(operation_progress, "current")
        progress_total = _count(operation_progress, "total")
        if progress_total > 0:
            summary = f"Scheduled refresh is running ({current}/{progress_total} rule(s))."
        else:
            summary = "Scheduled refresh is running."
    elif stale > 0 or missing > 0:
        status = "degraded"
        summary = (
            "Scheduled scope is outside its freshness target: "
            f"{stale} stale, {missing} missing, {pending} pending snapshot(s)."
        )
    elif pending > 0:
        status = "pending"
        summary = f"Scheduled scope has {pending} new rule snapshot(s) awaiting first refresh."
    elif total == 0:
        status = "healthy"
        summary = "Scheduled scope is healthy; there are currently no rules in scope."
    elif fresh >= total:
        status = "healthy"
        summary = f"All {fresh}/{total} scheduled-scope rule snapshots are within freshness SLA."
    else:
        status = "degraded"
        summary = (
            "Scheduled scope freshness is incomplete: "
            f"{fresh}/{total} rule snapshots are confirmed fresh."
        )

    historical_failure_superseded = (
        status == "healthy" and historical_status in _HISTORICAL_FAILURE_STATUSES
    )
    return {
        "status": status,
        "summary": summary,
        "historical_status": historical_status,
        "historical_failure_superseded": historical_failure_superseded,
        "total_rules": total,
        "fresh_snapshots": fresh,
        "stale_snapshots": stale,
        "missing_snapshots": missing,
        "pending_snapshots": pending,
    }
