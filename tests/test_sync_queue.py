from __future__ import annotations

from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
from app.schemas import SyncResult
from app.services import operation_status, sync_queue
from app.services.sync import SyncService


class _RecordingExecutor:
    def __init__(self) -> None:
        self.submitted: list[tuple[object, str]] = []

    def submit(self, fn, rule_id: str) -> None:
        self.submitted.append((fn, rule_id))


def test_sync_queue_processor_marks_successful_rule_ok(
    db_session,
    monkeypatch,
) -> None:
    operation_status.reset_operations_for_tests()
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
    payload = operation_status.operations_status_payload()
    assert payload["operations"][0]["type"] == "qb_sync"
    assert payload["operations"][0]["status"] == "success"
    assert payload["operations"][0]["current"] == 1
    assert payload["operations"][0]["total"] == 1
    operation_status.reset_operations_for_tests()


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


def test_sync_queue_worker_skips_per_rule_feed_reconciliation(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    rule = Rule(
        rule_name="Queued Batch Item",
        content_name="Queued Batch Item",
        normalized_title="Queued Batch Item",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.PENDING,
    )
    db_session.add_all([settings, rule])
    db_session.commit()
    reconcile_flags: list[bool] = []

    def fake_sync_rule(self, rule_id: str, *, reconcile_feeds: bool = True) -> SyncResult:
        reconcile_flags.append(reconcile_feeds)
        queued_rule = self.session.get(Rule, rule_id)
        assert queued_rule is not None
        queued_rule.last_sync_status = SyncStatus.OK
        self.session.commit()
        return SyncResult(
            success=True,
            action="update",
            rule_id=rule_id,
            rule_name=queued_rule.rule_name,
            message="ok",
        )

    monkeypatch.setattr(SyncService, "sync_rule", fake_sync_rule)

    sync_queue._process_and_finalize(rule.id)

    assert reconcile_flags == [False]


def test_sync_queue_prepares_feed_reconciliation_once_for_batch(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    rules = [
        Rule(
            rule_name=f"Queued Prep {index}",
            content_name=f"Queued Prep {index}",
            normalized_title=f"Queued Prep {index}",
            media_type=MediaType.SERIES,
            quality_profile=QualityProfile.PLAIN,
            last_sync_status=SyncStatus.PENDING,
        )
        for index in range(2)
    ]
    db_session.add(settings)
    db_session.add_all(rules)
    db_session.commit()
    prepared_rule_names: list[list[str]] = []
    reconcile_calls = 0

    def fake_refresh_language_feeds_for_rules(self, queued_rules):
        prepared_rule_names.append([rule.rule_name for rule in queued_rules])

    def fake_reconcile_qb_jackett_feeds(self):
        nonlocal reconcile_calls
        reconcile_calls += 1

    monkeypatch.setattr(
        SyncService,
        "_refresh_language_feeds_for_rules",
        fake_refresh_language_feeds_for_rules,
    )
    monkeypatch.setattr(
        SyncService,
        "_reconcile_qb_jackett_feeds",
        fake_reconcile_qb_jackett_feeds,
    )

    sync_queue._prepare_queued_rule_syncs([rule.id for rule in rules])

    assert prepared_rule_names == [["Queued Prep 0", "Queued Prep 1"]]
    assert reconcile_calls == 1


def test_sync_queue_updates_progress_after_refilling_worker_slot(monkeypatch) -> None:
    operation_status.reset_operations_for_tests()
    executor = _RecordingExecutor()
    handle = operation_status.start_operation(
        operation_type="qb_sync",
        label="Syncing qBittorrent rules",
        total=3,
        current=1,
        message="qB sync 1/3 completed; 2 active, 1 queued.",
    )
    monkeypatch.setattr(sync_queue, "_EXECUTOR", executor)
    monkeypatch.setattr(sync_queue, "_QUEUE_OPERATION_ID", handle.operation_id)
    monkeypatch.setattr(sync_queue, "_TOTAL_ENQUEUED", 3)
    monkeypatch.setattr(sync_queue, "_TOTAL_COMPLETED", 1)
    monkeypatch.setattr(sync_queue, "_TOTAL_FAILED", 0)
    monkeypatch.setattr(sync_queue, "_ACTIVE_TASKS", 2)
    monkeypatch.setattr(sync_queue, "_ADAPTIVE_WORKER_LIMIT", 3)
    sync_queue._QUEUED_RULE_IDS.clear()
    sync_queue._QUEUED_RULE_ID_SET.clear()
    sync_queue._QUEUED_RULE_IDS.append("third-rule")
    sync_queue._QUEUED_RULE_ID_SET.add("third-rule")

    with sync_queue._QUEUE_CONDITION:
        assert sync_queue._dispatch_next_rule_sync_locked() is True

    payload = operation_status.operations_status_payload()
    assert executor.submitted == [(sync_queue._process_and_finalize, "third-rule")]
    assert payload["operations"][0]["message"] == (
        "qB sync 1/3 completed; 3 active (limit 3), 0 queued."
    )
    operation_status.reset_operations_for_tests()


def test_sync_queue_adaptive_limit_ramps_up_after_successes(monkeypatch) -> None:
    monkeypatch.setattr(sync_queue, "_ADAPTIVE_WORKER_LIMIT", 3)
    monkeypatch.setattr(sync_queue, "_SYNC_SUCCESS_STREAK", 0)

    for _ in range(sync_queue._SYNC_SUCCESS_STREAK_TO_INCREASE):
        sync_queue._record_sync_outcome_locked(sync_queue.RuleSyncOutcome(success=True))

    assert sync_queue._ADAPTIVE_WORKER_LIMIT == 4
    assert sync_queue._SYNC_SUCCESS_STREAK == 0


def test_sync_queue_adaptive_limit_backs_off_on_timeout_failure(monkeypatch) -> None:
    monkeypatch.setattr(sync_queue, "_ADAPTIVE_WORKER_LIMIT", 12)
    monkeypatch.setattr(sync_queue, "_SYNC_SUCCESS_STREAK", 5)

    sync_queue._record_sync_outcome_locked(
        sync_queue.RuleSyncOutcome(success=False, should_backoff=True)
    )

    assert sync_queue._ADAPTIVE_WORKER_LIMIT == 6
    assert sync_queue._SYNC_SUCCESS_STREAK == 0


def test_sync_queue_dispatch_uses_adaptive_limit(monkeypatch) -> None:
    operation_status.reset_operations_for_tests()
    executor = _RecordingExecutor()
    handle = operation_status.start_operation(
        operation_type="qb_sync",
        label="Syncing qBittorrent rules",
        total=6,
        current=1,
        message="qB sync 1/6 completed.",
    )
    monkeypatch.setattr(sync_queue, "_EXECUTOR", executor)
    monkeypatch.setattr(sync_queue, "_QUEUE_OPERATION_ID", handle.operation_id)
    monkeypatch.setattr(sync_queue, "_TOTAL_ENQUEUED", 6)
    monkeypatch.setattr(sync_queue, "_TOTAL_COMPLETED", 1)
    monkeypatch.setattr(sync_queue, "_TOTAL_FAILED", 0)
    monkeypatch.setattr(sync_queue, "_ACTIVE_TASKS", 4)
    monkeypatch.setattr(sync_queue, "_ADAPTIVE_WORKER_LIMIT", 5)
    sync_queue._QUEUED_RULE_IDS.clear()
    sync_queue._QUEUED_RULE_ID_SET.clear()
    sync_queue._QUEUED_RULE_IDS.append("fifth-rule")
    sync_queue._QUEUED_RULE_ID_SET.add("fifth-rule")

    with sync_queue._QUEUE_CONDITION:
        assert sync_queue._dispatch_next_rule_sync_locked() is True
        assert sync_queue._dispatch_next_rule_sync_locked() is False

    payload = operation_status.operations_status_payload()
    assert executor.submitted == [(sync_queue._process_and_finalize, "fifth-rule")]
    assert payload["operations"][0]["message"] == (
        "qB sync 1/6 completed; 5 active (limit 5), 0 queued."
    )
    operation_status.reset_operations_for_tests()
