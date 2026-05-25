from __future__ import annotations

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule
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
        "torrentParams": {"category": app_payload["assignedCategory"], "stopped": True},
    }
    monkeypatch.setattr(SyncService, "_safe_remote_rules", lambda self: {"The Boys": remote_payload})

    result = SyncService(db_session, settings).sync_all()

    assert result.drift_detected == 0
    assert rule.remote_rule_drift_message == ""
