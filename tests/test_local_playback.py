from __future__ import annotations

from pathlib import Path

import pytest

from app.services.local_playback import (
    LocalPlaybackFile,
    QbLocalPlaybackMatch,
    find_qb_local_playback_matches,
    register_local_playback_file,
    reset_local_playback_tokens,
    resolve_local_playback_token,
    resolve_qb_local_playback_file,
)


@pytest.fixture(autouse=True)
def _reset_local_playback_tokens() -> None:
    reset_local_playback_tokens()
    yield
    reset_local_playback_tokens()


class _FakeQbClient:
    def __init__(
        self,
        torrent: dict[str, object] | None,
        files: list[dict[str, object]],
        torrents: list[dict[str, object]] | None = None,
    ) -> None:
        self._torrent = torrent
        self._files = files
        self._torrents = (
            list(torrents) if torrents is not None else ([torrent] if torrent is not None else [])
        )

    def get_torrent(self, info_hash: str) -> dict[str, object] | None:
        assert info_hash == "abc123"
        return self._torrent

    def get_torrents(self, *, hashes: str | None = None) -> list[dict[str, object]]:
        assert hashes is None
        return list(self._torrents)

    def get_torrent_files(self, info_hash: str) -> list[dict[str, object]]:
        assert info_hash == "abc123"
        return list(self._files)


def test_resolve_qb_local_playback_file_prefers_matching_completed_file(tmp_path: Path) -> None:
    series_root = tmp_path / "The Beauty [imdbid-tt33517752]"
    episode_directory = series_root / "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265"
    episode_directory.mkdir(parents=True)
    episode_path = episode_directory / "The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
    episode_path.write_bytes(b"episode-4")

    fake_client = _FakeQbClient(
        torrent={
            "hash": "abc123",
            "progress": 1,
            "size": 8,
            "completed": 8,
            "save_path": str(series_root),
            "content_path": str(episode_directory),
            "root_path": str(episode_directory),
        },
        files=[
            {
                "index": 3,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                "progress": 1,
                "is_seed": True,
            },
            {
                "index": 4,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E05.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                "progress": 1,
                "is_seed": True,
            },
        ],
    )

    playback_file = resolve_qb_local_playback_file(
        fake_client,
        info_hash="abc123",
        file_idx=3,
        filename_hint="The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
    )

    assert playback_file == LocalPlaybackFile(
        file_path=episode_path,
        filename=episode_path.name,
        media_type="video/x-matroska",
    )


def test_resolve_qb_local_playback_file_returns_none_for_incomplete_torrent(tmp_path: Path) -> None:
    episode_path = tmp_path / "movie.mkv"
    episode_path.write_bytes(b"partial")
    fake_client = _FakeQbClient(
        torrent={
            "hash": "abc123",
            "progress": 0.75,
            "size": 100,
            "completed": 75,
            "content_path": str(episode_path),
        },
        files=[
            {
                "index": 0,
                "name": "movie.mkv",
                "progress": 1,
                "is_seed": True,
            },
        ],
    )

    assert resolve_qb_local_playback_file(fake_client, info_hash="abc123", file_idx=0) is None


def test_register_local_playback_file_round_trips_token(tmp_path: Path) -> None:
    file_path = tmp_path / "movie.mkv"
    file_path.write_bytes(b"movie")

    token = register_local_playback_file(
        LocalPlaybackFile(
            file_path=file_path,
            filename=file_path.name,
            media_type="video/x-matroska",
        )
    )

    resolved = resolve_local_playback_token(token)

    assert resolved == LocalPlaybackFile(
        file_path=file_path,
        filename=file_path.name,
        media_type="video/x-matroska",
    )


def test_find_qb_local_playback_matches_filters_by_imdb_and_episode(tmp_path: Path) -> None:
    series_root = tmp_path / "The Beauty [imdbid-tt33517752]"
    episode_directory = series_root / "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265"
    episode_directory.mkdir(parents=True)
    episode_path = episode_directory / "The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
    episode_path.write_bytes(b"episode-4")

    fake_client = _FakeQbClient(
        torrent={
            "hash": "abc123",
            "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265",
            "progress": 1,
            "size": 8,
            "completed": 8,
            "save_path": str(series_root),
            "content_path": str(episode_directory),
            "root_path": str(episode_directory),
        },
        files=[
            {
                "index": 3,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                "progress": 1,
                "is_seed": True,
            }
        ],
        torrents=[
            {
                "hash": "abc123",
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265",
                "progress": 1,
                "size": 8,
                "completed": 8,
                "save_path": str(series_root),
                "content_path": str(episode_directory),
                "root_path": str(episode_directory),
                "category": "Series/The Beauty [imdbid-tt33517752]",
            },
            {
                "hash": "ignored",
                "name": "Other.Show.S01.1080p",
                "progress": 1,
                "size": 8,
                "completed": 8,
                "save_path": str(tmp_path / "Other"),
                "category": "Series/Other Show [imdbid-tt00000001]",
            },
        ],
    )

    matches = find_qb_local_playback_matches(
        fake_client,
        imdb_id="tt33517752",
        season_number=1,
        episode_number=4,
    )

    assert matches == [
        QbLocalPlaybackMatch(
            info_hash="abc123",
            torrent_name="The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265",
            playback_file=LocalPlaybackFile(
                file_path=episode_path,
                filename=episode_path.name,
                media_type="video/x-matroska",
            ),
        )
    ]


def test_find_qb_local_playback_matches_prefers_filename_episode_over_parent_pack_range(
    tmp_path: Path,
) -> None:
    series_root = tmp_path / "The Rookie [imdbid-tt7587890]"
    episode_directory = series_root / "The.Rookie.S08E01-E14.1080p.WEB-DL"
    episode_directory.mkdir(parents=True)
    episode_10 = episode_directory / "The.Rookie.S08E10.1080p.mkv"
    episode_12 = episode_directory / "The.Rookie.S08E12.1080p.mkv"
    episode_10.write_bytes(b"episode-10")
    episode_12.write_bytes(b"episode-12")

    fake_client = _FakeQbClient(
        torrent={
            "hash": "abc123",
            "name": "The.Rookie.S08E01-E14.1080p.WEB-DL",
            "progress": 1,
            "size": 20,
            "completed": 20,
            "save_path": str(series_root),
            "content_path": str(episode_directory),
            "root_path": str(episode_directory),
        },
        files=[
            {
                "index": 10,
                "name": "The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E10.1080p.mkv",
                "progress": 1,
                "is_seed": True,
            },
            {
                "index": 12,
                "name": "The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E12.1080p.mkv",
                "progress": 1,
                "is_seed": True,
            },
        ],
        torrents=[
            {
                "hash": "abc123",
                "name": "The.Rookie.S08E01-E14.1080p.WEB-DL",
                "progress": 1,
                "size": 20,
                "completed": 20,
                "save_path": str(series_root),
                "content_path": str(episode_directory),
                "root_path": str(episode_directory),
                "category": "Series/The Rookie [imdbid-tt7587890]",
            }
        ],
    )

    matches = find_qb_local_playback_matches(
        fake_client,
        imdb_id="tt7587890",
        season_number=8,
        episode_number=12,
    )

    assert matches == [
        QbLocalPlaybackMatch(
            info_hash="abc123",
            torrent_name="The.Rookie.S08E01-E14.1080p.WEB-DL",
            playback_file=LocalPlaybackFile(
                file_path=episode_12,
                filename=episode_12.name,
                media_type="video/x-matroska",
            ),
        )
    ]
