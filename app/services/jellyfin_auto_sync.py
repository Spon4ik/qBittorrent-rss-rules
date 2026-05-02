from __future__ import annotations

import threading

from sqlalchemy.orm import Session, sessionmaker

from app.config import resolve_runtime_path
from app.models import AppSettings, utcnow
from app.services.jellyfin_sync_ops import JellyfinSyncBusyError, execute_jellyfin_sync
from app.services.settings_service import (
    DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
    MIN_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
    SettingsService,
    normalize_jellyfin_auto_sync_interval_seconds,
)


class JellyfinAutoSyncService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        poll_interval_seconds: float = DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval_seconds = max(
            float(MIN_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS),
            float(poll_interval_seconds),
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_seen_db_path: str | None = None
        self._last_seen_db_mtime_ns: int | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="jellyfin-auto-sync",
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
            jellyfin_config = SettingsService.resolve_jellyfin(settings)
            wait_seconds = float(
                normalize_jellyfin_auto_sync_interval_seconds(
                    jellyfin_config.auto_sync_interval_seconds
                )
            )

            if not jellyfin_config.is_configured or not jellyfin_config.auto_sync_enabled:
                self._last_seen_db_path = None
                self._last_seen_db_mtime_ns = None
                return wait_seconds

            db_path = resolve_runtime_path(jellyfin_config.db_path)
            if db_path is None:
                self._last_seen_db_path = None
                self._last_seen_db_mtime_ns = None
                return wait_seconds
            current_db_path = str(db_path)
            current_mtime_ns = db_path.stat().st_mtime_ns

            should_sync = (
                force
                or self._last_seen_db_path != current_db_path
                or self._last_seen_db_mtime_ns != current_mtime_ns
            )
            if not should_sync:
                return wait_seconds

            execution = execute_jellyfin_sync(
                session,
                settings=settings,
                allow_metadata_requests=False,
            )
            self._last_seen_db_path = current_db_path
            self._last_seen_db_mtime_ns = current_mtime_ns
            self._record_status(
                session,
                status=execution.message_level,
                message=execution.render_message(prefix="Automatic Jellyfin sync completed for"),
            )
            return wait_seconds
        except JellyfinSyncBusyError:
            return self._poll_interval_seconds
        except Exception as exc:
            session.rollback()
            self._last_seen_db_path = None
            self._last_seen_db_mtime_ns = None
            self._record_status(
                session,
                status="error",
                message=f"Automatic Jellyfin sync failed: {exc}",
            )
            return self._poll_interval_seconds
        finally:
            session.close()

    @staticmethod
    def _record_status(session: Session, *, status: str, message: str) -> None:
        settings = session.get(AppSettings, "default")
        if settings is None:
            return
        settings.jellyfin_auto_sync_last_run_at = utcnow()
        settings.jellyfin_auto_sync_last_status = str(status or "idle").strip().lower() or "idle"
        settings.jellyfin_auto_sync_last_message = str(message or "")
        session.add(settings)
        session.commit()


_service: JellyfinAutoSyncService | None = None


def start_jellyfin_auto_sync_service(
    *,
    session_factory: sessionmaker[Session],
    poll_interval_seconds: float = DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
) -> None:
    global _service
    if _service is None:
        _service = JellyfinAutoSyncService(
            session_factory=session_factory,
            poll_interval_seconds=poll_interval_seconds,
        )
    _service.start()


def stop_jellyfin_auto_sync_service() -> None:
    global _service
    if _service is None:
        return
    _service.stop()


def run_jellyfin_auto_sync_once(*, force: bool = False) -> None:
    if _service is None:
        return
    _service.run_once(force=force)
