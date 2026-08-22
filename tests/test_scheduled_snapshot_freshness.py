from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import event, text

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule, RuleSearchSnapshot
from app.services import functional_watchdog
from app.services.functional_invariants import evaluate_scheduled_fetch_effectiveness
from app.services.runtime_diagnostics import runtime_diagnostics_payload

NOW = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)


def _rule(name: str, *, enabled: bool = True, completion_disabled: bool = False) -> Rule:
    return Rule(
        rule_name=name,
        content_name=name,
        normalized_title=name,
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=enabled,
        movie_completion_auto_disabled=completion_disabled,
    )


def _stale_effectiveness_payload() -> dict[str, object]:
    return {
        "diagnostic_capabilities": ["scheduled_snapshot_freshness"],
        "runtime": {
            "instance_id": "runtime-fresh",
            "started_at": "2026-08-22T17:30:00+00:00",
        },
        "components": {
            "scheduled_rule_fetch": {
                "runtime_enabled": True,
                "overdue_seconds": 0.0,
                "readiness": {
                    "jackett_app_ready": True,
                    "error_type": None,
                },
                "schedule": {
                    "enabled": True,
                    "interval_minutes": 1440,
                    "scope": "enabled",
                    "last_run_at": "2026-08-21T15:23:07.632517+00:00",
                    "next_run_at": "2026-08-22T15:23:07.632517+00:00",
                    "last_status": "error",
                    "last_message": "Jackett app search is not configured in Settings.",
                },
                "scheduler": {
                    "created": True,
                    "running": True,
                    "started_at": "2026-08-22T17:30:00+00:00",
                    "poll_interval_seconds": 30,
                    "tick_in_progress": False,
                    "last_tick_started_at": "2026-08-22T17:59:29+00:00",
                    "last_tick_completed_at": "2026-08-22T17:59:30+00:00",
                    "last_tick_result": "not_due",
                    "last_tick_error_type": None,
                },
                "snapshot_freshness": {
                    "scope": "enabled",
                    "total_rules": 355,
                    "fresh_snapshots": 0,
                    "stale_snapshots": 355,
                    "missing_snapshots": 0,
                    "pending_snapshots": 0,
                    "freshness_limit_seconds": 172800.0,
                    "stale_cutoff": "2026-08-20T18:00:00+00:00",
                    "oldest_snapshot_at": "2026-08-13T20:20:00+00:00",
                    "newest_snapshot_at": "2026-08-13T20:20:00+00:00",
                    "oldest_snapshot_age_seconds": 768000.0,
                },
            }
        },
    }


def test_runtime_diagnostics_reports_stale_and_missing_snapshots_without_loading_json(
    db_session,
) -> None:
    settings = db_session.get(AppSettings, "default") or AppSettings(id="default")
    settings.jackett_api_url = "http://jackett.test"
    settings.jackett_api_key_encrypted = obfuscate_secret("apikey")
    settings.rules_fetch_schedule_enabled = True
    settings.rules_fetch_schedule_interval_minutes = 1440
    settings.rules_fetch_schedule_scope = "enabled"
    settings.rules_fetch_schedule_last_run_at = NOW - timedelta(days=1)
    settings.rules_fetch_schedule_next_run_at = NOW + timedelta(hours=1)
    settings.rules_fetch_schedule_last_status = "ok"

    stale = _rule("Stale enabled")
    stale.last_snapshot_at = NOW - timedelta(days=9)
    fresh = _rule("Fresh enabled")
    fresh.last_snapshot_at = NOW - timedelta(hours=2)
    missing = _rule("Missing overdue")
    missing.created_at = NOW - timedelta(days=9)
    recent_missing = _rule("Missing recent")
    recent_missing.created_at = NOW - timedelta(hours=1)
    disabled = _rule("Disabled stale", enabled=False)
    disabled.last_snapshot_at = NOW - timedelta(days=20)
    completed = _rule("Completed stale", completion_disabled=True)
    completed.last_snapshot_at = NOW - timedelta(days=20)
    db_session.add_all([settings, stale, fresh, missing, recent_missing, disabled, completed])
    db_session.flush()
    db_session.add_all(
        [
            RuleSearchSnapshot(
                rule_id=stale.id,
                inline_search={},
                fetched_at=stale.last_snapshot_at,
            ),
            RuleSearchSnapshot(
                rule_id=fresh.id,
                inline_search={},
                fetched_at=fresh.last_snapshot_at,
            ),
            RuleSearchSnapshot(
                rule_id=disabled.id,
                inline_search={},
                fetched_at=disabled.last_snapshot_at,
            ),
            RuleSearchSnapshot(
                rule_id=completed.id,
                inline_search={},
                fetched_at=completed.last_snapshot_at,
            ),
        ]
    )
    db_session.commit()
    db_session.execute(
        text(
            "UPDATE rule_search_snapshots "
            "SET inline_search = '{\"truncated\":' "
            "WHERE rule_id = :rule_id"
        ),
        {"rule_id": stale.id},
    )
    db_session.commit()

    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(str(statement))

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        payload = runtime_diagnostics_payload(db_session, now=NOW)
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    freshness = payload["components"]["scheduled_rule_fetch"]["snapshot_freshness"]

    assert "scheduled_snapshot_freshness" in payload["diagnostic_capabilities"]
    assert freshness["scope"] == "enabled"
    assert freshness["total_rules"] == 4
    assert freshness["fresh_snapshots"] == 1
    assert freshness["stale_snapshots"] == 1
    assert freshness["missing_snapshots"] == 1
    assert freshness["pending_snapshots"] == 1
    assert freshness["freshness_limit_seconds"] == 172800.0
    assert freshness["oldest_snapshot_at"] == (NOW - timedelta(days=9)).isoformat()
    assert not any("rule_search_snapshots" in statement.casefold() for statement in statements)


def test_f02_rejects_ready_historical_recovery_when_snapshots_are_stale() -> None:
    result = evaluate_scheduled_fetch_effectiveness(_stale_effectiveness_payload(), NOW)

    assert result.status == "fail"
    assert result.metrics["effectiveness_state"] == "stale_snapshots"
    assert result.metrics["stale_snapshots"] == 355
    assert "has not kept rule snapshots current" in result.summary
    assert "2026-08-13T20:20:00+00:00" in result.summary


class _FakeSession:
    def close(self) -> None:
        return None


def test_watchdog_promotes_stale_snapshot_failure_before_codex_dispatch(monkeypatch) -> None:
    payload = _stale_effectiveness_payload()
    monkeypatch.setattr(
        functional_watchdog,
        "runtime_diagnostics_payload",
        lambda session: payload,
    )
    watchdog = functional_watchdog.FunctionalWatchdog(
        session_factory=_FakeSession,
        interval_seconds=30,
    )

    for _ in range(functional_watchdog.FUNCTIONAL_INCIDENT_FAILURE_THRESHOLD):
        watchdog.run_once()

    status = watchdog.status()
    f02 = status["checks"]["F-02"]
    assert f02["status"] == "fail"
    assert f02["metrics"]["effectiveness_state"] == "stale_snapshots"
    assert f02["incident_active"] is True
    assert status["incident_count"] >= 1
    assert status["overall_state"] == "unhealthy"


def test_runtime_health_asset_surfaces_f02_failure_before_persistent_threshold() -> None:
    asset = (
        Path(__file__).resolve().parents[1] / "app" / "static" / "runtime_health.js"
    ).read_text(encoding="utf-8")

    assert 'if (invariant?.status === "fail")' in asset
    assert '"runtime warning"' in asset
    assert "Automatic functional QA detected an F-02 failure" in asset
