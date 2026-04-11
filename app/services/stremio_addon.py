from __future__ import annotations

import re
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import monotonic
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from app.models import AppSettings, MediaType
from app.schemas import (
    JackettSearchRequest,
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services.jackett import (
    JackettClient,
    JackettClientError,
    JackettHTTPError,
    JackettIndexerCapability,
    JackettTimeoutError,
    clamp_search_query_text,
)
from app.services.local_playback import (
    LocalPlaybackFile,
    QbLocalPlaybackMatch,
    find_qb_local_playback_matches,
    register_local_playback_file,
    resolve_qb_local_playback_file,
)
from app.services.metadata import MetadataClient, MetadataLookupError
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.selective_queue import (
    SEASON_EPISODE_RANGE_RE,
    VIDEO_FILE_EXTENSIONS,
    ParsedTorrentInfo,
    SelectiveQueueError,
    find_episode_file_entry,
    parse_torrent_info,
    text_matches_episode,
)
from app.services.settings_service import ResolvedStremioStreamProvider, SettingsService

STREMIO_ADDON_ID = "org.qbrssrules.stremio.local"
STREMIO_CATALOG_ID = "qb-search"
STREMIO_SUPPORTED_TYPES = frozenset({"movie", "series"})
STREMIO_SUPPORTED_ID_PREFIXES = ("tt",)
IMDB_ID_RE = re.compile(r"^(tt\d{5,12})(?::(\d{1,2}):(\d{1,3}))?$", re.IGNORECASE)
MAGNET_INFO_HASH_RE = re.compile(r"btih:([A-Fa-f0-9]{32,40})")
QUALITY_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:2160p|4k|uhd)\b", re.IGNORECASE), 500),
    (re.compile(r"\b1080p\b", re.IGNORECASE), 300),
    (re.compile(r"\b720p\b", re.IGNORECASE), 150),
    (re.compile(r"\b(?:hdr10\+?|hdr)\b", re.IGNORECASE), 60),
    (re.compile(r"\b(?:dolby[\s._-]*vision|dv)\b", re.IGNORECASE), 60),
    (re.compile(r"\bremux\b", re.IGNORECASE), 40),
    (re.compile(r"\bweb[\s._-]*dl\b", re.IGNORECASE), 25),
    (re.compile(r"\bwebrip\b", re.IGNORECASE), 20),
    (re.compile(r"\bbluray\b", re.IGNORECASE), 20),
    (re.compile(r"\b(?:hevc|x265|h\.?265)\b", re.IGNORECASE), 15),
)
NEGATIVE_QUALITY_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:cam|camrip|hdcam|ts|telesync|tc|telecine)\b", re.IGNORECASE), -300),
)
STREMIO_STREAM_LIMIT = 20
STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD = 2
STREMIO_STREAM_RESPONSE_BUDGET_SECONDS = 8.0
STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS = 5.0
STREMIO_HTTP_TORRENT_TIMEOUT_SECONDS = 0.75
STREMIO_LOCAL_PLAYBACK_QB_TIMEOUT_SECONDS = 2.0
STREMIO_EXTERNAL_PROVIDER_TIMEOUT_SECONDS = 2.5
STREMIO_DIRECT_SEARCH_TIMEOUT_SECONDS = 1.5
STREMIO_DIRECT_SEARCH_MAX_WORKERS = 6
STREMIO_DIRECT_SEARCH_INDEXER_LIMIT = 6
STREMIO_STREAM_CACHE_TTL_SECONDS = 180.0
STREMIO_METADATA_CACHE_TTL_SECONDS = 1800.0
STREMIO_STREAM_CACHE_MAX_AGE_SECONDS = 7200
STREMIO_STREAM_STALE_REVALIDATE_SECONDS = 14400
STREMIO_STREAM_STALE_ERROR_SECONDS = 604800
SEASON_ONLY_TEXT_RE = re.compile(
    r"(?i)\b(?:s(?P<season_short>\d{1,2})(?![\s._-]*e\d)|season[\s._-]*(?P<season_long>\d{1,2}))\b"
)
STREMIO_PRESENTS_SUFFIX_RE = re.compile(r"(?i)\bpresents\.?\s*$")
TITLE_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
LANGUAGE_TITLE_MARKERS: tuple[tuple[str, str], ...] = (
    ("russian", "ru"),
    (" rus ", "ru"),
    (" english ", "en"),
    (" eng ", "en"),
    (" hebrew ", "he"),
    (" heb ", "he"),
    (" multi ", "multi"),
)
CYRILLIC_TEXT_RE = re.compile(r"[\u0400-\u04ff]")
DIRECT_SEARCH_PRIORITY_MARKERS: tuple[str, ...] = (
    "kinozal",
    "rutor",
    "rutracker",
    "nnmclub",
    "torrentleech",
    "eztv",
    "tgx",
    "1337x",
)
DIRECT_SEARCH_MIN_PREFERRED_INDEXERS = 3
_STREMIO_STREAM_CACHE_LOCK = threading.Lock()
_STREMIO_STREAM_CACHE: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
_STREMIO_METADATA_CACHE_LOCK = threading.Lock()
_STREMIO_METADATA_CACHE: dict[tuple[str, str], tuple[float, MetadataResult | None]] = {}
STREMIO_EXTERNAL_PROVIDER_HEADERS: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="135", "Not-A.Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
}


@dataclass(frozen=True, slots=True)
class ParsedStremioId:
    imdb_id: str
    season_number: int | None = None
    episode_number: int | None = None

    @property
    def is_episode(self) -> bool:
        return self.season_number is not None and self.episode_number is not None


@dataclass(frozen=True, slots=True)
class ResolvedStreamTarget:
    info_hash: str
    file_idx: int | None = None
    filename: str | None = None
    file_size_bytes: int | None = None
    sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectedStreamCandidate:
    stream: dict[str, object]
    sort_key: tuple[int, int, int, int, int, str]


def reset_stremio_addon_caches() -> None:
    with _STREMIO_STREAM_CACHE_LOCK:
        _STREMIO_STREAM_CACHE.clear()
    with _STREMIO_METADATA_CACHE_LOCK:
        _STREMIO_METADATA_CACHE.clear()


def _cache_get_value[T](
    cache: dict[tuple[str, str], tuple[float, T]],
    *,
    key: tuple[str, str],
    ttl_seconds: float,
    lock: threading.Lock,
) -> T | None:
    now = monotonic()
    with lock:
        cached_entry = cache.get(key)
        if cached_entry is None:
            return None
        cached_at, cached_value = cached_entry
        if now - cached_at > ttl_seconds:
            cache.pop(key, None)
            return None
        return cached_value


def _cache_set_value[T](
    cache: dict[tuple[str, str], tuple[float, T]],
    *,
    key: tuple[str, str],
    value: T,
    lock: threading.Lock,
) -> None:
    with lock:
        cache[key] = (monotonic(), value)


def _normalize_stremio_media_type(value: str | None) -> str | None:
    cleaned = str(value or "").strip().lower()
    if cleaned in STREMIO_SUPPORTED_TYPES:
        return cleaned
    return None


def _media_type_from_stremio(value: str | None) -> MediaType | None:
    normalized = _normalize_stremio_media_type(value)
    if normalized == "movie":
        return MediaType.MOVIE
    if normalized == "series":
        return MediaType.SERIES
    return None


def _parse_stremio_id(value: str | None) -> ParsedStremioId | None:
    cleaned = str(value or "").strip()
    match = IMDB_ID_RE.match(cleaned)
    if not match:
        return None
    imdb_id = str(match.group(1)).lower()
    season_token = match.group(2)
    episode_token = match.group(3)
    if not season_token or not episode_token:
        return ParsedStremioId(imdb_id=imdb_id)
    try:
        season_number = int(season_token)
        episode_number = int(episode_token)
    except ValueError:
        return None
    if season_number < 0 or episode_number < 0:
        return None
    return ParsedStremioId(
        imdb_id=imdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )


def _stremio_catalog_entry(item_type: str) -> dict[str, object]:
    label = "Movies" if item_type == "movie" else "Series"
    return {
        "type": item_type,
        "id": STREMIO_CATALOG_ID,
        "name": f"qB RSS Rules {label}",
        "extra": [
            {"name": "search", "isRequired": True},
            {"name": "skip"},
        ],
    }


def _stream_quality_score(result: JackettSearchResult) -> int:
    return _quality_score_text(str(result.title or ""))


def _quality_score_text(title: str) -> int:
    cleaned_title = str(title or "")
    score = 0
    for pattern, weight in QUALITY_PATTERNS:
        if pattern.search(cleaned_title):
            score += weight
    for pattern, weight in NEGATIVE_QUALITY_PATTERNS:
        if pattern.search(cleaned_title):
            score += weight
    return score


def _stream_sort_key(result: JackettSearchResult) -> tuple[int, int, int, int, int, str]:
    published_score = 0
    published_at = str(result.published_at or "").strip()
    if published_at:
        published_score = int(
            published_at.replace("-", "")
            .replace(":", "")
            .replace("T", "")
            .replace("+", "")
            .replace("Z", "")
            .replace(".", "")[:14]
            or "0"
        )
    return (
        _stream_quality_score(result),
        int(result.seeders or 0),
        int(result.peers or 0),
        _stream_transport_score(result),
        published_score,
        str(result.title or "").casefold(),
    )


def _quality_first_stream_sort_key(
    result: JackettSearchResult,
) -> tuple[int, int, int, int, int, str]:
    return _stream_sort_key(result)


