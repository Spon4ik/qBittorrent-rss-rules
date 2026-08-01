from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import get_environment_settings
from app.models import AppSettings, MediaType
from app.services.metadata import MetadataClient, MetadataLookupError, MetadataLookupProvider
from app.services.settings_service import SettingsService

CINEMETA_SERIES_META_URL = "https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json"
IMDB_ID_RE = re.compile(r"(tt\d{5,12})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SeriesSeasonEpisodeInventory:
    imdb_id: str
    season_number: int
    known_episode_numbers: list[int]
    released_episode_numbers: list[int]
    source: str


def normalize_series_catalog_imdb_id(value: str | None) -> str | None:
    match = IMDB_ID_RE.search(str(value or "").strip())
    return match.group(1).lower() if match else None


class SeriesCatalogClient:
    def __init__(
        self,
        settings: AppSettings | None,
        *,
        allow_metadata_requests: bool = True,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.allow_metadata_requests = allow_metadata_requests
        self.timeout = (
            timeout if timeout is not None else get_environment_settings().request_timeout
        )
        self.transport = transport
        self.metadata_config = SettingsService.resolve_metadata(settings)
        self._cinemeta_payload_cache: dict[str, dict[str, object] | None] = {}
        self._season_cache: dict[tuple[str, int], SeriesSeasonEpisodeInventory | None] = {}
        self._series_ended_cache: dict[str, bool | None] = {}
        self._metadata_client: MetadataClient | None = None

    def season_inventory(
        self,
        *,
        imdb_id: str | None,
        season_number: int,
    ) -> SeriesSeasonEpisodeInventory | None:
        normalized_imdb_id = normalize_series_catalog_imdb_id(imdb_id)
        if not normalized_imdb_id or season_number < 1 or season_number > 99:
            return None

        cache_key = (normalized_imdb_id, season_number)
        if cache_key in self._season_cache:
            return self._season_cache[cache_key]

        inventory = self._cinemeta_season_inventory(
            imdb_id=normalized_imdb_id,
            season_number=season_number,
        )
        if inventory is None:
            inventory = self._omdb_season_inventory(
                imdb_id=normalized_imdb_id,
                season_number=season_number,
            )
        self._season_cache[cache_key] = inventory
        return inventory

    def series_video_ids(self, imdb_id: str | None) -> list[str]:
        normalized_imdb_id = normalize_series_catalog_imdb_id(imdb_id)
        if not normalized_imdb_id:
            return []
        payload = self._cinemeta_payload(normalized_imdb_id)
        if payload is None:
            return []
        videos = _cinemeta_videos(payload)
        if videos is None:
            return []
        return [
            str(video.get("id") or "").strip()
            for video in videos
            if isinstance(video, dict) and str(video.get("id") or "").strip()
        ]

    def series_is_known_ended(self, imdb_id: str | None) -> bool | None:
        normalized_imdb_id = normalize_series_catalog_imdb_id(imdb_id)
        if not normalized_imdb_id:
            return None
        if normalized_imdb_id in self._series_ended_cache:
            return self._series_ended_cache[normalized_imdb_id]

        payload = self._cinemeta_payload(normalized_imdb_id)
        if payload is None:
            self._series_ended_cache[normalized_imdb_id] = None
            return None
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            self._series_ended_cache[normalized_imdb_id] = None
            return None

        ended = _cinemeta_series_is_known_ended(meta)
        self._series_ended_cache[normalized_imdb_id] = ended
        return ended

    def _cinemeta_payload(self, imdb_id: str) -> dict[str, object] | None:
        if imdb_id in self._cinemeta_payload_cache:
            return self._cinemeta_payload_cache[imdb_id]
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.get(CINEMETA_SERIES_META_URL.format(imdb_id=imdb_id))
                response.raise_for_status()
                payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            self._cinemeta_payload_cache[imdb_id] = None
            return None
        if not isinstance(payload, dict):
            self._cinemeta_payload_cache[imdb_id] = None
            return None
        self._cinemeta_payload_cache[imdb_id] = payload
        return payload

    def _cinemeta_season_inventory(
        self,
        *,
        imdb_id: str,
        season_number: int,
    ) -> SeriesSeasonEpisodeInventory | None:
        payload = self._cinemeta_payload(imdb_id)
        if payload is None:
            return None
        videos = _cinemeta_videos(payload)
        if videos is None:
            return None

        now = datetime.now(UTC)
        known_episode_numbers: set[int] = set()
        released_episode_numbers: set[int] = set()
        for video in videos:
            if not isinstance(video, dict):
                continue
            try:
                video_season = int(str(video.get("season", "")).strip())
                episode_number = int(str(video.get("episode", "")).strip())
            except ValueError:
                continue
            if video_season != season_number or episode_number < 1 or episode_number > 99:
                continue
            known_episode_numbers.add(episode_number)
            released_at = _parse_cinemeta_released_at(video.get("released"))
            if released_at is None or released_at <= now:
                released_episode_numbers.add(episode_number)

        if not known_episode_numbers:
            return None
        return SeriesSeasonEpisodeInventory(
            imdb_id=imdb_id,
            season_number=season_number,
            known_episode_numbers=sorted(known_episode_numbers),
            released_episode_numbers=sorted(released_episode_numbers),
            source="Cinemeta",
        )

    def _metadata_client_for_catalog(self) -> MetadataClient | None:
        if not self.allow_metadata_requests:
            return None
        if self.metadata_config.provider.value == "disabled":
            return None
        if not self.metadata_config.api_key:
            return None
        if self._metadata_client is None:
            self._metadata_client = MetadataClient(
                self.metadata_config.provider,
                self.metadata_config.api_key,
            )
        return self._metadata_client

    def _omdb_season_inventory(
        self,
        *,
        imdb_id: str,
        season_number: int,
    ) -> SeriesSeasonEpisodeInventory | None:
        client = self._metadata_client_for_catalog()
        if client is None:
            return None
        try:
            listing = client.lookup_omdb_season(imdb_id, season_number)
        except MetadataLookupError:
            return None

        now = datetime.now(UTC)
        known_episode_numbers = sorted(
            {
                episode.episode_number
                for episode in listing.released_episodes
                if episode.episode_number > 0
            }
        )
        released_episode_numbers = sorted(
            {
                episode.episode_number
                for episode in listing.released_episodes
                if episode.released_at is not None and episode.released_at <= now
            }
        )
        if not known_episode_numbers:
            return None
        return SeriesSeasonEpisodeInventory(
            imdb_id=imdb_id,
            season_number=season_number,
            known_episode_numbers=known_episode_numbers,
            released_episode_numbers=released_episode_numbers,
            source="OMDb",
        )


def resolve_catalog_imdb_id_by_title(
    *,
    settings: AppSettings | None,
    allow_metadata_requests: bool,
    lookup_title: str,
) -> str | None:
    if not allow_metadata_requests:
        return None
    metadata_config = SettingsService.resolve_metadata(settings)
    if metadata_config.provider.value == "disabled" or not metadata_config.api_key:
        return None
    try:
        result = MetadataClient(
            metadata_config.provider,
            metadata_config.api_key,
        ).lookup(
            MetadataLookupProvider.OMDB,
            lookup_title,
            MediaType.SERIES,
        )
    except MetadataLookupError:
        return None
    return normalize_series_catalog_imdb_id(result.imdb_id)


def _cinemeta_videos(payload: dict[str, object]) -> list[object] | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    videos = meta.get("videos")
    return videos if isinstance(videos, list) else None


def _parse_cinemeta_released_at(value: object) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _cinemeta_series_is_known_ended(meta: dict[str, object]) -> bool | None:
    status = str(meta.get("status") or "").strip().casefold()
    if status in {"ended", "canceled", "cancelled"}:
        return True
    if status in {"continuing", "returning series", "in production"}:
        return False

    behavior_hints = meta.get("behaviorHints")
    if isinstance(behavior_hints, dict) and bool(behavior_hints.get("hasScheduledVideos")):
        return False

    for key in ("releaseInfo", "year"):
        value = str(meta.get(key) or "").strip()
        if value.endswith(("–", "-")):
            return False
    return None
