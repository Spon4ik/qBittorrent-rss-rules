from __future__ import annotations

import json
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


def test_f01_treats_active_due_work_as_pending_until_it_settles() -> None:
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

    assert result.status == "pending"
    assert "awaiting a settled result" in result.summary


def test_f01_fails_for_excessively_long_active_tick() -> None:
    result = functional_qa.evaluate_scheduled_fetch_liveness(
        _payload(
            tick_in_progress=True,
            started_at="2026-08-21T12:20:00+00:00",
            next_run_at="2026-08-21T12:00:00+00:00",
            overdue_seconds=3600.0,
        ),
        NOW,
    )

    assert result.status == "fail"
    assert "tick has been running" in result.summary


def test_runner_rechecks_pending_state_until_it_settles(tmp_path, monkeypatch) -> None:
    payloads = iter(
        [
            _payload(
                tick_in_progress=True,
                started_at=datetime.now(UTC).isoformat(),
                next_run_at="2026-08-21T12:58:00+00:00",
                overdue_seconds=120.0,
            ),
            _payload(
                completed_at=datetime.now(UTC).isoformat(),
                started_at=datetime.now(UTC).isoformat(),
                next_run_at="2099-08-22T12:00:00+00:00",
                overdue_seconds=0.0,
                tick_result="not_due",
            ),
        ]
    )
    calls = 0

    def fake_fetch_json(url: str, *, timeout_seconds: float):
        nonlocal calls
        calls += 1
        return next(payloads)

    monkeypatch.setattr(functional_qa, "_fetch_json", fake_fetch_json)

    exit_code = functional_qa.run(
        base_url="http://runtime.test",
        check_id="F-01",
        suite=None,
        timeout_seconds=1.0,
        output_dir=tmp_path,
        settle_timeout_seconds=1.0,
        poll_seconds=0.0,
    )

    assert exit_code == 0
    assert calls == 2
    report = json.loads((tmp_path / "functional-qa-report.json").read_text(encoding="utf-8"))
    assert report["attempts"] == 2
    assert report["results"][0]["status"] == "pass"


def test_observe_only_preserves_failure_evidence_without_blocking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        functional_qa,
        "_fetch_json",
        lambda url, timeout_seconds: _payload(runtime_enabled=False, running=False),
    )

    exit_code = functional_qa.run(
        base_url="http://runtime.test",
        check_id="F-01",
        suite=None,
        timeout_seconds=1.0,
        output_dir=tmp_path,
        settle_timeout_seconds=0.0,
        poll_seconds=0.0,
        observe_only=True,
    )

    assert exit_code == 0
    report = json.loads((tmp_path / "functional-qa-report.json").read_text(encoding="utf-8"))
    assert report["observe_only"] is True
    assert report["results"][0]["status"] == "fail"


def test_backend_finalizer_captures_predeploy_state_then_gates_postdeploy_suite() -> None:
    finalizer = (PROJECT_DIR / "Finalize Backend.cmd").read_text(encoding="utf-8")

    assert "Capturing pre-deploy functional baseline" in finalizer
    assert "--observe-only --settle-timeout 0" in finalizer
    assert 'call "scripts\\functional_qa.bat" --suite core' in finalizer
    assert "deployed runtime is current, but functional runtime QA FAILED" in finalizer
    assert finalizer.index("Capturing pre-deploy functional baseline") < finalizer.index(
        "Rebuilding and validating Docker"
    )
