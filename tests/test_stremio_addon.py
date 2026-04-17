from __future__ import annotations

from pathlib import Path

import pytest

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, MetadataProvider
from app.schemas import (
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services.jackett import JackettClient
from app.services.local_playback import reset_local_playback_tokens
from app.services.metadata import MetadataClient, MetadataLookupError
from app.services.qbittorrent import QbittorrentClient
from app.services.selective_queue import ParsedTorrentInfo, TorrentFileEntry
from app.services.stremio_addon import StremioAddonService, reset_stremio_addon_caches


@pytest.fixture(autouse=True)
def _reset_stremio_addon_caches() -> None:
    reset_stremio_addon_caches()
    reset_local_playback_tokens()
    yield
    reset_stremio_addon_caches()
    reset_local_playback_tokens()


def test_stremio_manifest_route_exposes_catalog_and_stream_resources(app_client) -> None:
    response = app_client.get("/stremio/manifest.json")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, OPTIONS"
    payload = response.json()
    assert payload["id"] == "org.qbrssrules.stremio.local"
    assert payload["version"] == "0.9.0+stremio.1"
    assert any(resource["name"] == "catalog" for resource in payload["resources"])
    assert any(resource["name"] == "stream" for resource in payload["resources"])
    assert any(
        catalog["id"] == "qb-search" and catalog["type"] == "movie"
        for catalog in payload["catalogs"]
    )
    assert any(
        catalog["id"] == "qb-search" and catalog["type"] == "series"
        for catalog in payload["catalogs"]
    )


def test_stremio_catalog_route_returns_metadata_search_results(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_search_omdb(self, query, media_type, *, limit=20, skip=0):
        assert query == "The Beauty"
        assert media_type == MediaType.SERIES
        assert limit == 20
        assert skip == 0
        return [
            MetadataResult(
                title="The Beauty",
                provider=MetadataLookupProvider.OMDB,
                imdb_id="tt33517752",
                source_id="tt33517752",
                media_type=MediaType.SERIES,
                year="2026",
                poster_url="https://img.example/the-beauty.jpg",
            )
        ]

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url="https://img.example/the-beauty.jpg",
        )

    monkeypatch.setattr(MetadataClient, "search_omdb", fake_search_omdb)
    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)

    response = app_client.get("/stremio/catalog/series/qb-search/search=The%20Beauty.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "metas": [
            {
                "id": "tt33517752",
                "type": "series",
                "name": "The Beauty",
                "releaseInfo": "2026",
                "poster": "https://img.example/the-beauty.jpg",
                "posterShape": "poster",
            }
        ]
    }


def test_stremio_stream_route_reuses_jackett_results_and_sorts_by_quality(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        assert imdb_id == "tt33517752"
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    seen_searches: list[tuple[str, tuple[str, ...], str | None]] = []

    def fake_search(self, payload):
        assert payload.media_type == MediaType.SERIES
        seen_searches.append((payload.query, tuple(payload.keywords_all), payload.imdb_id))
        if payload.query == "The Beauty S01E01":
            assert payload.imdb_id is None
            assert payload.imdb_id_only is False
            return JackettSearchRun(results=[], fallback_results=[])
        assert payload.query == "The Beauty"
        assert payload.imdb_id == "tt33517752"
        assert payload.imdb_id_only is True
        if payload.keywords_all == ["S01"]:
            return JackettSearchRun(results=[], fallback_results=[])
        assert payload.keywords_all == ["S01E01"]
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="1080",
                    title="The Beauty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:1111111111111111111111111111111111111111",
                    info_hash="1111111111111111111111111111111111111111",
                    indexer="alpha",
                    size_bytes=4 * 1024 * 1024 * 1024,
                    size_label="4.0 GB",
                    seeders=15,
                    peers=20,
                    published_at="2026-03-28T10:00:00+00:00",
                ),
                JackettSearchResult(
                    merge_key="2160",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="magnet:?xt=urn:btih:2222222222222222222222222222222222222222",
                    info_hash="2222222222222222222222222222222222222222",
                    indexer="megapeer",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=2,
                    peers=19,
                    published_at="2026-03-19T22:00:00+00:00",
                ),
            ]
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cacheMaxAge"] == 7200
    assert payload["staleRevalidate"] == 14400
    assert payload["staleError"] == 604800
    assert len(payload["streams"]) == 2
    assert payload["streams"][0]["infoHash"] == "2222222222222222222222222222222222222222"
    assert payload["streams"][0]["name"] == "qB RSS Rules\n2160p HDR DV WEB-DL"
    assert payload["streams"][0]["type"] == "series"
    assert payload["streams"][0]["tag"] == "2160p"
    assert payload["streams"][0]["seeders"] == 2
    assert payload["streams"][0]["title"].startswith("The Beauty  S01E01\r\n\r\n")
    assert "47.0 GB" in payload["streams"][0]["title"]
    assert "2160p HDR DV WEB-DL" in payload["streams"][0]["title"]
    assert "qbrssrules/megapeer" in payload["streams"][0]["title"]
    assert "description" not in payload["streams"][0]
    assert payload["streams"][0].get("fileIdx") is None
    assert payload["streams"][0]["behaviorHints"] == {
        "bingieGroup": "qB RSS Rules|2222222222222222222222222222222222222222"
    }
    assert payload["streams"][1]["infoHash"] == "1111111111111111111111111111111111111111"
    assert payload["streams"][1]["tag"] == "1080p"
    assert payload["streams"][1].get("fileIdx") is None
    assert set(seen_searches) == {
        ("The Beauty", ("S01E01",), "tt33517752"),
        ("The Beauty S01E01", (), None),
    }


