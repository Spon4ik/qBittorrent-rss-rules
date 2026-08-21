from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()
_error_count = 0
_last_error: dict[str, Any] | None = None


def record_unhandled_api_error(
    *,
    method: str,
    path: str,
    error_type: str,
) -> dict[str, Any]:
    """Record bounded, secret-free evidence for one unhandled API exception."""
    global _error_count, _last_error
    event: dict[str, Any] = {
        "id": f"api-{uuid.uuid4().hex[:12]}",
        "occurred_at": datetime.now(UTC).isoformat(),
        "method": str(method or "").strip().upper(),
        "path": str(path or "").strip(),
        "error_type": str(error_type or "Exception").strip() or "Exception",
    }
    with _LOCK:
        _error_count += 1
        _last_error = dict(event)
        event["count"] = _error_count
    return event


def api_error_status() -> dict[str, Any]:
    with _LOCK:
        return {
            "count": _error_count,
            "last": dict(_last_error) if _last_error is not None else None,
        }


def reset_api_error_registry_for_tests() -> None:
    global _error_count, _last_error
    with _LOCK:
        _error_count = 0
        _last_error = None
