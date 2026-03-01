from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import get_environment_settings
from app.models import MediaType, MetadataProvider
from app.schemas import MetadataResult

IMDB_ID_RE = re.compile(r"^tt\d+$")


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

    def lookup_by_imdb_id(self, imdb_id: str) -> MetadataResult:
        if self.provider == MetadataProvider.DISABLED:
            raise MetadataLookupError("Metadata lookup is disabled.")
        if not IMDB_ID_RE.match(imdb_id):
            raise MetadataLookupError("IMDb ID must look like tt1234567.")
        if not self.api_key:
            raise MetadataLookupError("OMDb API key is not configured.")

        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(
                    "https://www.omdbapi.com/",
                    params={"apikey": self.api_key, "i": imdb_id},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise MetadataLookupError(
                    "OMDb rejected the API key. Paste only the API key value, not the full OMDb URL."
                ) from exc
            raise MetadataLookupError(f"Metadata lookup failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise MetadataLookupError(f"Metadata lookup failed: {exc}") from exc

        if payload.get("Response") == "False":
            raise MetadataLookupError(payload.get("Error", "Metadata lookup failed."))

        media_type_raw = payload.get("Type", "series")
        if media_type_raw == "movie":
            media_type = MediaType.MOVIE
        else:
            media_type = MediaType.SERIES

        return MetadataResult(
            title=str(payload.get("Title", imdb_id)).strip(),
            imdb_id=imdb_id,
            media_type=media_type,
            year=str(payload.get("Year")) if payload.get("Year") else None,
        )
