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


def enqueue_rule_fetch(rule_id: str) -> bool:
    global _WORKER
    normalized = str(rule_id or "").strip()
    if not normalized:
        return False
    with _CONDITION:
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
            if retry:
                _RULE_IDS.append(rule_id)
                _CONDITION.wait(timeout=1.0)
            else:
                _RULE_ID_SET.discard(rule_id)
