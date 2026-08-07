from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Rule, SyncStatus
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.settings_service import SettingsService
from app.services.sync_queue import enqueue_rule_sync

LOGGER = logging.getLogger(__name__)

_TRANSIENT_ERROR_MARKERS = (
    "unable to connect",
    "connection refused",
    "connection reset",
    "connection aborted",
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "timed out",
    "timeout",
)


def _is_transient_qb_error(message: str | None) -> bool:
    normalized = str(message or "").casefold()
    return any(marker in normalized for marker in _TRANSIENT_ERROR_MARKERS)


class QbRecoveryScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float = 10.0,
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
            name="qb-recovery-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._poll_interval_seconds + 1.0))
        self._thread = None

    def run_once(self) -> int:
        session = self._session_factory()
        try:
            candidates = [
                rule
                for rule in session.scalars(
                    select(Rule).where(Rule.last_sync_status == SyncStatus.ERROR)
                ).all()
                if _is_transient_qb_error(rule.last_sync_error)
            ]
            if not candidates:
                return 0

            settings = SettingsService.get_or_create(session)
            connection = SettingsService.resolve_qb_connection(settings)
            if not connection.is_configured:
                return 0
            with QbittorrentClient(
                connection.base_url,
                connection.username,
                connection.password,
            ) as client:
                client.test_connection()

            rule_ids = [rule.id for rule in candidates]
            for rule in candidates:
                rule.last_sync_status = SyncStatus.PENDING
                rule.last_sync_error = None
                session.add(rule)
            session.commit()
            for rule_id in rule_ids:
                enqueue_rule_sync(rule_id)
            LOGGER.info("qBittorrent recovered; queued %d rule(s) for resync.", len(rule_ids))
            return len(rule_ids)
        except QbittorrentClientError:
            session.rollback()
            return 0
        except Exception:
            session.rollback()
            LOGGER.exception("qBittorrent recovery check failed.")
            return 0
        finally:
            session.close()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self._poll_interval_seconds)


_scheduler: QbRecoveryScheduler | None = None


def start_qb_recovery_scheduler(*, session_factory: sessionmaker[Session]) -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = QbRecoveryScheduler(session_factory=session_factory)
    _scheduler.start()


def stop_qb_recovery_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.stop()
    _scheduler = None
