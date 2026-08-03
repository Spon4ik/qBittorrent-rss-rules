from __future__ import annotations

import os
from types import SimpleNamespace

from sqlalchemy import select

from app.models import AppSettings, MediaType, QualityProfile, Rule
from app.services import operation_status
from app.services.series_catalog import SeriesSeasonEpisodeInventory
from app.services.stremio import StremioService, StremioSessionDoesNotExistError
from app.services.stremio_sync_ops import execute_stremio_sync
from app.services.watch_progress_sync import WatchProgressSyncSummary
from app.services.watch_state import WatchProgressRecord
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


def test_execute_stremio_sync_records_operation_progress(db_session, monkeypatch) -> None:
    operation_status.reset_operations_for_tests()
    settings = AppSettings(id="default")
    db_session.add(settings)
    db_session.commit()

    def fake_sync_rules(self, session):
        return type(
            "Summary",
            (),
            {
                "active_item_count": 5,
                "created_count": 1,
                "linked_count": 1,
                "updated_count": 1,
                "disabled_count": 0,
                "reenabled_count": 0,
                "unchanged_count": 2,
                "skipped_count": 0,
                "error_count": 0,
                "outcomes": [],
            },
        )()

    monkeypatch.setattr(StremioService, "sync_rules", fake_sync_rules)

    execute_stremio_sync(db_session, settings=settings)

    payload = operation_status.operations_status_payload()
    assert payload["operations"][0]["type"] == "stremio_sync"
    assert payload["operations"][0]["status"] == "success"
    assert payload["operations"][0]["current"] == 5
    assert payload["operations"][0]["total"] == 5
    operation_status.reset_operations_for_tests()


def test_execute_stremio_sync_runs_watch_progress_when_configured(db_session, monkeypatch) -> None:
    operation_status.reset_operations_for_tests()
    settings = AppSettings(id="default")
    db_session.add(settings)
    db_session.commit()
    calls: list[str] = []

    def fake_sync_rules(self, session):
        return type(
            "Summary",
            (),
            {
                "active_item_count": 5,
                "created_count": 0,
                "linked_count": 0,
                "updated_count": 0,
                "disabled_count": 0,
                "reenabled_count": 0,
                "unchanged_count": 5,
                "skipped_count": 0,
                "error_count": 0,
                "outcomes": [],
            },
        )()

    def fake_sync_watch_progress(session, *, settings=None):
        calls.append(settings.id)
        return WatchProgressSyncSummary(
            jellyfin_read_count=1,
            stremio_read_count=1,
            matched_count=1,
            jellyfin_write_count=1,
            stremio_write_count=0,
            skipped_count=0,
            error_count=0,
            messages=[],
        )

    monkeypatch.setattr(StremioService, "sync_rules", fake_sync_rules)
    monkeypatch.setattr("app.services.stremio_sync_ops.can_sync_watch_progress", lambda settings: True)
    monkeypatch.setattr("app.services.stremio_sync_ops.sync_watch_progress", fake_sync_watch_progress)

    execution = execute_stremio_sync(db_session, settings=settings)

    assert calls == ["default"]
    assert execution.watch_progress_summary is not None
    assert "1 watch-progress writes" in execution.detail_fragments()
    operation_status.reset_operations_for_tests()


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


def test_stremio_collect_watch_progress_reads_movie_and_episode_positions(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)

    def fake_fetch(_auth_key: str) -> list[dict[str, object]]:
        return [
            stremio_library_item(
                "tt1234567",
                "Movie",
                item_type="movie",
                state_overrides={
                    "timeWatched": 180_000,
                    "overallTimeWatched": 180_000,
                    "duration": 3_600_000,
                    "lastWatched": "2026-05-26T10:05:00.000Z",
                },
            ),
            stremio_library_item(
                "tt7654321",
                "Series",
                item_type="series",
                state_overrides={
                    "video_id": "tt7654321:1:2",
                    "timeWatched": 420_000,
                    "duration": 2_400_000,
                    "lastWatched": "2026-05-26T10:10:00.000Z",
                },
            ),
        ]

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", fake_fetch)

    records = service.collect_watch_progress()

    assert [record.item_key for record in records] == ["tt1234567", "tt7654321:S01E02"]
    assert records[0].position_ms == 180_000
    assert records[0].duration_ms == 3_600_000
    assert records[1].provider_video_id == "tt7654321:1:2"
    assert records[1].updated_at is not None


