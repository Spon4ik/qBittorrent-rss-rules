from __future__ import annotations

import logging
import threading
from collections import deque

from app.db import get_session_factory
from app.services.rule_fetch_ops import run_rules_fetch_batch

LOGGER = logging.getLogger(__name__)

_CONDITION = threading.Condition()
_RULE_IDS: deque[str] = deque()
_RULE_ID_SET: set[str] = set()
_WORKER: threading.Thread | None = None
_STOP_EVENT = threading.Event()


def start_rule_fetch_queue() -> None:
    """Allow the application-owned initial-fetch queue to accept work."""
    _STOP_EVENT.clear()


def stop_rule_fetch_queue() -> None:
    """Finish the active fetch and join the worker before its app shuts down."""
    global _WORKER
    with _CONDITION:
        _STOP_EVENT.set()
        _RULE_IDS.clear()
        _RULE_ID_SET.clear()
        worker = _WORKER
        _CONDITION.notify_all()
    if worker is not None and worker is not threading.current_thread():
        worker.join()
    with _CONDITION:
        if _WORKER is worker and (worker is None or not worker.is_alive()):
            _WORKER = None


def enqueue_rule_fetch(rule_id: str) -> bool:
    global _WORKER
    normalized = str(rule_id or "").strip()
    if not normalized:
        return False
    with _CONDITION:
        if _STOP_EVENT.is_set():
            return False
        if normalized in _RULE_ID_SET:
            return False
        _RULE_IDS.append(normalized)
        _RULE_ID_SET.add(normalized)
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(
                target=_worker_loop,
                name="rule-fetch-queue",
                daemon=True,
            )
            _WORKER.start()
        return True


def _worker_loop() -> None:
    global _WORKER
    while True:
        with _CONDITION:
            if _STOP_EVENT.is_set():
                _RULE_IDS.clear()
                _RULE_ID_SET.clear()
                _WORKER = None
                return
            if not _RULE_IDS:
                _WORKER = None
                return
            rule_id = _RULE_IDS.popleft()
        session = get_session_factory()()
        retry = False
        try:
            result = run_rules_fetch_batch(
                session,
                run_all=False,
                rule_ids=[rule_id],
                include_disabled=True,
            )
            retry = result.get("status") == "busy"
        except Exception:
            session.rollback()
            LOGGER.exception("Failed to fetch initial snapshot for rule %s.", rule_id)
        finally:
            session.close()
        with _CONDITION:
            if retry and not _STOP_EVENT.is_set():
                _RULE_IDS.append(rule_id)
                _CONDITION.wait(timeout=1.0)
            else:
                _RULE_ID_SET.discard(rule_id)
