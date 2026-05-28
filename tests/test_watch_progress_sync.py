from __future__ import annotations

from datetime import UTC, datetime

from app.services.watch_progress_sync import WatchProgressSyncService
from app.services.watch_state import WatchProgressRecord


def test_watch_progress_sync_writes_newer_stremio_progress_to_jellyfin() -> None:
    jellyfin_writes: list[WatchProgressRecord] = []
    stremio_writes: list[WatchProgressRecord] = []
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="movie",
                item_key="tt1234567",
                provider_item_id="jf-movie",
                position_ms=120_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
            )
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="movie",
                item_key="tt1234567",
                provider_item_id="tt1234567",
                position_ms=180_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 5, tzinfo=UTC),
            )
        ],
        jellyfin_writer=jellyfin_writes.append,
        stremio_writer=stremio_writes.append,
    )

    summary = service.sync()

    assert summary.matched_count == 1
    assert summary.jellyfin_write_count == 1
    assert summary.stremio_write_count == 0
    assert summary.skipped_count == 0
    assert jellyfin_writes[0].source == "stremio"
    assert jellyfin_writes[0].position_ms == 180_000
    assert stremio_writes == []


def test_watch_progress_sync_writes_newer_jellyfin_progress_to_stremio() -> None:
    jellyfin_writes: list[WatchProgressRecord] = []
    stremio_writes: list[WatchProgressRecord] = []
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="episode",
                item_key="tt7654321:S01E02",
                provider_item_id="jf-episode",
                position_ms=420_000,
                duration_ms=2_400_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 10, tzinfo=UTC),
            )
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="episode",
                item_key="tt7654321:S01E02",
                provider_item_id="tt7654321:1:2",
                position_ms=240_000,
                duration_ms=2_400_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
            )
        ],
        jellyfin_writer=jellyfin_writes.append,
        stremio_writer=stremio_writes.append,
    )

    summary = service.sync()

    assert summary.stremio_write_count == 1
    assert summary.jellyfin_write_count == 0
    assert stremio_writes[0].source == "jellyfin"
    assert stremio_writes[0].position_ms == 420_000
    assert jellyfin_writes == []


def test_watch_progress_sync_skips_small_delta() -> None:
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="movie",
                item_key="tt1234567",
                provider_item_id="jf-movie",
                position_ms=120_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 0, tzinfo=UTC),
            )
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="movie",
                item_key="tt1234567",
                provider_item_id="tt1234567",
                position_ms=130_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 10, 5, tzinfo=UTC),
            )
        ],
        jellyfin_writer=lambda record: None,
        stremio_writer=lambda record: None,
    )

    summary = service.sync()

    assert summary.matched_count == 1
    assert summary.skipped_count == 1
    assert summary.jellyfin_write_count == 0
    assert summary.stremio_write_count == 0


def test_watch_progress_sync_matches_series_by_parent_when_latest_episodes_differ() -> None:
    stremio_writes: list[WatchProgressRecord] = []
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="episode",
                item_key="tt1190634:S05E05",
                provider_item_id="jf-boys-s05e05",
                position_ms=1_080_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 20, 45, tzinfo=UTC),
            )
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="episode",
                item_key="tt1190634:S04E08",
                provider_item_id="tt1190634",
                provider_video_id="tt1190634:4:8",
                position_ms=0,
                duration_ms=3_600_000,
                completed=True,
                updated_at=datetime(2026, 1, 10, 18, 25, tzinfo=UTC),
            )
        ],
        jellyfin_writer=lambda record: None,
        stremio_writer=stremio_writes.append,
    )

    summary = service.sync()

    assert summary.matched_count == 1
    assert summary.stremio_write_count == 1
    assert stremio_writes[0].item_key == "tt1190634:S05E05"


def test_watch_progress_sync_writes_all_completed_jellyfin_series_episodes_to_stremio() -> None:
    stremio_writes: list[WatchProgressRecord] = []
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="episode",
                item_key="tt1190634:S05E01",
                provider_item_id="jf-boys-s05e01",
                position_ms=0,
                duration_ms=3_600_000,
                completed=True,
                updated_at=datetime(2026, 5, 26, 19, 45, tzinfo=UTC),
            ),
            WatchProgressRecord(
                source="jellyfin",
                media_type="episode",
                item_key="tt1190634:S05E05",
                provider_item_id="jf-boys-s05e05",
                position_ms=1_080_000,
                duration_ms=3_600_000,
                completed=False,
                updated_at=datetime(2026, 5, 26, 20, 45, tzinfo=UTC),
            ),
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="episode",
                item_key="tt1190634:S04E08",
                provider_item_id="tt1190634",
                provider_video_id="tt1190634:4:8",
                position_ms=0,
                duration_ms=3_600_000,
                completed=True,
                updated_at=datetime(2026, 1, 10, 18, 25, tzinfo=UTC),
            )
        ],
        jellyfin_writer=lambda record: None,
        stremio_writer=stremio_writes.append,
    )

    summary = service.sync()

    assert summary.stremio_write_count == 2
    assert [record.item_key for record in stremio_writes] == ["tt1190634:S05E01", "tt1190634:S05E05"]


def test_watch_progress_sync_writes_jellyfin_progress_to_stremio_placeholder() -> None:
    stremio_writes: list[WatchProgressRecord] = []
    service = WatchProgressSyncService(
        jellyfin_records=[
            WatchProgressRecord(
                source="jellyfin",
                media_type="episode",
                item_key="tt11815682:S05E09",
                provider_item_id="jf-hacks-s05e09",
                position_ms=0,
                duration_ms=None,
                completed=True,
                updated_at=datetime(2026, 5, 28, 7, 24, tzinfo=UTC),
            )
        ],
        stremio_records=[
            WatchProgressRecord(
                source="stremio",
                media_type="episode",
                item_key="tt11815682:S00E00",
                provider_item_id="tt11815682",
                position_ms=0,
                duration_ms=None,
                completed=False,
                updated_at=None,
            )
        ],
        jellyfin_writer=lambda record: None,
        stremio_writer=stremio_writes.append,
    )

    summary = service.sync()

    assert summary.matched_count == 1
    assert summary.stremio_write_count == 1
    assert stremio_writes[0].item_key == "tt11815682:S05E09"
