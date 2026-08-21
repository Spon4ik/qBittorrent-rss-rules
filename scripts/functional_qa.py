from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.services import functional_invariants as _functional_invariants  # noqa: E402

CHECKS = _functional_invariants.CHECKS
SUITES = _functional_invariants.SUITES
CheckResult = _functional_invariants.CheckResult
CheckSpec = _functional_invariants.CheckSpec

# Preserve the CLI module's existing evaluator seam for tests and external callers while
# keeping the canonical implementation in app.services.functional_invariants.
evaluate_scheduled_fetch_effectiveness = (
    _functional_invariants.evaluate_scheduled_fetch_effectiveness
)
evaluate_scheduled_fetch_liveness = _functional_invariants.evaluate_scheduled_fetch_liveness

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_SETTLE_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_SECONDS = 5.0


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