def test_stremio_stream_route_does_not_use_series_start_year_for_episode_searches(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        assert imdb_id == "tt1888075"
        return MetadataResult(
            title="Death in Paradise",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2011",
            poster_url=None,
        )

    seen_searches: list[tuple[str, tuple[str, ...], str | None, str | None]] = []

    def fake_search(self, payload):
        assert payload.media_type == MediaType.SERIES
        seen_searches.append(
            (
                payload.query,
                tuple(payload.keywords_all),
                payload.imdb_id,
                payload.release_year,
            )
        )
        if payload.query == "Death in Paradise S14E01":
            assert payload.release_year is None
            return JackettSearchRun(
                results=[
                    JackettSearchResult(
                        merge_key="dip-s14e01",
                        title="Death in Paradise S14E01 1080p WEB-DL",
                        link="magnet:?xt=urn:btih:3333333333333333333333333333333333333333",
                        info_hash="3333333333333333333333333333333333333333",
                        indexer="alpha",
                        size_bytes=2 * 1024 * 1024 * 1024,
                        size_label="2.0 GB",
                        seeders=12,
                        peers=20,
                        published_at="2025-02-10T10:00:00+00:00",
                    )
                ],
                fallback_results=[],
            )
        assert payload.release_year is None
        return JackettSearchRun(results=[], fallback_results=[])

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/stremio/stream/series/tt1888075:14:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["infoHash"] == "3333333333333333333333333333333333333333"
    assert set(seen_searches) == {
        ("Death in Paradise", ("S14E01",), "tt1888075", None),
        ("Death in Paradise", ("S14",), "tt1888075", None),
        ("Death in Paradise S14E01", (), None, None),
    }


def test_stremio_stream_route_returns_empty_for_unsupported_id(app_client) -> None:
    response = app_client.get("/stremio/stream/movie/tmdb:12345.json")

    assert response.status_code == 200
    assert response.json() == {
        "streams": [],
        "cacheMaxAge": 7200,
        "staleRevalidate": 14400,
        "staleError": 604800,
    }


def test_stremio_addon_routes_answer_options_with_cors_headers(app_client) -> None:
    response = app_client.options("/stremio/manifest.json")

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET, OPTIONS"


def test_stremio_stream_route_falls_back_to_cinemeta_when_omdb_lookup_fails(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("bad-omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        raise MetadataLookupError(f"OMDb lookup failed for {imdb_id}")

    def fake_lookup_cinemeta_by_imdb_id(*, imdb_id, media_type):
        assert imdb_id == "tt33517752"
        assert media_type == MediaType.SERIES
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        assert payload.media_type == MediaType.SERIES
        if payload.query == "The Beauty S01E01":
            assert payload.imdb_id is None
            return JackettSearchRun(results=[], fallback_results=[])
        assert payload.query == "The Beauty"
        assert payload.imdb_id == "tt33517752"
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="2160",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="magnet:?xt=urn:btih:2222222222222222222222222222222222222222",
                    info_hash="2222222222222222222222222222222222222222",
                    indexer="megapeer",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=2,
                    peers=19,
                    published_at="2026-03-19T22:00:00+00:00",
                ),
            ]
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(
        StremioAddonService,
        "_lookup_cinemeta_by_imdb_id",
        staticmethod(fake_lookup_cinemeta_by_imdb_id),
    )
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["infoHash"] == "2222222222222222222222222222222222222222"


def test_stremio_stream_route_accepts_http_torrent_download_links(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        assert imdb_id == "tt33517752"
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "The Beauty S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        assert payload.query == "The Beauty"
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="http-download",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="http://jackett.test/dl/the-beauty-s01e01.torrent",
                    info_hash=None,
                    indexer="megapeer",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=2,
                    peers=19,
                    published_at="2026-03-19T22:00:00+00:00",
                ),
            ]
        )

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/dl/the-beauty-s01e01.torrent"
        assert timeout_seconds > 0
        return (b"d4:infod4:name4:testee", "the-beauty-s01e01.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        assert torrent_bytes == b"d4:infod4:name4:testee"
        assert source_name == "the-beauty-s01e01.torrent"
        return ParsedTorrentInfo(
            info_hash="3333333333333333333333333333333333333333",
            filename=source_name,
            files=[
                TorrentFileEntry(
                    file_id=5,
                    path="The.Beauty.S01E01.2160p.WEB-DL.H265.mkv",
                ),
                TorrentFileEntry(
                    file_id=6,
                    path="The.Beauty.S01E02.2160p.WEB-DL.H265.mkv",
                ),
            ],
            tracker_urls=["https://tracker.example/announce"],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._download_torrent_bytes_for_stremio",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr("app.services.stremio_addon.parse_torrent_info", fake_parse_torrent_info)

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["infoHash"] == "3333333333333333333333333333333333333333"
    assert payload["streams"][0]["fileIdx"] == 5
    assert payload["streams"][0]["behaviorHints"] == {
        "bingieGroup": "qB RSS Rules|3333333333333333333333333333333333333333",
        "filename": "The.Beauty.S01E01.2160p.WEB-DL.H265.mkv",
    }
    assert payload["streams"][0]["sources"][0] == "tracker:https://tracker.example/announce"
    assert payload["streams"][0]["title"].startswith("The Beauty  S01E01\r\n\r\n")
    assert "47.0 GB" in payload["streams"][0]["title"]
    assert "2160p HDR DV WEB-DL" in payload["streams"][0]["title"]
    assert "qbrssrules/megapeer" in payload["streams"][0]["title"]


def test_stremio_stream_route_uses_season_fallback_for_episode_packs(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    seen_payloads: list[tuple[str, tuple[str, ...], str | None]] = []

    def fake_search(self, payload):
        seen_payloads.append((payload.query, tuple(payload.keywords_all), payload.imdb_id))
        if payload.keywords_all == ["S01E04"]:
            return JackettSearchRun(
                results=[],
                fallback_results=[
                    JackettSearchResult(
                        merge_key="exact-episode",
                        title="The Beauty S01E04 Repack 2026 1080p DSNP WEB-DL",
                        link="magnet:?xt=urn:btih:4444444444444444444444444444444444444444",
                        info_hash="4444444444444444444444444444444444444444",
                        indexer="tpb",
                        size_bytes=1_300_000_000,
                        size_label="1.3 GB",
                        seeders=29,
                        peers=60,
                        published_at="2026-03-28T10:00:00+00:00",
                    ),
                ],
            )
        if payload.query == "The Beauty S01E04" and payload.imdb_id is None:
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.keywords_all == ["S01"]:
            return JackettSearchRun(
                results=[],
                fallback_results=[
                    JackettSearchResult(
                        merge_key="season-pack",
                        title="The Beauty - S1E1-11 - 2026 2160p HDR DV WEB-DL",
                        link="http://jackett.test/dl/the-beauty-s01-pack.torrent",
                        info_hash=None,
                        indexer="kinozal",
                        size_bytes=47 * 1024 * 1024 * 1024,
                        size_label="47.0 GB",
                        seeders=25,
                        peers=28,
                        published_at="2026-03-28T09:00:00+00:00",
                    ),
                ],
            )
        raise AssertionError(f"Unexpected keywords_all: {payload.keywords_all!r}")

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/dl/the-beauty-s01-pack.torrent"
        assert timeout_seconds > 0
        return (b"d4:infod4:name4:testee", "the-beauty-s01-pack.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        return ParsedTorrentInfo(
            info_hash="5555555555555555555555555555555555555555",
            filename=source_name,
            files=[
                TorrentFileEntry(file_id=5, path="The.Beauty.S01E04.2160p.WEB-DL.H265.mkv"),
                TorrentFileEntry(file_id=6, path="The.Beauty.S01E05.2160p.WEB-DL.H265.mkv"),
            ],
            tracker_urls=["https://tracker.example/announce"],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._download_torrent_bytes_for_stremio",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr("app.services.stremio_addon.parse_torrent_info", fake_parse_torrent_info)

    response = app_client.get("/stremio/stream/series/tt33517752:1:4.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 2
    assert payload["streams"][0]["infoHash"] == "5555555555555555555555555555555555555555"
    assert payload["streams"][0]["type"] == "series"
    assert payload["streams"][0]["tag"] == "2160p"
    assert payload["streams"][0]["fileIdx"] == 5
    assert payload["streams"][0]["title"].startswith("The Beauty  S01E04\r\n\r\n")
    assert "47.0 GB" in payload["streams"][0]["title"]
    assert "2160p HDR DV WEB-DL" in payload["streams"][0]["title"]
    assert "qbrssrules/kinozal" in payload["streams"][0]["title"]
    assert payload["streams"][1]["infoHash"] == "4444444444444444444444444444444444444444"
    assert payload["streams"][1].get("fileIdx") is None
    assert payload["streams"][1]["tag"] == "1080p"
    assert set(seen_payloads) == {
        ("The Beauty", ("S01E04",), "tt33517752"),
        ("The Beauty S01E04", (), None),
        ("The Beauty", ("S01",), "tt33517752"),
    }


def test_stremio_stream_route_prefers_local_qb_playback_for_completed_files(
    app_client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
        qb_base_url="http://qb.test",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("adminadmin"),
    )
    db_session.add(settings)
    db_session.commit()

    series_root = tmp_path / "The Beauty [imdbid-tt33517752]"
    episode_directory = series_root / "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265"
    episode_directory.mkdir(parents=True)
    episode_path = episode_directory / "The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
    episode_bytes = b"episode-1-local-playback"
    episode_path.write_bytes(episode_bytes)

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "The Beauty S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="local-2160",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="http://jackett.test/dl/the-beauty-s01-pack.torrent",
                    info_hash=None,
                    indexer="kinozal",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=25,
                    peers=28,
                    published_at="2026-03-28T09:00:00+00:00",
                ),
            ],
            fallback_results=[],
        )

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/dl/the-beauty-s01-pack.torrent"
        assert timeout_seconds > 0
        return (b"d4:infod4:name4:testee", "the-beauty-s01-pack.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        return ParsedTorrentInfo(
            info_hash="5555555555555555555555555555555555555555",
            filename=source_name,
            files=[
                TorrentFileEntry(
                    file_id=5, path="The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
                ),
            ],
            tracker_urls=["https://tracker.example/announce"],
        )

    def fake_login(self):
        self._authenticated = True

    def fake_close(self):
        return None

    def fake_get_torrent(self, info_hash):
        assert info_hash == "5555555555555555555555555555555555555555"
        return {
            "hash": info_hash,
            "progress": 1,
            "size": len(episode_bytes),
            "completed": len(episode_bytes),
            "save_path": str(series_root),
            "content_path": str(episode_directory),
            "root_path": str(episode_directory),
        }

    def fake_get_torrent_files(self, info_hash):
        assert info_hash == "5555555555555555555555555555555555555555"
        return [
            {
                "index": 5,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                "progress": 1,
                "is_seed": True,
            }
        ]

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._download_torrent_bytes_for_stremio",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr("app.services.stremio_addon.parse_torrent_info", fake_parse_torrent_info)
    monkeypatch.setattr(QbittorrentClient, "login", fake_login)
    monkeypatch.setattr(QbittorrentClient, "close", fake_close)
    monkeypatch.setattr(QbittorrentClient, "get_torrent", fake_get_torrent)
    monkeypatch.setattr(QbittorrentClient, "get_torrent_files", fake_get_torrent_files)

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["name"] == "qB RSS Rules\nLocal 2160p HDR DV WEB-DL"
    assert payload["streams"][0]["tag"] == "2160p"
    assert (
        payload["streams"][0]["title"] == "The Beauty  S01E01\r\n\r\n📁 Local qB file  ⚙️ qbrssrules"
    )
    assert payload["streams"][0]["behaviorHints"] == {
        "bingieGroup": "qB RSS Rules|5555555555555555555555555555555555555555",
        "filename": "The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
        "notWebReady": True,
    }
    assert "infoHash" not in payload["streams"][0]
    assert payload["streams"][0]["url"].startswith("http://testserver/stremio/local-playback/")

    local_response = app_client.get(
        payload["streams"][0]["url"],
        headers={"Range": "bytes=0-6"},
    )

    assert local_response.status_code in {200, 206}
    assert local_response.content.startswith(episode_bytes[:7])


def test_stremio_stream_route_keeps_quality_sorted_variant_set_and_marks_local_exact_variant(
    app_client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
        qb_base_url="http://qb.test",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("adminadmin"),
    )
    db_session.add(settings)
    db_session.commit()

    series_root = tmp_path / "The Beauty [imdbid-tt33517752]"
    episode_directory = series_root / "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265"
    episode_directory.mkdir(parents=True)
    episode_path = episode_directory / "The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
    episode_path.write_bytes(b"episode-1-local-playback")

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "The Beauty S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="local-2160",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="magnet:?xt=urn:btih:5555555555555555555555555555555555555555",
                    info_hash="5555555555555555555555555555555555555555",
                    indexer="kinozal",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=25,
                    peers=28,
                    published_at="2026-03-28T09:00:00+00:00",
                ),
                JackettSearchResult(
                    merge_key="1080-high-seed",
                    title="The Beauty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:6666666666666666666666666666666666666666",
                    info_hash="6666666666666666666666666666666666666666",
                    indexer="rutracker",
                    size_bytes=2_300_000_000,
                    size_label="2.3 GB",
                    seeders=361,
                    peers=410,
                    published_at="2026-03-28T10:00:00+00:00",
                ),
                JackettSearchResult(
                    merge_key="1080-low-seed",
                    title="The Beauty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:7777777777777777777777777777777777777777",
                    info_hash="7777777777777777777777777777777777777777",
                    indexer="rutor",
                    size_bytes=2_100_000_000,
                    size_label="2.1 GB",
                    seeders=19,
                    peers=24,
                    published_at="2026-03-28T08:00:00+00:00",
                ),
            ],
            fallback_results=[],
        )

    def fake_login(self):
        self._authenticated = True

    def fake_close(self):
        return None

    def fake_get_torrent(self, info_hash):
        if info_hash != "5555555555555555555555555555555555555555":
            return None
        return {
            "hash": info_hash,
            "progress": 1,
            "size": len(episode_path.read_bytes()),
            "completed": len(episode_path.read_bytes()),
            "save_path": str(series_root),
            "content_path": str(episode_directory),
            "root_path": str(episode_directory),
        }

    def fake_get_torrent_files(self, info_hash):
        assert info_hash == "5555555555555555555555555555555555555555"
        return [
            {
                "index": 5,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E01.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                "progress": 1,
                "is_seed": True,
            }
        ]

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(QbittorrentClient, "login", fake_login)
    monkeypatch.setattr(QbittorrentClient, "close", fake_close)
    monkeypatch.setattr(QbittorrentClient, "get_torrent", fake_get_torrent)
    monkeypatch.setattr(QbittorrentClient, "get_torrent_files", fake_get_torrent_files)

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 3
    assert payload["streams"][0]["name"] == "qB RSS Rules\nLocal 2160p HDR DV WEB-DL"
    assert payload["streams"][0]["tag"] == "2160p"
    assert payload["streams"][0]["url"].startswith("http://testserver/stremio/local-playback/")
    assert payload["streams"][1]["infoHash"] == "6666666666666666666666666666666666666666"
    assert payload["streams"][1]["tag"] == "1080p"
    assert payload["streams"][1]["seeders"] == 361
    assert payload["streams"][2]["infoHash"] == "7777777777777777777777777777777777777777"
    assert payload["streams"][2]["tag"] == "1080p"
    assert payload["streams"][2]["seeders"] == 19


