from __future__ import annotations

from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
from app.schemas import SyncResult
from app.services import sync_queue
from app.services.sync import SyncService


def test_sync_queue_processor_marks_successful_rule_ok(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    rule = Rule(
        rule_name="Queued Success",
        content_name="Queued Success",
        normalized_title="Queued Success",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.PENDING,
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    def fake_sync_rule(self, rule_id: str, *, reconcile_feeds: bool = True) -> SyncResult:
        queued_rule = self.session.get(Rule, rule_id)
        assert queued_rule is not None
        assert queued_rule.last_sync_status == SyncStatus.SYNCING
        queued_rule.last_sync_status = SyncStatus.OK
        queued_rule.last_sync_error = None
        self.session.commit()
        return SyncResult(
            success=True,
            action="update",
            rule_id=rule_id,
            rule_name=queued_rule.rule_name,
            message="ok",
        )

    monkeypatch.setattr(SyncService, "sync_rule", fake_sync_rule)

    sync_queue._process_rule_sync(rule.id)

    db_session.expire_all()
    refreshed_rule = db_session.get(Rule, rule.id)
    assert refreshed_rule is not None
    assert refreshed_rule.last_sync_status == SyncStatus.OK
    assert refreshed_rule.last_sync_error is None


def test_sync_queue_processor_records_unexpected_failure(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    rule = Rule(
        rule_name="Queued Failure",
        content_name="Queued Failure",
        normalized_title="Queued Failure",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.PENDING,
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    def fail_sync_rule(self, rule_id: str, *, reconcile_feeds: bool = True) -> SyncResult:
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(SyncService, "sync_rule", fail_sync_rule)

    sync_queue._process_rule_sync(rule.id)

    db_session.expire_all()
    refreshed_rule = db_session.get(Rule, rule.id)
    assert refreshed_rule is not None
    assert refreshed_rule.last_sync_status == SyncStatus.ERROR
    assert refreshed_rule.last_sync_error == "worker exploded"
