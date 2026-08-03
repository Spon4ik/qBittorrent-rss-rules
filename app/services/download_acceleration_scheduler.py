from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session, sessionmaker

from app.services.download_acceleration import DownloadAccelerationService
from app.services.qbittorrent import QbittorrentClient
from app.services.real_debrid import RealDebridClient
from app.services.real_debrid_auth import ensure_real_debrid_access_token
from app.services.settings_service import SettingsService

LOGGER = logging.getLogger(__name__)


class DownloadAccelerationScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float = 15.0,
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
            name="download-acceleration-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_seconds + 1.0)
        self._thread = None

    def run_once(self) -> None:
        session = self._session_factory()
        try:
            settings = SettingsService.get_or_create(session)
            rd_config = SettingsService.resolve_real_debrid(settings)
            qb_config = SettingsService.resolve_qb_connection(settings)
            if not (rd_config.enabled and rd_config.is_connected and qb_config.is_configured):
                return
            access_token = ensure_real_debrid_access_token(session, settings)
            with (
                QbittorrentClient(
                    qb_config.base_url, qb_config.username, qb_config.password
                ) as qb_client,
                RealDebridClient(access_token) as rd_client,
            ):
                DownloadAccelerationService(
                    session,
                    settings,
                    qb_client=qb_client,
                    real_debrid_client=rd_client,
                ).run_once()
        except Exception:
            session.rollback()
            LOGGER.exception("Download acceleration scheduler tick failed.")
        finally:
            session.close()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self._poll_interval_seconds)


_scheduler: DownloadAccelerationScheduler | None = None


def start_download_acceleration_scheduler(
    *, session_factory: sessionmaker[Session]
) -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = DownloadAccelerationScheduler(session_factory=session_factory)
    _scheduler.start()


def stop_download_acceleration_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.stop()
