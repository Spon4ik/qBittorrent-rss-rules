from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import app.services.stremio_addon as stremio_addon_module
from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, MetadataProvider
from app.schemas import (
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services.jackett import JackettClient, JackettIndexerCapability
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
    assert payload["version"] == "0.9.2+stremio.1"
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


def test_stremio_catalog_route_falls_back_to_cinemeta_when_omdb_title_search_is_empty(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        metadata_provider=MetadataProvider.OMDB,
        omdb_api_key_encrypted=obfuscate_secret("bad-omdb-key"),
    )
    db_session.add(settings)
    db_session.commit()

    def fake_search_omdb(self, query, media_type, *, limit=20, skip=0):
        assert query == "Jury Duty"
        assert media_type == MediaType.SERIES
        assert limit == 20
        assert skip == 0
        return []

    def fake_cinemeta_search(*, search_text, media_type, limit=20, skip=0):
        assert search_text == "Jury Duty"
        assert media_type == MediaType.SERIES
        assert limit == 20
        assert skip == 0
        return [
            MetadataResult(
                title="Jury Duty Presents: Company Retreat",
                provider=MetadataLookupProvider.OMDB,
                imdb_id="tt22074164",
                source_id="tt22074164",
                media_type=MediaType.SERIES,
                year="2023",
                poster_url="https://img.example/jury-duty.jpg",
            )
        ]

    monkeypatch.setattr(MetadataClient, "search_omdb", fake_search_omdb)
    monkeypatch.setattr(
        StremioAddonService,
        "_search_cinemeta_catalog",
        staticmethod(fake_cinemeta_search),
    )

    response = app_client.get("/stremio/catalog/series/qb-search/search=Jury%20Duty.json")

    assert response.status_code == 200
    assert response.json() == {
        "metas": [
            {
                "id": "tt22074164",
                "type": "series",
                "name": "Jury Duty Presents: Company Retreat",
                "releaseInfo": "2023",
                "poster": "https://img.example/jury-duty.jpg",
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
    assert "Exact" in payload["streams"][0]["title"]
    assert "qbrssrules/megapeer" in payload["streams"][0]["title"]
    assert "description" not in payload["streams"][0]
    assert payload["streams"][0].get("fileIdx") is None
    assert payload["streams"][0]["behaviorHints"] == {
        "bingieGroup": "qB RSS Rules|2222222222222222222222222222222222222222"
    }
    assert payload["streams"][1]["infoHash"] == "1111111111111111111111111111111111111111"
    assert payload["streams"][1]["tag"] == "1080p"
    assert payload["streams"][1].get("fileIdx") is None
    assert ("The Beauty", ("S01E01",), "tt33517752") in set(seen_searches)
    assert len(seen_searches) in {1, 2}
    if len(seen_searches) == 2:
        assert ("The Beauty S01E01", (), None) in set(seen_searches)


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


def test_stremio_stream_route_uses_broad_title_episode_fallback_when_imdb_episode_path_is_too_thin(
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

    seen_searches: list[tuple[str, str | None, int | None, int | None, tuple[str, ...]]] = []

    def fake_lookup_by_imdb_id(self, imdb_id):
        assert imdb_id == "tt22074164"
        return MetadataResult(
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        seen_searches.append(
            (
                payload.query,
                payload.imdb_id,
                payload.season_number,
                payload.episode_number,
                tuple(payload.keywords_all),
            )
        )
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            if payload.keywords_all == ["S01E01"]:
                return JackettSearchRun(
                    results=[
                        JackettSearchResult(
                            merge_key="tpb-720",
                            title="Jury Duty Presents: Company Retreat S01E01 720p WEB-DL",
                            link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            indexer="The Pirate Bay",
                            size_bytes=953_100_000,
                            size_label="953.1 MB",
                            seeders=5,
                            peers=7,
                            published_at="2026-04-07T10:00:00+00:00",
                        )
                    ],
                    fallback_results=[],
                )
            if payload.keywords_all == ["S01"]:
                return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    seen_broad_queries: list[str] = []

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query, **kwargs):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        seen_broad_queries.append(query)
        if query != "Company Retreat":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="rutor-1080",
                    title="Jury Duty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    info_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    indexer="Rutor",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=1,
                    peers=1,
                    published_at="2026-04-07T10:05:00+00:00",
                ),
                JackettSearchResult(
                    merge_key="rutracker-1080-a",
                    title="Jury Duty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc",
                    info_hash="cccccccccccccccccccccccccccccccccccccccc",
                    indexer="Rutracker",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=0,
                    peers=0,
                    published_at="2026-04-07T10:04:00+00:00",
                ),
                JackettSearchResult(
                    merge_key="rutracker-1080-b",
                    title="Jury Duty S01E01 WEB-DL 1080p Proper",
                    link="magnet:?xt=urn:btih:dddddddddddddddddddddddddddddddddddddddd",
                    info_hash="dddddddddddddddddddddddddddddddddddddddd",
                    indexer="Rutracker",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=0,
                    peers=0,
                    published_at="2026-04-07T10:03:00+00:00",
                ),
            ],
            fallback_results=[],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 4
    assert payload["streams"][0]["infoHash"] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    assert payload["streams"][0]["name"] == "qB RSS Rules\n1080p WEB-DL"
    assert payload["streams"][1]["infoHash"] == "cccccccccccccccccccccccccccccccccccccccc"
    assert payload["streams"][1]["name"] == "qB RSS Rules\n1080p WEB-DL"
    assert payload["streams"][2]["infoHash"] == "dddddddddddddddddddddddddddddddddddddddd"
    assert payload["streams"][2]["name"] == "qB RSS Rules\n1080p WEB-DL"
    assert payload["streams"][3]["infoHash"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert payload["streams"][3]["name"] == "qB RSS Rules\n720p WEB-DL"
    assert seen_broad_queries == ["Company Retreat"]


def test_stremio_stream_route_accepts_season_pack_and_series_title_variant_for_episode_fallback(
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

    seen_broad_queries: list[str] = []

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query, **kwargs):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        seen_broad_queries.append(query)
        if query != "Jury Duty":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="season-pack",
                    title="Быть присяжным / Jury Duty [S01] (2023) WEBRip 1080p | HDrezka Studio",
                    link="magnet:?xt=urn:btih:14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    info_hash="14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    indexer="Rutor",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=6,
                    peers=16,
                    published_at="2026-04-08T08:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["streams"][0]["infoHash"] == "14544b87fe01a84ffb8a3b75c5c9094180029fd9"
    assert "qbrssrules/Rutor" in payload["streams"][0]["title"]
    assert "RU" in payload["streams"][0]["title"]
    assert set(seen_broad_queries) == {
        "Company Retreat",
        "Jury Duty",
        "Jury Duty Presents",
        "Jury Duty Presents: Company Retreat",
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
                    size_bytes=2_300_000_000,
                ),
                TorrentFileEntry(
                    file_id=6,
                    path="The.Beauty.S01E02.2160p.WEB-DL.H265.mkv",
                    size_bytes=2_100_000_000,
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
        "videoSize": 2300000000,
    }
    assert payload["streams"][0]["sources"][0] == "tracker:https://tracker.example/announce"
    assert payload["streams"][0]["title"].startswith("The Beauty  S01E01\r\n\r\n")
    assert "2.1 GB" in payload["streams"][0]["title"]
    assert "Pack 47.0 GB" in payload["streams"][0]["title"]
    assert "2160p HDR DV WEB-DL" in payload["streams"][0]["title"]
    assert "Exact" in payload["streams"][0]["title"]
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
                TorrentFileEntry(
                    file_id=5,
                    path="The.Beauty.S01E04.2160p.WEB-DL.H265.mkv",
                    size_bytes=2_300_000_000,
                ),
                TorrentFileEntry(
                    file_id=6,
                    path="The.Beauty.S01E05.2160p.WEB-DL.H265.mkv",
                    size_bytes=2_100_000_000,
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

    response = app_client.get("/stremio/stream/series/tt33517752:1:4.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 2
    assert payload["streams"][0]["infoHash"] == "5555555555555555555555555555555555555555"
    assert payload["streams"][0]["type"] == "series"
    assert payload["streams"][0]["tag"] == "2160p"
    assert payload["streams"][0]["fileIdx"] == 5
    assert payload["streams"][0]["title"].startswith("The Beauty  S01E04\r\n\r\n")
    assert "2.1 GB" in payload["streams"][0]["title"]
    assert "Pack 47.0 GB" in payload["streams"][0]["title"]
    assert "2160p HDR DV WEB-DL" in payload["streams"][0]["title"]
    assert "Fallback" in payload["streams"][0]["title"] or "Precise title" in payload["streams"][0]["title"]
    assert "qbrssrules/kinozal" in payload["streams"][0]["title"]
    assert payload["streams"][1]["infoHash"] == "4444444444444444444444444444444444444444"
    assert payload["streams"][1].get("fileIdx") is None
    assert payload["streams"][1]["tag"] == "1080p"
    assert set(seen_payloads) == {
        ("The Beauty", ("S01E04",), "tt33517752"),
        ("The Beauty S01E04", (), None),
        ("The Beauty", ("S01",), "tt33517752"),
    }


def test_stremio_stream_route_prefers_requested_episode_file_over_parent_pack_range(
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
            title="The Rookie",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "The Rookie S08E12":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="season-pack",
                    title="The Rookie - S8E01-14 - 2026 1080p WEB-DL",
                    link="http://jackett.test/dl/the-rookie-s08-pack.torrent",
                    info_hash=None,
                    indexer="kinozal",
                    size_bytes=19_200_000_000,
                    size_label="19.2 GB",
                    seeders=17,
                    peers=24,
                    published_at="2026-04-09T10:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/dl/the-rookie-s08-pack.torrent"
        assert timeout_seconds > 0
        return (b"d4:infod4:name4:testee", "the-rookie-s08-pack.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        assert torrent_bytes == b"d4:infod4:name4:testee"
        assert source_name == "the-rookie-s08-pack.torrent"
        return ParsedTorrentInfo(
            info_hash="9999999999999999999999999999999999999999",
            filename=source_name,
            files=[
                TorrentFileEntry(
                    file_id=10,
                    path="The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E10.1080p.mkv",
                    size_bytes=1_600_000_000,
                ),
                TorrentFileEntry(
                    file_id=12,
                    path="The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E12.1080p.mkv",
                    size_bytes=1_700_000_000,
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

    response = app_client.get("/stremio/stream/series/tt7587890:8:12.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["infoHash"] == "9999999999999999999999999999999999999999"
    assert payload["streams"][0]["fileIdx"] == 12
    assert payload["streams"][0]["behaviorHints"]["filename"] == "The.Rookie.S08E12.1080p.mkv"
    assert payload["streams"][0]["behaviorHints"]["videoSize"] == 1700000000
    assert payload["streams"][0]["title"].startswith("The Rookie  S08E12\r\n\r\n")
    assert "1.6 GB" in payload["streams"][0]["title"]
    assert "Pack 19.2 GB" in payload["streams"][0]["title"]


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


def test_stremio_stream_route_merges_external_provider_streams_and_sorts_globally(
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

    monkeypatch.setenv(
        "QB_RULES_STREMIO_STREAM_PROVIDER_MANIFESTS",
        "Torrentio|https://torrentio.strem.fun/manifest.json",
    )
    from app.config import get_environment_settings

    get_environment_settings.cache_clear()

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
                    merge_key="qb-1080",
                    title="The Beauty S01E01 WEB-DL 1080p",
                    link="magnet:?xt=urn:btih:1111111111111111111111111111111111111111",
                    info_hash="1111111111111111111111111111111111111111",
                    indexer="alpha",
                    size_bytes=4_000_000_000,
                    size_label="4.0 GB",
                    seeders=200,
                    peers=250,
                    published_at="2026-03-28T10:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    def fake_fetch_external_provider_streams(
        provider,
        *,
        item_type,
        item_id,
        timeout_seconds,
    ):
        assert provider.label == "Torrentio"
        assert item_type == "series"
        assert item_id == "tt33517752:1:1"
        assert timeout_seconds > 0
        normalized_stream = stremio_addon_module._with_provider_attribution(
            {
                "name": "Torrentio\n2160p",
                "type": "series",
                "title": "The Beauty S01E01 WEB-DL 2160p HDR  👤 5",
                "infoHash": "2222222222222222222222222222222222222222",
                "seeders": 5,
                "sources": ["tracker:https://tracker.example/announce"],
            },
            provider_label="Torrentio",
            item_type=item_type,
        )
        return [
            stremio_addon_module.CollectedStreamCandidate(
                stream=normalized_stream,
                sort_key=stremio_addon_module._provider_stream_sort_key(normalized_stream),
            )
        ]

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._fetch_external_provider_streams",
        fake_fetch_external_provider_streams,
    )

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 2
    assert payload["streams"][0]["name"] == "Torrentio\n2160p"
    assert payload["streams"][0]["infoHash"] == "2222222222222222222222222222222222222222"
    assert "Torrentio" in payload["streams"][0]["title"]
    assert payload["streams"][1]["name"] == "qB RSS Rules\n1080p WEB-DL"


def test_stream_url_from_manifest_url_quotes_episode_item_ids() -> None:
    assert stremio_addon_module._stream_url_from_manifest_url(
        "https://torrentio.strem.fun/providers=rutor,rutracker|sort=qualitysize/manifest.json",
        item_type="series",
        item_id="tt22074164:1:1",
    ) == (
        "https://torrentio.strem.fun/providers=rutor,rutracker|sort=qualitysize/"
        "stream/series/tt22074164%3A1%3A1.json"
    )


def test_fetch_external_provider_streams_uses_browser_like_headers(monkeypatch) -> None:
    provider = stremio_addon_module.ResolvedStremioStreamProvider(
        label="Torrentio",
        manifest_url="https://torrentio.strem.fun/providers=rutor,rutracker|sort=qualitysize/manifest.json",
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "streams": [
                    {
                        "name": "Torrentio\n1080p",
                        "title": "The Beauty S01E01 WEB-DL 1080p",
                        "infoHash": "1111111111111111111111111111111111111111",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout, follow_redirects):
            assert timeout == 2.5
            assert follow_redirects is True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url, *, headers):
            assert url == (
                "https://torrentio.strem.fun/providers=rutor,rutracker|sort=qualitysize/"
                "stream/series/tt22074164%3A1%3A1.json"
            )
            assert headers == stremio_addon_module.STREMIO_EXTERNAL_PROVIDER_HEADERS
            return FakeResponse()

    monkeypatch.setattr(stremio_addon_module.httpx, "Client", FakeClient)

    streams = stremio_addon_module._fetch_external_provider_streams(
        provider,
        item_type="series",
        item_id="tt22074164:1:1",
        timeout_seconds=2.5,
    )

    assert len(streams) == 1
    assert streams[0].stream["infoHash"] == "1111111111111111111111111111111111111111"


def test_stremio_stream_route_skips_non_video_episode_torrent_after_broad_subtitle_fallback(
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
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            if payload.keywords_all == ["S01E01"]:
                return JackettSearchRun(results=[], fallback_results=[])
            if payload.keywords_all == ["S01"]:
                return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    seen_broad_queries: list[str] = []

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        seen_broad_queries.append(query)
        if query != "Company Retreat":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="bad-pdf",
                    title="Forest Bathing Retreat",
                    link="http://jackett.test/download/retreat.torrent",
                    indexer="RuTracker.org",
                    size_bytes=89_900_000,
                    size_label="89.9 MB",
                    seeders=6,
                    peers=6,
                    published_at="2026-04-07T10:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/download/retreat.torrent"
        assert timeout_seconds > 0
        return (b"fake", "retreat.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        assert torrent_bytes == b"fake"
        assert source_name == "retreat.torrent"
        return ParsedTorrentInfo(
            info_hash="812cd685894f74d1394f4508aa5c784c64ba2fff",
            filename=source_name,
            files=[TorrentFileEntry(file_id=0, path="Forest Bathing Retreat.pdf")],
            tracker_urls=["https://tracker.example/announce"],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )
    monkeypatch.setattr(
        "app.services.stremio_addon._download_torrent_bytes_for_stremio",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr(
        "app.services.stremio_addon.parse_torrent_info",
        fake_parse_torrent_info,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:1.json")

    assert response.status_code == 200
    assert response.json()["streams"] == []
    assert seen_broad_queries == [
        "Company Retreat",
        "Jury Duty",
        "Jury Duty Presents: Company Retreat",
        "Jury Duty Presents",
    ]


def test_stremio_stream_route_skips_single_file_http_torrent_without_episode_match(
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
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E02":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query, **kwargs):
        if query != "Jury Duty":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="bad-http-movie",
                    title="Работа присяжного / Jury Duty (1995) WEBRip | A",
                    link="http://jackett.test/download/movie.torrent",
                    indexer="RuTor",
                    size_bytes=1_500_000_000,
                    size_label="1.5 GB",
                    seeders=1,
                    peers=1,
                    published_at="2026-04-08T08:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    def fake_download_torrent_bytes(link, *, timeout_seconds):
        assert link == "http://jackett.test/download/movie.torrent"
        assert timeout_seconds > 0
        return (b"fake", "movie.torrent")

    def fake_parse_torrent_info(torrent_bytes, *, source_name="queued-result.torrent"):
        assert torrent_bytes == b"fake"
        assert source_name == "movie.torrent"
        return ParsedTorrentInfo(
            info_hash="38e976b3fb0fe4ea6fabc4deba11d6b785944ccc",
            filename=source_name,
            files=[TorrentFileEntry(file_id=0, path="Присяжный (Jury Duty) [by ale_X2008] fix2.avi")],
            tracker_urls=["https://tracker.example/announce"],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )
    monkeypatch.setattr(
        "app.services.stremio_addon._download_torrent_bytes_for_stremio",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr(
        "app.services.stremio_addon.parse_torrent_info",
        fake_parse_torrent_info,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:2.json")

    assert response.status_code == 200
    assert response.json()["streams"] == []


def test_stremio_stream_route_filters_to_preferred_language_matches_when_configured(
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

    monkeypatch.setenv("QB_RULES_STREMIO_PREFERRED_LANGUAGES", "ru")
    from app.config import get_environment_settings

    get_environment_settings.cache_clear()

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            if payload.keywords_all == ["S01E01"]:
                return JackettSearchRun(
                    results=[
                        JackettSearchResult(
                            merge_key="tpb-1080",
                            title="Jury Duty Presents Company Retreat S01E01 1080p WEB-DL",
                            link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                            indexer="The Pirate Bay",
                            size_bytes=1_500_000_000,
                            size_label="1.5 GB",
                            seeders=100,
                            peers=140,
                            published_at="2026-04-08T08:05:00+00:00",
                        )
                    ],
                    fallback_results=[],
                )
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query, **kwargs):
        if query != "Jury Duty":
            return JackettSearchRun(results=[], fallback_results=[])
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="rutor-ru",
                    title="Быть присяжным / Jury Duty [S01] (2023) WEBRip 1080p | HDrezka Studio",
                    link="magnet:?xt=urn:btih:14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    info_hash="14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    indexer="Rutor",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=6,
                    peers=16,
                    published_at="2026-04-08T08:00:00+00:00",
                    torznab_attrs={"language": "rus"},
                )
            ],
            fallback_results=[],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert [stream["infoHash"] for stream in payload["streams"]] == [
        "14544b87fe01a84ffb8a3b75c5c9094180029fd9"
    ]


def test_stremio_stream_route_stops_broad_title_variants_after_preferred_language_match(
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
        stremio_preferred_languages="ru",
    )
    db_session.add(settings)
    db_session.commit()

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url=None,
        )

    def fake_search(self, payload):
        if payload.query == "Company Retreat" and payload.imdb_id == "tt22074164":
            return JackettSearchRun(results=[], fallback_results=[])
        if payload.query == "Company Retreat S01E01":
            return JackettSearchRun(results=[], fallback_results=[])
        raise AssertionError(f"Unexpected payload: {payload!r}")

    seen_queries: list[str] = []

    def fake_run_jackett_unstructured_title_search(*, api_url, api_key, query, **kwargs):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        seen_queries.append(query)
        if query != "Company Retreat":
            raise AssertionError(f"Unexpected fallback query after preferred match: {query}")
        return JackettSearchRun(
            results=[
                JackettSearchResult(
                    merge_key="rutor-ru",
                    title="Быть присяжным / Jury Duty [S01] (2023) WEBRip 1080p | HDrezka Studio",
                    link="magnet:?xt=urn:btih:14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    info_hash="14544b87fe01a84ffb8a3b75c5c9094180029fd9",
                    indexer="Rutor",
                    size_bytes=1_900_000_000,
                    size_label="1.9 GB",
                    seeders=6,
                    peers=16,
                    published_at="2026-04-08T08:00:00+00:00",
                    torznab_attrs={"language": "rus"},
                )
            ],
            fallback_results=[],
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._run_jackett_unstructured_title_search",
        fake_run_jackett_unstructured_title_search,
    )

    response = app_client.get("/stremio/stream/series/tt22074164:1:1.json")

    assert response.status_code == 200
    assert seen_queries == ["Company Retreat"]
    assert [stream["infoHash"] for stream in response.json()["streams"]] == [
        "14544b87fe01a84ffb8a3b75c5c9094180029fd9"
    ]


def test_result_matches_requested_episode_rejects_conflicting_explicit_season_before_http_probe() -> (
    None
):
    assert (
        stremio_addon_module._result_matches_requested_episode(
            JackettSearchResult(
                title="Jury Duty - S2E1-8 - 2026 MVO (HDrezka Studio), Sub WEBDL 1080p - RUSSIAN",
                link="http://jackett.test/download/s2.torrent",
            ),
            season_number=1,
            episode_number=1,
        )
        is False
    )
    assert (
        stremio_addon_module._result_matches_requested_episode(
            JackettSearchResult(
                title="Быть присяжным / Jury Duty [S01] (2023) WEBRip 1080p | HDrezka Studio",
                link="http://jackett.test/download/s1.torrent",
            ),
            season_number=1,
            episode_number=1,
        )
        is True
    )
    assert (
        stremio_addon_module._result_matches_requested_episode(
            JackettSearchResult(
                title="Работа присяжного / Jury Duty (1995) WEBRip | A",
                link="http://jackett.test/download/movie.torrent",
            ),
            season_number=1,
            episode_number=1,
        )
        is False
    )
    assert (
        stremio_addon_module._result_matches_requested_episode(
            JackettSearchResult(
                title="Jury Duty Presents: Company Retreat",
                link="http://jackett.test/download/ambiguous.torrent",
            ),
            season_number=1,
            episode_number=1,
        )
        is True
    )


def test_episode_query_variants_prioritize_base_series_title_for_subtitle_names() -> None:
    assert stremio_addon_module._episode_query_variants(
        "Jury Duty Presents: Company Retreat"
    ) == (
        "Company Retreat",
        "Jury Duty",
        "Jury Duty Presents: Company Retreat",
        "Jury Duty Presents",
    )


def test_unstructured_direct_search_prioritizes_and_caps_indexers(monkeypatch) -> None:
    configured_indexers = [
        JackettIndexerCapability(indexer_id="alpha", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="beta", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="rutracker", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="gamma", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="kinozal", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="rutor", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="delta", supported_params=frozenset({"q"})),
        JackettIndexerCapability(indexer_id="nnmclub", supported_params=frozenset({"q"})),
    ]
    seen_indexers: list[str] = []

    def fake_configured_indexers_for_mode(self, search_mode):
        assert search_mode == "search"
        return configured_indexers

    def fake_run_single_direct_search_indexer(*, api_url, api_key, indexer_id, query):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        assert query == "Company Retreat"
        seen_indexers.append(indexer_id)
        return (
            f'{indexer_id}: t=search q="Company Retreat"',
            [],
            None,
        )

    monkeypatch.setattr(
        JackettClient,
        "_configured_indexers_for_mode",
        fake_configured_indexers_for_mode,
    )
    monkeypatch.setattr(
        stremio_addon_module,
        "_run_single_direct_search_indexer",
        fake_run_single_direct_search_indexer,
    )

    run = stremio_addon_module._run_jackett_unstructured_title_search(
        api_url="http://jackett.test",
        api_key="jackett-key",
        query="Company Retreat",
    )

    assert run is not None
    assert seen_indexers == ["kinozal", "rutor", "rutracker", "nnmclub"]
    assert run.request_variants == [
        'kinozal: t=search q="Company Retreat"',
        'rutor: t=search q="Company Retreat"',
        'rutracker: t=search q="Company Retreat"',
        'nnmclub: t=search q="Company Retreat"',
    ]
    assert run.results == []
    assert not run.warning_messages


def test_collect_enriched_search_run_returns_after_sufficient_exact_episode_matches(
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

    text_search_started = threading.Event()
    allow_text_search_to_finish = threading.Event()
    text_search_finished = threading.Event()

    def fake_run_jackett_search(*, api_url, api_key, payload):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        if payload.imdb_id_only:
            assert text_search_started.wait(timeout=0.2)
            return JackettSearchRun(
                results=[
                    JackettSearchResult(
                        merge_key="exact-a",
                        title="The Beauty S01E01 WEB-DL 2160p",
                        link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        indexer="alpha",
                    ),
                    JackettSearchResult(
                        merge_key="exact-b",
                        title="The Beauty S01E01 WEB-DL 1080p",
                        link="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        info_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        indexer="beta",
                    ),
                ],
                fallback_results=[],
            )
        text_search_started.set()
        allow_text_search_to_finish.wait(timeout=1.0)
        text_search_finished.set()
        return JackettSearchRun(results=[], fallback_results=[])

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(
        stremio_addon_module,
        "_run_jackett_search",
        fake_run_jackett_search,
    )

    service = StremioAddonService(settings)
    payload = stremio_addon_module.JackettSearchRequest(
        query="The Beauty",
        media_type=MediaType.SERIES,
        imdb_id="tt33517752",
        season_number=1,
        episode_number=1,
    )

    started_at = time.perf_counter()
    run = service.collect_enriched_search_run(payload=payload)
    elapsed = time.perf_counter() - started_at
    allow_text_search_to_finish.set()

    assert text_search_started.is_set()
    assert not text_search_finished.is_set()
    assert elapsed < 0.7
    assert run is not None
    assert [result.merge_key for result in list(run.results or [])] == ["exact-a", "exact-b"]


def test_collect_enriched_search_run_skips_broad_episode_fallback_when_provider_merge_can_supply_breadth(
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

    monkeypatch.setenv(
        "QB_RULES_STREMIO_STREAM_PROVIDER_MANIFESTS",
        "Torrentio|https://torrentio.strem.fun/manifest.json",
    )
    from app.config import get_environment_settings

    get_environment_settings.cache_clear()

    def fake_lookup_by_imdb_id(self, imdb_id):
        return MetadataResult(
            title="Jury Duty Presents: Company Retreat",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    seen_queries: list[str] = []

    def fake_run_jackett_search(*, api_url, api_key, payload):
        assert api_url == "http://jackett.test"
        assert api_key == "jackett-key"
        seen_queries.append(str(payload.query))
        if payload.imdb_id_only:
            return JackettSearchRun(
                results=[
                    JackettSearchResult(
                        merge_key="exact-ru",
                        title="Jury Duty S01E01 WEB-DL 1080p RUS",
                        link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        indexer="rutor",
                    )
                ],
                fallback_results=[],
            )
        return JackettSearchRun(results=[], fallback_results=[])

    def fail_unstructured_title_search(**kwargs):
        raise AssertionError(f"unexpected broad title fallback: {kwargs}")

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(
        stremio_addon_module,
        "_run_jackett_search",
        fake_run_jackett_search,
    )
    monkeypatch.setattr(
        stremio_addon_module,
        "_run_jackett_unstructured_title_search",
        fail_unstructured_title_search,
    )

    service = StremioAddonService(settings)
    payload = stremio_addon_module.JackettSearchRequest(
        query="Company Retreat",
        media_type=MediaType.SERIES,
        imdb_id="tt22074164",
        season_number=1,
        episode_number=1,
    )

    run = service.collect_enriched_search_run(payload=payload)

    assert run is not None
    assert [result.merge_key for result in list(run.results or [])] == ["exact-ru"]
    assert seen_queries == [
        "Company Retreat",
        "Company Retreat S01E01",
    ]


def test_collect_enriched_search_run_keeps_broad_episode_fallback_rows_out_of_precise_lane(
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
            title="Young Sherlock",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2026",
            poster_url=None,
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(
        stremio_addon_module.StremioAddonService,
        "_collect_search_runs_for_target",
        lambda self, **kwargs: [
            JackettSearchRun(
                results=[
                    JackettSearchResult(
                        merge_key="exact-primary",
                        title="Young Sherlock S01E01 2160p HDR10 WEB-DL (2026)",
                        link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        indexer="alpha",
                    )
                ],
                fallback_results=[],
            ),
            JackettSearchRun(
                results=[],
                fallback_results=[
                    JackettSearchResult(
                        merge_key="fallback-test-cut",
                        title="Young Sherlock Test Cut S01E01 2160p HDR10 (2026)",
                        link="magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        info_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        indexer="beta",
                    )
                ],
            ),
        ],
    )

    service = StremioAddonService(settings)
    payload = stremio_addon_module.JackettSearchRequest(
        query="Young Sherlock",
        media_type=MediaType.SERIES,
        imdb_id="tt8599532",
        season_number=1,
        episode_number=1,
    )

    run = service.collect_enriched_search_run(payload=payload)

    assert run is not None
    assert [result.merge_key for result in list(run.results or [])] == ["exact-primary"]
    assert [result.merge_key for result in list(run.fallback_results or [])] == [
        "fallback-test-cut"
    ]


def test_stremio_stream_route_dedupes_same_infohash_across_qb_and_external_sources(
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

    monkeypatch.setenv(
        "QB_RULES_STREMIO_STREAM_PROVIDER_MANIFESTS",
        "Torrentio|https://torrentio.strem.fun/manifest.json",
    )
    from app.config import get_environment_settings

    get_environment_settings.cache_clear()

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
                    merge_key="shared-hash",
                    title="The Beauty S01E01 WEB-DL 2160p",
                    link="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    info_hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    indexer="alpha",
                    size_bytes=8_000_000_000,
                    size_label="8.0 GB",
                    seeders=12,
                    peers=40,
                    published_at="2026-03-28T10:00:00+00:00",
                )
            ],
            fallback_results=[],
        )

    def fake_fetch_external_provider_streams(
        provider,
        *,
        item_type,
        item_id,
        timeout_seconds,
    ):
        del provider, item_id, timeout_seconds
        normalized_stream = stremio_addon_module._with_provider_attribution(
            {
                "name": "Torrentio\n2160p",
                "type": "series",
                "title": "The Beauty S01E01 WEB-DL 2160p  👤 80",
                "infoHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "seeders": 80,
            },
            provider_label="Torrentio",
            item_type=item_type,
        )
        return [
            stremio_addon_module.CollectedStreamCandidate(
                stream=normalized_stream,
                sort_key=stremio_addon_module._provider_stream_sort_key(normalized_stream),
            )
        ]

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)
    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(
        "app.services.stremio_addon._fetch_external_provider_streams",
        fake_fetch_external_provider_streams,
    )

    response = app_client.get("/stremio/stream/series/tt33517752:1:1.json")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["infoHash"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert "Torrentio" in payload["streams"][0]["title"]
    get_environment_settings.cache_clear()
