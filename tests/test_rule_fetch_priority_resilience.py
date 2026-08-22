from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule, utcnow
from app.services import rule_fetch_ops


def _rule(name: str) -> Rule:
    return Rule(
        rule_name=name,
        content_name=name,
        normalized_title=name,
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )


def _successful_fetch(session, *, rule, feed_urls_override=None):
    del session, feed_urls_override
    return {
        "rule_id": rule.id,
        "rule_name": rule.rule_name,
        "success": True,
        "state": "no_matches",
        "rank": 3,
        "filtered_count": 0,
        "fetched_count": 0,
        "warnings": [],
        "notices": [],
        "error": "",
    }


def test_batch_prioritization_uses_rule_summary_without_loading_malformed_snapshot_timestamp(
    db_session,
    monkeypatch,
) -> None:
    now = utcnow()
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("apikey"),
        rules_fetch_parallelism=1,
    )
    oldest = _rule("Oldest Summary")
    newest = _rule("Newest Summary")
    oldest.last_snapshot_at = now - timedelta(days=9)
    newest.last_snapshot_at = now - timedelta(days=1)
    db_session.add_all([settings, oldest, newest])
    db_session.flush()
    db_session.execute(
        text(
            "INSERT INTO rule_search_snapshots "
            "(rule_id, payload, inline_search, fetched_at, created_at, updated_at) "
            "VALUES (:rule_id, '{}', '{}', 'not-a-timestamp', :now, :now)"
        ),
        {"rule_id": oldest.id, "now": now},
    )
    db_session.commit()

    fetched: list[str] = []

    def fake_execute_rule_fetch(session, *, rule, feed_urls_override=None):
        fetched.append(rule.rule_name)
        return _successful_fetch(
            session,
            rule=rule,
            feed_urls_override=feed_urls_override,
        )

    monkeypatch.setattr(rule_fetch_ops, "execute_rule_fetch", fake_execute_rule_fetch)

    result = rule_fetch_ops.run_rules_fetch_batch(db_session, run_all=True)

    assert result["status"] == "ok"
    assert fetched == ["Oldest Summary", "Newest Summary"]


def test_legacy_missing_summary_degrades_malformed_snapshot_timestamp_to_missing_priority(
    db_session,
    monkeypatch,
) -> None:
    now = utcnow()
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("apikey"),
        rules_fetch_parallelism=1,
    )
    corrupt = _rule("A Corrupt Legacy Timestamp")
    healthy = _rule("B Healthy Missing Snapshot")
    db_session.add_all([settings, corrupt, healthy])
    db_session.flush()
    db_session.execute(
        text(
            "INSERT INTO rule_search_snapshots "
            "(rule_id, payload, inline_search, fetched_at, created_at, updated_at) "
            "VALUES (:rule_id, '{}', '{}', 'not-a-timestamp', :now, :now)"
        ),
        {"rule_id": corrupt.id, "now": now},
    )
    db_session.commit()

    fetched: list[str] = []

    def fake_execute_rule_fetch(session, *, rule, feed_urls_override=None):
        fetched.append(rule.rule_name)
        return _successful_fetch(
            session,
            rule=rule,
            feed_urls_override=feed_urls_override,
        )

    monkeypatch.setattr(rule_fetch_ops, "execute_rule_fetch", fake_execute_rule_fetch)

    result = rule_fetch_ops.run_rules_fetch_batch(db_session, run_all=True)

    assert result["status"] == "ok"
    assert fetched == ["A Corrupt Legacy Timestamp", "B Healthy Missing Snapshot"]
