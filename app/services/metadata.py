from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import get_environment_settings
from app.models import MediaType, MetadataProvider
from app.schemas import MetadataLookupProvider, MetadataResult

IMDB_ID_RE = re.compile(r"^tt\d+$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
ISBN_RE = re.compile(r"^(?:97[89])?\d{9}[\dXx]$")
OPENLIBRARY_ID_RE = re.compile(r"^OL\d+[MW]$", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(\d{4})\b")

_LOOKUP_PROVIDER_CATALOG: tuple[dict[str, object], ...] = (
    {
        "value": MetadataLookupProvider.OMDB.value,
        "label": "OMDb (Video)",
        "media_types": [MediaType.SERIES.value, MediaType.MOVIE.value],
    },
    {
        "value": MetadataLookupProvider.MUSICBRAINZ.value,
        "label": "MusicBrainz",
        "media_types": [MediaType.MUSIC.value],
    },
    {
        "value": MetadataLookupProvider.OPENLIBRARY.value,
        "label": "OpenLibrary",
        "media_types": [MediaType.AUDIOBOOK.value],
    },
    {
        "value": MetadataLookupProvider.GOOGLE_BOOKS.value,
        "label": "Google Books",
        "media_types": [MediaType.AUDIOBOOK.value],
    },
)


class MetadataLookupError(RuntimeError):
    pass


def normalize_omdb_api_key(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    if "://" in cleaned:
        parsed = urlparse(cleaned)
        query_value = parse_qs(parsed.query).get("apikey", [])
        if query_value and query_value[0].strip():
            return query_value[0].strip()

    if "apikey=" in cleaned:
        query_value = parse_qs(cleaned.lstrip("?")).get("apikey", [])
        if query_value and query_value[0].strip():
            return query_value[0].strip()

    return cleaned


def metadata_lookup_provider_catalog() -> list[dict[str, object]]:
    return [
        {
            "value": str(item["value"]),
            "label": str(item["label"]),
            "media_types": list(item["media_types"]),
        }
        for item in _LOOKUP_PROVIDER_CATALOG
    ]


def metadata_lookup_provider_choices(media_type: MediaType | str | None) -> list[dict[str, object]]:
    raw_media_type = media_type.value if isinstance(media_type, MediaType) else str(media_type or "")
    if not raw_media_type or raw_media_type == MediaType.OTHER.value:
        return metadata_lookup_provider_catalog()
    return [
        item
        for item in metadata_lookup_provider_catalog()
        if raw_media_type in item["media_types"]
    ]


def default_metadata_lookup_provider(media_type: MediaType | str | None) -> str:
    choices = metadata_lookup_provider_choices(media_type)
    if not choices:
        return MetadataLookupProvider.OMDB.value
    return str(choices[0]["value"])


def _extract_year(value: object) -> str | None:
    if value in {None, ""}:
        return None
    match = YEAR_RE.search(str(value))
    if not match:
        return None
    return match.group(1)


class MetadataClient:
    def __init__(
        self,
        provider: MetadataProvider,
        api_key: str | None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = normalize_omdb_api_key(api_key)
        self.timeout = timeout if timeout is not None else get_environment_settings().request_timeout
        self.transport = transport

    def lookup(
        self,
        provider: MetadataLookupProvider | str,
        lookup_value: str,
        media_type: MediaType = MediaType.SERIES,
    ) -> MetadataResult:
        if self.provider == MetadataProvider.DISABLED:
            raise MetadataLookupError("Metadata lookup is disabled.")

        cleaned_lookup_value = lookup_value.strip()
        if not cleaned_lookup_value:
            raise MetadataLookupError("Enter a title or source ID first.")

        try:
            lookup_provider = (
                provider
                if isinstance(provider, MetadataLookupProvider)
                else MetadataLookupProvider(str(provider))
            )
        except ValueError as exc:
            raise MetadataLookupError(f"Unsupported metadata provider: {provider}") from exc

        if lookup_provider == MetadataLookupProvider.OMDB:
            return self._lookup_omdb(cleaned_lookup_value, media_type)
        if lookup_provider == MetadataLookupProvider.MUSICBRAINZ:
            return self._lookup_musicbrainz(cleaned_lookup_value)
        if lookup_provider == MetadataLookupProvider.OPENLIBRARY:
            return self._lookup_openlibrary(cleaned_lookup_value)
        return self._lookup_google_books(cleaned_lookup_value)

    def lookup_by_imdb_id(self, imdb_id: str) -> MetadataResult:
        return self.lookup(MetadataLookupProvider.OMDB, imdb_id, MediaType.SERIES)

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        provider_label: str,
    ) -> dict[str, object]:
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            if provider_label == "OMDb" and exc.response.status_code in {401, 403}:
                raise MetadataLookupError(
                    "OMDb rejected the API key. Paste only the API key value, not the full OMDb URL."
                ) from exc
            raise MetadataLookupError(f"{provider_label} lookup failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise MetadataLookupError(f"{provider_label} lookup failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise MetadataLookupError(f"{provider_label} lookup failed: invalid JSON response.")
        return payload

    def _lookup_omdb(self, lookup_value: str, media_type: MediaType) -> MetadataResult:
        if IMDB_ID_RE.match(lookup_value) and not self.api_key:
            raise MetadataLookupError("OMDb API key is not configured.")
        if not self.api_key:
            raise MetadataLookupError("OMDb API key is not configured.")

        params: dict[str, object] = {"apikey": self.api_key}
        if IMDB_ID_RE.match(lookup_value):
            params["i"] = lookup_value
        else:
            params["t"] = lookup_value
            if media_type == MediaType.MOVIE:
                params["type"] = "movie"
            elif media_type == MediaType.SERIES:
                params["type"] = "series"

        payload = self._request_json(
            "https://www.omdbapi.com/",
            params=params,
            provider_label="OMDb",
        )
        if payload.get("Response") == "False":
            raise MetadataLookupError(str(payload.get("Error", "Metadata lookup failed.")))

        media_type_raw = str(payload.get("Type", "")).strip().lower()
        if media_type_raw == "movie":
            resolved_media_type = MediaType.MOVIE
        elif media_type_raw == "series":
            resolved_media_type = MediaType.SERIES
        elif media_type in {MediaType.MOVIE, MediaType.SERIES}:
            resolved_media_type = media_type
        else:
            resolved_media_type = MediaType.SERIES

        imdb_id = str(payload.get("imdbID", "")).strip() or None
        return MetadataResult(
            title=str(payload.get("Title", lookup_value)).strip(),
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=resolved_media_type,
            year=_extract_year(payload.get("Year")),
        )

    def _lookup_musicbrainz(self, lookup_value: str) -> MetadataResult:
        headers = {
            "Accept": "application/json",
            "User-Agent": "qBittorrent-RSS-Rule-Manager/0.1 (localhost)",
        }
        if UUID_RE.match(lookup_value):
            payload = self._request_json(
                f"https://musicbrainz.org/ws/2/release-group/{lookup_value}",
                params={"fmt": "json"},
                headers=headers,
                provider_label="MusicBrainz",
            )
        else:
            payload = self._request_json(
                "https://musicbrainz.org/ws/2/release-group/",
                params={"query": lookup_value, "limit": 1, "fmt": "json"},
                headers=headers,
                provider_label="MusicBrainz",
            )
            release_groups = payload.get("release-groups")
            if not isinstance(release_groups, list) or not release_groups:
                raise MetadataLookupError("MusicBrainz returned no matches.")
            first_match = release_groups[0]
            if not isinstance(first_match, dict):
                raise MetadataLookupError("MusicBrainz returned an invalid result.")
            payload = first_match

        source_id = str(payload.get("id", "")).strip() or None
        return MetadataResult(
            title=str(payload.get("title", lookup_value)).strip(),
            provider=MetadataLookupProvider.MUSICBRAINZ,
            source_id=source_id,
            media_type=MediaType.MUSIC,
            year=_extract_year(payload.get("first-release-date")),
        )

    def _lookup_openlibrary(self, lookup_value: str) -> MetadataResult:
        if ISBN_RE.match(lookup_value):
            payload = self._request_json(
                f"https://openlibrary.org/isbn/{lookup_value}.json",
                provider_label="OpenLibrary",
            )
            source_id = str(payload.get("key", lookup_value)).strip("/") or lookup_value
            title = str(payload.get("title", lookup_value)).strip()
            year = _extract_year(payload.get("publish_date"))
        elif OPENLIBRARY_ID_RE.match(lookup_value):
            resource = "works" if lookup_value.upper().endswith("W") else "books"
            payload = self._request_json(
                f"https://openlibrary.org/{resource}/{lookup_value}.json",
                provider_label="OpenLibrary",
            )
            source_id = str(payload.get("key", lookup_value)).strip("/") or lookup_value
            title = str(payload.get("title", lookup_value)).strip()
            year = _extract_year(payload.get("first_publish_date") or payload.get("publish_date"))
        else:
            payload = self._request_json(
                "https://openlibrary.org/search.json",
                params={"title": lookup_value, "limit": 1},
                provider_label="OpenLibrary",
            )
            docs = payload.get("docs")
            if not isinstance(docs, list) or not docs:
                raise MetadataLookupError("OpenLibrary returned no matches.")
            first_match = docs[0]
            if not isinstance(first_match, dict):
                raise MetadataLookupError("OpenLibrary returned an invalid result.")
            source_id = str(first_match.get("key", lookup_value)).strip("/") or lookup_value
            title = str(first_match.get("title", lookup_value)).strip()
            year = _extract_year(first_match.get("first_publish_year"))

        return MetadataResult(
            title=title,
            provider=MetadataLookupProvider.OPENLIBRARY,
            source_id=source_id,
            media_type=MediaType.AUDIOBOOK,
            year=year,
        )

    def _lookup_google_books(self, lookup_value: str) -> MetadataResult:
        query = f"isbn:{lookup_value}" if ISBN_RE.match(lookup_value) else f"intitle:{lookup_value}"
        payload = self._request_json(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": query, "maxResults": 1, "printType": "books"},
            provider_label="Google Books",
        )
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise MetadataLookupError("Google Books returned no matches.")
        first_match = items[0]
        if not isinstance(first_match, dict):
            raise MetadataLookupError("Google Books returned an invalid result.")
        volume_info = first_match.get("volumeInfo")
        if not isinstance(volume_info, dict):
            raise MetadataLookupError("Google Books returned an invalid result.")

        return MetadataResult(
            title=str(volume_info.get("title", lookup_value)).strip(),
            provider=MetadataLookupProvider.GOOGLE_BOOKS,
            source_id=str(first_match.get("id", lookup_value)).strip() or lookup_value,
            media_type=MediaType.AUDIOBOOK,
            year=_extract_year(volume_info.get("publishedDate")),
        )
