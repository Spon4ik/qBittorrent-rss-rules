from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.schemas import (
    JackettSearchRequest,
    JackettSearchResult,
    SearchSourceKind,
)
from app.services.real_debrid import RealDebridClient
from app.services.selective_queue import text_matches_episode

TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)
ACTIONABLE_TORRENT_STATUSES = frozenset(
    {
        "magnet_conversion",
        "waiting_files_selection",
        "queued",
        "downloading",
        "downloaded",
    }
)


def search_real_debrid(
    client: RealDebridClient,
    payload: JackettSearchRequest,
    *,
    max_pages: int = 10,
) -> list[JackettSearchResult]:
    rows: list[JackettSearchResult] = []
    for item in _paged_items(client.list_torrents, max_pages=max_pages):
        row = _torrent_result(item)
        if row is not None and _matches(row, payload):
            rows.append(row)
    for item in _paged_items(client.list_downloads, max_pages=max_pages):
        row = _download_result(item)
        if row is not None and _matches(row, payload):
            rows.append(row)
    rows.sort(
        key=lambda row: (
            0 if row.source_kind == SearchSourceKind.REAL_DEBRID_TORRENT else 1,
            str(row.published_at or ""),
            row.title.casefold(),
        ),
        reverse=False,
    )
    return rows


def _paged_items(fetch: Any, *, max_pages: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, max(1, max_pages) + 1):
        batch = fetch(page=page, limit=100)
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def _torrent_result(item: dict[str, Any]) -> JackettSearchResult | None:
    provider_id = str(item.get("id") or "").strip()
    title = str(item.get("filename") or item.get("original_filename") or "").strip()
    if not provider_id or not title:
        return None
    info_hash = str(item.get("hash") or "").strip().casefold()
    if len(info_hash) != 40 or any(char not in "0123456789abcdef" for char in info_hash):
        info_hash = ""
    size_bytes = _optional_int(item.get("bytes"))
    status = str(item.get("status") or "unknown").strip().casefold()
    published_at = str(item.get("added") or item.get("ended") or "").strip() or None
    return JackettSearchResult(
        merge_key=f"hash:{info_hash}" if info_hash else f"rd-torrent:{provider_id}",
        title=title,
        link=f"real-debrid://torrent/{provider_id}",
        indexer="Real-Debrid cloud",
        guid=f"real-debrid:torrent:{provider_id}",
        info_hash=info_hash or None,
        size_bytes=size_bytes,
        size_label=_format_size(size_bytes),
        published_at=published_at,
        published_label=_format_date(published_at),
        text_surface=_normalize_text(title),
        source_kind=SearchSourceKind.REAL_DEBRID_TORRENT,
        grouped_links=[f"real-debrid://torrent/{provider_id}"],
        grouped_indexers=["Real-Debrid cloud"],
        provider_id=provider_id,
        provider_status=status,
        queue_capability="qbittorrent"
        if info_hash and status in ACTIONABLE_TORRENT_STATUSES
        else "disabled",
        in_real_debrid=True,
    )


def _download_result(item: dict[str, Any]) -> JackettSearchResult | None:
    provider_id = str(item.get("id") or "").strip()
    title = str(item.get("filename") or "").strip()
    if not provider_id or not title:
        return None
    size_bytes = _optional_int(item.get("filesize"))
    published_at = str(item.get("generated") or "").strip() or None
    return JackettSearchResult(
        merge_key=f"rd-download:{provider_id}",
        title=title,
        link=f"real-debrid://download/{provider_id}",
        indexer="Real-Debrid history",
        guid=f"real-debrid:download:{provider_id}",
        size_bytes=size_bytes,
        size_label=_format_size(size_bytes),
        published_at=published_at,
        published_label=_format_date(published_at),
        text_surface=_normalize_text(title),
        source_kind=SearchSourceKind.REAL_DEBRID_DOWNLOAD,
        grouped_links=[f"real-debrid://download/{provider_id}"],
        grouped_indexers=["Real-Debrid history"],
        provider_id=provider_id,
        provider_status="downloaded",
        queue_capability="jdownloader",
        in_real_debrid=True,
    )


def _matches(result: JackettSearchResult, payload: JackettSearchRequest) -> bool:
    text = _normalize_text(result.title)
    query_tokens = _tokens(payload.query)
    if query_tokens and not all(token in text for token in query_tokens):
        return False
    if payload.release_year and payload.release_year not in text:
        return False
    if any(_normalize_text(term) not in text for term in payload.keywords_all):
        return False
    if any(_normalize_text(term) in text for term in payload.keywords_not):
        return False
    groups = list(payload.keywords_any_groups or [])
    if not groups and payload.keywords_any:
        groups = [list(payload.keywords_any)]
    for group in groups:
        if group and not any(_normalize_text(term) in text for term in group):
            return False
    if payload.season_number is not None and payload.episode_number is not None:
        if not text_matches_episode(
            result.title,
            season_number=int(payload.season_number),
            episode_number=int(payload.episode_number),
        ):
            return False
    if payload.size_min_mb is not None and (
        result.size_bytes is None or result.size_bytes < int(payload.size_min_mb * 1024 * 1024)
    ):
        return False
    if payload.size_max_mb is not None and (
        result.size_bytes is None or result.size_bytes > int(payload.size_max_mb * 1024 * 1024)
    ):
        return False
    return True


def _tokens(value: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(value)]


def _normalize_text(value: object | None) -> str:
    return " ".join(_tokens(str(value or "")))


def _optional_int(value: object | None) -> int | None:
    try:
        numeric = int(str(value))
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= 0 else None


def _format_size(value: int | None) -> str | None:
    if value is None:
        return None
    numeric = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if numeric < 1024 or unit == "TB":
            return f"{numeric:.1f} {unit}"
        numeric /= 1024
    return None


def _format_date(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return cleaned
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
