from __future__ import annotations

import threading

from sqlalchemy.orm import Session, sessionmaker

from app.models import AppSettings, utcnow
from app.services.settings_service import (
    DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
    MIN_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
    SettingsService,
    normalize_stremio_auto_sync_interval_seconds,
)
from app.services.stremio import StremioService
from app.services.stremio_sync_ops import StremioSyncBusyError, execute_stremio_sync


class StremioAutoSyncService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float = DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval_seconds = max(
            float(MIN_STREMIO_AUTO_SYNC_INTERVAL_SECONDS),
            float(poll_interval_seconds),
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_seen_signature: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="stremio-auto-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is None:
            return
        self._thread.join(timeout=max(1.0, self._poll_interval_seconds + 1.0))
        self._thread = None

    def run_once(self, *, force: bool = False) -> None:
        self._tick(force=force)

    def _run_loop(self) -> None:
        force = True
        while not self._stop_event.is_set():
            wait_seconds = self._tick(force=force)
            force = False
            self._stop_event.wait(wait_seconds)

    def _tick(self, *, force: bool) -> float:
        session = self._session_factory()
        try:
            settings = SettingsService.get_or_create(session)
            stremio_config = SettingsService.resolve_stremio(settings)
            wait_seconds = float(
                normalize_stremio_auto_sync_interval_seconds(
                    stremio_config.auto_sync_interval_seconds
                )
            )

            service = StremioService(settings)
            if not stremio_config.auto_sync_enabled or not service.can_resolve_auth():
                self._last_seen_signature = None
                return wait_seconds

            current_signature = service.fetch_library_signature()
            should_sync = force or self._last_seen_signature != current_signature
            if not should_sync:
                return wait_seconds

            execution = execute_stremio_sync(
                session,
                settings=settings,
                allow_metadata_requests=False,
            )
            self._last_seen_signature = current_signature
            self._record_status(
                session,
                status=execution.message_level,
                message=execution.render_message(prefix="Automatic Stremio sync completed"),
            )
            return wait_seconds
        except StremioSyncBusyError:
            return self._poll_interval_seconds
        except Exception as exc:
            session.rollback()
            self._last_seen_signature = None
            self._record_status(
                session,
                status="error",
                message=f"Automatic Stremio sync failed: {exc}",
            )
            return self._poll_interval_seconds
        finally:
            session.close()

    @staticmethod
    def _record_status(session: Session, *, status: str, message: str) -> None:
        settings = session.get(AppSettings, "default")
        if settings is None:
            return
        settings.stremio_auto_sync_last_run_at = utcnow()
        settings.stremio_auto_sync_last_status = str(status or "idle").strip().lower() or "idle"
        settings.stremio_auto_sync_last_message = str(message or "")
        session.add(settings)
        session.commit()


_service: StremioAutoSyncService | None = None


def start_stremio_auto_sync_service(
    *,
    session_factory: sessionmaker[Session],
    poll_interval_seconds: float = DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
) -> None:
    global _service
    if _service is None:
        _service = StremioAutoSyncService(
            session_factory=session_factory,
            poll_interval_seconds=poll_interval_seconds,
        )
    _service.start()


def stop_stremio_auto_sync_service() -> None:
    global _service
    if _service is None:
        return
    _service.stop()


def run_stremio_auto_sync_once(*, force: bool = False) -> None:
    if _service is None:
        return
    _service.run_once(force=force)
