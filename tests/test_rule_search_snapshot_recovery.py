from __future__ import annotations

from sqlalchemy import text

from app.models import MediaType, QualityProfile, Rule, utcnow
from app.schemas import JackettSearchRequest, JackettSearchRun
from app.services.rule_search_snapshots import save_rule_search_snapshot


def test_save_snapshot_overwrites_corrupt_legacy_row_without_deserializing_old_values(
    db_session,
) -> None:
    rule = Rule(
        rule_name="Snapshot Recovery",
        content_name="Snapshot Recovery",
        normalized_title="Snapshot Recovery",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    db_session.add(rule)
    db_session.flush()
    db_session.execute(
        text(
            "INSERT INTO rule_search_snapshots "
            "(rule_id, payload, inline_search, fetched_at, created_at, updated_at) "
            "VALUES (:rule_id, '{\"truncated\":', '{\"truncated\":', "
            "'not-a-timestamp', :now, :now)"
        ),
        {"rule_id": rule.id, "now": utcnow()},
    )
    db_session.commit()

    snapshot = save_rule_search_snapshot(
        db_session,
        rule_id=rule.id,
        payload=JackettSearchRequest(query="Snapshot Recovery"),
        run=JackettSearchRun(),
        ignored_full_regex=False,
    )
    db_session.commit()

    assert snapshot.rule_id == rule.id
    assert snapshot.payload["query"] == "Snapshot Recovery"
    assert snapshot.inline_search["query"] == "Snapshot Recovery"
    assert snapshot.fetched_at is not None
    assert snapshot.release_filter_cache_key is None
    assert snapshot.release_filtered_count is None
    assert snapshot.release_fetched_count is None
