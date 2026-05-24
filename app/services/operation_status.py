from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ACTIVE_STATUSES = frozenset({"queued", "running"})
DEFAULT_RECENT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class OperationHandle:
    operation_id: str


@dataclass(slots=True)
class OperationRecord:
    operation_id: str
    operation_type: str
    label: str
    status: str
    current: int
    total: int | None
    message: str
    errors: list[str]
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


_LOCK = threading.RLock()
_OPERATIONS: dict[str, OperationRecord] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_count(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, int(value))


def _percent(current: int, total: int | None) -> int | None:
    if total is None or total <= 0:
        return None
    if current >= total:
        return 100
    return max(0, min(99, round((current / total) * 100)))


def _payload_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return 0


def start_operation(
    *,
    operation_type: str,
    label: str,
    total: int | None = None,
    current: int = 0,
    message: str = "",
    status: str = "running",
) -> OperationHandle:
    operation_id = str(uuid.uuid4())
    timestamp = _now()
    normalized_total = _normalize_count(total)
    normalized_current = _normalize_count(current) or 0
    with _LOCK:
        _OPERATIONS[operation_id] = OperationRecord(
            operation_id=operation_id,
            operation_type=str(operation_type or "operation").strip() or "operation",
            label=str(label or "Operation").strip() or "Operation",
            status=str(status or "running").strip().lower() or "running",
            current=normalized_current,
            total=normalized_total,
            message=str(message or ""),
            errors=[],
            started_at=timestamp,
            updated_at=timestamp,
        )
    return OperationHandle(operation_id=operation_id)


def update_operation(
    operation_id: str | None,
    *,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    if not operation_id:
        return
    with _LOCK:
        operation = _OPERATIONS.get(operation_id)
        if operation is None:
            return
        if current is not None:
            operation.current = _normalize_count(current) or 0
        if total is not None:
            operation.total = _normalize_count(total)
        if message is not None:
            operation.message = str(message or "")
        if status is not None:
            operation.status = str(status or "running").strip().lower() or "running"
        if error:
            operation.errors.append(str(error))
        operation.updated_at = _now()


def complete_operation(
    operation_id: str | None,
    *,
    status: str = "success",
    message: str | None = None,
    error: str | None = None,
) -> None:
    if not operation_id:
        return
    with _LOCK:
        operation = _OPERATIONS.get(operation_id)
        if operation is None:
            return
        if operation.total is not None:
            operation.current = max(operation.current, operation.total)
        if message is not None:
            operation.message = str(message or "")
        if error:
            operation.errors.append(str(error))
        operation.status = str(status or "success").strip().lower() or "success"
        timestamp = _now()
        operation.completed_at = timestamp
        operation.updated_at = timestamp


def fail_operation(operation_id: str | None, *, message: str | None = None, error: str) -> None:
    complete_operation(operation_id, status="error", message=message, error=error)


def _operation_payload(operation: OperationRecord) -> dict[str, object]:
    percent = _percent(operation.current, operation.total)
    return {
        "id": operation.operation_id,
        "type": operation.operation_type,
        "label": operation.label,
        "status": operation.status,
        "current": operation.current,
        "total": operation.total or 0,
        "percent": percent,
        "message": operation.message,
        "errors": list(operation.errors),
        "started_at": operation.started_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
        "completed_at": operation.completed_at.isoformat()
        if operation.completed_at is not None
        else None,
    }


def operations_status_payload(*, recent_seconds: int = DEFAULT_RECENT_SECONDS) -> dict[str, object]:
    cutoff = _now() - timedelta(seconds=max(0, int(recent_seconds)))
    with _LOCK:
        stale_ids = [
            operation_id
            for operation_id, operation in _OPERATIONS.items()
            if operation.completed_at is not None and operation.completed_at < cutoff
        ]
        for operation_id in stale_ids:
            _OPERATIONS.pop(operation_id, None)
        operations = sorted(
            _OPERATIONS.values(),
            key=lambda item: (item.completed_at is not None, item.started_at),
        )
        payload_operations = [_operation_payload(operation) for operation in operations]

    known_totals = [item for item in payload_operations if _payload_int(item, "total") > 0]
    total = sum(_payload_int(item, "total") for item in known_totals)
    current = sum(
        min(_payload_int(item, "current"), _payload_int(item, "total"))
        for item in known_totals
    )
    is_running = any(str(item["status"]) in ACTIVE_STATUSES for item in payload_operations)
    summary_percent = _percent(current, total) if known_totals else None
    if known_totals and not is_running and current >= total:
        summary_percent = 100
    return {
        "summary": {
            "is_running": is_running,
            "operation_count": len(payload_operations),
            "active_count": sum(
                1 for item in payload_operations if str(item["status"]) in ACTIVE_STATUSES
            ),
            "current": current,
            "total": total,
            "percent": summary_percent,
        },
        "operations": payload_operations,
    }


def reset_operations_for_tests() -> None:
    with _LOCK:
        _OPERATIONS.clear()


def update_operation_for_tests(operation_id: str, **values: object) -> None:
    with _LOCK:
        operation = _OPERATIONS[operation_id]
        for key, value in values.items():
            setattr(operation, key, value)
