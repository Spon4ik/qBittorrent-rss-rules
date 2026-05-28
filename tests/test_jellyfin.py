from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule
from app.services import operation_status
from app.services.jellyfin import JellyfinError, JellyfinService
from app.services.jellyfin_sync_ops import execute_jellyfin_sync
from app.services.watch_progress_sync import WatchProgressSyncSummary
from app.services.watch_state import WatchProgressRecord
from tests.jellyfin_test_utils import (
    add_jellyfin_episode,
    add_jellyfin_movie,
    add_jellyfin_series,
    add_jellyfin_user,
    add_jellyfin_userdata,
    create_jellyfin_test_db,
)

SENTINEL_ITEM_ID = "00000000-0000-0000-0000-000000000001"
PRIMARY_USER_ID = "7144A9EC-B152-4999-8363-8953F3F709C8"


def test_execute_jellyfin_sync_records_operation_progress(db_session, monkeypatch) -> None:
    operation_status.reset_operations_for_tests()
    settings = AppSettings(id="default")
    db_session.add(settings)
    db_session.commit()

    def fake_sync_rules(self, session):
        return type(
            "Summary",
            (),
            {
                "user_name": "Spon4ik",
                "synced_count": 1,
                "unchanged_count": 2,
                "skipped_count": 3,
                "error_count": 0,
                "outcomes": [],
            },
        )()

    monkeypatch.setattr(JellyfinService, "sync_rules", fake_sync_rules)

    execute_jellyfin_sync(db_session, settings=settings)

    payload = operation_status.operations_status_payload()
    assert payload["operations"][0]["type"] == "jellyfin_sync"
    assert payload["operations"][0]["status"] == "success"
    assert payload["operations"][0]["current"] == 6
    assert payload["operations"][0]["total"] == 6
    operation_status.reset_operations_for_tests()


def test_execute_jellyfin_sync_runs_watch_progress_when_configured(db_session, monkeypatch) -> None:
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
                "user_name": "Spon4ik",
                "synced_count": 0,
                "unchanged_count": 1,
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
            jellyfin_write_count=0,
            stremio_write_count=1,
            skipped_count=0,
            error_count=0,
            messages=[],
        )

    monkeypatch.setattr(JellyfinService, "sync_rules", fake_sync_rules)
    monkeypatch.setattr("app.services.jellyfin_sync_ops.can_sync_watch_progress", lambda settings: True)
    monkeypatch.setattr("app.services.jellyfin_sync_ops.sync_watch_progress", fake_sync_watch_progress)

    execution = execute_jellyfin_sync(db_session, settings=settings)

    assert calls == ["default"]
    assert execution.watch_progress_summary is not None
    assert "1 watch-progress writes" in execution.detail_fragments()
    operation_status.reset_operations_for_tests()


