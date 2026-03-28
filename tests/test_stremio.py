from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.models import AppSettings, MediaType, QualityProfile, Rule
from app.services.stremio import StremioService
from app.services.stremio_sync_ops import execute_stremio_sync
from tests.stremio_test_utils import create_stremio_local_storage, stremio_library_item


def _install_stremio_api(
    monkeypatch,
    *,
    items: list[dict[str, object]],
    meta_items: list[list[object]] | None = None,
) -> None:
    resolved_meta = meta_items or [[item["_id"], index + 1] for index, item in enumerate(items)]

    def fake_post_api(self, endpoint, payload):
        if endpoint == "datastoreGet":
            return items
        if endpoint == "datastoreMeta":
            return resolved_meta
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(StremioService, "_post_api", fake_post_api)


def test_stremio_service_discovers_auth_from_local_storage(monkeypatch, tmp_path) -> None:
    storage_path = create_stremio_local_storage(
        tmp_path,
        auth_key="stremio-auth",
        user_id="fedcba9876543210",
    )
    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem")],
    )

    service = StremioService(
        AppSettings(
            id="default",
            stremio_local_storage_path=str(storage_path),
            stremio_auto_sync_enabled=True,
            stremio_auto_sync_interval_seconds=30,
        )
    )

    summary = service.test_connection()

    assert summary.auth_source == "local storage"
    assert summary.local_storage_path == str(storage_path.resolve())
    assert summary.user_id == "fedcba9876543210"
    assert summary.total_item_count == 1
    assert summary.active_item_count == 1


def test_stremio_sync_creates_missing_managed_rule(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
        default_quality_profile=QualityProfile.UHD_2160P_HDR,
        default_add_paused=True,
        default_enabled=True,
        default_feed_urls=["http://feed.example/default"],
    )
    db_session.add(settings)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    summary = StremioService(settings).sync_rules(db_session)

    created_rule = db_session.scalar(
        select(Rule).where(Rule.stremio_library_item_id == "tt13016388")
    )
    assert created_rule is not None
    assert summary.created_count == 1
    assert created_rule.stremio_managed is True
    assert created_rule.media_type == MediaType.SERIES
    assert created_rule.quality_profile == QualityProfile.UHD_2160P_HDR
    assert created_rule.use_regex is True
    assert created_rule.feed_urls == ["http://feed.example/default"]
    assert created_rule.assigned_category.startswith("Series/3 Body Problem")


def test_stremio_sync_links_existing_rule_by_title(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    rule = Rule(
        rule_name="3 Body Problem Rule",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/3bp"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.linked_count == 1
    assert rule.stremio_library_item_id == "tt13016388"
    assert rule.stremio_library_item_type == "series"
    assert rule.stremio_managed is False
    assert rule.imdb_id == "tt13016388"


def test_stremio_sync_disables_completed_movie_rule_via_shared_watch_state(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    rule = Rule(
        rule_name="Hoppers Rule",
        content_name="Hoppers",
        normalized_title="Hoppers",
        imdb_id="tt26443616",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/hoppers"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt26443616", "Hoppers", item_type="movie", completed=True)],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.linked_count == 1
    assert rule.enabled is False
    assert rule.movie_completion_auto_disabled is True
    assert rule.movie_completion_sources == ["stremio"]


def test_stremio_sync_reenables_movie_rule_when_completion_clears(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    rule = Rule(
        rule_name="Hoppers Rule",
        content_name="Hoppers",
        normalized_title="Hoppers",
        imdb_id="tt26443616",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        movie_completion_auto_disabled=True,
        movie_completion_sources=["stremio"],
        stremio_library_item_id="tt26443616",
        stremio_library_item_type="movie",
        feed_urls=["http://feed.example/hoppers"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt26443616", "Hoppers", item_type="movie", completed=False)],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.reenabled_count == 1
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


def test_stremio_sync_disables_removed_managed_rule(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    rule = Rule(
        rule_name="3 Body Problem",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        imdb_id="tt13016388",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        stremio_library_item_id="tt13016388",
        stremio_library_item_type="series",
        stremio_managed=True,
        feed_urls=["http://feed.example/3bp"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(monkeypatch, items=[])

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.disabled_count == 1
    assert rule.enabled is False
    assert rule.stremio_auto_disabled is True


def test_stremio_sync_reenables_returned_managed_rule(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    rule = Rule(
        rule_name="3 Body Problem",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        imdb_id="tt13016388",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        stremio_library_item_id="tt13016388",
        stremio_library_item_type="series",
        stremio_managed=True,
        stremio_auto_disabled=True,
        feed_urls=["http://feed.example/3bp"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.reenabled_count == 1
    assert rule.enabled is True
    assert rule.stremio_auto_disabled is False


def test_stremio_sync_skips_ambiguous_title_matches(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    first_rule = Rule(
        rule_name="3 Body Problem A",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/a"],
    )
    second_rule = Rule(
        rule_name="3 Body Problem B",
        content_name="3 Body Problem",
        normalized_title="3 Body Problem",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/b"],
    )
    db_session.add(settings)
    db_session.add_all([first_rule, second_rule])
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(first_rule)
    db_session.refresh(second_rule)
    assert summary.created_count == 0
    assert summary.linked_count == 0
    assert summary.skipped_count == 1
    assert first_rule.stremio_library_item_id is None
    assert second_rule.stremio_library_item_id is None


def test_execute_stremio_sync_pushes_changed_rules_to_qb_when_configured(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    settings = AppSettings(
        id="default",
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password_encrypted="encoded",
        stremio_local_storage_path=str(storage_path),
        stremio_auto_sync_enabled=True,
        stremio_auto_sync_interval_seconds=30,
    )
    db_session.add(settings)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    pushed_rule_ids: list[str] = []

    def fake_sync_rule(self, rule_id):
        pushed_rule_ids.append(rule_id)
        return SimpleNamespace(success=True, message="Rule synced to qBittorrent.")

    monkeypatch.setattr("app.services.stremio_sync_ops.SyncService.sync_rule", fake_sync_rule)
    monkeypatch.setattr(
        "app.services.settings_service.reveal_secret",
        lambda value: "secret" if value else None,
    )

    execution = execute_stremio_sync(db_session, settings=settings)

    created_rule = db_session.scalar(
        select(Rule).where(Rule.stremio_library_item_id == "tt13016388")
    )
    assert created_rule is not None
    assert execution.qb_sync_success_count == 1
    assert pushed_rule_ids == [created_rule.id]
