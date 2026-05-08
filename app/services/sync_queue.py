from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any

from app.db import get_session_factory
from app.models import Rule, SyncStatus
from app.services.settings_service import SettingsService
from app.services.sync import SyncService

LOGGER = logging.getLogger(__name__)

_QUEUE_CONDITION = threading.Condition()
_QUEUED_RULE_IDS: deque[str] = deque()
_QUEUED_RULE_ID_SET: set[str] = set()
_WORKER_THREAD: threading.Thread | None = None


def enqueue_rule_sync(rule_id: str) -> dict[str, Any]:
    normalized_rule_id = str(rule_id or "").strip()
    if not normalized_rule_id:
        return {"enqueued": False, "duplicate": False, "queue_depth": len(_QUEUED_RULE_IDS)}

    with _QUEUE_CONDITION:
        duplicate = normalized_rule_id in _QUEUED_RULE_ID_SET
        if not duplicate:
            _QUEUED_RULE_IDS.append(normalized_rule_id)
            _QUEUED_RULE_ID_SET.add(normalized_rule_id)
        _ensure_worker_locked()
        _QUEUE_CONDITION.notify()
        return {
            "enqueued": not duplicate,
            "duplicate": duplicate,
            "queue_depth": len(_QUEUED_RULE_IDS),
        }


def _ensure_worker_locked() -> None:
    global _WORKER_THREAD
    if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
        return
    _WORKER_THREAD = threading.Thread(
        target=_sync_worker_loop,
        name="rule-sync-queue",
        daemon=True,
    )
    _WORKER_THREAD.start()


def _sync_worker_loop() -> None:
    global _WORKER_THREAD
    while True:
        with _QUEUE_CONDITION:
            if not _QUEUED_RULE_IDS:
                _WORKER_THREAD = None
                return
            rule_id = _QUEUED_RULE_IDS.popleft()
            _QUEUED_RULE_ID_SET.discard(rule_id)
        _process_rule_sync(rule_id)


def _process_rule_sync(rule_id: str) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        rule = session.get(Rule, rule_id)
        if rule is None:
            return
        rule.last_sync_status = SyncStatus.SYNCING
        rule.last_sync_error = None
        session.add(rule)
        session.commit()

        settings = SettingsService.get_or_create(session)
        SyncService(session, settings).sync_rule(rule_id)
    except Exception as exc:  # pragma: no cover - defensive background fallback
        LOGGER.exception("Failed to process queued qB rule sync for %s.", rule_id)
        session.rollback()
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
    finally:
        session.close()