def test_execute_jellyfin_sync_top_errors_ignores_successful_watch_progress_messages(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(id="default")
    db_session.add(settings)
    db_session.commit()

    def fake_sync_rules(self, session):
        return type(
            "Summary",
            (),
            {
                "user_name": "Spon4ik",
                "synced_count": 0,
                "unchanged_count": 1,
                "skipped_count": 0,
                "error_count": 0,
                "outcomes": [],
            },
        )()

    def fake_sync_watch_progress(session, *, settings=None):
        return WatchProgressSyncSummary(
            jellyfin_read_count=1,
            stremio_read_count=1,
            matched_count=1,
            jellyfin_write_count=0,
            stremio_write_count=1,
            skipped_count=0,
            error_count=0,
            messages=["Updated Stremio from Jellyfin for tt11815682."],
        )

    monkeypatch.setattr(JellyfinService, "sync_rules", fake_sync_rules)
    monkeypatch.setattr("app.services.jellyfin_sync_ops.can_sync_watch_progress", lambda settings: True)
    monkeypatch.setattr("app.services.jellyfin_sync_ops.sync_watch_progress", fake_sync_watch_progress)

    execution = execute_jellyfin_sync(db_session, settings=settings)

    assert execution.top_errors() == []


def test_jellyfin_collect_watch_progress_reads_positions(tmp_path: Path) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(db_path, series_id="series-1", title="Series", imdb_id="tt7654321")
    add_jellyfin_episode(
        db_path,
        episode_id="episode-1",
        series_id="series-1",
        title="Episode 2",
        season_number=1,
        episode_number=2,
    )
    add_jellyfin_movie(db_path, movie_id="movie-1", title="Movie", imdb_id="tt1234567")
    add_jellyfin_userdata(
        db_path,
        item_id="episode-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key=None,
        playback_position_ticks=4_200_000_000,
        last_played_date="2026-05-26 10:10:00.0000000",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="movie-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key=None,
        playback_position_ticks=1_800_000_000,
        last_played_date="2026-05-26 10:05:00.0000000",
    )
    service = JellyfinService(
        AppSettings(id="default", jellyfin_db_path=str(db_path), jellyfin_user_name="Spon4ik")
    )

    records = service.collect_watch_progress()

    assert [record.item_key for record in records] == ["tt7654321:S01E02", "tt1234567"]
    assert records[0].position_ms == 420_000
    assert records[1].position_ms == 180_000


def test_jellyfin_collect_watch_progress_does_not_complete_from_play_count_only(
    tmp_path: Path,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(db_path, series_id="series-1", title="Series", imdb_id="tt7654321")
    add_jellyfin_episode(
        db_path,
        episode_id="episode-1",
        series_id="series-1",
        title="Episode 5",
        season_number=5,
        episode_number=5,
    )
    add_jellyfin_userdata(
        db_path,
        item_id="episode-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key=None,
        played=0,
        play_count=1,
        playback_position_ticks=10_805_661_379,
        last_played_date="2026-05-26 20:45:51.9284615",
    )
    service = JellyfinService(
        AppSettings(id="default", jellyfin_db_path=str(db_path), jellyfin_user_name="Spon4ik")
    )

    records = service.collect_watch_progress()

    assert len(records) == 1
    assert records[0].item_key == "tt7654321:S05E05"
    assert records[0].position_ms == 1_080_566
    assert not records[0].completed


def test_jellyfin_connect_falls_back_to_snapshot_when_live_db_open_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    service = JellyfinService(AppSettings(id="default", jellyfin_db_path=str(db_path)))
    original_open = service._open_readonly_connection
    opened_paths: list[Path] = []

    def flaky_open(path: Path):
        opened_paths.append(path)
        if path == db_path:
            raise sqlite3.OperationalError("unable to open database file")
        return original_open(path)

    monkeypatch.setattr(service, "_open_readonly_connection", flaky_open)

    with service._connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM Users").fetchone()[0] == 1

    assert opened_paths[0] == db_path
    assert opened_paths[1].name == "jellyfin.db"
    assert opened_paths[1] != db_path


def test_jellyfin_write_watch_progress_uses_http_api(monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        jellyfin_server_url="http://jellyfin.local",
        jellyfin_api_key_encrypted=obfuscate_secret("token"),
    )
    service = JellyfinService(settings)
    calls: list[tuple[str, str, dict[str, object]]] = []

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url, *, headers=None, json=None):
            calls.append((url, headers["X-Emby-Token"], json))
            return type("Response", (), {"raise_for_status": lambda self: None})()

    monkeypatch.setattr("app.services.jellyfin.httpx.Client", FakeClient)

    service.write_watch_progress(
        WatchProgressRecord(
            source="stremio",
            media_type="episode",
            item_key="tt7654321:S01E02",
            provider_item_id="stremio-episode",
            provider_parent_id="episode-1",
            position_ms=420_000,
            duration_ms=2_400_000,
            completed=False,
            updated_at=None,
        )
    )

    assert calls == [
        (
            "http://jellyfin.local/Sessions/Playing/Progress",
            "token",
            {
                "ItemId": "episode-1",
                "PositionTicks": 4_200_000_000,
                "IsPaused": True,
            },
        )
    ]


def _build_basic_jellyfin_db(db_path: Path) -> Path:
    create_jellyfin_test_db(db_path)
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-ALPHA",
        title="The Last of Us",
        clean_name="The Last of Us",
        production_year=2023,
        imdb_id="tt3581920",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="EP-1",
        series_id="SERIES-ALPHA",
        title="When You're Lost in the Darkness",
        season_number=1,
        episode_number=1,
        imdb_id="tt14500888",
        tvdb_id="9001001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="EP-2",
        series_id="SERIES-ALPHA",
        title="Infected",
        season_number=1,
        episode_number=2,
        imdb_id="tt14500890",
        tvdb_id="9001002",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="EP-3",
        series_id="SERIES-ALPHA",
        title="Long Long Time",
        season_number=1,
        episode_number=3,
        imdb_id="tt14500892",
        tvdb_id="9001003",
    )
    return db_path


def test_jellyfin_test_connection_auto_selects_single_user(tmp_path: Path) -> None:
    db_path = _build_basic_jellyfin_db(tmp_path / "jellyfin.db")

    settings = AppSettings(
        id="default",
        jellyfin_db_path=str(db_path),
    )

    result = JellyfinService(settings).test_connection()

    assert result.db_path == str(db_path.resolve())
    assert result.selected_user.username == "Spon4ik"
    assert [user.username for user in result.users] == ["Spon4ik"]