def test_stremio_collect_watch_progress_includes_active_series_without_progress(
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)

    def fake_fetch(_auth_key: str) -> list[dict[str, object]]:
        return [
            stremio_library_item(
                "tt11815682",
                "Hacks",
                item_type="series",
                state_overrides={},
            )
        ]

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", fake_fetch)

    records = service.collect_watch_progress()

    assert len(records) == 1
    assert records[0].source == "stremio"
    assert records[0].media_type == "episode"
    assert records[0].item_key == "tt11815682:S00E00"
    assert records[0].provider_item_id == "tt11815682"
    assert records[0].position_ms == 0
    assert records[0].completed is False


def test_stremio_write_watch_progress_preserves_existing_state(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    writes: list[tuple[str, dict[str, object]]] = []

    payload = stremio_library_item(
        "tt1234567",
        "Movie",
        item_type="movie",
        state_overrides={"custom": "keep-me", "duration": 3_600_000},
    )

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", lambda _auth_key: [payload])
    monkeypatch.setattr(
        service,
        "_write_library_item_payload",
        lambda auth_key, updated_payload: writes.append((auth_key, updated_payload)),
    )

    service.write_watch_progress(
        WatchProgressRecord(
            source="jellyfin",
            media_type="movie",
            item_key="tt1234567",
            provider_item_id="jf-movie",
            position_ms=240_000,
            duration_ms=3_600_000,
            completed=False,
            updated_at=None,
        )
    )

    assert writes[0][0] == "key"
    assert writes[0][1]["state"]["custom"] == "keep-me"
    assert writes[0][1]["state"]["timeWatched"] == 240_000
    assert writes[0][1]["state"]["overallTimeWatched"] == 240_000


def test_stremio_write_unwatched_movie_clears_stale_completion_markers(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    writes: list[dict[str, object]] = []
    payload = stremio_library_item(
        "tt30825738",
        "Star Wars: The Mandalorian and Grogu",
        item_type="movie",
        state_overrides={
            "flaggedWatched": 1,
            "timesWatched": 1,
            "watched": "undefined:1:eJwDAAAAAAE=",
            "timeWatched": 72_000,
            "overallTimeWatched": 72_000,
            "duration": 7_915_520,
        },
    )

    monkeypatch.setattr(
        service,
        "_run_with_auth_fallback",
        lambda operation: ("auth", operation("key")),
    )
    monkeypatch.setattr(service, "_fetch_library_payloads", lambda _auth_key: [payload])
    monkeypatch.setattr(
        service,
        "_write_library_item_payload",
        lambda _auth_key, updated_payload: writes.append(updated_payload),
    )

    service.write_watch_progress(
        WatchProgressRecord(
            source="jellyfin",
            media_type="movie",
            item_key="tt30825738",
            provider_item_id="jf-grogu",
            position_ms=72_000,
            duration_ms=7_915_520,
            completed=False,
            updated_at=None,
        )
    )

    state = writes[0]["state"]
    assert state["flaggedWatched"] == 0
    assert state["timesWatched"] == 0
    assert state["watched"] == ""
    assert not service._watch_progress_record_from_payload(writes[0]).completed


def test_stremio_write_watch_progress_sets_episode_video_id_from_item_key(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    writes: list[dict[str, object]] = []
    payload = stremio_library_item(
        "tt1190634",
        "The Boys",
        item_type="series",
        state_overrides={"video_id": "tt1190634:4:8", "duration": 3_600_000},
    )

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", lambda _auth_key: [payload])
    monkeypatch.setattr(
        service,
        "_write_library_item_payload",
        lambda _auth_key, updated_payload: writes.append(updated_payload),
    )

    service.write_watch_progress(
        WatchProgressRecord(
            source="jellyfin",
            media_type="episode",
            item_key="tt1190634:S05E05",
            provider_item_id="jf-boys-s05e05",
            position_ms=1_080_000,
            duration_ms=3_600_000,
            completed=False,
            updated_at=None,
        )
    )

    assert writes[0]["state"]["video_id"] == "tt1190634:5:5"
    assert writes[0]["state"]["timeWatched"] == 1_080_000


def test_stremio_write_watch_progress_marks_series_episode_not_whole_series(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    writes: list[dict[str, object]] = []
    payload = stremio_library_item(
        "tt1190634",
        "The Boys",
        item_type="series",
        state_overrides={
            "video_id": "tt1190634:4:8",
            "watched": "",
            "flaggedWatched": 1,
            "timesWatched": 1,
            "duration": 3_600_000,
        },
    )

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", lambda _auth_key: [payload])
    monkeypatch.setattr(
        service,
        "_write_library_item_payload",
        lambda _auth_key, updated_payload: writes.append(updated_payload),
    )
    monkeypatch.setattr(
        service,
        "_series_video_ids",
        lambda imdb_id: ["tt1190634:5:1", "tt1190634:5:2", "tt1190634:5:5"],
    )

    service.write_watch_progress(
        WatchProgressRecord(
            source="jellyfin",
            media_type="episode",
            item_key="tt1190634:S05E05",
            provider_item_id="jf-boys-s05e05",
            position_ms=3_600_000,
            duration_ms=3_600_000,
            completed=True,
            updated_at=None,
        )
    )

    state = writes[0]["state"]
    assert state["flaggedWatched"] == 0
    assert state["timesWatched"] == 0
    assert state["watched"].startswith("tt1190634:5:5:3:")
    assert service._watched_bitfield_get_video(state["watched"], ["tt1190634:5:1", "tt1190634:5:2", "tt1190634:5:5"], "tt1190634:5:5")


def test_stremio_collect_watch_progress_ignores_whole_series_watched_flags_for_episode(monkeypatch) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    payload = stremio_library_item(
        "tt1190634",
        "The Boys",
        item_type="series",
        state_overrides={
            "video_id": "tt1190634:5:5",
            "watched": "tt1190634:4:8:95:eJxjYACDhv///9czAAAP/wP9",
            "flaggedWatched": 1,
            "timesWatched": 1,
            "timeWatched": 1_080_000,
            "overallTimeWatched": 1_080_000,
            "duration": 0,
        },
    )

    monkeypatch.setattr(
        service,
        "_series_video_ids",
        lambda imdb_id: ["tt1190634:5:1", "tt1190634:5:2", "tt1190634:5:5"],
    )

    record = service._watch_progress_record_from_payload(payload)

    assert record is not None
    assert record.item_key == "tt1190634:S05E05"
    assert not record.completed


def test_stremio_write_watch_progress_clears_episode_bit_for_in_progress_record(
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    service = StremioService(settings)
    monkeypatch.setattr(
        service,
        "_series_video_ids",
        lambda imdb_id: ["tt1190634:5:1", "tt1190634:5:2", "tt1190634:5:5"],
    )
    existing_watched = service._watched_bitfield_set_video(
        "",
        "tt1190634",
        "tt1190634:5:5",
        True,
    )
    payload = stremio_library_item(
        "tt1190634",
        "The Boys",
        item_type="series",
        state_overrides={
            "video_id": "tt1190634:5:5",
            "watched": existing_watched,
            "flaggedWatched": 0,
            "timesWatched": 0,
        },
    )
    writes: list[dict[str, object]] = []

    monkeypatch.setattr(service, "_run_with_auth_fallback", lambda operation: ("auth", operation("key")))
    monkeypatch.setattr(service, "_fetch_library_payloads", lambda _auth_key: [payload])
    monkeypatch.setattr(
        service,
        "_write_library_item_payload",
        lambda _auth_key, updated_payload: writes.append(updated_payload),
    )
    service.write_watch_progress(
        WatchProgressRecord(
            source="jellyfin",
            media_type="episode",
            item_key="tt1190634:S05E05",
            provider_item_id="jf-boys-s05e05",
            position_ms=1_080_566,
            duration_ms=None,
            completed=False,
            updated_at=None,
        )
    )

    state = writes[0]["state"]
    assert not service._watched_bitfield_get_video(
        state["watched"],
        ["tt1190634:5:1", "tt1190634:5:2", "tt1190634:5:5"],
        "tt1190634:5:5",
    )


def test_stremio_service_retries_older_local_auth_when_newest_session_is_stale(
    monkeypatch, tmp_path
) -> None:
    storage_path = create_stremio_local_storage(
        tmp_path,
        auth_key="fresh-but-stale",
        user_id="fedcba9876543210",
    )
    older_payload = (
        '\x00noise{"auth":{"key":"older-valid","user":{"_id":"0123456789abcdef"}}}\x00tail'
    )
    older_file = storage_path / "000000.ldb"
    older_file.write_bytes(older_payload.encode("utf-8"))
    stale_file = storage_path / "000001.ldb"
    os.utime(older_file, (1_700_000_000, 1_700_000_000))
    os.utime(stale_file, (1_700_000_100, 1_700_000_100))

    seen_auth_keys: list[str] = []

    def fake_post_api(self, endpoint, payload):
        assert endpoint == "datastoreGet"
        seen_auth_keys.append(str(payload["authKey"]))
        if payload["authKey"] == "fresh-but-stale":
            raise StremioSessionDoesNotExistError(
                "Stremio API datastoreGet failed: Session does not exist"
            )
        return [stremio_library_item("tt13016388", "3 Body Problem")]

    monkeypatch.setattr(StremioService, "_post_api", fake_post_api)

    service = StremioService(
        AppSettings(
            id="default",
            stremio_local_storage_path=str(storage_path),
            stremio_auto_sync_enabled=True,
            stremio_auto_sync_interval_seconds=30,
        )
    )

    summary = service.test_connection()

    assert seen_auth_keys == ["fresh-but-stale", "older-valid"]
    assert summary.auth_source == "local storage"
    assert summary.user_id == "0123456789abcdef"
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


def test_stremio_sync_preserves_manually_edited_managed_rule_titles(
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
        rule_name="Custom Grogu Rule",
        content_name="My Grogu Title",
        normalized_title="Grogu Search Title",
        imdb_id="tt30825738",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        stremio_library_item_id="tt30825738",
        stremio_library_item_type="movie",
        stremio_managed=True,
        feed_urls=["http://feed.example/grogu"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt30825738",
                "Star Wars: The Mandalorian and Grogu",
                item_type="movie",
            )
        ],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.unchanged_count == 1
    assert rule.content_name == "My Grogu Title"
    assert rule.normalized_title == "Grogu Search Title"


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


def test_stremio_sync_disables_finished_series_when_latest_known_episode_is_watched(
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
        rule_name="Finished Show Rule",
        content_name="Finished Show",
        normalized_title="Finished Show",
        imdb_id="tt1234500",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/finished-show"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(
        StremioService,
        "_released_episode_numbers_for_season",
        lambda self, **kwargs: [1, 2, 3] if kwargs["season_number"] == 1 else None,
    )
    monkeypatch.setattr(
        StremioService,
        "_known_episode_numbers_for_season",
        lambda self, **kwargs: [1, 2, 3] if kwargs["season_number"] == 1 else None,
    )
    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt1234500",
                "Finished Show",
                item_type="series",
                state_overrides={"video_id": "tt1234500:1:3"},
            )
        ],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.disabled_count == 1
    assert rule.enabled is False
    assert rule.movie_completion_auto_disabled is True
    assert rule.movie_completion_sources == ["stremio"]


def test_stremio_sync_keeps_series_enabled_when_later_episode_is_planned(
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
        rule_name="Planned Episode Rule",
        content_name="Planned Episode Show",
        normalized_title="Planned Episode Show",
        imdb_id="tt39378684",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/planned-episode"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(
        StremioService,
        "_released_episode_numbers_for_season",
        lambda self, **kwargs: list(range(1, 8)) if kwargs["season_number"] == 1 else None,
    )
    monkeypatch.setattr(
        StremioService,
        "_known_episode_numbers_for_season",
        lambda self, **kwargs: list(range(1, 9)) if kwargs["season_number"] == 1 else None,
    )
    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt39378684",
                "Planned Episode Show",
                item_type="series",
                state_overrides={"video_id": "tt39378684:1:7"},
            )
        ],
    )

    summary = StremioService(settings).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.linked_count == 1
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


