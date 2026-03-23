from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR

HOVER_DEBUG_LOG_PATH = ROOT_DIR / "logs" / "hover-debug.log"
_RECENT_EVENT_LIMIT = 400
_events: deque[dict[str, Any]] = deque(maxlen=_RECENT_EVENT_LIMIT)
_lock = threading.Lock()


def record_hover_event(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    payload.setdefault("timestamp", datetime.now(UTC).isoformat())
    HOVER_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _events.append(payload)
        with HOVER_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return payload


def list_hover_events(*, limit: int = 50, session_id: str | None = None) -> list[dict[str, Any]]:
    normalized_limit = max(1, min(int(limit), _RECENT_EVENT_LIMIT))
    with _lock:
        items = list(_events)
    if session_id:
        items = [item for item in items if str(item.get("session_id") or "") == session_id]
    return items[-normalized_limit:]


def clear_hover_events(*, session_id: str | None = None) -> int:
    with _lock:
        if session_id:
            retained = [item for item in _events if str(item.get("session_id") or "") != session_id]
            cleared_count = len(_events) - len(retained)
            _events.clear()
            _events.extend(retained)
            return cleared_count

        cleared_count = len(_events)
        _events.clear()
        return cleared_count


def hover_debug_log_path() -> Path:
    return HOVER_DEBUG_LOG_PATH