def _collection_priority_stream_sort_key(
    result: JackettSearchResult,
) -> tuple[int, int, int, int, int, str]:
    published_score = 0
    published_at = str(result.published_at or "").strip()
    if published_at:
        published_score = int(
            published_at.replace("-", "")
            .replace(":", "")
            .replace("T", "")
            .replace("+", "")
            .replace("Z", "")
            .replace(".", "")[:14]
            or "0"
        )
    return (
        _stream_transport_score(result),
        _stream_quality_score(result),
        int(result.seeders or 0),
        int(result.peers or 0),
        published_score,
        str(result.title or "").casefold(),
    )


def _stream_transport_score(result: JackettSearchResult) -> int:
    link = str(result.link or "").strip()
    scheme = urlsplit(link).scheme.lower()
    if scheme == "magnet":
        return 1000
    if str(result.info_hash or "").strip() and scheme not in {"http", "https"}:
        return 800
    return 0


def _quality_label_from_title(title: str) -> str:
    cleaned = str(title or "")
    labels: list[str] = []
    if re.search(r"\b(?:2160p|4k|uhd)\b", cleaned, re.IGNORECASE):
        labels.append("2160p")
    elif re.search(r"\b1080p\b", cleaned, re.IGNORECASE):
        labels.append("1080p")
    elif re.search(r"\b720p\b", cleaned, re.IGNORECASE):
        labels.append("720p")
    if re.search(r"\b(?:hdr10\+?|hdr)\b", cleaned, re.IGNORECASE):
        labels.append("HDR")
    if re.search(r"\b(?:dolby[\s._-]*vision|dv)\b", cleaned, re.IGNORECASE):
        labels.append("DV")
    if re.search(r"\bremux\b", cleaned, re.IGNORECASE):
        labels.append("Remux")
    elif re.search(r"\bweb[\s._-]*dl\b", cleaned, re.IGNORECASE):
        labels.append("WEB-DL")
    elif re.search(r"\bwebrip\b", cleaned, re.IGNORECASE):
        labels.append("WEBRip")
    return " ".join(labels).strip() or "Torrent"


def _quality_tag_from_title(title: str) -> str:
    cleaned = str(title or "")
    if re.search(r"\b(?:2160p|4k|uhd)\b", cleaned, re.IGNORECASE):
        return "2160p"
    if re.search(r"\b1080p\b", cleaned, re.IGNORECASE):
        return "1080p"
    if re.search(r"\b720p\b", cleaned, re.IGNORECASE):
        return "720p"
    if re.search(r"\bremux\b", cleaned, re.IGNORECASE):
        return "Remux"
    if re.search(r"\bweb[\s._-]*dl\b", cleaned, re.IGNORECASE):
        return "WEB-DL"
    if re.search(r"\bwebrip\b", cleaned, re.IGNORECASE):
        return "WEBRip"
    return "Torrent"


def _stream_display_label(
    *,
    metadata_title: str,
    season_number: int | None,
    episode_number: int | None,
) -> str:
    cleaned_title = str(metadata_title or "").strip() or "Unknown title"
    if season_number is not None and episode_number is not None:
        return f"{cleaned_title}  S{int(season_number):02d}E{int(episode_number):02d}"
    return cleaned_title


def _preferred_episode_query_title(metadata_title: str) -> str:
    cleaned_title = str(metadata_title or "").strip()
    if not cleaned_title:
        return ""
    if ":" not in cleaned_title:
        return cleaned_title
    segments = [segment.strip() for segment in cleaned_title.split(":") if segment.strip()]
    if len(segments) < 2:
        return cleaned_title
    preferred_segment = segments[-1]
    if len(preferred_segment) < 4:
        return cleaned_title
    return preferred_segment


def _episode_query_variants(metadata_title: str) -> tuple[str, ...]:
    cleaned_title = str(metadata_title or "").strip()
    if not cleaned_title:
        return ()
    variants: list[str] = []
    seen_variants: set[str] = set()

    def add_variant(candidate: str) -> None:
        cleaned_candidate = clamp_search_query_text(candidate).strip()
        if len(cleaned_candidate) < 4:
            return
        dedupe_key = cleaned_candidate.casefold()
        if dedupe_key in seen_variants:
            return
        seen_variants.add(dedupe_key)
        variants.append(cleaned_candidate)

    preferred_title = _preferred_episode_query_title(cleaned_title)
    add_variant(preferred_title)
    if ":" in cleaned_title:
        prefix = cleaned_title.split(":", 1)[0].strip()
        stripped_prefix = STREMIO_PRESENTS_SUFFIX_RE.sub("", prefix).strip()
        # For subtitle-style titles, the base series name is usually the highest-yield
        # broad fallback for season packs, so try it before the noisier full subtitle text.
        add_variant(stripped_prefix)
        add_variant(cleaned_title)
        add_variant(prefix)
    else:
        add_variant(cleaned_title)
    return tuple(variants)


def _stream_title(
    *,
    metadata_title: str,
    season_number: int | None,
    episode_number: int | None,
    result: JackettSearchResult,
    source_count: int,
    filename_hint: str | None,
    selected_file_size_bytes: int | None,
) -> str:
    display_label = _stream_display_label(
        metadata_title=metadata_title,
        season_number=season_number,
        episode_number=episode_number,
    )
    detail_parts = [f"\U0001f464 {int(result.seeders or 0)}"]
    if result.peers is not None:
        detail_parts.append(f"Peers {int(result.peers)}")
    if result.leechers is not None:
        detail_parts.append(f"Leechers {int(result.leechers)}")
    if result.grabs is not None:
        detail_parts.append(f"Grabs {int(result.grabs)}")
    selected_size_label = _format_size_bytes(selected_file_size_bytes)
    torrent_size_label = str(result.size_label or "").strip()
    if selected_size_label:
        detail_parts.append(f"\U0001f4be {selected_size_label}")
        if (
            torrent_size_label
            and result.size_bytes is not None
            and selected_file_size_bytes is not None
            and selected_file_size_bytes < result.size_bytes
        ):
            detail_parts.append(f"Pack {torrent_size_label}")
    elif torrent_size_label:
        detail_parts.append(f"\U0001f4be {torrent_size_label}")
    variant_label = _quality_label_from_title(str(result.title or ""))
    if variant_label and variant_label.casefold() != "torrent":
        detail_parts.append(variant_label)
    source_label = str(result.indexer or "").strip()
    if source_label:
        detail_parts.append(f"\u2699\ufe0f qbrssrules/{source_label}")
    else:
        detail_parts.append("\u2699\ufe0f qbrssrules")
    language_label = _language_label_from_result(result)
    if language_label:
        detail_parts.append(language_label)
    query_source = str(dict(result.torznab_attrs or {}).get("querysource") or "").strip()
    if query_source:
        detail_parts.append(query_source)
    if source_count > 0:
        detail_parts.append(f"Sources {source_count}")
    if filename_hint:
        detail_parts.append(f"File {filename_hint}")
    return f"{display_label}\r\n\r\n{'  '.join(detail_parts)}"


def _stream_response_payload(streams: list[dict[str, object]]) -> dict[str, object]:
    sanitized_streams = [
        {key: value for key, value in stream.items() if not str(key).startswith("_")}
        for stream in streams
    ]
    return {
        "streams": sanitized_streams,
        "cacheMaxAge": STREMIO_STREAM_CACHE_MAX_AGE_SECONDS,
        "staleRevalidate": STREMIO_STREAM_STALE_REVALIDATE_SECONDS,
        "staleError": STREMIO_STREAM_STALE_ERROR_SECONDS,
    }


def _stremio_manifest_version(app_version: str) -> str:
    base_version = str(app_version or "").strip() or "0.0.0"
    if "+" in base_version:
        return base_version
    return f"{base_version}+stremio.1"


def _download_torrent_bytes_for_stremio(
    link: str,
    *,
    timeout_seconds: float,
) -> tuple[bytes, str]:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(link)
        response.raise_for_status()
        final_name = (
            PurePosixPath(response.url.path).name
            or PurePosixPath(urlsplit(link).path).name
            or "stremio-result.torrent"
        )
        return response.content, final_name


def _format_size_bytes(value: int | None) -> str | None:
    if value is None:
        return None
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def _resolved_file_from_torrent(
    parsed_torrent: ParsedTorrentInfo,
    *,
    season_number: int | None,
    episode_number: int | None,
) -> tuple[int | None, str | None, int | None]:
    if season_number is not None and episode_number is not None:
        entry = find_episode_file_entry(
            parsed_torrent.files,
            season_number=season_number,
            episode_number=episode_number,
        )
        if entry is not None:
            return (
                entry.file_id,
                PurePosixPath(entry.path).name or entry.path,
                entry.size_bytes,
            )
        return None, None, None
    if len(parsed_torrent.files) == 1:
        entry = parsed_torrent.files[0]
        return entry.file_id, PurePosixPath(entry.path).name or entry.path, entry.size_bytes
    return None, None, None


def _is_probably_video_filename(filename: str | None) -> bool:
    cleaned_filename = str(filename or "").strip()
    if not cleaned_filename:
        return False
    return PurePosixPath(cleaned_filename).suffix.casefold() in VIDEO_FILE_EXTENSIONS