def test_stremio_sync_keeps_series_enabled_when_catalog_evidence_is_missing(
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
        rule_name="Still Open Show Rule",
        content_name="Still Open Show",
        normalized_title="Still Open Show",
        imdb_id="tt7777000",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/still-open-show"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.series_catalog.SeriesCatalogClient.season_inventory",
        lambda self, **kwargs: None,
    )
    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt7777000",
                "Still Open Show",
                item_type="series",
                state_overrides={"video_id": "tt7777000:1:3"},
            )
        ],
    )

    summary = StremioService(settings, allow_metadata_requests=False).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.linked_count == 1
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


def test_stremio_sync_reenables_auto_disabled_series_when_next_season_is_known(
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
        rule_name="Revived Show Rule",
        content_name="Revived Show",
        normalized_title="Revived Show",
        imdb_id="tt7777001",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        movie_completion_auto_disabled=True,
        movie_completion_sources=["stremio"],
        stremio_library_item_id="tt7777001",
        stremio_library_item_type="series",
        feed_urls=["http://feed.example/revived-show"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    def fake_inventory(self, *, imdb_id, season_number):
        if season_number == 1:
            return SeriesSeasonEpisodeInventory(
                imdb_id=imdb_id,
                season_number=1,
                known_episode_numbers=[1, 2, 3],
                released_episode_numbers=[1, 2, 3],
                source="Cinemeta",
            )
        if season_number == 2:
            return SeriesSeasonEpisodeInventory(
                imdb_id=imdb_id,
                season_number=2,
                known_episode_numbers=[1],
                released_episode_numbers=[],
                source="Cinemeta",
            )
        return None

    monkeypatch.setattr(
        "app.services.series_catalog.SeriesCatalogClient.season_inventory",
        fake_inventory,
    )
    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt7777001",
                "Revived Show",
                item_type="series",
                state_overrides={"video_id": "tt7777001:1:3"},
            )
        ],
    )

    summary = StremioService(settings, allow_metadata_requests=False).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.reenabled_count == 1
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


