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
