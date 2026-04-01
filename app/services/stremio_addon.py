from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx

from app.models import AppSettings, MediaType
from app.schemas import (
    JackettSearchRequest,
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services.jackett import JackettClient, JackettClientError, clamp_search_query_text
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
    ParsedTorrentInfo,
    SelectiveQueueError,
    find_episode_file_entry,
    parse_torrent_info,
    text_matches_episode,
)
from app.services.settings_service import SettingsService

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
STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS = 1.8
STREMIO_HTTP_TORRENT_TIMEOUT_SECONDS = 0.75
STREMIO_LOCAL_PLAYBACK_QB_TIMEOUT_SECONDS = 2.0
STREMIO_STREAM_CACHE_TTL_SECONDS = 180.0
STREMIO_METADATA_CACHE_TTL_SECONDS = 1800.0
STREMIO_STREAM_CACHE_MAX_AGE_SECONDS = 7200
STREMIO_STREAM_STALE_REVALIDATE_SECONDS = 14400
STREMIO_STREAM_STALE_ERROR_SECONDS = 604800
_STREMIO_STREAM_CACHE_LOCK = threading.Lock()
_STREMIO_STREAM_CACHE: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
_STREMIO_METADATA_CACHE_LOCK = threading.Lock()
_STREMIO_METADATA_CACHE: dict[tuple[str, str], tuple[float, MetadataResult | None]] = {}


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


def _stream_title(
    *,
    metadata_title: str,
    season_number: int | None,
    episode_number: int | None,
    result: JackettSearchResult,
) -> str:
    display_label = _stream_display_label(
        metadata_title=metadata_title,
        season_number=season_number,
        episode_number=episode_number,
    )
    detail_parts = [f"\U0001f464 {int(result.seeders or 0)}"]
    size_label = str(result.size_label or "").strip()
    if size_label:
        detail_parts.append(f"\U0001f4be {size_label}")
    variant_label = _quality_label_from_title(str(result.title or ""))
    if variant_label and variant_label.casefold() != "torrent":
        detail_parts.append(variant_label)
    source_label = str(result.indexer or "").strip()
    if source_label:
        detail_parts.append(f"\u2699\ufe0f qbrssrules/{source_label}")
    else:
        detail_parts.append("\u2699\ufe0f qbrssrules")
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


def _resolved_filename_from_torrent(
    parsed_torrent: ParsedTorrentInfo,
    *,
    season_number: int | None,
    episode_number: int | None,
) -> tuple[int | None, str | None]:
    if season_number is not None and episode_number is not None:
        entry = find_episode_file_entry(
            parsed_torrent.files,
            season_number=season_number,
            episode_number=episode_number,
        )
        if entry is not None:
            return entry.file_id, PurePosixPath(entry.path).name or entry.path
    if len(parsed_torrent.files) == 1:
        entry = parsed_torrent.files[0]
        return entry.file_id, PurePosixPath(entry.path).name or entry.path
    return None, None


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
                file_idx, filename = _resolved_filename_from_torrent(
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
    info_hash = target.info_hash
    behavior_hints: dict[str, object] = {
        "bingieGroup": f"qB RSS Rules|{info_hash}",
    }
    if target.filename:
        behavior_hints["filename"] = target.filename
    stream: dict[str, object] = {
        "name": _stream_name(result),
        "tag": _quality_tag_from_title(str(result.title or "")),
        "type": item_type,
        "title": _stream_title(
            metadata_title=metadata_title,
            season_number=season_number,
            episode_number=episode_number,
            result=result,
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


class StremioAddonService:
    def __init__(self, settings: AppSettings | None) -> None:
        self.settings = settings
        self._jackett_config = SettingsService.resolve_jackett(settings)
        self._metadata_config = SettingsService.resolve_metadata(settings)
        self._qb_config = SettingsService.resolve_qb_connection(settings)

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
            return {"metas": []}

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

        runs: list[JackettSearchRun] = []
        if parsed_id.is_episode:
            episode_release_year: str | None = None
            exact_payload = JackettSearchRequest(
                query=clamp_search_query_text(metadata.title, fallback=parsed_id.imdb_id),
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
                    f"{metadata.title} S{int(parsed_id.season_number or 0):02d}E{int(parsed_id.episode_number or 0):02d}",
                    fallback=parsed_id.imdb_id,
                ),
                media_type=media_type,
                release_year=episode_release_year,
            )
            completed_runs: dict[str, JackettSearchRun] = {}
            search_futures = {}
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
                done, pending = wait(
                    search_futures, timeout=STREMIO_SEARCH_COLLECTION_BUDGET_SECONDS
                )
                for future in done:
                    run = future.result()
                    if run is None:
                        continue
                    completed_runs[search_futures[future]] = run
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

            if (
                exact_run is not None
                and _search_run_result_count(exact_run) < STREMIO_EPISODE_FALLBACK_SEARCH_THRESHOLD
            ):
                season_payload = JackettSearchRequest(
                    query=clamp_search_query_text(metadata.title, fallback=parsed_id.imdb_id),
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
        else:
            movie_payload = JackettSearchRequest(
                query=clamp_search_query_text(metadata.title, fallback=parsed_id.imdb_id),
                media_type=media_type,
                imdb_id=parsed_id.imdb_id,
                imdb_id_only=True,
                release_year=metadata.year or None,
            )
            movie_run = _run_jackett_search(
                api_url=api_url,
                api_key=api_key,
                payload=movie_payload,
            )
            if movie_run is not None:
                runs.append(movie_run)

        deduped_results: list[JackettSearchResult] = []
        seen_merge_keys: set[str] = set()
        for run in runs:
            for result in [*list(run.results or []), *list(run.fallback_results or [])]:
                merge_key = str(result.merge_key or "")
                if merge_key and merge_key in seen_merge_keys:
                    continue
                if merge_key:
                    seen_merge_keys.add(merge_key)
                deduped_results.append(result)

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
            stream_candidates.extend(
                _collect_stream_candidates(
                    collection_results,
                    metadata_title=metadata.title,
                    item_type=normalized_type,
                    season_number=parsed_id.season_number if parsed_id.is_episode else None,
                    episode_number=parsed_id.episode_number if parsed_id.is_episode else None,
                    deadline=deadline,
                )
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
