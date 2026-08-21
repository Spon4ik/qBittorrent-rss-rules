from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

MAX_ACTIVE_TICK_SECONDS = 1800.0
KNOWN_RECOVERABLE_READINESS_ERRORS = frozenset(
    {
        "Jackett app search is not configured in Settings.",
    }
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    title: str
    status: str
    summary: str
    metrics: dict[str, Any]
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class CheckSpec:
    check_id: str
    title: str
    evaluator: Callable[[dict[str, Any], datetime], CheckResult]


def parse_datetime(value: object | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: object | None, *, default: float = 0.0) -> float:
    try:
        return float(cast(Any, value)) if value is not None else default
    except (TypeError, ValueError):
        return default


def _mapping(value: object | None) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _scheduled_component(payload: dict[str, Any]) -> dict[str, Any] | None:
    components = _mapping(payload.get("components"))
    component = components.get("scheduled_rule_fetch")
    return cast(dict[str, Any], component) if isinstance(component, dict) else None


def evaluate_scheduled_fetch_liveness(
    payload: dict[str, Any],
    now: datetime | None = None,
) -> CheckResult:
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    component = _scheduled_component(payload)
    if component is None:
        return CheckResult(
            check_id="F-01",
            title="Scheduled fetch liveness",
            status="fail",
            summary="Runtime diagnostics did not include scheduled_rule_fetch state.",
            metrics={},
        )

    schedule = _mapping(component.get("schedule"))
    scheduler = _mapping(component.get("scheduler"))
    schedule_enabled = bool(schedule.get("enabled"))
    runtime_enabled = bool(component.get("runtime_enabled"))
    scheduler_running = bool(scheduler.get("running"))
    tick_in_progress = bool(scheduler.get("tick_in_progress"))
    poll_interval = max(0.0, _number(scheduler.get("poll_interval_seconds")))
    overdue_seconds = max(0.0, _number(component.get("overdue_seconds")))
    last_tick_completed_at = parse_datetime(scheduler.get("last_tick_completed_at"))
    last_tick_started_at = parse_datetime(scheduler.get("last_tick_started_at"))
    last_tick_result = str(scheduler.get("last_tick_result") or "").strip()
    last_tick_error_type = str(scheduler.get("last_tick_error_type") or "").strip()
    next_run_at = parse_datetime(schedule.get("next_run_at"))

    tick_age_seconds = (
        max(0.0, (observed_at - last_tick_completed_at).total_seconds())
        if last_tick_completed_at is not None
        else None
    )
    active_tick_age_seconds = (
        max(0.0, (observed_at - last_tick_started_at).total_seconds())
        if tick_in_progress and last_tick_started_at is not None
        else None
    )
    metrics = {
        "schedule_enabled": schedule_enabled,
        "runtime_enabled": runtime_enabled,
        "interval_minutes": schedule.get("interval_minutes"),
        "last_run_at": schedule.get("last_run_at"),
        "next_run_at": schedule.get("next_run_at"),
        "overdue_seconds": round(overdue_seconds, 3),
        "scheduler_created": bool(scheduler.get("created")),
        "scheduler_running": scheduler_running,
        "scheduler_started_at": scheduler.get("started_at"),
        "poll_interval_seconds": poll_interval or None,
        "tick_in_progress": tick_in_progress,
        "last_tick_started_at": scheduler.get("last_tick_started_at"),
        "last_tick_completed_at": scheduler.get("last_tick_completed_at"),
        "last_tick_result": last_tick_result,
        "last_tick_error_type": last_tick_error_type or None,
        "tick_age_seconds": round(tick_age_seconds, 3) if tick_age_seconds is not None else None,
        "active_tick_age_seconds": (
            round(active_tick_age_seconds, 3) if active_tick_age_seconds is not None else None
        ),
    }

    if not schedule_enabled:
        return CheckResult(
            check_id="F-01",
            title="Scheduled fetch liveness",
            status="skip",
            summary="Scheduled fetch is intentionally disabled.",
            metrics=metrics,
        )

    failures: list[str] = []
    if not runtime_enabled:
        failures.append("persisted schedule is enabled but the runtime scheduler feature is disabled")
    if not scheduler_running:
        failures.append("runtime scheduler thread is not running")

    if tick_in_progress:
        if last_tick_started_at is None:
            failures.append("scheduler reports a tick in progress without a start timestamp")
        elif active_tick_age_seconds is not None and active_tick_age_seconds > MAX_ACTIVE_TICK_SECONDS:
            failures.append(
                f"scheduler tick has been running for {active_tick_age_seconds:.0f}s "
                f"(limit {MAX_ACTIVE_TICK_SECONDS:.0f}s)"
            )
        if failures:
            return CheckResult(
                check_id="F-01",
                title="Scheduled fetch liveness",
                status="fail",
                summary="; ".join(failures) + ".",
                metrics=metrics,
            )
        return CheckResult(
            check_id="F-01",
            title="Scheduled fetch liveness",
            status="pending",
            summary="Scheduler is executing a tick; awaiting a settled result.",
            metrics=metrics,
        )

    if last_tick_result == "error" or last_tick_error_type:
        failures.append(
            "last scheduler tick failed"
            + (f" with {last_tick_error_type}" if last_tick_error_type else "")
        )
    if last_tick_completed_at is None:
        failures.append("scheduler has no completed tick evidence")
    else:
        max_tick_age = max(120.0, poll_interval * 4.0)
        if tick_age_seconds is not None and tick_age_seconds > max_tick_age:
            failures.append(
                f"last scheduler tick is stale ({tick_age_seconds:.0f}s old; limit {max_tick_age:.0f}s)"
            )

    overdue_grace = max(60.0, poll_interval * 2.0)
    if overdue_seconds > overdue_grace:
        failures.append(f"next scheduled run is overdue by {overdue_seconds:.0f}s")
    elif next_run_at is None:
        failures.append("enabled schedule has no next_run_at")

    if failures:
        return CheckResult(
            check_id="F-01",
            title="Scheduled fetch liveness",
            status="fail",
            summary="; ".join(failures) + ".",
            metrics=metrics,
        )

    return CheckResult(
        check_id="F-01",
        title="Scheduled fetch liveness",
        status="pass",
        summary="Scheduler is alive, ticking recently, and the next run is not overdue.",
        metrics=metrics,
    )


def evaluate_scheduled_fetch_effectiveness(
    payload: dict[str, Any],
    now: datetime | None = None,
) -> CheckResult:
    del now
    component = _scheduled_component(payload)
    if component is None:
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="fail",
            summary="Runtime diagnostics did not include scheduled_rule_fetch state.",
            metrics={},
        )

    schedule = _mapping(component.get("schedule"))
    readiness = _mapping(component.get("readiness"))
    runtime = _mapping(payload.get("runtime"))
    schedule_enabled = bool(schedule.get("enabled"))
    jackett_ready = bool(readiness.get("jackett_app_ready"))
    last_status = str(schedule.get("last_status") or "idle").strip().casefold() or "idle"
    last_message = str(schedule.get("last_message") or "").strip()
    last_run_at = parse_datetime(schedule.get("last_run_at"))
    runtime_started_at = parse_datetime(runtime.get("started_at"))
    last_run_current_runtime = bool(
        last_run_at is not None
        and runtime_started_at is not None
        and last_run_at >= runtime_started_at
    )
    historical_run = bool(
        last_run_at is not None
        and runtime_started_at is not None
        and last_run_at < runtime_started_at
    )

    metrics: dict[str, Any] = {
        "schedule_enabled": schedule_enabled,
        "jackett_app_ready": jackett_ready,
        "last_status": last_status,
        "last_run_at": schedule.get("last_run_at"),
        "runtime_instance_id": runtime.get("instance_id"),
        "runtime_started_at": runtime.get("started_at"),
        "last_run_current_runtime": last_run_current_runtime,
        "historical_run": historical_run,
        "effectiveness_state": "unknown",
    }

    if not schedule_enabled:
        metrics["effectiveness_state"] = "disabled"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="skip",
            summary="Scheduled fetch is intentionally disabled.",
            metrics=metrics,
        )

    if not jackett_ready:
        metrics["effectiveness_state"] = "unhealthy_readiness"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="fail",
            summary="Scheduled fetch is enabled but Jackett app search is not currently ready.",
            metrics=metrics,
        )

    if last_status == "error" and last_run_current_runtime:
        metrics["effectiveness_state"] = "unhealthy_current_run"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="fail",
            summary="The current runtime's latest scheduled fetch completed with error status.",
            metrics=metrics,
        )

    if last_status == "error" and historical_run:
        if last_message in KNOWN_RECOVERABLE_READINESS_ERRORS:
            metrics["effectiveness_state"] = "recovered_historical"
            return CheckResult(
                check_id="F-02",
                title="Scheduled fetch effectiveness",
                status="pass",
                summary=(
                    "A previous runtime reported a Jackett-readiness error, but the current "
                    "runtime is ready and has not reproduced it."
                ),
                metrics=metrics,
            )
        metrics["effectiveness_state"] = "historical_error_unverified"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="pass",
            summary=(
                "The latest scheduled-fetch error belongs to a previous runtime; current "
                "prerequisites are ready but the historical failure is not automatically cleared."
            ),
            metrics=metrics,
        )

    if last_status == "partial":
        metrics["effectiveness_state"] = "partial"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="pass",
            summary="The latest scheduled fetch completed partially; the scheduler remains effective.",
            metrics=metrics,
        )

    if last_run_at is None:
        metrics["effectiveness_state"] = "ready_not_run"
        return CheckResult(
            check_id="F-02",
            title="Scheduled fetch effectiveness",
            status="pass",
            summary="Scheduled fetch prerequisites are ready; no scheduled run has completed yet.",
            metrics=metrics,
        )

    metrics["effectiveness_state"] = "healthy"
    return CheckResult(
        check_id="F-02",
        title="Scheduled fetch effectiveness",
        status="pass",
        summary="Scheduled fetch prerequisites are ready and no current-runtime failure is present.",
        metrics=metrics,
    )


