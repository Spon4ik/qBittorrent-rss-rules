from __future__ import annotations

import httpx

from app.models import MediaType, MetadataProvider
from app.schemas import MetadataLookupProvider
from app.services.metadata import MetadataClient


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

    result = client.lookup(MetadataLookupProvider.OPENLIBRARY, "Project Hail Mary", MediaType.AUDIOBOOK)

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

    result = client.lookup(MetadataLookupProvider.GOOGLE_BOOKS, "The Way of Kings", MediaType.AUDIOBOOK)

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

    result = client.lookup(MetadataLookupProvider.GOOGLE_BOOKS, "9780593135204", MediaType.AUDIOBOOK)

    assert result.title == "Project Hail Mary"
    assert result.source_id == "book-9780593135204"
    assert result.year == "2021"
