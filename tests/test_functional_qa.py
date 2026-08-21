from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import functional_qa  # noqa: E402

NOW = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


def _payload(
    *,
    schedule_enabled: bool = True,
    runtime_enabled: bool = True,
    running: bool = True,
    tick_in_progress: bool = False,
    completed_at: str | None = "2026-08-21T12:59:30+00:00",
    started_at: str | None = "2026-08-21T12:59:29+00:00",
    tick_result: str = "not_due",
    error_type: str | None = None,
    next_run_at: str | None = "2026-08-22T12:00:00+00:00",
    overdue_seconds: float = 0.0,
) -> dict[str, object]:
    return {
        "components": {
            "scheduled_rule_fetch": {
                "runtime_enabled": runtime_enabled,
                "overdue_seconds": overdue_seconds,
                "schedule": {
                    "enabled": schedule_enabled,
                    "interval_minutes": 1440,
                    "last_run_at": "2026-08-21T12:00:00+00:00",
                    "next_run_at": next_run_at,
                },
                "scheduler": {
                    "created": running,
                    "running": running,
                    "poll_interval_seconds": 30,
                    "tick_in_progress": tick_in_progress,
                    "last_tick_started_at": started_at,
                    "last_tick_completed_at": completed_at,
                    "last_tick_result": tick_result,
                    "last_tick_error_type": error_type,
                },
            }
        }
    }


def test_f01_passes_for_live_recent_scheduler_with_future_run() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(_payload(), NOW)

    assert result.status == "pass"
    assert result.metrics["scheduler_running"] is True
    assert result.metrics["overdue_seconds"] == 0.0


def test_f01_skips_when_schedule_is_intentionally_disabled() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(schedule_enabled=False, runtime_enabled=False, running=False),
        NOW,
    )

    assert result.status == "skip"


def test_f01_fails_when_persisted_schedule_is_enabled_but_runtime_scheduler_is_disabled() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(runtime_enabled=False, running=False),
        NOW,
    )

    assert result.status == "fail"
    assert "runtime scheduler feature is disabled" in result.summary
    assert "thread is not running" in result.summary


def test_f01_fails_for_stale_tick_and_overdue_schedule() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(
            completed_at="2026-08-21T12:50:00+00:00",
            next_run_at="2026-08-14T20:42:48+00:00",
            overdue_seconds=571032.0,
        ),
        NOW,
    )

    assert result.status == "fail"
    assert "last scheduler tick is stale" in result.summary
    assert "next scheduled run is overdue" in result.summary


def test_f01_exposes_swallowed_scheduler_exception() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(tick_result="error", error_type="OperationalError"),
        NOW,
    )

    assert result.status == "fail"
    assert "OperationalError" in result.summary


def test_f01_allows_due_work_while_scheduler_tick_is_actively_running() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(
            tick_in_progress=True,
            completed_at="2026-08-21T12:40:00+00:00",
            started_at="2026-08-21T12:59:00+00:00",
            next_run_at="2026-08-21T12:58:00+00:00",
            overdue_seconds=120.0,
        ),
        NOW,
    )

    assert result.status == "pass"
    assert "currently executing" in result.summary


def test_backend_finalizer_runs_core_functional_suite_after_deployment() -> None:
    finalizer = (PROJECT_DIR / "Finalize Backend.cmd").read_text(encoding="utf-8")

    assert 'call "scripts\\functional_qa.bat" --suite core' in finalizer
    assert "deployed runtime is current, but functional runtime QA FAILED" in finalizer
