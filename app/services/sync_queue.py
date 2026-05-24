from __future__ import annotations

import concurrent.futures
import logging
import threading
from collections import deque
from dataclasses import dataclass
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
_QUEUE_FEEDS_PREPARED = False
_QUEUE_FEEDS_PREPARING = False
_QUEUE_RECONCILE_PER_RULE = False

_INITIAL_SYNC_WORKER_LIMIT = 3
_MAX_SYNC_WORKER_LIMIT = 24
_SYNC_SUCCESS_STREAK_TO_INCREASE = 8
_ADAPTIVE_WORKER_LIMIT = _INITIAL_SYNC_WORKER_LIMIT
_SYNC_SUCCESS_STREAK = 0
_BACKOFF_ERROR_MARKERS = (
    "timeout",
    "timed out",
    "connect",
    "connection",
    "too many requests",
    "429",
    "502",
    "503",
    "504",
)


@dataclass(frozen=True)
class RuleSyncOutcome:
    success: bool
    should_backoff: bool = False


def enqueue_rule_sync(rule_id: str) -> dict[str, Any]:
    global _QUEUE_FEEDS_PREPARED, _QUEUE_FEEDS_PREPARING, _QUEUE_OPERATION_ID
    global _QUEUE_RECONCILE_PER_RULE
    global _TOTAL_COMPLETED, _TOTAL_ENQUEUED, _TOTAL_FAILED
    normalized_rule_id = str(rule_id or "").strip()
    if not normalized_rule_id:
        return {"enqueued": False, "duplicate": False, "queue_depth": len(_QUEUED_RULE_IDS)}

    with _QUEUE_CONDITION:
        if not _QUEUED_RULE_IDS and _ACTIVE_TASKS == 0:
            _TOTAL_ENQUEUED = 0
            _TOTAL_COMPLETED = 0
            _TOTAL_FAILED = 0
            _QUEUE_FEEDS_PREPARED = False
            _QUEUE_FEEDS_PREPARING = False
            _QUEUE_RECONCILE_PER_RULE = False
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
            "worker_limit": _ADAPTIVE_WORKER_LIMIT,
            "max_worker_limit": _MAX_SYNC_WORKER_LIMIT,
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
    elif _QUEUE_FEEDS_PREPARING:
        message = "Preparing qB RSS feeds before parallel rule sync."
    elif _ACTIVE_TASKS or _QUEUED_RULE_IDS:
        message = (
            f"qB sync {_TOTAL_COMPLETED}/{_TOTAL_ENQUEUED} completed; "
            f"{_ACTIVE_TASKS} active (limit {_ADAPTIVE_WORKER_LIMIT}), "
            f"{len(_QUEUED_RULE_IDS)} queued."
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
    global _EXECUTOR, _QUEUE_FEEDS_PREPARED, _QUEUE_FEEDS_PREPARING
    global _QUEUE_RECONCILE_PER_RULE, _WORKER_THREAD

    with _QUEUE_CONDITION:
        if _EXECUTOR is None:
            _EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=_MAX_SYNC_WORKER_LIMIT,
                thread_name_prefix="sync-worker",
            )

    while True:
        prepare_rule_ids: list[str] | None = None
        with _QUEUE_CONDITION:
            if not _QUEUED_RULE_IDS and _ACTIVE_TASKS == 0:
                _WORKER_THREAD = None
                return
            if not _QUEUE_FEEDS_PREPARED and not _QUEUE_FEEDS_PREPARING:
                _QUEUE_FEEDS_PREPARING = True
                prepare_rule_ids = list(_QUEUED_RULE_IDS)
                _update_queue_operation_locked()
            elif _QUEUE_FEEDS_PREPARING:
                _QUEUE_CONDITION.wait(timeout=1.0)
                continue
            elif not _QUEUED_RULE_IDS or _ACTIVE_TASKS >= _ADAPTIVE_WORKER_LIMIT:
                _QUEUE_CONDITION.wait(timeout=1.0)
                continue
            else:
                _dispatch_next_rule_sync_locked()
        if prepare_rule_ids is not None:
            preparation_failed = False
            try:
                _prepare_queued_rule_syncs(prepare_rule_ids)
            except Exception:
                preparation_failed = True
                LOGGER.exception("Failed to prepare queued qB rule sync batch.")
            finally:
                with _QUEUE_CONDITION:
                    _QUEUE_FEEDS_PREPARED = True
                    _QUEUE_FEEDS_PREPARING = False
                    _QUEUE_RECONCILE_PER_RULE = preparation_failed
                    _update_queue_operation_locked()
                    _QUEUE_CONDITION.notify_all()


