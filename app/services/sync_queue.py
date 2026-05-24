from __future__ import annotations

import concurrent.futures
import logging
import threading
from collections import deque
from typing import Any

from app.db import get_session_factory
from app.models import Rule, SyncStatus
from app.services.operation_status import complete_operation, start_operation, update_operation
from app.services.settings_service import SettingsService
from app.services.sync import SyncService

LOGGER = logging.getLogger(__name__)

_QUEUE_CONDITION = threading.Condition()
_QUEUED_RULE_IDS: deque[str] = deque()
_QUEUED_RULE_ID_SET: set[str] = set()

_TOTAL_ENQUEUED = 0
_TOTAL_COMPLETED = 0
_TOTAL_FAILED = 0
_ACTIVE_TASKS = 0
_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_WORKER_THREAD: threading.Thread | None = None
_QUEUE_OPERATION_ID: str | None = None


def enqueue_rule_sync(rule_id: str) -> dict[str, Any]:
    global _QUEUE_OPERATION_ID, _TOTAL_ENQUEUED, _TOTAL_COMPLETED, _TOTAL_FAILED
    normalized_rule_id = str(rule_id or "").strip()
    if not normalized_rule_id:
        return {"enqueued": False, "duplicate": False, "queue_depth": len(_QUEUED_RULE_IDS)}

    with _QUEUE_CONDITION:
        if not _QUEUED_RULE_IDS and _ACTIVE_TASKS == 0:
            _TOTAL_ENQUEUED = 0
            _TOTAL_COMPLETED = 0
            _TOTAL_FAILED = 0
            _QUEUE_OPERATION_ID = start_operation(
                operation_type="qb_sync",
                label="Syncing qBittorrent rules",
                total=0,
                status="queued",
                message="qBittorrent rule sync queued.",
            ).operation_id

        duplicate = normalized_rule_id in _QUEUED_RULE_ID_SET
        if not duplicate:
            _QUEUED_RULE_IDS.append(normalized_rule_id)
            _QUEUED_RULE_ID_SET.add(normalized_rule_id)
            _TOTAL_ENQUEUED += 1
        _update_queue_operation_locked()
        _ensure_worker_locked()
        _QUEUE_CONDITION.notify()
        return {
            "enqueued": not duplicate,
            "duplicate": duplicate,
            "queue_depth": len(_QUEUED_RULE_IDS),
        }


def get_sync_queue_status() -> dict[str, Any]:
    with _QUEUE_CONDITION:
        return {
            "is_running": _ACTIVE_TASKS > 0 or len(_QUEUED_RULE_IDS) > 0,
            "queued": len(_QUEUED_RULE_IDS),
            "active": _ACTIVE_TASKS,
            "total_enqueued": _TOTAL_ENQUEUED,
            "completed": _TOTAL_COMPLETED,
            "failed": _TOTAL_FAILED,
        }


def _ensure_worker_locked() -> None:
    global _WORKER_THREAD
    if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
        return
    _WORKER_THREAD = threading.Thread(
        target=_sync_worker_loop,
        name="rule-sync-queue-dispatcher",
        daemon=True,
    )
    _WORKER_THREAD.start()


def _update_queue_operation_locked() -> None:
    if _QUEUE_OPERATION_ID is None:
        return
    if _TOTAL_FAILED:
        message = (
            f"qB sync {_TOTAL_COMPLETED}/{_TOTAL_ENQUEUED} completed; "
            f"{_TOTAL_FAILED} failed."
        )
    elif _ACTIVE_TASKS or _QUEUED_RULE_IDS:
        message = (
            f"qB sync {_TOTAL_COMPLETED}/{_TOTAL_ENQUEUED} completed; "
            f"{_ACTIVE_TASKS} active, {len(_QUEUED_RULE_IDS)} queued."
        )
    else:
        message = f"qB sync completed for {_TOTAL_COMPLETED}/{_TOTAL_ENQUEUED} rule(s)."
    update_operation(
        _QUEUE_OPERATION_ID,
        current=_TOTAL_COMPLETED + _TOTAL_FAILED,
        total=_TOTAL_ENQUEUED,
        message=message,
        status="running" if _ACTIVE_TASKS else "queued",
    )