def test_jellyfin_test_connection_requires_explicit_user_for_multi_user_db(tmp_path: Path) -> None:
    db_path = _build_basic_jellyfin_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id="USER-2", username="Guest")

    settings = AppSettings(
        id="default",
        jellyfin_db_path=str(db_path),
    )

    with pytest.raises(JellyfinError, match="Multiple Jellyfin users were found"):
        JellyfinService(settings).test_connection()


def test_jellyfin_sync_series_rules_updates_to_next_unseen_episode_and_preserves_ahead_rule(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = _build_basic_jellyfin_db(tmp_path / "jellyfin.db")
    add_jellyfin_userdata(
        db_path,
        item_id="EP-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key="ep-1",
        play_count=1,
    )
    add_jellyfin_userdata(
        db_path,
        item_id=SENTINEL_ITEM_ID,
        user_id=PRIMARY_USER_ID,
        custom_data_key="9001002",
        played=1,
        play_count=1,
    )

    settings = AppSettings(
        id="default",
        jellyfin_db_path=str(db_path),
    )
    behind_rule = Rule(
        rule_name="The Last of Us Behind",
        content_name="The Last of Us",
        normalized_title="The Last of Us",
        imdb_id="tt3581920",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=1,
        start_episode=1,
        feed_urls=["http://feed.example/behind"],
    )
    ahead_rule = Rule(
        rule_name="The Last of Us Ahead",
        content_name="The Last of Us",
        normalized_title="The Last of Us",
        imdb_id="tt3581920",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=2,
        start_episode=1,
        feed_urls=["http://feed.example/ahead"],
    )
    db_session.add_all([settings, behind_rule, ahead_rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_series_rules(db_session)

    assert summary.user_name == "Spon4ik"
    assert summary.synced_count == 2
    assert summary.unchanged_count == 0
    assert summary.skipped_count == 0
    assert summary.error_count == 0

    db_session.refresh(behind_rule)
    db_session.refresh(ahead_rule)
    assert (behind_rule.start_season, behind_rule.start_episode) == (1, 4)
    assert behind_rule.jellyfin_existing_episode_numbers == ["S01E03"]
    assert (ahead_rule.start_season, ahead_rule.start_episode) == (2, 1)
    assert ahead_rule.jellyfin_existing_episode_numbers == ["S01E03"]


def test_jellyfin_sync_series_rules_can_match_title_only_rules(tmp_path: Path, db_session) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-TITLE",
        title="Shrinking",
        clean_name="Shrinking",
        production_year=2023,
    )
    add_jellyfin_episode(
        db_path,
        episode_id="TITLE-EP-1",
        series_id="SERIES-TITLE",
        title="Coin Flip",
        season_number=1,
        episode_number=1,
        tvdb_id="1001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="TITLE-EP-2",
        series_id="SERIES-TITLE",
        title="Fortress of Solitude",
        season_number=1,
        episode_number=2,
        tvdb_id="1002",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="TITLE-EP-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key="title-ep-1",
        play_count=1,
    )

    settings = AppSettings(
        id="default",
        jellyfin_db_path=str(db_path),
    )
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/shrinking"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_series_rules(db_session)

    assert summary.synced_count == 1
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (1, 3)
    assert rule.jellyfin_existing_episode_numbers == ["S01E02"]


def test_jellyfin_sync_series_rules_refreshes_existing_unseen_inventory_without_rolling_back_floor(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-INVENTORY",
        title="Severance",
        clean_name="Severance",
        production_year=2022,
        imdb_id="tt11280740",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="INV-EP-1",
        series_id="SERIES-INVENTORY",
        title="Good News About Hell",
        season_number=1,
        episode_number=1,
        tvdb_id="21001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="INV-EP-2",
        series_id="SERIES-INVENTORY",
        title="Half Loop",
        season_number=1,
        episode_number=2,
        tvdb_id="21002",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="INV-EP-3",
        series_id="SERIES-INVENTORY",
        title="In Perpetuity",
        season_number=1,
        episode_number=3,
        tvdb_id="21003",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="INV-EP-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key="inv-ep-1",
        play_count=1,
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="Severance Rule",
        content_name="Severance",
        normalized_title="Severance",
        imdb_id="tt11280740",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=2,
        start_episode=1,
        jellyfin_existing_episode_numbers=["S01E02"],
        feed_urls=["http://feed.example/severance"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_series_rules(db_session)

    assert summary.synced_count == 1
    assert summary.unchanged_count == 0
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (2, 1)
    assert rule.jellyfin_existing_episode_numbers == ["S01E02", "S01E03"]


def test_jellyfin_sync_series_rules_records_existing_inventory_without_watched_progress(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-LIBRARY-ONLY",
        title="Shrinking",
        clean_name="Shrinking",
        production_year=2023,
    )
    add_jellyfin_episode(
        db_path,
        episode_id="LIB-ONLY-EP-1",
        series_id="SERIES-LIBRARY-ONLY",
        title="I Will Be Grape",
        season_number=3,
        episode_number=7,
        tvdb_id="31007",
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=7,
        feed_urls=["http://feed.example/shrinking"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_series_rules(db_session)

    assert summary.synced_count == 1
    assert summary.unchanged_count == 0
    assert summary.skipped_count == 0
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (3, 8)
    assert rule.jellyfin_existing_episode_numbers == ["S03E07"]


def test_jellyfin_sync_series_rules_keeps_watched_floor_when_rule_allows_existing_unseen_search(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-UPGRADE-HUNT",
        title="Ted",
        clean_name="Ted",
        production_year=2024,
    )
    add_jellyfin_episode(
        db_path,
        episode_id="TED-EP-1",
        series_id="SERIES-UPGRADE-HUNT",
        title="Just Say Yes",
        season_number=1,
        episode_number=1,
        tvdb_id="41001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="TED-EP-2",
        series_id="SERIES-UPGRADE-HUNT",
        title="My Two Dads",
        season_number=1,
        episode_number=2,
        tvdb_id="41002",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="TED-EP-3",
        series_id="SERIES-UPGRADE-HUNT",
        title="Ejectile Dysfunction",
        season_number=1,
        episode_number=3,
        tvdb_id="41003",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="TED-EP-1",
        user_id=PRIMARY_USER_ID,
        custom_data_key="ted-ep-1",
        play_count=1,
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="Ted Rule",
        content_name="Ted",
        normalized_title="Ted",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        jellyfin_search_existing_unseen=True,
        start_season=1,
        start_episode=1,
        feed_urls=["http://feed.example/ted"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_series_rules(db_session)

    assert summary.synced_count == 1
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (1, 2)
    assert rule.jellyfin_existing_episode_numbers == ["S01E02", "S01E03"]


def test_jellyfin_sync_series_rules_jump_to_next_season_episode_zero_when_catalog_marks_finale(
    tmp_path: Path,
    db_session,
    monkeypatch,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-FINALE",
        title="The Last of Us",
        clean_name="The Last of Us",
        production_year=2023,
        imdb_id="tt3581920",
    )
    for episode_number in range(1, 11):
        add_jellyfin_episode(
            db_path,
            episode_id=f"FINALE-EP-{episode_number}",
            series_id="SERIES-FINALE",
            title=f"Episode {episode_number}",
            season_number=1,
            episode_number=episode_number,
            tvdb_id=f"990{episode_number:02d}",
        )
    add_jellyfin_userdata(
        db_path,
        item_id="FINALE-EP-10",
        user_id=PRIMARY_USER_ID,
        custom_data_key="finale-ep-10",
        play_count=1,
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="The Last of Us Rule",
        content_name="The Last of Us",
        normalized_title="The Last of Us",
        imdb_id="tt3581920",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=1,
        start_episode=10,
        feed_urls=["http://feed.example/the-last-of-us"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    service = JellyfinService(settings)
    monkeypatch.setattr(
        service,
        "_released_episode_numbers_for_season",
        lambda **kwargs: list(range(1, 11)) if kwargs["season_number"] == 1 else None,
    )

    summary = service.sync_series_rules(db_session)

    assert summary.synced_count == 1
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (2, 0)
    assert rule.jellyfin_known_episode_numbers[-1] == "S01E10"
    assert rule.jellyfin_watched_episode_numbers[-1] == "S01E10"


def test_jellyfin_sync_series_rules_preserve_remembered_history_after_episode_cleanup(
    tmp_path: Path,
    db_session,
    monkeypatch,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-REMEMBERED",
        title="The Last of Us",
        clean_name="The Last of Us",
        production_year=2023,
        imdb_id="tt3581920",
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="Remembered History Rule",
        content_name="The Last of Us",
        normalized_title="The Last of Us",
        imdb_id="tt3581920",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=1,
        start_episode=1,
        jellyfin_known_episode_numbers=["S01E10"],
        jellyfin_watched_episode_numbers=["S01E10"],
        feed_urls=["http://feed.example/remembered-history"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    service = JellyfinService(settings)
    monkeypatch.setattr(
        service,
        "_released_episode_numbers_for_season",
        lambda **kwargs: list(range(1, 11)) if kwargs["season_number"] == 1 else None,
    )

    summary = service.sync_series_rules(db_session)

    assert summary.synced_count == 1
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (2, 0)
    assert rule.jellyfin_existing_episode_numbers == []
    assert rule.jellyfin_known_episode_numbers == ["S01E10"]
    assert rule.jellyfin_watched_episode_numbers == ["S01E10"]


def test_jellyfin_sync_rules_disables_completed_movies_via_shared_watch_state(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_movie(
        db_path,
        movie_id="MOVIE-SHOWMAN",
        title="Michael McIntyre: Showman",
        clean_name="Michael McIntyre: Showman",
        production_year=2020,
        imdb_id="tt11860624",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="MOVIE-SHOWMAN",
        user_id=PRIMARY_USER_ID,
        custom_data_key=None,
        played=1,
        play_count=1,
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="Showman Rule",
        content_name="Michael McIntyre: Showman",
        normalized_title="Michael McIntyre: Showman",
        imdb_id="tt11860624",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/showman"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_rules(db_session)

    assert summary.synced_count == 1
    assert summary.unchanged_count == 0
    assert summary.skipped_count == 0
    db_session.refresh(rule)
    assert rule.enabled is False
    assert rule.jellyfin_auto_disabled is False
    assert rule.movie_completion_auto_disabled is True
    assert rule.movie_completion_sources == ["jellyfin"]


def test_jellyfin_sync_rules_reenables_auto_disabled_movie_when_keep_search_is_enabled(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_movie(
        db_path,
        movie_id="MOVIE-RIP",
        title="The Rip",
        clean_name="The Rip",
        production_year=2026,
        imdb_id="tt32642706",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="MOVIE-RIP",
        user_id=PRIMARY_USER_ID,
        custom_data_key=None,
        played=1,
        play_count=1,
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="The Rip Rule",
        content_name="The Rip",
        normalized_title="The Rip",
        imdb_id="tt32642706",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        jellyfin_search_existing_unseen=True,
        enabled=False,
        jellyfin_auto_disabled=True,
        movie_completion_auto_disabled=True,
        movie_completion_sources=["jellyfin"],
        feed_urls=["http://feed.example/the-rip"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_rules(db_session)

    assert summary.synced_count == 1
    assert summary.unchanged_count == 0
    db_session.refresh(rule)
    assert rule.enabled is True
    assert rule.jellyfin_auto_disabled is False
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == ["jellyfin"]


def test_jellyfin_sync_rules_leaves_unfinished_movie_rule_enabled(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_movie(
        db_path,
        movie_id="MOVIE-HOPPERS",
        title="Hoppers",
        clean_name="Hoppers",
        production_year=2026,
        imdb_id="tt26443616",
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
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
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_rules(db_session)

    assert summary.synced_count == 0
    assert summary.unchanged_count == 1
    db_session.refresh(rule)
    assert rule.enabled is True
    assert rule.movie_completion_auto_disabled is False
    assert rule.movie_completion_sources == []


def test_jellyfin_sync_rules_skips_duplicate_imdb_movie_matches(
    tmp_path: Path,
    db_session,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id=PRIMARY_USER_ID, username="Spon4ik")
    add_jellyfin_movie(
        db_path,
        movie_id="MOVIE-INCREDIBLES",
        title="The Incredibles",
        clean_name="The Incredibles",
        production_year=2004,
        imdb_id="tt0317705",
    )
    add_jellyfin_movie(
        db_path,
        movie_id="MOVIE-INCREDIBLES-SEQUEL",
        title="Incredibles 2",
        clean_name="Incredibles 2",
        production_year=2018,
        imdb_id="tt0317705",
    )

    settings = AppSettings(id="default", jellyfin_db_path=str(db_path))
    rule = Rule(
        rule_name="The Incredibles Rule",
        content_name="The Incredibles",
        normalized_title="The Incredibles",
        imdb_id="tt0317705",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=True,
        feed_urls=["http://feed.example/the-incredibles"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    summary = JellyfinService(settings).sync_rules(db_session)

    assert summary.error_count == 0
    assert summary.skipped_count == 1
    assert summary.outcomes[0].status == "skipped"
    assert 'Multiple Jellyfin movie items matched IMDb ID "tt0317705".' in (
        summary.outcomes[0].message
    )