def _dispatch_next_rule_sync_locked() -> bool:
    global _ACTIVE_TASKS
    if (
        _EXECUTOR is None
        or not _QUEUED_RULE_IDS
        or _ACTIVE_TASKS >= _ADAPTIVE_WORKER_LIMIT
    ):
        return False
    rule_id = _QUEUED_RULE_IDS.popleft()
    _QUEUED_RULE_ID_SET.discard(rule_id)
    _ACTIVE_TASKS += 1
    _update_queue_operation_locked()
    _EXECUTOR.submit(_process_and_finalize, rule_id)
    return True


def _process_and_finalize(rule_id: str) -> None:
    global _ACTIVE_TASKS, _QUEUE_OPERATION_ID, _TOTAL_COMPLETED, _TOTAL_FAILED
    outcome = RuleSyncOutcome(success=False, should_backoff=True)
    try:
        with _QUEUE_CONDITION:
            reconcile_feeds = _QUEUE_RECONCILE_PER_RULE
        outcome = _process_rule_sync(rule_id, reconcile_feeds=reconcile_feeds)
    except Exception:
        LOGGER.exception("Unhandled error in rule sync worker for %s", rule_id)
    finally:
        with _QUEUE_CONDITION:
            _ACTIVE_TASKS -= 1
            _record_sync_outcome_locked(outcome)
            if outcome.success:
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


def _process_rule_sync(rule_id: str, *, reconcile_feeds: bool = True) -> RuleSyncOutcome:
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
            return RuleSyncOutcome(success=True)
        rule.last_sync_status = SyncStatus.SYNCING
        rule.last_sync_error = None
        session.add(rule)
        session.commit()

        settings = SettingsService.get_or_create(session)
        SyncService(session, settings).sync_rule(rule_id, reconcile_feeds=reconcile_feeds)
        if direct_operation_id is not None:
            complete_operation(direct_operation_id, message="qB sync completed for 1 rule(s).")
        return RuleSyncOutcome(success=True)
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
        return RuleSyncOutcome(success=False, should_backoff=_is_backoff_error(exc))
    finally:
        session.close()


def _record_sync_outcome_locked(outcome: RuleSyncOutcome) -> None:
    global _ADAPTIVE_WORKER_LIMIT, _SYNC_SUCCESS_STREAK
    if outcome.success:
        _SYNC_SUCCESS_STREAK += 1
        if (
            _SYNC_SUCCESS_STREAK >= _SYNC_SUCCESS_STREAK_TO_INCREASE
            and _ADAPTIVE_WORKER_LIMIT < _MAX_SYNC_WORKER_LIMIT
        ):
            _ADAPTIVE_WORKER_LIMIT += 1
            _SYNC_SUCCESS_STREAK = 0
        return

    _SYNC_SUCCESS_STREAK = 0
    if outcome.should_backoff and _ADAPTIVE_WORKER_LIMIT > 1:
        _ADAPTIVE_WORKER_LIMIT = max(1, _ADAPTIVE_WORKER_LIMIT // 2)


def _is_backoff_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(marker in message for marker in _BACKOFF_ERROR_MARKERS)


def _prepare_queued_rule_syncs(rule_ids: list[str]) -> None:
    cleaned_rule_ids = [str(rule_id or "").strip() for rule_id in rule_ids if str(rule_id or "").strip()]
    if not cleaned_rule_ids:
        return
    session_factory = get_session_factory()
    session = session_factory()
    try:
        rules = [
            rule
            for rule_id in cleaned_rule_ids
            if (rule := session.get(Rule, rule_id)) is not None
        ]
        if not rules:
            return
        settings = SettingsService.get_or_create(session)
        service = SyncService(session, settings)
        service._refresh_language_feeds_for_rules(rules)
        service._reconcile_qb_jackett_feeds()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