def test_stremio_sync_reenables_auto_disabled_series_when_catalog_says_continuing(
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
        rule_name="Continuing Show Rule",
        content_name="Continuing Show",
        normalized_title="Continuing Show",
        imdb_id="tt7777002",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        movie_completion_auto_disabled=True,
        movie_completion_sources=["stremio"],
        stremio_library_item_id="tt7777002",
        stremio_library_item_type="series",
        feed_urls=["http://feed.example/continuing-show"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(
        StremioService,
        "_released_episode_numbers_for_season",
        lambda self, **kwargs: list(range(1, 9)) if kwargs["season_number"] == 15 else None,
    )
    monkeypatch.setattr(
        StremioService,
        "_known_episode_numbers_for_season",
        lambda self, **kwargs: list(range(1, 9)) if kwargs["season_number"] == 15 else None,
    )
    monkeypatch.setattr(
        "app.services.series_catalog.SeriesCatalogClient.series_is_known_ended",
        lambda self, imdb_id: False,
    )
    _install_stremio_api(
        monkeypatch,
        items=[
            stremio_library_item(
                "tt7777002",
                "Continuing Show",
                item_type="series",
                state_overrides={"video_id": "tt7777002:15:8"},
            )
        ],
    )

    summary = StremioService(settings, allow_metadata_requests=False).sync_rules(db_session)

    db_session.refresh(rule)
    assert summary.reenabled_count == 1
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


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
