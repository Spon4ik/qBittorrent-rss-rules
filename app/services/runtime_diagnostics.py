from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_environment_settings
from app.services.rule_fetch_ops import schedule_payload
from app.services.rule_fetch_scheduler import rule_fetch_scheduler_status
from app.services.runtime_identity import runtime_identity_payload
from app.services.settings_service import SettingsService


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def runtime_diagnostics_payload(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return bounded, secret-free runtime state for deterministic functional QA."""
    generated_at = _as_utc(now) or datetime.now(UTC)
    settings = SettingsService.get_or_create(session)
    environment = get_environment_settings()
    schedule = schedule_payload(settings)
    next_run_at = _as_utc(getattr(settings, "rules_fetch_schedule_next_run_at", None))
    overdue_seconds = 0.0
    if bool(schedule.get("enabled")) and next_run_at is not None and next_run_at < generated_at:
        overdue_seconds = max(0.0, (generated_at - next_run_at).total_seconds())

    jackett_ready = False
    readiness_error_type: str | None = None
    try:
        jackett_ready = SettingsService.resolve_jackett(settings).app_ready
    except Exception as exc:
        readiness_error_type = type(exc).__name__

    return {
        "generated_at": generated_at.isoformat(),
        "runtime": runtime_identity_payload(),
        "components": {
            "scheduled_rule_fetch": {
                "runtime_enabled": bool(environment.enable_rule_fetch_scheduler),
                "schedule": schedule,
                "scheduler": rule_fetch_scheduler_status(),
                "overdue_seconds": overdue_seconds,
                "readiness": {
                    "jackett_app_ready": jackett_ready,
                    "error_type": readiness_error_type,
                },
            }
        },
    }
