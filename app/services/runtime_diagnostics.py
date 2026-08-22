from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_environment_settings
from app.models import Rule, RuleSearchSnapshot
from app.services.api_error_registry import api_error_status
from app.services.rule_fetch_ops import schedule_payload
from app.services.rule_fetch_scheduler import rule_fetch_scheduler_status
from app.services.runtime_identity import runtime_identity_payload
from app.services.settings_service import SettingsService

RUNTIME_DIAGNOSTIC_CAPABILITIES = (
    "unhandled_api_error_telemetry",
    "scheduled_snapshot_freshness",
)
SNAPSHOT_FRESHNESS_INTERVAL_MULTIPLIER = 2.0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _scheduled_snapshot_freshness(
    session: Session,
    *,
    schedule: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    interval_minutes = max(1, int(schedule.get("interval_minutes") or 1))
    freshness_limit_seconds = float(interval_minutes * 60) * SNAPSHOT_FRESHNESS_INTERVAL_MULTIPLIER
    stale_cutoff = generated_at - timedelta(seconds=freshness_limit_seconds)
    scope = str(schedule.get("scope") or "enabled").strip().casefold() or "enabled"

    filters = [
        Rule.movie_completion_auto_disabled.is_(False),
        Rule.jellyfin_auto_disabled.is_(False),
    ]
    if scope != "all":
        filters.append(Rule.enabled.is_(True))

    joined = Rule.__table__.outerjoin(
        RuleSearchSnapshot.__table__,
        RuleSearchSnapshot.rule_id == Rule.id,
    )
    total_rules = int(
        session.scalar(
            select(func.count()).select_from(joined).where(*filters)
        )
        or 0
    )
    missing_snapshots = int(
        session.scalar(
            select(func.count())
            .select_from(joined)
            .where(
                *filters,
                RuleSearchSnapshot.rule_id.is_(None),
                Rule.created_at < stale_cutoff,
            )
        )
        or 0
    )
    pending_snapshots = int(
        session.scalar(
            select(func.count())
            .select_from(joined)
            .where(
                *filters,
                RuleSearchSnapshot.rule_id.is_(None),
                Rule.created_at >= stale_cutoff,
            )
        )
        or 0
    )
    stale_snapshots = int(
        session.scalar(
            select(func.count())
            .select_from(joined)
            .where(
                *filters,
                RuleSearchSnapshot.fetched_at.is_not(None),
                RuleSearchSnapshot.fetched_at < stale_cutoff,
            )
        )
        or 0
    )
    oldest_snapshot_at = _as_utc(
        session.scalar(
            select(func.min(RuleSearchSnapshot.fetched_at))
            .select_from(joined)
            .where(*filters, RuleSearchSnapshot.fetched_at.is_not(None))
        )
    )
    newest_snapshot_at = _as_utc(
        session.scalar(
            select(func.max(RuleSearchSnapshot.fetched_at))
            .select_from(joined)
            .where(*filters, RuleSearchSnapshot.fetched_at.is_not(None))
        )
    )
    oldest_snapshot_age_seconds = (
        max(0.0, (generated_at - oldest_snapshot_at).total_seconds())
        if oldest_snapshot_at is not None
        else None
    )

    return {
        "scope": scope,
        "total_rules": total_rules,
        "fresh_snapshots": max(
            0,
            total_rules - missing_snapshots - pending_snapshots - stale_snapshots,
        ),
        "stale_snapshots": stale_snapshots,
        "missing_snapshots": missing_snapshots,
        "pending_snapshots": pending_snapshots,
        "freshness_limit_seconds": freshness_limit_seconds,
        "stale_cutoff": stale_cutoff.isoformat(),
        "oldest_snapshot_at": oldest_snapshot_at.isoformat() if oldest_snapshot_at else None,
        "newest_snapshot_at": newest_snapshot_at.isoformat() if newest_snapshot_at else None,
        "oldest_snapshot_age_seconds": (
            round(oldest_snapshot_age_seconds, 3)
            if oldest_snapshot_age_seconds is not None
            else None
        ),
    }


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

    snapshot_freshness = _scheduled_snapshot_freshness(
        session,
        schedule=schedule,
        generated_at=generated_at,
    )

    return {
        "generated_at": generated_at.isoformat(),
        "runtime": runtime_identity_payload(),
        "diagnostic_capabilities": list(RUNTIME_DIAGNOSTIC_CAPABILITIES),
        "components": {
            "api": {
                "unhandled_errors": api_error_status(),
            },
            "scheduled_rule_fetch": {
                "runtime_enabled": bool(environment.enable_rule_fetch_scheduler),
                "schedule": schedule,
                "scheduler": rule_fetch_scheduler_status(),
                "overdue_seconds": overdue_seconds,
                "readiness": {
                    "jackett_app_ready": jackett_ready,
                    "error_type": readiness_error_type,
                },
                "snapshot_freshness": snapshot_freshness,
            },
        },
    }
