from __future__ import annotations

from types import SimpleNamespace

from app.db import get_session_factory
from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
from app.services import qb_recovery_scheduler
from app.services.settings_service import SettingsService


def test_recovery_scheduler_requeues_transient_qb_failures(db_session, monkeypatch) -> None:
    settings = AppSettings(id="default")
    transient_rule = Rule(
        rule_name="qB Was Down",
        content_name="qB Was Down",
        normalized_title="qB Was Down",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.ERROR,
        last_sync_error="Unable to connect to qBittorrent: connection refused",
    )
    permanent_rule = Rule(
        rule_name="Bad Credentials",
        content_name="Bad Credentials",
        normalized_title="Bad Credentials",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.ERROR,
        last_sync_error="qBittorrent rejected the provided credentials.",
    )
    db_session.add_all([settings, transient_rule, permanent_rule])
    db_session.commit()

    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(
            is_configured=True,
            base_url="http://qb.example",
            username="user",
            password="secret",
        ),
    )
    monkeypatch.setattr(
        qb_recovery_scheduler.QbittorrentClient,
        "test_connection",
        lambda self: None,
    )
    enqueued: list[str] = []
    monkeypatch.setattr(qb_recovery_scheduler, "enqueue_rule_sync", enqueued.append)

    scheduler = qb_recovery_scheduler.QbRecoveryScheduler(
        session_factory=get_session_factory(), poll_interval_seconds=5
    )
    assert scheduler.run_once() == 1

    db_session.expire_all()
    assert db_session.get(Rule, transient_rule.id).last_sync_status == SyncStatus.PENDING
    assert db_session.get(Rule, transient_rule.id).last_sync_error is None
    assert db_session.get(Rule, permanent_rule.id).last_sync_status == SyncStatus.ERROR
    assert enqueued == [transient_rule.id]


def test_recovery_scheduler_leaves_failures_when_qb_is_still_down(
    db_session, monkeypatch
) -> None:
    settings = AppSettings(id="default")
    rule = Rule(
        rule_name="Still Down",
        content_name="Still Down",
        normalized_title="Still Down",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        last_sync_status=SyncStatus.ERROR,
        last_sync_error="Unable to connect to qBittorrent: timed out",
    )
    db_session.add_all([settings, rule])
    db_session.commit()
    monkeypatch.setattr(
        SettingsService,
        "resolve_qb_connection",
        lambda settings: SimpleNamespace(
            is_configured=True,
            base_url="http://qb.example",
            username="user",
            password="secret",
        ),
    )

    def fail_connection(self) -> None:
        raise qb_recovery_scheduler.QbittorrentClientError("still unavailable")

    monkeypatch.setattr(
        qb_recovery_scheduler.QbittorrentClient, "test_connection", fail_connection
    )
    monkeypatch.setattr(
        qb_recovery_scheduler,
        "enqueue_rule_sync",
        lambda rule_id: (_ for _ in ()).throw(AssertionError("must not enqueue")),
    )

    scheduler = qb_recovery_scheduler.QbRecoveryScheduler(
        session_factory=get_session_factory(), poll_interval_seconds=5
    )
    assert scheduler.run_once() == 0
    db_session.expire_all()
    assert db_session.get(Rule, rule.id).last_sync_status == SyncStatus.ERROR
