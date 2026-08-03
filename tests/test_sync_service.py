from __future__ import annotations

import threading
import time

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
from app.services.sync import SyncService


def test_sync_service_skips_feed_with_broken_sample_download(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Broken Kinozal",
        content_name="Broken Kinozal",
        normalized_title="Broken Kinozal",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://localhost:9117/api/v2.0/indexers/kinozal/results/torznab/api?apikey=abc&t=search",
            "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search",
        ],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: "kinozal" not in feed_url,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert "Skipped Jackett feeds with broken sample downloads: kinozal." in result.message
    assert sent_rule_defs[0]["affectedFeeds"] == [
        "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"
    ]


def test_sync_service_checks_tracker_health_in_parallel(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Parallel Feeds",
        content_name="Parallel Feeds",
        normalized_title="Parallel Feeds",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            f"http://localhost:9117/api/v2.0/indexers/tracker{index}/results/torznab/api"
            for index in range(4)
        ],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_health_check(self, feed_url):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return "tracker0" in feed_url

    sent_rule_defs: list[dict[str, object]] = []
    monkeypatch.setattr(SyncService, "_jackett_feed_sample_download_works", slow_health_check)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.set_rule",
        lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def),
    )

    result = SyncService(db_session, settings).sync_rule(rule.id, reconcile_feeds=False)

    assert result.success is True
    assert max_active > 1
    assert sent_rule_defs[0]["affectedFeeds"] == [rule.feed_urls[0]]


def test_sync_all_compares_remote_against_health_filtered_payload(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Filtered Feeds",
        content_name="Filtered Feeds",
        normalized_title="Filtered Feeds",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://localhost:9117/api/v2.0/indexers/kinozal/results/torznab/api?apikey=abc&t=search",
            "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search",
        ],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(SyncService, "_reconcile_qb_jackett_feeds", lambda self: None)
    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: "kinozal" not in feed_url,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))
    sync = SyncService(db_session, settings)
    initial = sync.sync_rule(rule.id, reconcile_feeds=False)
    assert initial.success is True
    filtered_payload = sent_rule_defs.pop()
    monkeypatch.setattr(SyncService, "_safe_remote_rules", lambda self: {"Filtered Feeds": filtered_payload})

    result = SyncService(db_session, settings).sync_all()

    assert result.drift_detected == 0


def test_sync_service_keeps_feeds_when_all_sample_downloads_work(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Healthy Feeds",
        content_name="Healthy Feeds",
        normalized_title="Healthy Feeds",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search",
        ],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert result.message == "Rule synced to qBittorrent."
    assert sent_rule_defs[0]["affectedFeeds"] == [
        "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"
    ]


def test_sync_rule_uses_feed_urls_for_qb_payload_not_search_indexers(
    monkeypatch, db_session
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Split Scope",
        content_name="Split Scope",
        normalized_title="Split Scope",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"
        ],
        search_indexers=["kinozal"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.set_rule",
        lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def),
    )

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert sent_rule_defs[0]["affectedFeeds"] == [
        "http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"
    ]
    assert "kinozal" not in sent_rule_defs[0]["affectedFeeds"]