def evaluate_unhandled_api_errors(
    payload: dict[str, Any],
    now: datetime | None = None,
) -> CheckResult:
    del now
    components = _mapping(payload.get("components"))
    api_component = _mapping(components.get("api"))
    if "unhandled_errors" not in api_component:
        return CheckResult(
            check_id="F-03",
            title="Unhandled API errors",
            status="fail",
            summary="Runtime diagnostics did not include unhandled API error telemetry.",
            metrics={},
        )

    error_status = _mapping(api_component.get("unhandled_errors"))
    last_error = _mapping(error_status.get("last"))
    count = max(0, int(_number(error_status.get("count"))))
    metrics: dict[str, Any] = {
        "unhandled_error_count": count,
        "last_error_id": last_error.get("id"),
        "last_error_at": last_error.get("occurred_at"),
        "last_error_method": last_error.get("method"),
        "last_error_path": last_error.get("path"),
        "last_error_type": last_error.get("error_type"),
    }

    if count > 0:
        method = str(last_error.get("method") or "API").strip()
        path = str(last_error.get("path") or "request").strip()
        error_type = str(last_error.get("error_type") or "Exception").strip()
        error_id = str(last_error.get("id") or "unknown").strip()
        return CheckResult(
            check_id="F-03",
            title="Unhandled API errors",
            status="fail",
            summary=(
                f"Current runtime recorded {count} unhandled API exception(s); latest "
                f"{method} {path} failed with {error_type} ({error_id})."
            ),
            metrics=metrics,
        )

    return CheckResult(
        check_id="F-03",
        title="Unhandled API errors",
        status="pass",
        summary="Current runtime has recorded no unhandled API exceptions.",
        metrics=metrics,
    )


CHECKS: dict[str, CheckSpec] = {
    "F-01": CheckSpec(
        check_id="F-01",
        title="Scheduled fetch liveness",
        evaluator=evaluate_scheduled_fetch_liveness,
    ),
    "F-02": CheckSpec(
        check_id="F-02",
        title="Scheduled fetch effectiveness",
        evaluator=evaluate_scheduled_fetch_effectiveness,
    ),
    "F-03": CheckSpec(
        check_id="F-03",
        title="Unhandled API errors",
        evaluator=evaluate_unhandled_api_errors,
    ),
}
SUITES: dict[str, tuple[str, ...]] = {"core": ("F-01", "F-02", "F-03")}
