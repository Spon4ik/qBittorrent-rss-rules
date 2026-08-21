from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_SETTLE_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_SECONDS = 5.0
MAX_ACTIVE_TICK_SECONDS = 1800.0


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


def _parse_datetime(value: object | None) -> datetime | None:
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
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def evaluate_scheduled_fetch_liveness(
    payload: dict[str, Any],
    now: datetime | None = None,
) -> CheckResult:
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    components = payload.get("components") if isinstance(payload, dict) else None
    component = components.get("scheduled_rule_fetch") if isinstance(components, dict) else None
    if not isinstance(component, dict):
        return CheckResult(
            check_id="F-01",
            title="Scheduled fetch liveness",
            status="fail",
            summary="Runtime diagnostics did not include scheduled_rule_fetch state.",
            metrics={},
        )

    schedule = component.get("schedule") if isinstance(component.get("schedule"), dict) else {}
    scheduler = component.get("scheduler") if isinstance(component.get("scheduler"), dict) else {}
    schedule_enabled = bool(schedule.get("enabled"))
    runtime_enabled = bool(component.get("runtime_enabled"))
    scheduler_running = bool(scheduler.get("running"))
    tick_in_progress = bool(scheduler.get("tick_in_progress"))
    poll_interval = max(0.0, _number(scheduler.get("poll_interval_seconds")))
    overdue_seconds = max(0.0, _number(component.get("overdue_seconds")))
    last_tick_completed_at = _parse_datetime(scheduler.get("last_tick_completed_at"))
    last_tick_started_at = _parse_datetime(scheduler.get("last_tick_started_at"))
    last_tick_result = str(scheduler.get("last_tick_result") or "").strip()
    last_tick_error_type = str(scheduler.get("last_tick_error_type") or "").strip()
    next_run_at = _parse_datetime(schedule.get("next_run_at"))

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


CHECKS: dict[str, CheckSpec] = {
    "F-01": CheckSpec(
        check_id="F-01",
        title="Scheduled fetch liveness",
        evaluator=evaluate_scheduled_fetch_liveness,
    )
}
SUITES: dict[str, tuple[str, ...]] = {"core": ("F-01",)}


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - local QA URL
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Timed out reading {url} after {timeout_seconds:g}s") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach {url}: {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected payload type from {url}")
    return payload


def _selected_checks(*, check_id: str | None, suite: str | None) -> list[CheckSpec]:
    if check_id:
        spec = CHECKS.get(check_id.upper())
        if spec is None:
            raise ValueError(f"Unknown functional check: {check_id}")
        return [spec]
    selected_suite = suite or "core"
    check_ids = SUITES.get(selected_suite)
    if check_ids is None:
        raise ValueError(f"Unknown functional suite: {selected_suite}")
    return [CHECKS[item] for item in check_ids]


def _default_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_DIR / "logs" / "qa" / f"functional-{stamp}"


def _evaluate_specs(
    specs: list[CheckSpec],
    *,
    diagnostics_url: str,
    timeout_seconds: float,
) -> list[CheckResult]:
    observed_at = datetime.now(UTC)
    try:
        payload = _fetch_json(diagnostics_url, timeout_seconds=timeout_seconds)
    except RuntimeError as exc:
        return [
            CheckResult(
                check_id=spec.check_id,
                title=spec.title,
                status="fail",
                summary=str(exc),
                metrics={"diagnostics_url": diagnostics_url},
            )
            for spec in specs
        ]

    results: list[CheckResult] = []
    for spec in specs:
        check_started = time.perf_counter()
        result = spec.evaluator(payload, observed_at)
        results.append(replace(result, duration_ms=int((time.perf_counter() - check_started) * 1000)))
    return results


def _timeout_pending_results(
    results: list[CheckResult],
    *,
    settle_timeout_seconds: float,
) -> list[CheckResult]:
    return [
        replace(
            item,
            status="fail",
            summary=(
                f"{item.summary.rstrip('.')} did not settle within "
                f"{settle_timeout_seconds:.0f}s."
            ),
        )
        if item.status == "pending"
        else item
        for item in results
    ]


def run(
    *,
    base_url: str,
    check_id: str | None,
    suite: str | None,
    timeout_seconds: float,
    output_dir: Path | None,
    settle_timeout_seconds: float = DEFAULT_SETTLE_TIMEOUT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    observe_only: bool = False,
) -> int:
    specs = _selected_checks(check_id=check_id, suite=suite)
    diagnostics_url = f"{base_url.rstrip('/')}/api/diagnostics/runtime"
    started = time.perf_counter()
    settle_started = time.monotonic()
    attempts = 0

    while True:
        attempts += 1
        results = _evaluate_specs(
            specs,
            diagnostics_url=diagnostics_url,
            timeout_seconds=timeout_seconds,
        )
        if not any(item.status == "pending" for item in results):
            break
        if observe_only or settle_timeout_seconds <= 0:
            break
        elapsed = time.monotonic() - settle_started
        if elapsed >= settle_timeout_seconds:
            results = _timeout_pending_results(
                results,
                settle_timeout_seconds=settle_timeout_seconds,
            )
            break
        remaining = settle_timeout_seconds - elapsed
        time.sleep(min(max(0.0, poll_seconds), remaining))

    destination = output_dir or _default_output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / "functional-qa-report.json"
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "diagnostics_url": diagnostics_url,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "attempts": attempts,
        "observe_only": observe_only,
        "settle_timeout_seconds": settle_timeout_seconds,
        "results": [asdict(item) for item in results],
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for result in results:
        print(f"{result.status.upper()} {result.check_id}: {result.summary}")
        if result.status in {"fail", "pending"} and result.metrics:
            compact = json.dumps(result.metrics, sort_keys=True, separators=(",", ":"))
            print(f"  metrics: {compact}")
    print(f"Saved functional QA report: {report_path}")
    if observe_only:
        return 0
    return 1 if any(item.status in {"fail", "pending"} for item in results) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic deployed-runtime functional invariants."
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--check", help="Run one functional invariant, for example F-01.")
    selection.add_argument("--suite", choices=sorted(SUITES), help="Run a maintained functional suite.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--settle-timeout", type=float, default=DEFAULT_SETTLE_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="Capture and report invariant state without failing the caller.",
    )
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(
            base_url=args.base_url,
            check_id=args.check,
            suite=args.suite,
            timeout_seconds=max(0.1, args.timeout),
            output_dir=args.output_dir,
            settle_timeout_seconds=max(0.0, args.settle_timeout),
            poll_seconds=max(0.0, args.poll_seconds),
            observe_only=bool(args.observe_only),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
