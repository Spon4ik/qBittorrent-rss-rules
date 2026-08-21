from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.services.rule_fetch_ops import run_due_scheduled_fetch


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


class RuleFetchScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval_seconds = max(5.0, float(poll_interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._tick_in_progress = False
        self._last_tick_started_at: datetime | None = None
        self._last_tick_completed_at: datetime | None = None
        self._last_tick_result = "never"
        self._last_tick_error_type: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = datetime.now(UTC)
        self._thread = threading.Thread(
            target=self._run_loop,
            name="rule-fetch-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is None:
            return
        self._thread.join(timeout=max(1.0, self._poll_interval_seconds + 1.0))
        self._thread = None

    def run_once(self) -> None:
        self._tick()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            thread = self._thread
            return {
                "created": True,
                "running": bool(thread is not None and thread.is_alive()),
                "poll_interval_seconds": self._poll_interval_seconds,
                "started_at": _iso(self._started_at),
                "tick_in_progress": self._tick_in_progress,
                "last_tick_started_at": _iso(self._last_tick_started_at),
                "last_tick_completed_at": _iso(self._last_tick_completed_at),
                "last_tick_result": self._last_tick_result,
                "last_tick_error_type": self._last_tick_error_type,
            }

    def _mark_tick_started(self) -> None:
        with self._state_lock:
            self._tick_in_progress = True
            self._last_tick_started_at = datetime.now(UTC)

    def _mark_tick_completed(self, *, result: str, error_type: str | None = None) -> None:
        with self._state_lock:
            self._tick_in_progress = False
            self._last_tick_completed_at = datetime.now(UTC)
            self._last_tick_result = result
            self._last_tick_error_type = error_type

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._poll_interval_seconds)

    def _tick(self) -> None:
        self._mark_tick_started()
        session = self._session_factory()
        try:
            result = run_due_scheduled_fetch(session)
        except Exception as exc:
            # Scheduler must stay alive, but deterministic diagnostics must expose the failure.
            session.rollback()
            self._mark_tick_completed(result="error", error_type=type(exc).__name__)
        else:
            batch_status = str((result or {}).get("status") or "").strip()
            self._mark_tick_completed(
                result=f"run:{batch_status or 'unknown'}" if result is not None else "not_due"
            )
        finally:
            session.close()


_scheduler: RuleFetchScheduler | None = None


def start_rule_fetch_scheduler(
    *,
    session_factory: sessionmaker[Session],
    poll_interval_seconds: float,
) -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = RuleFetchScheduler(
            session_factory=session_factory,
            poll_interval_seconds=poll_interval_seconds,
        )
    _scheduler.start()


def stop_rule_fetch_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.stop()


def run_rule_fetch_scheduler_once() -> None:
    if _scheduler is None:
        return
    _scheduler.run_once()


def rule_fetch_scheduler_status() -> dict[str, Any]:
    if _scheduler is None:
        return {
            "created": False,
            "running": False,
            "poll_interval_seconds": None,
            "started_at": None,
            "tick_in_progress": False,
            "last_tick_started_at": None,
            "last_tick_completed_at": None,
            "last_tick_result": "never",
            "last_tick_error_type": None,
        }
    return _scheduler.status()
