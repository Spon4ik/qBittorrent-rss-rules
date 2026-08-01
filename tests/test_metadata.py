from __future__ import annotations

import httpx
import pytest

from app.models import MediaType, MetadataProvider
from app.schemas import MetadataLookupProvider
from app.services.metadata import (
    MetadataClient,
    MetadataLookupError,
    default_metadata_lookup_provider,
    metadata_lookup_provider_choices,
)
from app.services.series_catalog import SeriesCatalogClient


def test_smart_audiobook_is_default_audiobook_lookup_provider() -> None:
    choices = metadata_lookup_provider_choices(MediaType.AUDIOBOOK)

    assert choices[0]["value"] == MetadataLookupProvider.SMART_AUDIOBOOK.value
    assert choices[0]["label"] == "Smart audiobook"
    assert default_metadata_lookup_provider(MediaType.AUDIOBOOK) == "smart_audiobook"


def test_metadata_client_omdb_supports_season_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.omdbapi.com"
        assert request.url.params["i"] == "tt0944947"
        assert request.url.params["Season"] == "1"
        return httpx.Response(
            200,
            json={
                "Response": "True",
                "Title": "Game of Thrones",
                "Season": "1",
                "totalSeasons": "8",
                "Episodes": [
                    {"Episode": "1", "Released": "17 Apr 2011"},
                    {"Episode": "2", "Released": "24 Apr 2011"},
                    {"Episode": "3", "Released": "01 May 2011"},
                ],
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    listing = client.lookup_omdb_season("tt0944947", 1)

    assert listing.imdb_id == "tt0944947"
    assert listing.season_number == 1
    assert listing.total_seasons == 8
    assert [episode.episode_number for episode in listing.released_episodes] == [1, 2, 3]
    assert listing.released_episodes[0].released_at is not None


def test_series_catalog_client_uses_cinemeta_episode_inventory_before_omdb() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "v3-cinemeta.strem.io"
        return httpx.Response(
            200,
            json={
                "meta": {
                    "videos": [
                        {
                            "id": "tt1234500:1:1",
                            "season": 1,
                            "episode": 1,
                            "released": "2026-01-01T00:00:00.000Z",
                        },
                        {
                            "id": "tt1234500:1:2",
                            "season": 1,
                            "episode": 2,
                            "released": "2099-01-01T00:00:00.000Z",
                        },
                        {
                            "id": "tt1234500:2:1",
                            "season": 2,
                            "episode": 1,
                            "released": "2099-02-01T00:00:00.000Z",
                        },
                    ],
                    "status": "Continuing",
                    "releaseInfo": "2024–",
                },
            },
        )

    client = SeriesCatalogClient(
        None,
        allow_metadata_requests=False,
        transport=httpx.MockTransport(handler),
    )

    inventory = client.season_inventory(imdb_id="tt1234500", season_number=1)

    assert inventory is not None
    assert inventory.source == "Cinemeta"
    assert inventory.known_episode_numbers == [1, 2]
    assert inventory.released_episode_numbers == [1]
    assert client.series_video_ids("tt1234500") == [
        "tt1234500:1:1",
        "tt1234500:1:2",
        "tt1234500:2:1",
    ]
    assert client.series_is_known_ended("tt1234500") is False


def test_metadata_client_omdb_supports_title_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.omdbapi.com"
        assert request.url.params["t"] == "Dune Part Two"
        assert request.url.params["type"] == "movie"
        return httpx.Response(
            200,
            json={
                "Response": "True",
                "Title": "Dune: Part Two",
                "Type": "movie",
                "Year": "2024",
                "imdbID": "tt15239678",
                "Poster": "https://img.omdbapi.com/dune-part-two.jpg",
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(MetadataLookupProvider.OMDB, "Dune Part Two", MediaType.MOVIE)

    assert result.title == "Dune: Part Two"
    assert result.provider == MetadataLookupProvider.OMDB
    assert result.imdb_id == "tt15239678"
    assert result.media_type == MediaType.MOVIE
    assert result.year == "2024"
    assert result.poster_url == "https://img.omdbapi.com/dune-part-two.jpg"


def test_metadata_client_omdb_supports_id_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["i"] == "tt0944947"
        return httpx.Response(
            200,
            json={
                "Response": "True",
                "Title": "Game of Thrones",
                "Type": "series",
                "Year": "2011-2019",
                "imdbID": "tt0944947",
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup_by_imdb_id("tt0944947")

    assert result.title == "Game of Thrones"
    assert result.imdb_id == "tt0944947"
    assert result.media_type == MediaType.SERIES
    assert result.year == "2011"


def test_metadata_client_omdb_supports_search_lookup() -> None:
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_pages.append(str(request.url.params["page"]))
        assert request.url.params["s"] == "The Beauty"
        assert request.url.params["type"] == "series"
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json={
                    "Response": "True",
                    "Search": [
                        {
                            "Title": "The Beauty",
                            "Year": "2026-",
                            "imdbID": "tt33517752",
                            "Type": "series",
                            "Poster": "https://img.omdbapi.com/the-beauty.jpg",
                        },
                        {
                            "Title": "The Beauty Inside",
                            "Year": "2018",
                            "imdbID": "tt7998242",
                            "Type": "series",
                            "Poster": "N/A",
                        },
                    ],
                    "totalResults": "2",
                },
            )
        raise AssertionError(f"Unexpected page request: {request.url}")

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    results = client.search_omdb("The Beauty", MediaType.SERIES)

    assert seen_pages == ["1"]
    assert [item.imdb_id for item in results] == ["tt33517752", "tt7998242"]
    assert results[0].title == "The Beauty"
    assert results[0].media_type == MediaType.SERIES
    assert results[0].year == "2026"
    assert results[0].poster_url == "https://img.omdbapi.com/the-beauty.jpg"
    assert results[1].poster_url is None


def test_metadata_client_omdb_search_supports_skip_and_limit() -> None:
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_pages.append(str(request.url.params["page"]))
        return httpx.Response(
            200,
            json={
                "Response": "True",
                "Search": [
                    {
                        "Title": f"Movie {offset}",
                        "Year": "2024",
                        "imdbID": f"tt100000{offset}",
                        "Type": "movie",
                        "Poster": "N/A",
                    }
                    for offset in range(10)
                ],
                "totalResults": "25",
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    results = client.search_omdb("Movie", MediaType.MOVIE, limit=3, skip=12)

    assert seen_pages == ["2"]
    assert [item.imdb_id for item in results] == ["tt1000002", "tt1000003", "tt1000004"]


def test_metadata_client_omdb_reports_invalid_or_inactive_api_key_clearly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"Response": "False", "Error": "Invalid API key!"})

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MetadataLookupError) as excinfo:
        client.lookup_by_imdb_id("tt0944947")

    assert (
        str(excinfo.value)
        == "OMDb rejected the API key. Use the raw API key value only; if you already did, the key may be invalid, inactive, or not yet approved by OMDb."
    )


def test_metadata_client_musicbrainz_supports_search_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "musicbrainz.org"
        assert request.url.params["query"] == "Kind of Blue"
        return httpx.Response(
            200,
            json={
                "release-groups": [
                    {
                        "id": "f5093c06-23e3-404f-aeaa-40f72885ee3a",
                        "title": "Kind of Blue",
                        "first-release-date": "1959-08-17",
                    }
                ]
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(MetadataLookupProvider.MUSICBRAINZ, "Kind of Blue", MediaType.MUSIC)

    assert result.provider == MetadataLookupProvider.MUSICBRAINZ
    assert result.source_id == "f5093c06-23e3-404f-aeaa-40f72885ee3a"
    assert result.media_type == MediaType.MUSIC
    assert result.year == "1959"


def test_metadata_client_musicbrainz_supports_uuid_lookup() -> None:
    release_group_id = "f5093c06-23e3-404f-aeaa-40f72885ee3a"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{release_group_id}")
        return httpx.Response(
            200,
            json={
                "id": release_group_id,
                "title": "Kind of Blue",
                "first-release-date": "1959-08-17",
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(MetadataLookupProvider.MUSICBRAINZ, release_group_id, MediaType.MUSIC)

    assert result.source_id == release_group_id
    assert result.title == "Kind of Blue"


def test_metadata_client_openlibrary_supports_title_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openlibrary.org"
        assert request.url.path == "/search.json"
        assert request.url.params["title"] == "Project Hail Mary"
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "key": "/works/OL12345W",
                        "title": "Project Hail Mary",
                        "first_publish_year": 2021,
                    }
                ]
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(
        MetadataLookupProvider.OPENLIBRARY, "Project Hail Mary", MediaType.AUDIOBOOK
    )

    assert result.provider == MetadataLookupProvider.OPENLIBRARY
    assert result.source_id == "works/OL12345W"
    assert result.media_type == MediaType.AUDIOBOOK
    assert result.year == "2021"


def test_metadata_client_openlibrary_supports_id_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works/OL27448W.json"
        return httpx.Response(
            200,
            json={
                "key": "/works/OL27448W",
                "title": "The Hobbit",
                "first_publish_date": "1937",
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(MetadataLookupProvider.OPENLIBRARY, "OL27448W", MediaType.AUDIOBOOK)

    assert result.title == "The Hobbit"
    assert result.source_id == "works/OL27448W"
    assert result.year == "1937"


def test_metadata_client_google_books_supports_title_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        assert request.url.params["q"] == "intitle:The Way of Kings"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "book-123",
                        "volumeInfo": {
                            "title": "The Way of Kings",
                            "publishedDate": "2010-08-31",
                        },
                    }
                ]
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(
        MetadataLookupProvider.GOOGLE_BOOKS, "The Way of Kings", MediaType.AUDIOBOOK
    )

    assert result.provider == MetadataLookupProvider.GOOGLE_BOOKS
    assert result.source_id == "book-123"
    assert result.year == "2010"


def test_metadata_client_google_books_supports_isbn_lookup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "isbn:9780593135204"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "book-9780593135204",
                        "volumeInfo": {
                            "title": "Project Hail Mary",
                            "publishedDate": "2021",
                        },
                    }
                ]
            },
        )

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(
        MetadataLookupProvider.GOOGLE_BOOKS, "9780593135204", MediaType.AUDIOBOOK
    )

    assert result.title == "Project Hail Mary"
    assert result.source_id == "book-9780593135204"
    assert result.year == "2021"


def test_metadata_client_smart_audiobook_lookup_uses_google_books_first_for_isbn() -> None:
    seen_requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.url.host or "", request.url.params.get("q", "")))
        if request.url.host == "www.googleapis.com":
            assert request.url.params["q"] == "isbn:9785961436891"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "book-9785961436891",
                            "volumeInfo": {
                                "title": "The Last Question",
                                "authors": ["Isaac Asimov"],
                                "publisher": "Eksmo",
                                "publishedDate": "2024",
                                "industryIdentifiers": [
                                    {
                                        "type": "ISBN_13",
                                        "identifier": "9785961436891",
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected fallback request: {request.url}")

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    result = client.lookup(
        MetadataLookupProvider.SMART_AUDIOBOOK, "9785961436891", MediaType.AUDIOBOOK
    )

    assert result.provider == MetadataLookupProvider.GOOGLE_BOOKS
    assert result.title == "The Last Question"
    assert result.authors == ["Isaac Asimov"]
    assert result.publisher == "Eksmo"
    assert result.isbn == "9785961436891"
    assert result.source_id == "book-9785961436891"
    assert seen_requests == [("www.googleapis.com", "isbn:9785961436891")]


def test_metadata_client_smart_audiobook_lookup_reports_all_provider_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json={"items": []})
        if request.url.host == "openlibrary.org":
            assert request.url.path == "/isbn/9785961436891.json"
            return httpx.Response(404, json={"error": "not found"})
        raise AssertionError(f"Unexpected request: {request.url}")

    client = MetadataClient(
        MetadataProvider.OMDB,
        "secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MetadataLookupError) as exc_info:
        client.lookup(
            MetadataLookupProvider.SMART_AUDIOBOOK,
            "9785961436891",
            MediaType.AUDIOBOOK,
        )

    error_message = str(exc_info.value)
    assert "Google Books returned no matches." in error_message
    assert "OpenLibrary lookup failed" in error_message
    assert "Try searching by book title and author." in error_message