def _sync_worker_loop() -> None:
    global _WORKER_THREAD, _EXECUTOR, _ACTIVE_TASKS

    with _QUEUE_CONDITION:
        if _EXECUTOR is None:
            _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="sync-worker"
            )

    while True:
        with _QUEUE_CONDITION:
            if not _QUEUED_RULE_IDS and _ACTIVE_TASKS == 0:
                _WORKER_THREAD = None
                return
            if not _QUEUED_RULE_IDS or _ACTIVE_TASKS >= 3:
                _QUEUE_CONDITION.wait(timeout=1.0)
                continue

            rule_id = _QUEUED_RULE_IDS.popleft()
            _QUEUED_RULE_ID_SET.discard(rule_id)
            _ACTIVE_TASKS += 1

        _EXECUTOR.submit(_process_and_finalize, rule_id)


def _process_and_finalize(rule_id: str) -> None:
    global _ACTIVE_TASKS, _QUEUE_OPERATION_ID, _TOTAL_COMPLETED, _TOTAL_FAILED
    success = False
    try:
        success = _process_rule_sync(rule_id)
    except Exception:
        LOGGER.exception("Unhandled error in rule sync worker for %s", rule_id)
    finally:
        with _QUEUE_CONDITION:
            _ACTIVE_TASKS -= 1
            if success:
                _TOTAL_COMPLETED += 1
            else:
                _TOTAL_FAILED += 1
            if not _QUEUED_RULE_IDS and _ACTIVE_TASKS == 0 and _QUEUE_OPERATION_ID is not None:
                if _TOTAL_FAILED:
                    complete_operation(
                        _QUEUE_OPERATION_ID,
                        status="error",
                        message=(
                            f"qB sync completed with {_TOTAL_FAILED} failure(s): "
                            f"{_TOTAL_COMPLETED}/{_TOTAL_ENQUEUED} succeeded."
                        ),
                    )
                else:
                    complete_operation(
                        _QUEUE_OPERATION_ID,
                        message=f"qB sync completed for {_TOTAL_COMPLETED} rule(s).",
                    )
                _QUEUE_OPERATION_ID = None
            else:
                _update_queue_operation_locked()
            _QUEUE_CONDITION.notify_all()


def _process_rule_sync(rule_id: str) -> bool:
    direct_operation_id: str | None = None
    with _QUEUE_CONDITION:
        if _QUEUE_OPERATION_ID is None:
            direct_operation_id = start_operation(
                operation_type="qb_sync",
                label="Syncing qBittorrent rules",
                total=1,
                message="Pushing one rule to qBittorrent.",
            ).operation_id
    session_factory = get_session_factory()
    session = session_factory()
    try:
        rule = session.get(Rule, rule_id)
        if rule is None:
            if direct_operation_id is not None:
                complete_operation(direct_operation_id, message="qB sync skipped; rule not found.")
            return True
        rule.last_sync_status = SyncStatus.SYNCING
        rule.last_sync_error = None
        session.add(rule)
        session.commit()

        settings = SettingsService.get_or_create(session)
        SyncService(session, settings).sync_rule(rule_id)
        if direct_operation_id is not None:
            complete_operation(direct_operation_id, message="qB sync completed for 1 rule(s).")
        return True
    except Exception as exc:  # pragma: no cover - defensive background fallback
        LOGGER.exception("Failed to process queued qB rule sync for %s.", rule_id)
        session.rollback()
        if direct_operation_id is not None:
            complete_operation(
                direct_operation_id,
                status="error",
                message=f"qB sync failed: {exc}",
                error=str(exc),
            )
        try:
            rule = session.get(Rule, rule_id)
            if rule is not None:
                rule.last_sync_status = SyncStatus.ERROR
                rule.last_sync_error = str(exc)
                session.add(rule)
                session.commit()
        except Exception:
            session.rollback()
            LOGGER.exception("Failed to record queued qB rule sync failure for %s.", rule_id)
        return False
    finally:
        session.close()
