from __future__ import annotations

import threading
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.services.functional_invariants import CHECKS, CheckResult
from app.services.runtime_diagnostics import runtime_diagnostics_payload

DEFAULT_FUNCTIONAL_WATCHDOG_INTERVAL_SECONDS = 300.0
FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD = 3


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


class FunctionalWatchdog:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        interval_seconds: float = DEFAULT_FUNCTIONAL_WATCHDOG_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._interval_seconds = max(30.0, float(interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._last_check_at: datetime | None = None
        self._checks: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = datetime.now(UTC)
        self._thread = threading.Thread(
            target=self._run_loop,
            name="functional-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is None:
            return
        self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))
        self._thread = None

    def run_once(self) -> None:
        session = self._session_factory()
        try:
            payload = runtime_diagnostics_payload(session)
            observed_at = datetime.now(UTC)
            results = [spec.evaluator(payload, observed_at) for spec in CHECKS.values()]
            self._record_results(results, observed_at=observed_at)
        finally:
            session.close()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            thread = self._thread
            checks = {check_id: dict(state) for check_id, state in self._checks.items()}
            incident_count = sum(1 for state in checks.values() if state.get("incident_active"))
            effectiveness_state = str(
                checks.get("F-02", {}).get("metrics", {}).get("effectiveness_state") or ""
            )
            if incident_count:
                overall_state = "unhealthy"
            elif any(state.get("status") == "fail" for state in checks.values()):
                overall_state = "warning"
            elif effectiveness_state in {"recovered_historical", "historical_error_unverified"}:
                overall_state = "degraded_historical"
            elif checks:
                overall_state = "healthy"
            else:
                overall_state = "starting"
            return {
                "created": True,
                "running": bool(thread is not None and thread.is_alive()),
                "interval_seconds": self._interval_seconds,
                "failure_threshold": FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD,
                "started_at": _iso(self._started_at),
                "last_check_at": _iso(self._last_check_at),
                "overall_state": overall_state,
                "incident_count": incident_count,
                "checks": checks,
            }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self._record_watchdog_error(exc)
            self._stop_event.wait(self._interval_seconds)

    def _record_results(self, results: list[CheckResult], *, observed_at: datetime) -> None:
        with self._state_lock:
            self._last_check_at = observed_at
            for result in results:
                previous = self._checks.get(result.check_id, {})
                previous_failures = int(previous.get("consecutive_failures") or 0)
                previous_first_failure = previous.get("first_failure_at")
                previous_incident = bool(previous.get("incident_active"))
                first_failure_at: str | None
                last_failure_at: str | None
                recovered_at: str | None
                if result.status == "fail":
                    consecutive_failures = previous_failures + 1
                    first_failure_at = (
                        str(previous_first_failure)
                        if previous_first_failure
                        else observed_at.isoformat()
                    )
                    last_failure_at = observed_at.isoformat()
                    recovered_at = None
                else:
                    consecutive_failures = 0
                    first_failure_at = None
                    previous_last_failure = previous.get("last_failure_at")
                    last_failure_at = (
                        str(previous_last_failure) if previous_last_failure else None
                    )
                    previous_recovered = previous.get("recovered_at")
                    recovered_at = (
                        observed_at.isoformat()
                        if previous_failures > 0 or previous_incident
                        else (str(previous_recovered) if previous_recovered else None)
                    )
                incident_active = (
                    result.status == "fail"
                    and consecutive_failures >= FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD
                )
                state = asdict(result)
                state.update(
                    {
                        "observed_at": observed_at.isoformat(),
                        "consecutive_failures": consecutive_failures,
                        "first_failure_at": first_failure_at,
                        "last_failure_at": last_failure_at,
                        "recovered_at": recovered_at,
                        "incident_active": incident_active,
                    }
                )
                self._checks[result.check_id] = state

    def _record_watchdog_error(self, exc: Exception) -> None:
        observed_at = datetime.now(UTC)
        synthetic = CheckResult(
            check_id="WATCHDOG",
            title="Functional watchdog",
            status="fail",
            summary="Functional watchdog iteration failed.",
            metrics={"error_type": type(exc).__name__},
        )
        self._record_results([synthetic], observed_at=observed_at)


_watchdog: FunctionalWatchdog | None = None


def start_functional_watchdog(
    *,
    session_factory: sessionmaker[Session],
    interval_seconds: float = DEFAULT_FUNCTIONAL_WATCHDOG_INTERVAL_SECONDS,
) -> None:
    global _watchdog
    if _watchdog is None:
        _watchdog = FunctionalWatchdog(
            session_factory=session_factory,
            interval_seconds=interval_seconds,
        )
    _watchdog.start()


def stop_functional_watchdog() -> None:
    if _watchdog is None:
        return
    _watchdog.stop()


def functional_watchdog_status() -> dict[str, Any]:
    if _watchdog is None:
        return {
            "created": False,
            "running": False,
            "interval_seconds": DEFAULT_FUNCTIONAL_WATCHDOG_INTERVAL_SECONDS,
            "failure_threshold": FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD,
            "started_at": None,
            "last_check_at": None,
            "overall_state": "not_started",
            "incident_count": 0,
            "checks": {},
        }
    return _watchdog.status()