def test_stremio_stream_route_uses_local_qb_inventory_when_jackett_misses_best_variant(
    app_client,
    db_session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
        qb_base_url="http://qb.test",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("adminadmin"),
    )
    db_session.add(settings)
    db_session.commit()

    series_root = tmp_path / "The Beauty [imdbid-tt33517752]"
    episode_directory = series_root / "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265"
    episode_directory.mkdir(parents=True)
    episode_path = episode_directory / "The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv"
    episode_path.write_bytes(b"episode-4-local-playback")

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.keywords_all == ["S01E04"]:
            return JackettSearchRun(
                results=[
                    JackettSearchResult(
                        merge_key="exact-1080",
                        title="The Beauty S01E04 Repack 2026 1080p DSNP WEB-DL",
                        link="magnet:?xt=urn:btih:4444444444444444444444444444444444444444",
                        info_hash="4444444444444444444444444444444444444444",
                        indexer="tpb",
                        size_bytes=1_300_000_000,
                        size_label="1.3 GB",
                        seeders=29,
                        peers=60,
                        published_at="2026-03-28T10:00:00+00:00",
                    ),
                ],
                fallback_results=[],
            )
        if payload.query == "The Beauty S01E04":
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.keywords_all == ["S01"]:
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    def fake_login(self):
        self._authenticated = True

    def fake_close(self):
        return None

    def fake_get_torrents(self, *, hashes=None):
        if hashes is not None:
            raise AssertionError("Inventory scan should not request filtered hashes")
        return [
            {
                "hash": "5555555555555555555555555555555555555555",
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265",
                "progress": 1,
                "size": len(episode_path.read_bytes()),
                "completed": len(episode_path.read_bytes()),
                "save_path": str(series_root),
                "content_path": str(episode_directory),
                "root_path": str(episode_directory),
                "category": "Series/The Beauty [imdbid-tt33517752]",
            }
        ]

    def fake_get_torrent(self, info_hash):
        if info_hash == "5555555555555555555555555555555555555555":
            return {
                "hash": info_hash,
                "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265",
                "progress": 1,
                "size": len(episode_path.read_bytes()),
                "completed": len(episode_path.read_bytes()),
                "save_path": str(series_root),
                "content_path": str(episode_directory),
                "root_path": str(episode_directory),
                "category": "Series/The Beauty [imdbid-tt33517752]",
            }
        return None

    def fake_get_torrent_files(self, info_hash):
        if info_hash == "5555555555555555555555555555555555555555":
            return [
                {
                    "index": 3,
                    "name": "The.Beauty.S01.2160p.DSNP.WEB-DL.DV.HDR.H.265/The.Beauty.S01E04.2160p.DSNP.WEB-DL.DV.HDR.H.265.mkv",
                    "progress": 1,
                    "is_seed": True,
                    "size": len(episode_path.read_bytes()),
                }
            ]
        raise AssertionError(f"Unexpected info hash: {info_hash}")

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(QbittorrentClient, "login", fake_login)
    monkeypatch.setattr(QbittorrentClient, "close", fake_close)
    monkeypatch.setattr(QbittorrentClient, "get_torrents", fake_get_torrents)
    monkeypatch.setattr(QbittorrentClient, "get_torrent", fake_get_torrent)
    monkeypatch.setattr(QbittorrentClient, "get_torrent_files", fake_get_torrent_files)

    response = app_client.get("/stremio/stream/series/tt33517752:1:4.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 2
    assert payload["streams"][0]["name"] == "qB RSS Rules\nLocal 2160p HDR DV WEB-DL"
    assert payload["streams"][0]["tag"] == "2160p"
    assert payload["streams"][0]["url"].startswith("http://testserver/stremio/local-playback/")
    assert payload["streams"][1]["infoHash"] == "4444444444444444444444444444444444444444"
    assert payload["streams"][1]["tag"] == "1080p"


def test_stremio_stream_route_does_not_cache_empty_results(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="The Beauty",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    call_counter = {"count": 0}

    def fake_search(self, payload):
        call_counter["count"] += 1
        if call_counter["count"] <= 3:
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="recovered",
                    title="The Beauty S01E01 WEB-DL 2160p HDR Dolby Vision",
                    link="magnet:?xt=urn:btih:7777777777777777777777777777777777777777",
                    info_hash="7777777777777777777777777777777777777777",
                    indexer="megapeer",
                    size_bytes=47 * 1024 * 1024 * 1024,
                    size_label="47.0 GB",
                    seeders=7,
                    peers=21,
                    published_at="2026-03-28T10:00:00+00:00",
                ),
            ],
            fallback_results=[],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    first_response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")
    second_response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["streams"] == []
    assert len(second_response.json()["streams"]) == 1
    assert (
        second_response.json()["streams"][0]["infoHash"]
        == "7777777777777777777777777777777777777777"
    )
    assert call_counter["count"] > 3
