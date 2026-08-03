from __future__ import annotations

from app.models import MediaType
from app.schemas import JackettSearchRequest, SearchSourceKind
from app.services.real_debrid_search import search_real_debrid


class FakeRealDebridSearchClient:
    def list_torrents(self, *, page: int, limit: int):
        assert limit == 100
        if page > 1:
            return []
        return [
            {
                "id": "torrent-1",
                "filename": "Dune.Part.Two.2024.2160p.mkv",
                "hash": "a" * 40,
                "bytes": 10 * 1024**3,
                "status": "downloaded",
                "added": "2026-08-01T12:00:00Z",
            },
            {
                "id": "torrent-2",
                "filename": "Unrelated.Movie.2024.mkv",
                "hash": "b" * 40,
                "status": "downloaded",
            },
        ]

    def list_downloads(self, *, page: int, limit: int):
        if page > 1:
            return []
        return [
            {
                "id": "download-1",
                "filename": "Dune.Part.Two.2024.Extras.mkv",
                "filesize": 1024,
                "generated": "2026-08-02T12:00:00Z",
            }
        ]


def test_real_debrid_search_returns_cloud_and_history_without_public_indexer() -> None:
    payload = JackettSearchRequest(
        query="Dune Part Two",
        media_type=MediaType.MOVIE,
        release_year="2024",
    )

    rows = search_real_debrid(FakeRealDebridSearchClient(), payload)

    assert [row.provider_id for row in rows] == ["torrent-1", "download-1"]
    assert rows[0].merge_key == f"hash:{'a' * 40}"
    assert rows[0].queue_capability == "qbittorrent"
    assert rows[0].source_kind == SearchSourceKind.REAL_DEBRID_TORRENT
    assert rows[1].queue_capability == "jdownloader"
    assert rows[1].source_kind == SearchSourceKind.REAL_DEBRID_DOWNLOAD


def test_real_debrid_series_search_honors_episode_floor_and_keywords() -> None:
    class SeriesClient(FakeRealDebridSearchClient):
        def list_torrents(self, *, page: int, limit: int):
            if page > 1:
                return []
            return [
                {
                    "id": "pack",
                    "filename": "Silo.S03E01-04.2160p.WEB-DL",
                    "hash": "c" * 40,
                    "status": "downloaded",
                },
                {
                    "id": "old",
                    "filename": "Silo.S03E01-03.1080p.WEB-DL",
                    "hash": "d" * 40,
                    "status": "downloaded",
                },
            ]

        def list_downloads(self, *, page: int, limit: int):
            return []

    payload = JackettSearchRequest(
        query="Silo",
        media_type=MediaType.SERIES,
        season_number=3,
        episode_number=4,
        keywords_any_groups=[["2160p", "4k"]],
    )

    rows = search_real_debrid(SeriesClient(), payload)

    assert [row.provider_id for row in rows] == ["pack"]
