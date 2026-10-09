from __future__ import annotations

import threading

from app.models import MediaType, QualityProfile, Rule
from app.services import rule_fetch_queue
from app.services.rule_fetch_ops import select_due_rule_fetches


def test_rule_fetch_queue_joins_active_work_on_shutdown(db_session, monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_fetch(*args, **kwargs):
        started.set()
        release.wait()
        finished.set()
        return {"status": "complete"}

    monkeypatch.setattr(rule_fetch_queue, "run_rules_fetch_batch", blocking_fetch)
    rule_fetch_queue.start_rule_fetch_queue()
    rule = Rule(
        rule_name="Queue Shutdown Fixture",
        content_name="Queue Shutdown Fixture",
        normalized_title="Queue Shutdown Fixture",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    db_session.add(rule)
    db_session.commit()
    try:
        assert rule_fetch_queue.enqueue_rule_fetch(rule.id) is True
        assert started.wait(timeout=1.0)
        assert rule_fetch_queue.enqueue_rule_fetch(rule.id) is False
        release.set()
        rule_fetch_queue.stop_rule_fetch_queue()
    finally:
        release.set()
        rule_fetch_queue.stop_rule_fetch_queue()

    assert finished.is_set()
    assert rule_fetch_queue._WORKER is None
    assert not any(thread.name == "rule-fetch-queue" for thread in threading.enumerate())


def test_stopped_queue_leaves_missing_snapshot_recoverable(db_session) -> None:
    rule = Rule(
        rule_name="Durable Missing Snapshot",
        content_name="Durable Missing Snapshot",
        normalized_title="Durable Missing Snapshot",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    db_session.add(rule)
    db_session.commit()

    rule_fetch_queue.stop_rule_fetch_queue()
    assert rule_fetch_queue.enqueue_rule_fetch(rule.id) is False

    recovered = select_due_rule_fetches(db_session)
    assert [item.rule_id for item in recovered] == [rule.id]