def _result_title_matches_episode(
    result: JackettSearchResult,
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    return text_matches_episode(
        str(result.title or ""),
        season_number=season_number,
        episode_number=episode_number,
    )


def _result_title_matches_requested_season_pack(
    result: JackettSearchResult,
    *,
    season_number: int,
) -> bool:
    title_text = str(result.title or "")
    for match in SEASON_ONLY_TEXT_RE.finditer(title_text):
        raw_season = match.group("season_short") or match.group("season_long")
        if raw_season is not None and int(raw_season) == season_number:
            return True
    return False


def _result_title_has_conflicting_requested_season(
    result: JackettSearchResult,
    *,
    season_number: int,
) -> bool:
    title_text = str(result.title or "")
    explicit_season_found = False
    for match in SEASON_EPISODE_RANGE_RE.finditer(title_text):
        explicit_season_found = True
        if int(match.group("season")) == season_number:
            return False
    for match in SEASON_ONLY_TEXT_RE.finditer(title_text):
        raw_season = match.group("season_short") or match.group("season_long")
        if raw_season is None:
            continue
        explicit_season_found = True
        if int(raw_season) == season_number:
            return False
    return explicit_season_found


def _result_title_has_explicit_standalone_year(result: JackettSearchResult) -> bool:
    return TITLE_YEAR_RE.search(str(result.title or "")) is not None


def _tracker_sources_from_urls(tracker_urls: list[str]) -> tuple[str, ...]:
    sources: list[str] = []
    seen_sources: set[str] = set()
    for tracker_url in tracker_urls:
        cleaned = str(tracker_url or "").strip()
        if not cleaned:
            continue
        source_value = f"tracker:{cleaned}"
        normalized = source_value.casefold()
        if normalized in seen_sources:
            continue
        seen_sources.add(normalized)
        sources.append(source_value)
    return tuple(sources)


def _tracker_sources_from_magnet_link(link: str) -> tuple[str, ...]:
    parsed = urlsplit(link)
    sources: list[str] = []
    seen_sources: set[str] = set()
    for tracker_url in parse_qs(parsed.query).get("tr", []):
        cleaned = str(tracker_url or "").strip()
        if not cleaned:
            continue
        source_value = f"tracker:{cleaned}"
        normalized = source_value.casefold()
        if normalized in seen_sources:
            continue
        seen_sources.add(normalized)
        sources.append(source_value)
    return tuple(sources)


def _resolve_stream_target(
    result: JackettSearchResult,
    *,
    season_number: int | None = None,
    episode_number: int | None = None,
    http_timeout_seconds: float | None = None,
) -> ResolvedStreamTarget | None:
    link = str(result.link or "").strip()
    direct_info_hash = str(result.info_hash or "").strip().lower() or None
    if link:
        match = MAGNET_INFO_HASH_RE.search(link)
        if match:
            return ResolvedStreamTarget(
                info_hash=match.group(1).lower(),
                sources=_tracker_sources_from_magnet_link(link),
            )
        parsed = urlsplit(link)
        scheme = parsed.scheme.lower()
    else:
        scheme = ""
        parsed = urlsplit("")
    if scheme == "magnet":
        xt_values = parse_qs(parsed.query).get("xt", [])
        for xt_value in xt_values:
            match = MAGNET_INFO_HASH_RE.search(str(xt_value))
            if match:
                return ResolvedStreamTarget(
                    info_hash=match.group(1).lower(),
                    sources=_tracker_sources_from_magnet_link(link),
                )
        if direct_info_hash:
            return ResolvedStreamTarget(
                info_hash=direct_info_hash,
                sources=_tracker_sources_from_magnet_link(link),
            )
        return None
    if scheme in {"http", "https"}:
        timeout_seconds = max(
            0.1, float(http_timeout_seconds or STREMIO_HTTP_TORRENT_TIMEOUT_SECONDS)
        )
        try:
            torrent_bytes, source_name = _download_torrent_bytes_for_stremio(
                link,
                timeout_seconds=timeout_seconds,
            )
            parsed_torrent = parse_torrent_info(torrent_bytes, source_name=source_name)
            if parsed_torrent.info_hash:
                file_idx, filename, file_size_bytes = _resolved_file_from_torrent(
                    parsed_torrent,
                    season_number=season_number,
                    episode_number=episode_number,
                )
                if (
                    season_number is not None
                    and episode_number is not None
                    and parsed_torrent.files
                    and file_idx is None
                ):
                    return None
                return ResolvedStreamTarget(
                    info_hash=parsed_torrent.info_hash.casefold(),
                    file_idx=file_idx,
                    filename=filename,
                    file_size_bytes=file_size_bytes,
                    sources=_tracker_sources_from_urls(parsed_torrent.tracker_urls),
                )
        except (SelectiveQueueError, httpx.HTTPError):
            if direct_info_hash:
                return ResolvedStreamTarget(info_hash=direct_info_hash)
            return None
    if direct_info_hash:
        return ResolvedStreamTarget(info_hash=direct_info_hash)
    return None


def _stream_name(result: JackettSearchResult) -> str:
    return f"qB RSS Rules\n{_quality_label_from_title(str(result.title or ''))}"


def _language_label_from_result(result: JackettSearchResult) -> str | None:
    language_tokens = _language_tokens_from_result(result)
    if not language_tokens:
        return None
    ordered_tokens = [token.upper() for token in language_tokens if token != "multi"]
    if "multi" in language_tokens:
        ordered_tokens.append("MULTI")
    if ordered_tokens:
        return "/".join(ordered_tokens)
    return None


def _language_tokens_from_result(result: JackettSearchResult) -> tuple[str, ...]:
    attrs = {
        str(key).casefold(): str(value).strip().casefold()
        for key, value in dict(result.torznab_attrs or {}).items()
    }
    detected_tokens: list[str] = []
    seen_tokens: set[str] = set()

    def add_token(candidate: str) -> None:
        token = str(candidate or "").strip().casefold()
        if not token:
            return
        if token in {"eng", "english"}:
            token = "en"
        elif token in {"rus", "russian"}:
            token = "ru"
        elif token in {"heb", "hebrew"}:
            token = "he"
        if token in seen_tokens:
            return
        seen_tokens.add(token)
        detected_tokens.append(token)

    for attr_key in ("language", "languages", "lang"):
        attr_value = attrs.get(attr_key, "")
        if not attr_value:
            continue
        for raw_value in re.split(r"[\s,;/+|()]+", attr_value):
            add_token(raw_value)

    padded_title = f" {str(result.title or '').casefold()} "
    for needle, language_code in LANGUAGE_TITLE_MARKERS:
        if needle in padded_title:
            add_token(language_code)
    if CYRILLIC_TEXT_RE.search(str(result.title or "")):
        add_token("ru")
    return tuple(detected_tokens)


def _local_stream_name(result: JackettSearchResult) -> str:
    return f"qB RSS Rules\nLocal {_quality_tag_from_title(str(result.title or ''))}"


def _local_stream_title(
    *,
    metadata_title: str,
    season_number: int | None,
    episode_number: int | None,
) -> str:
    display_label = _stream_display_label(
        metadata_title=metadata_title,
        season_number=season_number,
        episode_number=episode_number,
    )
    return f"{display_label}\r\n\r\n\U0001f4c1 Local qB file  \u2699\ufe0f qbrssrules"


def _local_playback_url(base_url: str, token: str) -> str:
    cleaned_base_url = str(base_url or "").rstrip("/")
    return f"{cleaned_base_url}/stremio/local-playback/{token}"


def _local_match_sort_key(match: QbLocalPlaybackMatch) -> tuple[int, str]:
    quality_text = f"{match.torrent_name} {match.playback_file.filename}"
    return (
        _quality_score_text(quality_text),
        quality_text.casefold(),
    )


def _local_inventory_stream_sort_key(
    match: QbLocalPlaybackMatch,
) -> tuple[int, int, int, int, int, str]:
    quality_text = f"{match.torrent_name} {match.playback_file.filename}"
    return (
        _quality_score_text(quality_text),
        0,
        0,
        0,
        0,
        quality_text.casefold(),
    )


def _stream_from_local_qb_match(
    *,
    match: QbLocalPlaybackMatch,
    metadata_title: str,
    item_type: str,
    season_number: int | None,
    episode_number: int | None,
    addon_base_url: str,
) -> dict[str, object]:
    quality_text = f"{match.torrent_name} {match.playback_file.filename}"
    return _local_stream_from_playback_file(
        playback_file=match.playback_file,
        info_hash=match.info_hash,
        quality_text=quality_text,
        metadata_title=metadata_title,
        item_type=item_type,
        season_number=season_number,
        episode_number=episode_number,
        addon_base_url=addon_base_url,
    )


def _local_stream_from_playback_file(
    *,
    playback_file: LocalPlaybackFile,
    info_hash: str,
    quality_text: str,
    metadata_title: str,
    item_type: str,
    season_number: int | None,
    episode_number: int | None,
    addon_base_url: str,
) -> dict[str, object]:
    token = register_local_playback_file(playback_file)
    return {
        "name": f"qB RSS Rules\nLocal {_quality_label_from_title(quality_text)}",
        "tag": _quality_tag_from_title(quality_text),
        "type": item_type,
        "title": _local_stream_title(
            metadata_title=metadata_title,
            season_number=season_number,
            episode_number=episode_number,
        ),
        "url": _local_playback_url(addon_base_url, token),
        "behaviorHints": {
            "bingieGroup": f"qB RSS Rules|{info_hash}",
            "filename": playback_file.filename,
            "notWebReady": True,
        },
        "_dedupeInfoHash": info_hash,
    }


def _stream_identity_key(stream: dict[str, object]) -> str:
    info_hash = (
        str(stream.get("infoHash") or stream.get("_dedupeInfoHash") or "").strip().casefold()
    )
    if info_hash:
        return f"hash:{info_hash}"
    stream_url = str(stream.get("url") or "").strip()
    if stream_url:
        return f"url:{stream_url}"
    stream_name = str(stream.get("name") or "").strip().casefold()
    return f"name:{stream_name}"


def _stream_from_result_with_timeout(
    result: JackettSearchResult,
    *,
    metadata_title: str,
    item_type: str,
    season_number: int | None,
    episode_number: int | None,
    http_timeout_seconds: float,
) -> dict[str, object] | None:
    target = _resolve_stream_target(
        result,
        season_number=season_number,
        episode_number=episode_number,
        http_timeout_seconds=http_timeout_seconds,
    )
    if not target:
        return None
    if target.filename and not _is_probably_video_filename(target.filename):
        return None
    info_hash = target.info_hash
    behavior_hints: dict[str, object] = {
        "bingieGroup": f"qB RSS Rules|{info_hash}",
    }
    if target.filename:
        behavior_hints["filename"] = target.filename
    if target.file_size_bytes is not None:
        behavior_hints["videoSize"] = int(target.file_size_bytes)
    stream: dict[str, object] = {
        "name": _stream_name(result),
        "tag": _quality_tag_from_title(str(result.title or "")),
        "type": item_type,
        "title": _stream_title(
            metadata_title=metadata_title,
            season_number=season_number,
            episode_number=episode_number,
            result=result,
            source_count=len(list(target.sources)),
            filename_hint=target.filename,
            selected_file_size_bytes=target.file_size_bytes,
        ),
        "infoHash": info_hash,
        "sources": [*list(target.sources), f"dht:{info_hash}"],
        "behaviorHints": behavior_hints,
    }
    if target.file_idx is not None:
        stream["fileIdx"] = int(target.file_idx)
    if result.seeders is not None:
        stream["seeders"] = int(result.seeders)
    return stream


def _result_matches_requested_episode(
    result: JackettSearchResult,
    *,
    season_number: int | None,
    episode_number: int | None,
) -> bool:
    if season_number is None or episode_number is None:
        return True
    if _result_title_matches_episode(
        result,
        season_number=season_number,
        episode_number=episode_number,
    ):
        return True
    if _result_title_matches_requested_season_pack(
        result,
        season_number=season_number,
    ):
        return True
    if _result_title_has_conflicting_requested_season(
        result,
        season_number=season_number,
    ):
        return False
    if _result_title_has_explicit_standalone_year(result):
        return False
    return urlsplit(str(result.link or "")).scheme.lower() in {"http", "https"}


def _collect_stream_candidates(
    candidates: list[JackettSearchResult],
    *,
    metadata_title: str,
    item_type: str,
    season_number: int | None,
    episode_number: int | None,
    deadline: float,
) -> list[CollectedStreamCandidate]:
    collected: list[CollectedStreamCandidate] = []
    seen_stream_keys: set[str] = set()
    for item in candidates:
        if not _result_matches_requested_episode(
            item,
            season_number=season_number,
            episode_number=episode_number,
        ):
            continue
        if len(collected) >= STREMIO_STREAM_LIMIT:
            break
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            break
        http_timeout_seconds = min(
            STREMIO_HTTP_TORRENT_TIMEOUT_SECONDS,
            max(0.1, remaining_seconds),
        )
        stream = _stream_from_result_with_timeout(
            item,
            metadata_title=metadata_title,
            item_type=item_type,
            season_number=season_number,
            episode_number=episode_number,
            http_timeout_seconds=http_timeout_seconds,
        )
        if not stream:
            continue
        stream_key = _stream_identity_key(stream)
        if stream_key in seen_stream_keys:
            continue
        seen_stream_keys.add(stream_key)
        collected.append(
            CollectedStreamCandidate(
                stream=stream,
                sort_key=_quality_first_stream_sort_key(item),
            )
        )
    return collected


def _upgrade_candidates_with_exact_local_playback(
    candidates: list[CollectedStreamCandidate],
    *,
    qb_client: QbittorrentClient,
    metadata_title: str,
    item_type: str,
    season_number: int | None,
    episode_number: int | None,
    addon_base_url: str,
) -> list[CollectedStreamCandidate]:
    upgraded_candidates: list[CollectedStreamCandidate] = []
    for candidate in candidates:
        stream = dict(candidate.stream)
        info_hash = str(stream.get("infoHash") or "").strip().casefold()
        if not info_hash:
            upgraded_candidates.append(candidate)
            continue
        behavior_hints = stream.get("behaviorHints")
        behavior_hints_dict = behavior_hints if isinstance(behavior_hints, dict) else {}
        raw_file_idx = stream.get("fileIdx")
        file_idx = raw_file_idx if isinstance(raw_file_idx, int) else None
        filename_hint = str(behavior_hints_dict.get("filename") or "").strip() or None
        try:
            playback_file = resolve_qb_local_playback_file(
                qb_client,
                info_hash=info_hash,
                file_idx=file_idx,
                filename_hint=filename_hint,
            )
        except QbittorrentClientError:
            playback_file = None
        if playback_file is None:
            upgraded_candidates.append(candidate)
            continue
        quality_text = " ".join(
            [
                str(stream.get("name") or "").replace("qB RSS Rules", "").strip(),
                str(behavior_hints_dict.get("filename") or "").strip(),
            ]
        ).strip() or str(stream.get("tag") or "Torrent")
        local_stream = _local_stream_from_playback_file(
            playback_file=playback_file,
            info_hash=info_hash,
            quality_text=quality_text,
            metadata_title=metadata_title,
            item_type=item_type,
            season_number=season_number,
            episode_number=episode_number,
            addon_base_url=addon_base_url,
        )
        if "seeders" in stream:
            local_stream["seeders"] = stream["seeders"]
        upgraded_candidates.append(
            CollectedStreamCandidate(
                stream=local_stream,
                sort_key=candidate.sort_key,
            )
        )
    return upgraded_candidates


def _stream_lookup_cache_key(item_type: str, item_id: str) -> tuple[str, str]:
    return (str(item_type or "").strip().casefold(), str(item_id or "").strip().casefold())


def _metadata_cache_key(imdb_id: str, media_type: MediaType) -> tuple[str, str]:
    return (str(imdb_id or "").strip().casefold(), media_type.value)


def _search_run_result_count(run: JackettSearchRun | None) -> int:
    if run is None:
        return 0
    return len(list(run.results or [])) + len(list(run.fallback_results or []))


def _search_run_episode_match_count(
    run: JackettSearchRun | None,
    *,
    season_number: int | None,
    episode_number: int | None,
) -> int:
    if run is None:
        return 0
    seen_merge_keys: set[str] = set()
    matches = 0
    for result in [*list(run.results or []), *list(run.fallback_results or [])]:
        merge_key = str(result.merge_key or "").strip()
        if merge_key and merge_key in seen_merge_keys:
            continue
        if not _result_matches_requested_episode(
            result,
            season_number=season_number,
            episode_number=episode_number,
        ):
            continue
        if merge_key:
            seen_merge_keys.add(merge_key)
        matches += 1
    return matches


def _episode_search_run_is_sufficient(
    run: JackettSearchRun | None,
    *,
    season_number: int | None,
    episode_number: int | None,
    preferred_languages: tuple[str, ...],
) -> bool:
    if (
        _search_run_episode_match_count(
            run,
            season_number=season_number,
            episode_number=episode_number,
        )
        < STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
    ):
        return False
    if preferred_languages and not _search_run_has_preferred_language_match(
        run,
        preferred_languages=preferred_languages,
        season_number=season_number,
        episode_number=episode_number,
    ):
        return False
    return True


def _episode_search_run_has_usable_match(
    run: JackettSearchRun | None,
    *,
    season_number: int | None,
    episode_number: int | None,
    preferred_languages: tuple[str, ...],
) -> bool:
    if (
        _search_run_episode_match_count(
            run,
            season_number=season_number,
            episode_number=episode_number,
        )
        <= 0
    ):
        return False
    if preferred_languages and not _search_run_has_preferred_language_match(
        run,
        preferred_languages=preferred_languages,
        season_number=season_number,
        episode_number=episode_number,
    ):
        return False
    return True


def _run_jackett_unstructured_title_search(
    *,
    api_url: str,
    api_key: str,
    query: str,
) -> JackettSearchRun | None:
    cleaned_query = clamp_search_query_text(query).strip()
    if not cleaned_query:
        return None
    client = JackettClient(api_url, api_key, timeout=STREMIO_DIRECT_SEARCH_TIMEOUT_SECONDS)
    attempted_requests: list[str] = []
    warning_messages: list[str] = []
    try:
        direct_indexers = client._configured_indexers_for_mode("search")
    except (JackettClientError, JackettHTTPError, JackettTimeoutError) as exc:
        direct_indexers = []
        warning_messages.append(str(exc))
    parsed_results: list[tuple[str | None, JackettSearchResult]] = []

    if direct_indexers:
        direct_indexers = _prioritize_direct_search_indexers(
            direct_indexers,
            query=cleaned_query,
        )
        if len(direct_indexers) > STREMIO_DIRECT_SEARCH_INDEXER_LIMIT:
            selected_indexers = direct_indexers[:STREMIO_DIRECT_SEARCH_INDEXER_LIMIT]
            warning_messages.append(
                "Jackett direct search limited to "
                f"{len(selected_indexers)}/{len(direct_indexers)} configured indexers: "
                + ", ".join(indexer.indexer_id for indexer in selected_indexers)
            )
            direct_indexers = selected_indexers
        futures: dict[Future[tuple[str, list[tuple[str | None, JackettSearchResult]], str | None]], str] = {}
        executor = ThreadPoolExecutor(
            max_workers=min(STREMIO_DIRECT_SEARCH_MAX_WORKERS, len(direct_indexers))
        )
        try:
            for indexer in direct_indexers:
                request_label = f'{indexer.indexer_id}: t=search q="{cleaned_query}"'
                attempted_requests.append(request_label)
                futures[
                    executor.submit(
                        _run_single_direct_search_indexer,
                        api_url=api_url,
                        api_key=api_key,
                        indexer_id=indexer.indexer_id,
                        query=cleaned_query,
                    )
                ] = request_label
            done, pending = wait(
                tuple(futures.keys()),
                timeout=STREMIO_DIRECT_SEARCH_TIMEOUT_SECONDS * 3,
            )
            for future in done:
                request_label, indexer_results, warning_message = future.result()
                if warning_message:
                    warning_messages.append(warning_message)
                if indexer_results:
                    parsed_results.extend(indexer_results)
            for future in pending:
                future.cancel()
                warning_messages.append(
                    f"Jackett direct search timed out for {futures[future]}"
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    else:
        request_label = f't=search q="{cleaned_query}"'
        attempted_requests.append(request_label)
        try:
            root = client._request_xml(
                client._torznab_endpoint("all"),
                params={
                    "apikey": api_key,
                    "t": "search",
                    "q": cleaned_query,
                },
            )
        except JackettClientError as exc:
            warning_messages.append(str(exc))
        else:
            for item in root.iter():
                if item.tag.rsplit("}", 1)[-1] != "item":
                    continue
                parsed_item = client._parse_item(item)
                if parsed_item is None:
                    continue
                published_at, result = parsed_item
                parsed_results.append((published_at.isoformat() if published_at else None, result))

    if parsed_results:
        deduped_results: list[JackettSearchResult] = []
        seen_merge_keys: set[str] = set()
        for _published_at, result in sorted(parsed_results, key=lambda item: item[0] or "", reverse=True):
            merge_key = str(result.merge_key or "").strip()
            dedupe_key = merge_key or f"{result.info_hash}|{result.guid}|{result.title}|{result.size_bytes}"
            if dedupe_key in seen_merge_keys:
                continue
            seen_merge_keys.add(dedupe_key)
            deduped_results.append(result)
        return JackettSearchRun(
            request_variants=attempted_requests,
            warning_messages=warning_messages,
            results=deduped_results,
            fallback_results=[],
        )

    return JackettSearchRun(
        request_variants=attempted_requests,
        warning_messages=warning_messages,
        results=[],
        fallback_results=[],
    )


def _prioritize_direct_search_indexers(
    indexers: list[JackettIndexerCapability],
    *,
    query: str,
) -> list[JackettIndexerCapability]:
    cleaned_query = str(query or "").strip()
    query_has_cyrillic = bool(CYRILLIC_TEXT_RE.search(cleaned_query))
    preferred_indexers: list[JackettIndexerCapability] = []
    non_preferred_indexers: list[JackettIndexerCapability] = []

    def sort_key(indexer: JackettIndexerCapability) -> tuple[int, str]:
        normalized_id = str(indexer.indexer_id or "").strip().casefold()
        score = 0
        for offset, marker in enumerate(DIRECT_SEARCH_PRIORITY_MARKERS):
            if marker in normalized_id:
                score += 100 - (offset * 5)
        if query_has_cyrillic and any(
            marker in normalized_id for marker in DIRECT_SEARCH_PRIORITY_MARKERS[:4]
        ):
            score += 20
        return (-score, normalized_id)

    for indexer in sorted(indexers, key=sort_key):
        normalized_id = str(indexer.indexer_id or "").strip().casefold()
        if any(marker in normalized_id for marker in DIRECT_SEARCH_PRIORITY_MARKERS):
            preferred_indexers.append(indexer)
        else:
            non_preferred_indexers.append(indexer)
    if len(preferred_indexers) >= DIRECT_SEARCH_MIN_PREFERRED_INDEXERS:
        return preferred_indexers
    return [*preferred_indexers, *non_preferred_indexers]


def _run_single_direct_search_indexer(
    *,
    api_url: str,
    api_key: str,
    indexer_id: str,
    query: str,
) -> tuple[str, list[tuple[str | None, JackettSearchResult]], str | None]:
    client = JackettClient(api_url, api_key, timeout=STREMIO_DIRECT_SEARCH_TIMEOUT_SECONDS)
    request_label = f'{indexer_id}: t=search q="{query}"'
    try:
        parsed_results, _successful_params, _attempted_requests, warning_messages = client._search_variant(
            indexer_id,
            {
                "apikey": api_key,
                "t": "search",
                "q": query,
            },
            continue_on_empty=False,
        )
    except JackettClientError as exc:
        return request_label, [], str(exc)
    normalized_results = [
        (published_at.isoformat() if published_at else None, result)
        for published_at, result in parsed_results
    ]
    warning_message = next((message for message in warning_messages if message), None)
    return request_label, normalized_results, warning_message


def _apply_preferred_language_filter(
    results: list[JackettSearchResult],
    *,
    preferred_languages: tuple[str, ...],
) -> list[JackettSearchResult]:
    if not preferred_languages:
        return results
    preferred_set = {language.casefold() for language in preferred_languages if language}
    if not preferred_set:
        return results
    matching_results = [
        result
        for result in results
        if set(_language_tokens_from_result(result)).intersection(preferred_set)
    ]
    return matching_results or results


def _combined_request_variants_from_runs(runs: list[JackettSearchRun]) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for run in runs:
        for variant in list(run.request_variants or []):
            cleaned_variant = str(variant or "").strip()
            normalized_variant = cleaned_variant.casefold()
            if not cleaned_variant or normalized_variant in seen:
                continue
            seen.add(normalized_variant)
            combined.append(cleaned_variant)
    return combined


def _combined_warning_messages_from_runs(runs: list[JackettSearchRun]) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for run in runs:
        for warning in list(run.warning_messages or []):
            cleaned_warning = str(warning or "").strip()
            normalized_warning = cleaned_warning.casefold()
            if not cleaned_warning or normalized_warning in seen:
                continue
            seen.add(normalized_warning)
            combined.append(cleaned_warning)
    return combined


def _search_run_has_preferred_language_match(
    run: JackettSearchRun | None,
    *,
    preferred_languages: tuple[str, ...],
    season_number: int | None,
    episode_number: int | None,
) -> bool:
    if run is None or not preferred_languages:
        return False
    preferred_set = {language.casefold() for language in preferred_languages if language}
    if not preferred_set:
        return False
    for result in [*list(run.results or []), *list(run.fallback_results or [])]:
        if not _result_matches_requested_episode(
            result,
            season_number=season_number,
            episode_number=episode_number,
        ):
            continue
        if set(_language_tokens_from_result(result)).intersection(preferred_set):
            return True
    return False


def _run_jackett_search(
    *,
    api_url: str,
    api_key: str,
    payload: JackettSearchRequest,
) -> JackettSearchRun | None:
    try:
        return JackettClient(api_url, api_key).search(payload)
    except JackettClientError:
        return None


def _stream_provider_label_from_manifest(provider: ResolvedStremioStreamProvider) -> str:
    explicit_label = str(provider.label or "").strip()
    if explicit_label:
        return explicit_label
    parsed = urlsplit(provider.manifest_url)
    hostname = str(parsed.hostname or "").strip()
    if "torrentio" in hostname.casefold():
        return "Torrentio"
    if hostname:
        return hostname
    return "External provider"


def _stream_url_from_manifest_url(
    manifest_url: str,
    *,
    item_type: str,
    item_id: str,
) -> str | None:
    cleaned_url = str(manifest_url or "").strip()
    if not cleaned_url:
        return None
    parsed = urlsplit(cleaned_url)
    normalized_path = str(parsed.path or "").rstrip("/")
    if not normalized_path.endswith("/manifest.json"):
        return None
    stream_path = (
        f"{normalized_path.removesuffix('/manifest.json')}/stream/"
        f"{quote(item_type, safe='')}/{quote(item_id, safe='')}.json"
    )
    return parsed._replace(path=stream_path, query="", fragment="").geturl()


def _provider_stream_payload_text(stream: dict[str, object]) -> str:
    text_parts = [
        str(stream.get("name") or "").strip(),
        str(stream.get("title") or "").strip(),
        str(stream.get("description") or "").strip(),
    ]
    behavior_hints = stream.get("behaviorHints")
    if isinstance(behavior_hints, dict):
        text_parts.append(str(behavior_hints.get("filename") or "").strip())
    return " ".join(part for part in text_parts if part)


def _provider_stream_seeders(stream: dict[str, object]) -> int:
    raw_value = stream.get("seeders")
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if cleaned.isdigit():
            return int(cleaned)
    payload_text = _provider_stream_payload_text(stream)
    match = re.search(
        r"(?:\bseeders?\b|[\U0001f464])\s*[:=]?\s*(\d{1,6})",
        payload_text,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    return 0


def _provider_stream_peers(stream: dict[str, object]) -> int:
    raw_value = stream.get("peers")
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if cleaned.isdigit():
            return int(cleaned)
    payload_text = _provider_stream_payload_text(stream)
    match = re.search(r"\bpeers?\b\s*[:=]?\s*(\d{1,6})", payload_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def _provider_stream_transport_score(stream: dict[str, object]) -> int:
    url_text = str(stream.get("url") or stream.get("externalUrl") or "").strip().lower()
    if str(stream.get("infoHash") or "").strip():
        if url_text.startswith("magnet:"):
            return 1000
        return 800
    if url_text.startswith("magnet:"):
        return 1000
    return 0


def _provider_stream_sort_key(stream: dict[str, object]) -> tuple[int, int, int, int, int, str]:
    payload_text = _provider_stream_payload_text(stream)
    return (
        _quality_score_text(payload_text),
        _provider_stream_seeders(stream),
        _provider_stream_peers(stream),
        _provider_stream_transport_score(stream),
        0,
        payload_text.casefold(),
    )


def _with_provider_attribution(
    stream: dict[str, object],
    *,
    provider_label: str,
    item_type: str,
) -> dict[str, object]:
    normalized_stream = deepcopy(stream)
    normalized_stream["type"] = item_type
    title_text = str(
        normalized_stream.get("title") or normalized_stream.get("description") or ""
    ).strip()
    if provider_label.casefold() not in title_text.casefold():
        normalized_stream["title"] = (
            f"{title_text}  \u2699\ufe0f {provider_label}"
            if title_text
            else f"\u2699\ufe0f {provider_label}"
        )
    elif title_text:
        normalized_stream["title"] = title_text
    name_text = str(normalized_stream.get("name") or "").strip()
    if not name_text:
        normalized_stream["name"] = (
            f"{provider_label}\n{_quality_label_from_title(_provider_stream_payload_text(normalized_stream))}"
        )
    return normalized_stream


def _fetch_external_provider_streams(
    provider: ResolvedStremioStreamProvider,
    *,
    item_type: str,
    item_id: str,
    timeout_seconds: float,
) -> list[CollectedStreamCandidate]:
    stream_url = _stream_url_from_manifest_url(
        provider.manifest_url,
        item_type=item_type,
        item_id=item_id,
    )
    if stream_url is None:
        return []
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                stream_url,
                headers=STREMIO_EXTERNAL_PROVIDER_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    raw_streams = payload.get("streams")
    if not isinstance(raw_streams, list):
        return []
    provider_label = _stream_provider_label_from_manifest(provider)
    candidates: list[CollectedStreamCandidate] = []
    for raw_stream in raw_streams:
        if not isinstance(raw_stream, dict):
            continue
        normalized_stream = _with_provider_attribution(
            raw_stream,
            provider_label=provider_label,
            item_type=item_type,
        )
        candidates.append(
            CollectedStreamCandidate(
                stream=normalized_stream,
                sort_key=_provider_stream_sort_key(normalized_stream),
            )
        )
    return candidates


def _candidate_selection_key(candidate: CollectedStreamCandidate) -> tuple[object, ...]:
    stream = candidate.stream
    sources = stream.get("sources")
    source_count = len(sources) if isinstance(sources, list) else 0
    behavior_hints = stream.get("behaviorHints")
    filename_present = isinstance(behavior_hints, dict) and bool(
        str(behavior_hints.get("filename") or "").strip()
    )
    return (
        *candidate.sort_key,
        int("fileIdx" in stream),
        int(filename_present),
        source_count,
        len(str(stream.get("title") or "")),
        len(str(stream.get("name") or "")),
    )


def _merge_stream_candidates(
    candidate_groups: list[list[CollectedStreamCandidate]],
) -> list[CollectedStreamCandidate]:
    merged_candidates: dict[str, CollectedStreamCandidate] = {}
    for group in candidate_groups:
        for candidate in group:
            stream_key = _stream_identity_key(candidate.stream)
            existing_candidate = merged_candidates.get(stream_key)
            if existing_candidate is None or _candidate_selection_key(
                candidate
            ) > _candidate_selection_key(existing_candidate):
                merged_candidates[stream_key] = candidate
    return list(merged_candidates.values())


class StremioAddonService:
    def __init__(self, settings: AppSettings | None) -> None:
        self.settings = settings
        self._jackett_config = SettingsService.resolve_jackett(settings)
        self._metadata_config = SettingsService.resolve_metadata(settings)
        self._qb_config = SettingsService.resolve_qb_connection(settings)
        self._stremio_config = SettingsService.resolve_stremio(settings)
        self._external_stream_providers = SettingsService.resolve_stremio_stream_providers(
            settings
        )

    def manifest(self, *, version: str) -> dict[str, object]:
        return {
            "id": STREMIO_ADDON_ID,
            "version": _stremio_manifest_version(version),
            "name": "qB RSS Rules",
            "description": "Local Stremio addon powered by qB RSS Rules search, OMDb metadata, and Jackett streams.",
            "resources": [
                {
                    "name": "catalog",
                    "types": ["movie", "series"],
                    "idPrefixes": list(STREMIO_SUPPORTED_ID_PREFIXES),
                },
                {
                    "name": "stream",
                    "types": ["movie", "series"],
                    "idPrefixes": list(STREMIO_SUPPORTED_ID_PREFIXES),
                },
            ],
            "types": ["movie", "series"],
            "idPrefixes": list(STREMIO_SUPPORTED_ID_PREFIXES),
            "catalogs": [
                _stremio_catalog_entry("movie"),
                _stremio_catalog_entry("series"),
            ],
            "behaviorHints": {
                "configurable": False,
                "configurationRequired": False,
                "p2p": True,
            },
        }

    def catalog_search(
        self,
        *,
        item_type: str,
        catalog_id: str,
        search_text: str | None,
        skip: int = 0,
    ) -> dict[str, object]:
        normalized_type = _normalize_stremio_media_type(item_type)
        if normalized_type is None or catalog_id != STREMIO_CATALOG_ID:
            return {"metas": []}
        cleaned_search = clamp_search_query_text(search_text or "").strip()
        if not cleaned_search:
            return {"metas": []}

        media_type = _media_type_from_stremio(normalized_type)
        if media_type is None:
            return {"metas": []}

        try:
            metadata_client = MetadataClient(
                self._metadata_config.provider,
                self._metadata_config.api_key,
            )
            results = metadata_client.search_omdb(
                cleaned_search,
                media_type,
                limit=20,
                skip=skip,
            )
        except MetadataLookupError:
            results = []

        if not results:
            results = self._search_cinemeta_catalog(
                search_text=cleaned_search,
                media_type=media_type,
                limit=20,
                skip=skip,
            )

        metas: list[dict[str, object]] = []
        for result in results:
            if not result.imdb_id:
                continue
            metas.append(
                {
                    "id": result.imdb_id,
                    "type": normalized_type,
                    "name": result.title,
                    "releaseInfo": result.year or "",
                    "poster": result.poster_url,
                    "posterShape": "poster",
                }
            )
        return {"metas": metas}

    def collect_enriched_search_run(
        self,
        *,
        payload: JackettSearchRequest,
    ) -> JackettSearchRun | None:
        if not self._jackett_config.app_ready:
            return None
        if payload.media_type not in {MediaType.MOVIE, MediaType.SERIES}:
            return None
        imdb_id = str(payload.imdb_id or "").strip().lower()
        if not imdb_id.startswith("tt"):
            return None

        parsed_id = ParsedStremioId(
            imdb_id=imdb_id,
            season_number=payload.season_number,
            episode_number=payload.episode_number,
        )
        metadata = self._resolve_stream_metadata(
            imdb_id=parsed_id.imdb_id,
            media_type=payload.media_type,
        )
        if metadata is None or metadata.media_type != payload.media_type:
            return None

        api_url = str(self._jackett_config.api_url or "").strip()
        api_key = str(self._jackett_config.api_key or "").strip()
        if not api_url or not api_key:
            return None

        runs = self._collect_search_runs_for_target(
            metadata=metadata,
            parsed_id=parsed_id,
            media_type=payload.media_type,
            api_url=api_url,
            api_key=api_key,
        )
        deduped_results = self._deduped_search_results_from_runs(runs)
        if not deduped_results:
            return None
        precise_results: list[JackettSearchResult] = []
        fallback_results: list[JackettSearchResult] = []
        for result in deduped_results:
            query_source = str(
                (result.torznab_attrs or {}).get("querysource") or ""
            ).strip()
            if query_source.casefold() == "fallback":
                fallback_results.append(result)
                continue
            precise_results.append(result)
        return JackettSearchRun(
            request_variants=_combined_request_variants_from_runs(runs),
            warning_messages=_combined_warning_messages_from_runs(runs),
            raw_results=list(precise_results),
            results=list(precise_results),
            raw_fallback_results=list(fallback_results),
            fallback_results=list(fallback_results),
        )

    @staticmethod
    def _search_cinemeta_catalog(
        *,
        search_text: str,
        media_type: MediaType,
        limit: int = 20,
        skip: int = 0,
    ) -> list[MetadataResult]:
        cleaned_search = clamp_search_query_text(search_text or "").strip()
        if not cleaned_search:
            return []
        stremio_type = "movie" if media_type == MediaType.MOVIE else "series"
        encoded_query = quote(cleaned_search, safe="")
        skip_value = max(0, int(skip))
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(
                    f"https://v3-cinemeta.strem.io/catalog/{stremio_type}/top/search={encoded_query}.json",
                    params={"skip": str(skip_value)} if skip_value else None,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []

        raw_metas = payload.get("metas")
        if not isinstance(raw_metas, list):
            return []

        results: list[MetadataResult] = []
        for raw_meta in raw_metas[: max(0, int(limit))]:
            if not isinstance(raw_meta, dict):
                continue
            imdb_id = str(raw_meta.get("imdb_id") or raw_meta.get("id") or "").strip() or None
            if not imdb_id or not imdb_id.startswith("tt"):
                continue
            title = str(raw_meta.get("name") or "").strip()
            if not title:
                continue
            results.append(
                MetadataResult(
                    title=title,
                    provider=MetadataLookupProvider.OMDB,
                    imdb_id=imdb_id,
                    source_id=imdb_id,
                    media_type=media_type,
                    year=str(raw_meta.get("releaseInfo") or raw_meta.get("year") or "").strip()
                    or None,
                    poster_url=str(raw_meta.get("poster") or "").strip() or None,
                )
            )
        return results

    def stream_lookup(
        self,
        *,
        item_type: str,
        item_id: str,
        base_url: str | None = None,
    ) -> dict[str, object]:
        normalized_type = _normalize_stremio_media_type(item_type)
        parsed_id = _parse_stremio_id(item_id)
        if normalized_type is None or parsed_id is None:
            return _stream_response_payload([])

        media_type = _media_type_from_stremio(normalized_type)
        if media_type is None:
            return _stream_response_payload([])
        if normalized_type == "movie" and parsed_id.is_episode:
            return _stream_response_payload([])
        if normalized_type == "series" and not parsed_id.is_episode:
            return _stream_response_payload([])
        if not self._jackett_config.app_ready:
            return _stream_response_payload([])
        api_url = str(self._jackett_config.api_url or "").strip()
        api_key = str(self._jackett_config.api_key or "").strip()
        if not api_url or not api_key:
            return _stream_response_payload([])

        cache_key = _stream_lookup_cache_key(normalized_type, item_id)
        cached_streams = _cache_get_value(
            _STREMIO_STREAM_CACHE,
            key=cache_key,
            ttl_seconds=STREMIO_STREAM_CACHE_TTL_SECONDS,
            lock=_STREMIO_STREAM_CACHE_LOCK,
        )
        if cached_streams is not None:
            return deepcopy(cached_streams)

        metadata = self._resolve_stream_metadata(
            imdb_id=parsed_id.imdb_id,
            media_type=media_type,
        )
        if metadata is None:
            return _stream_response_payload([])

        if metadata.media_type != media_type:
            return _stream_response_payload([])

        runs = self._collect_search_runs_for_target(
            metadata=metadata,
            parsed_id=parsed_id,
            media_type=media_type,
            api_url=api_url,
            api_key=api_key,
        )
        deduped_results = self._deduped_search_results_from_runs(runs)

        collection_results = sorted(
            deduped_results,
            key=_collection_priority_stream_sort_key,
            reverse=True,
        )
        stream_candidates: list[CollectedStreamCandidate] = []
        deadline = monotonic() + STREMIO_STREAM_RESPONSE_BUDGET_SECONDS
        cleaned_base_url = str(base_url or "").strip()
        qb_client: QbittorrentClient | None = None
        if self._qb_config.is_configured and cleaned_base_url:
            qb_client = QbittorrentClient(
                self._qb_config.base_url,
                self._qb_config.username,
                self._qb_config.password,
                timeout=min(
                    STREMIO_LOCAL_PLAYBACK_QB_TIMEOUT_SECONDS,
                    STREMIO_STREAM_RESPONSE_BUDGET_SECONDS,
                ),
            )
            try:
                qb_client.login()
            except QbittorrentClientError:
                qb_client.close()
                qb_client = None
        try:
            qb_stream_candidates = _collect_stream_candidates(
                collection_results,
                metadata_title=metadata.title,
                item_type=normalized_type,
                season_number=parsed_id.season_number if parsed_id.is_episode else None,
                episode_number=parsed_id.episode_number if parsed_id.is_episode else None,
                deadline=deadline,
            )
            external_candidate_groups: list[list[CollectedStreamCandidate]] = []
            if self._external_stream_providers:
                provider_executor = ThreadPoolExecutor(
                    max_workers=min(4, len(self._external_stream_providers))
                )
                provider_futures: dict[
                    Future[list[CollectedStreamCandidate]],
                    ResolvedStremioStreamProvider,
                ] = {}
                try:
                    for provider in self._external_stream_providers:
                        remaining_seconds = deadline - monotonic()
                        if remaining_seconds <= 0:
                            break
                        provider_futures[
                            provider_executor.submit(
                                _fetch_external_provider_streams,
                                provider,
                                item_type=normalized_type,
                                item_id=item_id,
                                timeout_seconds=min(
                                    STREMIO_EXTERNAL_PROVIDER_TIMEOUT_SECONDS,
                                    max(0.1, remaining_seconds),
                                ),
                            )
                        ] = provider
                    if provider_futures:
                        provider_done, provider_pending = wait(
                            tuple(provider_futures.keys()),
                            timeout=max(0.1, deadline - monotonic()),
                        )
                        for provider_future in provider_done:
                            try:
                                provider_candidates: list[CollectedStreamCandidate] = (
                                    provider_future.result()
                                )
                            except Exception:
                                provider_candidates = []
                            if provider_candidates:
                                external_candidate_groups.append(provider_candidates)
                        for provider_future in provider_pending:
                            provider_future.cancel()
                finally:
                    provider_executor.shutdown(wait=False, cancel_futures=True)
            stream_candidates.extend(
                _merge_stream_candidates([qb_stream_candidates, *external_candidate_groups])
            )
            if qb_client is not None and cleaned_base_url:
                try:
                    local_matches = find_qb_local_playback_matches(
                        qb_client,
                        imdb_id=parsed_id.imdb_id,
                        season_number=parsed_id.season_number if parsed_id.is_episode else None,
                        episode_number=parsed_id.episode_number if parsed_id.is_episode else None,
                    )
                except QbittorrentClientError:
                    local_matches = []
                if stream_candidates:
                    stream_candidates = _upgrade_candidates_with_exact_local_playback(
                        stream_candidates,
                        qb_client=qb_client,
                        metadata_title=metadata.title,
                        item_type=normalized_type,
                        season_number=parsed_id.season_number if parsed_id.is_episode else None,
                        episode_number=parsed_id.episode_number if parsed_id.is_episode else None,
                        addon_base_url=cleaned_base_url,
                    )
                local_matches.sort(key=_local_match_sort_key, reverse=True)
                seen_stream_keys = {
                    _stream_identity_key(candidate.stream) for candidate in stream_candidates
                }
                for match in local_matches:
                    if len(stream_candidates) >= STREMIO_STREAM_LIMIT:
                        break
                    local_stream = _stream_from_local_qb_match(
                        match=match,
                        metadata_title=metadata.title,
                        item_type=normalized_type,
                        season_number=parsed_id.season_number if parsed_id.is_episode else None,
                        episode_number=parsed_id.episode_number if parsed_id.is_episode else None,
                        addon_base_url=cleaned_base_url,
                    )
                    stream_key = _stream_identity_key(local_stream)
                    if stream_key in seen_stream_keys:
                        continue
                    seen_stream_keys.add(stream_key)
                    stream_candidates.append(
                        CollectedStreamCandidate(
                            stream=local_stream,
                            sort_key=_local_inventory_stream_sort_key(match),
                        )
                    )
        finally:
            if qb_client is not None:
                qb_client.close()
        stream_candidates.sort(key=lambda candidate: candidate.sort_key, reverse=True)
        streams = [candidate.stream for candidate in stream_candidates[:STREMIO_STREAM_LIMIT]]
        if len(streams) > STREMIO_STREAM_LIMIT:
            streams = streams[:STREMIO_STREAM_LIMIT]
        payload = _stream_response_payload(streams)
        if streams:
            _cache_set_value(
                _STREMIO_STREAM_CACHE,
                key=cache_key,
                value=deepcopy(payload),
                lock=_STREMIO_STREAM_CACHE_LOCK,
            )
        return payload

    def _collect_search_runs_for_target(
        self,
        *,
        metadata: MetadataResult,
        parsed_id: ParsedStremioId,
        media_type: MediaType,
        api_url: str,
        api_key: str,
    ) -> list[JackettSearchRun]:
        runs: list[JackettSearchRun] = []
        if parsed_id.is_episode:
            episode_release_year: str | None = None
            episode_query_variants = _episode_query_variants(metadata.title)
            preferred_query_title = (
                episode_query_variants[0] if episode_query_variants else metadata.title
            )
            exact_payload = JackettSearchRequest(
                query=clamp_search_query_text(
                    preferred_query_title or metadata.title,
                    fallback=parsed_id.imdb_id,
                ),
                media_type=media_type,
                imdb_id=parsed_id.imdb_id,
                imdb_id_only=True,
                release_year=episode_release_year,
                keywords_all=[
                    f"S{int(parsed_id.season_number or 0):02d}E{int(parsed_id.episode_number or 0):02d}"
                ],
            )
            text_episode_payload = JackettSearchRequest(
                query=clamp_search_query_text(
                    f"{preferred_query_title or metadata.title} S{int(parsed_id.season_number or 0):02d}E{int(parsed_id.episode_number or 0):02d}",
                    fallback=parsed_id.imdb_id,
                ),
                media_type=media_type,
                release_year=episode_release_year,
            )
            completed_runs: dict[str, JackettSearchRun] = {}
            search_futures: dict[Future[JackettSearchRun | None], str] = {}
            search_executor = ThreadPoolExecutor(max_workers=2)
            try:
                search_futures = {
                    search_executor.submit(
                        _run_jackett_search,
                        api_url=api_url,
                        api_key=api_key,
                        payload=exact_payload,
                    ): "exact",
                    search_executor.submit(
                        _run_jackett_search,
                        api_url=api_url,
                        api_key=api_key,
                        payload=text_episode_payload,
                    ): "text",
                }
                pending = set(search_futures)
                deadline = monotonic() + STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS
                while pending:
                    remaining_seconds = deadline - monotonic()
                    if remaining_seconds <= 0:
                        break
                    done, pending = wait(
                        pending,
                        timeout=remaining_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        break
                    for future in done:
                        run = future.result()
                        if run is None:
                            continue
                        completed_runs[search_futures[future]] = run
                    exact_completed_run = completed_runs.get("exact")
                    if _episode_search_run_is_sufficient(
                        exact_completed_run,
                        season_number=parsed_id.season_number,
                        episode_number=parsed_id.episode_number,
                        preferred_languages=self._stremio_config.preferred_languages,
                    ):
                        for future in pending:
                            future.cancel()
                        pending.clear()
                        break
                for future in pending:
                    future.cancel()
            finally:
                search_executor.shutdown(wait=False, cancel_futures=True)

            exact_run = completed_runs.get("exact")
            text_run = completed_runs.get("text")
            if exact_run is not None:
                runs.append(exact_run)
            if text_run is not None:
                runs.append(text_run)

            exact_run_has_usable_match = _episode_search_run_has_usable_match(
                exact_run,
                season_number=parsed_id.season_number,
                episode_number=parsed_id.episode_number,
                preferred_languages=self._stremio_config.preferred_languages,
            )
            provider_aggregation_can_supply_breadth = bool(
                self._external_stream_providers and exact_run_has_usable_match
            )

            if (
                not provider_aggregation_can_supply_breadth
                and exact_run is not None
                and _search_run_result_count(exact_run) < STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
            ):
                season_payload = JackettSearchRequest(
                    query=clamp_search_query_text(
                        preferred_query_title or metadata.title,
                        fallback=parsed_id.imdb_id,
                    ),
                    media_type=media_type,
                    imdb_id=parsed_id.imdb_id,
                    imdb_id_only=True,
                    release_year=episode_release_year,
                    keywords_all=[f"S{int(parsed_id.season_number or 0):02d}"],
                )
                season_run = _run_jackett_search(
                    api_url=api_url,
                    api_key=api_key,
                    payload=season_payload,
                )
                if season_run is not None:
                    runs.append(season_run)
            episode_match_count = sum(
                _search_run_episode_match_count(
                    run,
                    season_number=parsed_id.season_number,
                    episode_number=parsed_id.episode_number,
                )
                for run in runs
            )
            preferred_language_match_found = any(
                _search_run_has_preferred_language_match(
                    run,
                    preferred_languages=self._stremio_config.preferred_languages,
                    season_number=parsed_id.season_number,
                    episode_number=parsed_id.episode_number,
                )
                for run in runs
            )
            should_run_broad_episode_fallback = (
                not provider_aggregation_can_supply_breadth
                and episode_match_count < STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
            )
            if (
                not provider_aggregation_can_supply_breadth
                and self._stremio_config.preferred_languages
                and not preferred_language_match_found
            ):
                should_run_broad_episode_fallback = True
            if (
                not provider_aggregation_can_supply_breadth
                and not should_run_broad_episode_fallback
                and exact_run is not None
                and _search_run_result_count(exact_run)
                < STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
            ):
                normalized_preferred_query = (
                    preferred_query_title.casefold().strip()
                    if preferred_query_title
                    else ""
                )
                normalized_metadata_title = metadata.title.casefold().strip()
                if (
                    normalized_preferred_query
                    and normalized_preferred_query != normalized_metadata_title
                ):
                    should_run_broad_episode_fallback = True
            if should_run_broad_episode_fallback:
                broad_match_count = episode_match_count
                broad_preferred_language_match_found = preferred_language_match_found
                for query_variant in episode_query_variants:
                    broad_episode_run = _run_jackett_unstructured_title_search(
                        api_url=api_url,
                        api_key=api_key,
                        query=query_variant,
                    )
                    if broad_episode_run is None:
                        continue
                    runs.append(broad_episode_run)
                    broad_match_count += _search_run_episode_match_count(
                        broad_episode_run,
                        season_number=parsed_id.season_number,
                        episode_number=parsed_id.episode_number,
                    )
                    if _search_run_has_preferred_language_match(
                        broad_episode_run,
                        preferred_languages=self._stremio_config.preferred_languages,
                        season_number=parsed_id.season_number,
                        episode_number=parsed_id.episode_number,
                    ):
                        broad_preferred_language_match_found = True
                    if (
                        self._stremio_config.preferred_languages
                        and broad_preferred_language_match_found
                        and broad_match_count > 0
                    ):
                        break
                    if (
                        broad_match_count >= STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
                        and (
                            not self._stremio_config.preferred_languages
                            or broad_preferred_language_match_found
                        )
                    ):
                        break
            return runs

        movie_run = _run_jackett_search(
            api_url=api_url,
            api_key=api_key,
            payload=JackettSearchRequest(
                query=clamp_search_query_text(metadata.title, fallback=parsed_id.imdb_id),
                media_type=media_type,
                imdb_id=parsed_id.imdb_id,
                imdb_id_only=True,
                release_year=metadata.year or None,
            ),
        )
        if movie_run is not None:
            runs.append(movie_run)
        return runs

    def _deduped_search_results_from_runs(
        self,
        runs: list[JackettSearchRun],
    ) -> list[JackettSearchResult]:
        deduped_results: list[JackettSearchResult] = []
        seen_merge_keys: set[str] = set()
        for run_index, run in enumerate(runs):
            primary_results = list(run.results or [])
            fallback_results = list(run.fallback_results or [])
            for result_index, result in enumerate([*primary_results, *fallback_results]):
                result_copy = result.model_copy(deep=True)
                query_source_label = "Fallback"
                if result_index < len(primary_results):
                    query_source_label = "Exact" if run_index == 0 else "Precise title"
                result_copy.torznab_attrs = {
                    **dict(result_copy.torznab_attrs or {}),
                    "querysource": query_source_label,
                }
                merge_key = str(result_copy.merge_key or "")
                if merge_key and merge_key in seen_merge_keys:
                    continue
                if merge_key:
                    seen_merge_keys.add(merge_key)
                deduped_results.append(result_copy)
        return _apply_preferred_language_filter(
            deduped_results,
            preferred_languages=self._stremio_config.preferred_languages,
        )

    def _resolve_stream_metadata(
        self,
        *,
        imdb_id: str,
        media_type: MediaType,
    ) -> MetadataResult | None:
        cache_key = _metadata_cache_key(imdb_id, media_type)
        cached_metadata = _cache_get_value(
            _STREMIO_METADATA_CACHE,
            key=cache_key,
            ttl_seconds=STREMIO_METADATA_CACHE_TTL_SECONDS,
            lock=_STREMIO_METADATA_CACHE_LOCK,
        )
        if cached_metadata is not None:
            return cached_metadata

        metadata = self._lookup_cinemeta_by_imdb_id(imdb_id=imdb_id, media_type=media_type)
        if metadata is not None:
            _cache_set_value(
                _STREMIO_METADATA_CACHE,
                key=cache_key,
                value=metadata,
                lock=_STREMIO_METADATA_CACHE_LOCK,
            )
            return metadata

        try:
            metadata_client = MetadataClient(
                self._metadata_config.provider,
                self._metadata_config.api_key,
            )
            metadata = metadata_client.lookup_by_imdb_id(imdb_id)
            if metadata.media_type == media_type:
                _cache_set_value(
                    _STREMIO_METADATA_CACHE,
                    key=cache_key,
                    value=metadata,
                    lock=_STREMIO_METADATA_CACHE_LOCK,
                )
                return metadata
        except MetadataLookupError:
            pass

        return None

    @staticmethod
    def _lookup_cinemeta_by_imdb_id(
        *,
        imdb_id: str,
        media_type: MediaType,
    ) -> MetadataResult | None:
        stremio_type = "movie" if media_type == MediaType.MOVIE else "series"
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(
                    f"https://v3-cinemeta.strem.io/meta/{stremio_type}/{imdb_id}.json"
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            return None

        resolved_imdb_id = str(meta.get("imdb_id") or meta.get("id") or "").strip()
        if not resolved_imdb_id or resolved_imdb_id.casefold() != imdb_id.casefold():
            return None

        title = str(meta.get("name") or "").strip()
        if not title:
            return None

        return MetadataResult(
            title=title,
            provider=MetadataLookupProvider.OMDB,
            imdb_id=resolved_imdb_id,
            source_id=resolved_imdb_id,
            media_type=media_type,
            year=str(meta.get("releaseInfo") or meta.get("year") or "").strip() or None,
            poster_url=str(meta.get("poster") or "").strip() or None,
        )
