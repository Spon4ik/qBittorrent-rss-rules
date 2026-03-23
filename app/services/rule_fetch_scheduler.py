from __future__ import annotations

import threading

from sqlalchemy.orm import Session, sessionmaker

from app.services.rule_fetch_ops import run_due_scheduled_fetch


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

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
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

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            self._stop_event.wait(self._poll_interval_seconds)

    def _tick(self) -> None:
        session = self._session_factory()
        try:
            run_due_scheduled_fetch(session)
        except Exception:
            # Scheduler must never crash the app runtime loop.
            session.rollback()
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