def test_sync_rule_persists_qb_payload_diagnostics(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="The Boys",
        content_name="The Boys",
        normalized_title="The Boys",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.UHD_2160P_HDR,
        quality_exclude_tokens=["400p"],
        use_regex=False,
        feed_urls=["http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert "400p" in sent_rule_defs[0]["mustContain"]
    assert rule.last_synced_rule_payload == sent_rule_defs[0]
    assert rule.last_remote_rule_payload == {}
    assert rule.remote_rule_drift_message == ""


def test_sync_all_marks_remote_rule_drift_before_repair(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="The Boys",
        content_name="The Boys",
        normalized_title="The Boys",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.UHD_2160P_HDR,
        quality_exclude_tokens=["400p"],
        use_regex=False,
        feed_urls=["http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []
    stale_remote_rule = {
        "enabled": True,
        "mustContain": "The Boys",
        "mustNotContain": "",
        "useRegex": False,
        "episodeFilter": "",
        "smartFilter": False,
        "affectedFeeds": [],
        "ignoreDays": 0,
        "addPaused": True,
        "assignedCategory": "Series/The Boys [imdbid-unknown]",
        "savePath": "",
    }

    monkeypatch.setattr(SyncService, "_reconcile_qb_jackett_feeds", lambda self: None)
    monkeypatch.setattr(SyncService, "_safe_remote_rules", lambda self: {"The Boys": stale_remote_rule})
    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))

    result = SyncService(db_session, settings).sync_all()

    assert result.drift_detected == 1
    assert "400p" in sent_rule_defs[0]["mustContain"]
    assert rule.last_remote_rule_payload == stale_remote_rule
    assert rule.remote_rule_drift_message == ""
    assert rule.remote_rule_drift_detected_at is None
    assert rule.last_synced_rule_payload == sent_rule_defs[0]


def test_sync_rule_success_clears_previous_active_drift(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Rick and Morty",
        content_name="Rick and Morty",
        normalized_title="Rick and Morty",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.UHD_2160P_HDR,
        use_regex=False,
        feed_urls=["http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"],
        remote_rule_drift_message="Remote qB RSS rule differed from the app-generated payload for Rick and Morty.",
        remote_rule_drift_detected_at=None,
        last_remote_rule_payload={"mustContain": "Rick and Morty"},
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    sent_rule_defs: list[dict[str, object]] = []

    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.set_rule",
        lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def),
    )

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert rule.remote_rule_drift_message == ""
    assert rule.remote_rule_drift_detected_at is None
    assert rule.last_remote_rule_payload == {"mustContain": "Rick and Morty"}
    assert rule.last_synced_rule_payload == sent_rule_defs[0]


def test_sync_all_ignores_qb_owned_remote_rule_metadata(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="The Boys",
        content_name="The Boys",
        normalized_title="The Boys",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.UHD_2160P_HDR,
        quality_exclude_tokens=["400p"],
        use_regex=False,
        feed_urls=["http://localhost:9117/api/v2.0/indexers/rutor/results/torznab/api?apikey=abc&t=search"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    monkeypatch.setattr(SyncService, "_reconcile_qb_jackett_feeds", lambda self: None)
    monkeypatch.setattr(
        SyncService,
        "_jackett_feed_sample_download_works",
        lambda self, feed_url: True,
    )
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    sent_rule_defs: list[dict[str, object]] = []
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, rule_name, rule_def: sent_rule_defs.append(rule_def))

    expected = SyncService(db_session, settings)
    expected_rule = expected.sync_rule(rule.id, reconcile_feeds=False)
    assert expected_rule.success is True
    app_payload = sent_rule_defs.pop()
    remote_payload = {
        **app_payload,
        "lastMatch": "",
        "previouslyMatchedEpisodes": [],
        "priority": 0,
        "torrentParams": app_payload["torrentParams"],
    }
    monkeypatch.setattr(SyncService, "_safe_remote_rules", lambda self: {"The Boys": remote_payload})

    result = SyncService(db_session, settings).sync_all()

    assert result.drift_detected == 0
    assert rule.remote_rule_drift_message == ""


def test_sync_disabled_rule_removes_remote_rule_and_unused_categories(
    monkeypatch, db_session
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Hoppers Rule",
        content_name="Hoppers",
        normalized_title="Hoppers",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        remote_rule_name_last_synced="Hoppers Rule",
        last_synced_rule_payload={"enabled": True},
        remote_rule_drift_message="stale drift",
        last_remote_rule_payload={"enabled": True},
        last_sync_status=SyncStatus.OK,
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    calls: list[str] = []

    monkeypatch.setattr(
        SyncService,
        "_reconcile_qb_jackett_feeds",
        lambda self: calls.append("reconcile"),
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.create_category",
        lambda self, name: calls.append(f"create:{name}"),
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.set_rule",
        lambda self, rule_name, rule_def: calls.append(f"set:{rule_name}"),
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.remove_rule",
        lambda self, rule_name: calls.append(f"remove:{rule_name}"),
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.remove_unused_categories",
        lambda self: calls.append("remove-unused") or ["Movies/Hoppers"],
    )

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert calls == ["remove:Hoppers Rule", "remove-unused"]
    assert rule.remote_rule_name_last_synced is None
    assert rule.last_synced_rule_payload == {}
    assert rule.remote_rule_drift_message == ""
    assert rule.last_remote_rule_payload == {}
    assert rule.last_sync_status == SyncStatus.OK
    assert "removed from qBittorrent" in result.message


def test_sync_disabled_rule_removes_same_name_remote_rule_without_marker(
    monkeypatch,
    db_session,
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    rule = Rule(
        rule_name="Finished Without Marker",
        content_name="Finished Without Marker",
        normalized_title="Finished Without Marker",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        remote_rule_name_last_synced=None,
        last_synced_rule_payload={"enabled": True},
        last_remote_rule_payload={"enabled": True},
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    calls: list[str] = []

    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.get_rules",
        lambda self: {"Finished Without Marker": {"enabled": True}},
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.remove_rule",
        lambda self, rule_name: calls.append(f"remove:{rule_name}"),
    )
    monkeypatch.setattr(
        "app.services.sync.QbittorrentClient.remove_unused_categories",
        lambda self: calls.append("remove-unused") or [],
    )

    result = SyncService(db_session, settings).sync_rule(rule.id)

    assert result.success is True
    assert calls == ["remove:Finished Without Marker", "remove-unused"]
    assert rule.remote_rule_name_last_synced is None
    assert rule.last_synced_rule_payload == {}
    assert rule.last_remote_rule_payload == {}


def test_sync_all_cleans_disabled_rules_instead_of_recreating_them(monkeypatch, db_session) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
    )
    disabled_rule = Rule(
        rule_name="Disabled Finished Movie",
        content_name="Disabled Finished Movie",
        normalized_title="Disabled Finished Movie",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        remote_rule_name_last_synced="Disabled Finished Movie",
    )
    enabled_rule = Rule(
        rule_name="Enabled Movie",
        content_name="Enabled Movie",
        normalized_title="Enabled Movie",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
    )
    db_session.add_all([settings, disabled_rule, enabled_rule])
    db_session.commit()

    synced_ids: list[str] = []

    monkeypatch.setattr(SyncService, "_reconcile_qb_jackett_feeds", lambda self: None)
    monkeypatch.setattr(SyncService, "_safe_remote_rules", lambda self: {})
    original_sync_rule = SyncService.sync_rule

    def fake_sync_rule(self, rule_id: str, *, reconcile_feeds: bool = True):
        synced_ids.append(rule_id)
        return original_sync_rule(self, rule_id, reconcile_feeds=reconcile_feeds)

    monkeypatch.setattr(SyncService, "sync_rule", fake_sync_rule)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.remove_rule", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.remove_unused_categories", lambda self: [])
    monkeypatch.setattr("app.services.sync.QbittorrentClient.create_category", lambda self, name: None)
    monkeypatch.setattr("app.services.sync.QbittorrentClient.set_rule", lambda self, name, payload: None)

    result = SyncService(db_session, settings).sync_all()

    assert result.success_count == 2
    assert synced_ids == [disabled_rule.id, enabled_rule.id]
    assert disabled_rule.remote_rule_name_last_synced is None
