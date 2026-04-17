from __future__ import annotations

import base64
import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from app.config import get_environment_settings
from app.models import MediaType, Rule
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.rule_builder import normalize_jellyfin_episode_keys

VIDEO_FILE_EXTENSIONS = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".wmv",
}
SEASON_EPISODE_RANGE_RE = re.compile(
    r"(?i)s(?P<season>\d{1,2})[\s._-]*e(?P<start>\d{1,2})(?:[\s._-]*(?:-|to)[\s._-]*(?:e)?(?P<end>\d{1,2}))?"
)


class SelectiveQueueError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TorrentFileEntry:
    file_id: int
    path: str


@dataclass(frozen=True, slots=True)
class ParsedTorrentInfo:
    info_hash: str
    filename: str
    files: list[TorrentFileEntry]
    tracker_urls: list[str]


@dataclass(frozen=True, slots=True)
class EpisodeFileSelectionPlan:
    floor: tuple[int, int]
    excluded_episode_keys: frozenset[str]


@dataclass(frozen=True, slots=True)
class EpisodeFileSelectionResult:
    selected_file_ids: list[int]
    parsed_episode_file_count: int
    skipped_episode_file_count: int


@dataclass(frozen=True, slots=True)
class QueueResult:
    message: str = ""
    selected_file_count: int = 0
    skipped_file_count: int = 0
    deferred_file_selection: bool = False
    queued_via_torrent_file: bool = False


@dataclass(frozen=True, slots=True)
class StremioQueueSelection:
    info_hash: str
    tracker_urls: list[str]
    display_name: str | None = None
    file_idx: int | None = None


def find_episode_file_entry(
    files: list[TorrentFileEntry],
    *,
    season_number: int,
    episode_number: int,
) -> TorrentFileEntry | None:
    candidates: list[TorrentFileEntry] = []
    for entry in files:
        if not _is_video_file(entry.path):
            continue
        if text_matches_episode(
            entry.path,
            season_number=season_number,
            episode_number=episode_number,
        ):
            candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (entry.file_id, entry.path.casefold()))
    return candidates[0]


def text_matches_episode(
    text: str,
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    episode_matches = list(_episode_matches_for_path(text))
    return any(
        matched_season == season_number and start_episode <= episode_number <= end_episode
        for matched_season, start_episode, end_episode in episode_matches
    )


def build_episode_file_selection_plan(rule: Rule) -> EpisodeFileSelectionPlan | None:
    if rule.media_type != MediaType.SERIES:
        return None
    if rule.start_season is None or rule.start_episode is None:
        return None

    if bool(getattr(rule, "jellyfin_search_existing_unseen", False)):
        excluded_episode_keys = frozenset(
            normalize_jellyfin_episode_keys(
                list(getattr(rule, "jellyfin_watched_episode_numbers", []) or [])
            )
        )
    else:
        excluded_episode_keys = frozenset(
            normalize_jellyfin_episode_keys(
                list(getattr(rule, "jellyfin_known_episode_numbers", []) or [])
                + list(getattr(rule, "jellyfin_existing_episode_numbers", []) or [])
            )
        )

    return EpisodeFileSelectionPlan(
        floor=(int(rule.start_season), int(rule.start_episode)),
        excluded_episode_keys=excluded_episode_keys,
    )


def parse_magnet_info_hash(link: str) -> str | None:
    parsed = urlsplit(link)
    if parsed.scheme.casefold() != "magnet":
        return None
    xt_values = parse_qs(parsed.query).get("xt", [])
    for value in xt_values:
        prefix = "urn:btih:"
        if not value.casefold().startswith(prefix):
            continue
        raw_hash = value[len(prefix) :].strip()
        if len(raw_hash) == 40 and all(char in "0123456789abcdefABCDEF" for char in raw_hash):
            return raw_hash.casefold()
        if len(raw_hash) == 32:
            try:
                return base64.b32decode(raw_hash.upper()).hex()
            except Exception:
                continue
    return None


def build_magnet_link(
    *,
    info_hash: str,
    tracker_urls: list[str] | tuple[str, ...] = (),
    display_name: str | None = None,
) -> str:
    cleaned_hash = str(info_hash or "").strip().casefold()
    if len(cleaned_hash) != 40 or any(char not in "0123456789abcdef" for char in cleaned_hash):
        raise SelectiveQueueError("A valid 40-character hex info hash is required.")

    magnet_parts = [f"magnet:?xt=urn:btih:{cleaned_hash}"]
    cleaned_name = str(display_name or "").strip()
    if cleaned_name:
        magnet_parts.append(f"dn={quote(cleaned_name)}")

    seen_trackers: set[str] = set()
    for tracker_url in tracker_urls:
        cleaned_tracker = str(tracker_url or "").strip()
        if not cleaned_tracker:
            continue
        normalized_tracker = cleaned_tracker.casefold()
        if normalized_tracker in seen_trackers:
            continue
        seen_trackers.add(normalized_tracker)
        magnet_parts.append(f"tr={quote(cleaned_tracker, safe='')}")

    return "&".join(magnet_parts)


def queue_stremio_stream_selection(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    selection: StremioQueueSelection,
    category: str,
    save_path: str,
    paused: bool,
    sequential_download: bool,
    first_last_piece_prio: bool,
) -> tuple[QueueResult, str]:
    magnet_link = build_magnet_link(
        info_hash=selection.info_hash,
        tracker_urls=selection.tracker_urls,
        display_name=selection.display_name,
    )
    with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
        client.add_torrent_url(
            link=magnet_link,
            category=category,
            save_path=save_path,
            paused=paused,
            sequential_download=sequential_download,
            first_last_piece_prio=first_last_piece_prio,
        )

    if selection.file_idx is None:
        return QueueResult(message="Queued exact stream magnet in qBittorrent."), magnet_link

    _start_exact_file_selection_worker(
        qb_base_url=qb_base_url,
        qb_username=qb_username,
        qb_password=qb_password,
        info_hash=selection.info_hash,
        file_idx=selection.file_idx,
    )
    return (
        QueueResult(
            message=(
                "Queued exact stream magnet in qBittorrent. The selected Stremio file "
                "variant will be prioritized when torrent metadata becomes available."
            ),
            deferred_file_selection=True,
        ),
        magnet_link,
    )


def parse_torrent_info(
    torrent_bytes: bytes, *, source_name: str = "queued-result.torrent"
) -> ParsedTorrentInfo:
    if not torrent_bytes:
        raise SelectiveQueueError("Torrent response was empty.")

    if torrent_bytes[:1] != b"d":
        raise SelectiveQueueError("Result did not return a valid torrent file.")

    try:
        index = 1
        root: dict[bytes, Any] = {}
        info_slice: bytes | None = None
        while index < len(torrent_bytes) and torrent_bytes[index : index + 1] != b"e":
            key, index = _decode_bencode_bytes(torrent_bytes, index)
            value_start = index
            value, index = _decode_bencode_value(torrent_bytes, index)
            if key == b"info":
                info_slice = torrent_bytes[value_start:index]
            root[key] = value
        if index >= len(torrent_bytes):
            raise SelectiveQueueError("Torrent file ended unexpectedly.")
    except (TypeError, ValueError, IndexError) as exc:
        raise SelectiveQueueError("Result did not return a readable torrent file.") from exc

    info = root.get(b"info")
    if not isinstance(info, dict) or info_slice is None:
        raise SelectiveQueueError("Torrent metadata did not include an info dictionary.")

    info_hash = hashlib.sha1(info_slice).hexdigest()
    files = _extract_torrent_files(info)
    filename = _best_torrent_filename(root, info, source_name)
    return ParsedTorrentInfo(
        info_hash=info_hash,
        filename=filename,
        files=files,
        tracker_urls=_extract_torrent_tracker_urls(root),
    )


def select_missing_episode_file_ids(
    files: list[TorrentFileEntry],
    plan: EpisodeFileSelectionPlan,
) -> EpisodeFileSelectionResult:
    selected_file_ids: list[int] = []
    parsed_episode_file_count = 0
    skipped_episode_file_count = 0

    for entry in files:
        if not _is_video_file(entry.path):
            continue
        episode_matches = list(_episode_matches_for_path(entry.path))
        if not episode_matches:
            continue
        parsed_episode_file_count += 1
        if any(_selection_plan_accepts_episode_range(plan, match) for match in episode_matches):
            selected_file_ids.append(entry.file_id)
        else:
            skipped_episode_file_count += 1

    return EpisodeFileSelectionResult(
        selected_file_ids=selected_file_ids,
        parsed_episode_file_count=parsed_episode_file_count,
        skipped_episode_file_count=skipped_episode_file_count,
    )


def queue_result_with_optional_file_selection(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    link: str,
    category: str,
    save_path: str,
    paused: bool,
    sequential_download: bool,
    first_last_piece_prio: bool,
    rule: Rule | None,
) -> QueueResult:
    selection_plan = build_episode_file_selection_plan(rule) if rule is not None else None
    if selection_plan is None:
        with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
            client.add_torrent_url(
                link=link,
                category=category,
                save_path=save_path,
                paused=paused,
                sequential_download=sequential_download,
                first_last_piece_prio=first_last_piece_prio,
            )
        return QueueResult()

    magnet_info_hash = parse_magnet_info_hash(link)
    if magnet_info_hash:
        with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
            client.add_torrent_url(
                link=link,
                category=category,
                save_path=save_path,
                paused=paused,
                sequential_download=sequential_download,
                first_last_piece_prio=first_last_piece_prio,
            )
        _start_deferred_file_selection_worker(
            qb_base_url=qb_base_url,
            qb_username=qb_username,
            qb_password=qb_password,
            info_hash=magnet_info_hash,
            selection_plan=selection_plan,
        )
        return QueueResult(
            message=(
                "Queued in qBittorrent. Missing/unseen file selection will be applied when "
                "torrent metadata becomes available."
            ),
            deferred_file_selection=True,
        )

    try:
        torrent_bytes, source_name = _download_torrent_bytes(link)
        parsed_torrent = parse_torrent_info(torrent_bytes, source_name=source_name)
        selection_result = select_missing_episode_file_ids(parsed_torrent.files, selection_plan)
    except (SelectiveQueueError, httpx.HTTPError):
        with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
            client.add_torrent_url(
                link=link,
                category=category,
                save_path=save_path,
                paused=paused,
                sequential_download=sequential_download,
                first_last_piece_prio=first_last_piece_prio,
            )
        return QueueResult(
            message=(
                "Queued full torrent because selective missing/unseen file inspection was not "
                "available for this result."
            )
        )

    if selection_result.parsed_episode_file_count > 0 and not selection_result.selected_file_ids:
        raise SelectiveQueueError("No missing/unseen episode files were detected in this torrent.")

    with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
        client.add_torrent_file(
            torrent_bytes=torrent_bytes,
            filename=parsed_torrent.filename,
            category=category,
            save_path=save_path,
            paused=paused,
            sequential_download=sequential_download,
            first_last_piece_prio=first_last_piece_prio,
        )
        if selection_result.parsed_episode_file_count > 0 and selection_result.selected_file_ids:
            all_file_ids = [entry.file_id for entry in parsed_torrent.files]
            client.set_file_priority(parsed_torrent.info_hash, all_file_ids, 0)
            client.set_file_priority(
                parsed_torrent.info_hash, selection_result.selected_file_ids, 1
            )
            return QueueResult(
                message=(
                    f"Queued only missing/unseen episode files ({len(selection_result.selected_file_ids)} selected, "
                    f"{selection_result.skipped_episode_file_count} skipped)."
                ),
                selected_file_count=len(selection_result.selected_file_ids),
                skipped_file_count=selection_result.skipped_episode_file_count,
                queued_via_torrent_file=True,
            )

    return QueueResult(
        message="Queued full torrent because the torrent file did not expose episode-level files safely.",
        queued_via_torrent_file=True,
    )


def _start_deferred_file_selection_worker(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    info_hash: str,
    selection_plan: EpisodeFileSelectionPlan,
) -> None:
    worker = threading.Thread(
        target=_apply_deferred_file_selection,
        kwargs={
            "qb_base_url": qb_base_url,
            "qb_username": qb_username,
            "qb_password": qb_password,
            "info_hash": info_hash,
            "selection_plan": selection_plan,
        },
        daemon=True,
        name=f"qb-selective-queue-{info_hash[:8]}",
    )
    worker.start()


def _start_exact_file_selection_worker(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    info_hash: str,
    file_idx: int,
) -> None:
    worker = threading.Thread(
        target=_apply_exact_file_selection,
        kwargs={
            "qb_base_url": qb_base_url,
            "qb_username": qb_username,
            "qb_password": qb_password,
            "info_hash": info_hash,
            "file_idx": file_idx,
        },
        daemon=True,
        name=f"qb-stremio-exact-queue-{info_hash[:8]}",
    )
    worker.start()


def _apply_deferred_file_selection(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    info_hash: str,
    selection_plan: EpisodeFileSelectionPlan,
) -> None:
    deadline = time.monotonic() + 45.0
    poll_interval = 2.0
    while time.monotonic() < deadline:
        try:
            with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
                raw_files = client.get_torrent_files(info_hash)
                files = _normalize_qb_torrent_files(raw_files)
                selection_result = select_missing_episode_file_ids(files, selection_plan)
                if selection_result.parsed_episode_file_count == 0:
                    time.sleep(poll_interval)
                    continue
                if not selection_result.selected_file_ids:
                    return
                all_file_ids = [entry.file_id for entry in files]
                client.set_file_priority(info_hash, all_file_ids, 0)
                client.set_file_priority(info_hash, selection_result.selected_file_ids, 1)
                return
        except QbittorrentClientError:
            return
        time.sleep(poll_interval)


def _apply_exact_file_selection(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    info_hash: str,
    file_idx: int,
) -> None:
    deadline = time.monotonic() + 45.0
    poll_interval = 2.0
    while time.monotonic() < deadline:
        try:
            with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
                raw_files = client.get_torrent_files(info_hash)
                files = _normalize_qb_torrent_files(raw_files)
                if not files:
                    time.sleep(poll_interval)
                    continue
                available_file_ids = [entry.file_id for entry in files]
                if file_idx not in available_file_ids:
                    return
                client.set_file_priority(info_hash, available_file_ids, 0)
                client.set_file_priority(info_hash, [file_idx], 1)
                return
        except QbittorrentClientError:
            return
        time.sleep(poll_interval)


def _normalize_qb_torrent_files(payload: list[dict[str, object]]) -> list[TorrentFileEntry]:
    files: list[TorrentFileEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_index = item.get("index")
        if not isinstance(raw_index, int | str):
            continue
        try:
            file_id = int(raw_index)
        except (TypeError, ValueError):
            continue
        file_path = str(item.get("name") or "").strip()
        if not file_path:
            continue
        files.append(TorrentFileEntry(file_id=file_id, path=file_path))
    return files


def _download_torrent_bytes(link: str) -> tuple[bytes, str]:
    timeout = get_environment_settings().request_timeout
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(link)
        response.raise_for_status()
        final_name = (
            PurePosixPath(response.url.path).name
            or PurePosixPath(urlsplit(link).path).name
            or "queued-result.torrent"
        )
        return response.content, final_name


def _decode_bencode_value(data: bytes, index: int) -> tuple[Any, int]:
    token = data[index : index + 1]
    if token == b"i":
        end = data.index(b"e", index)
        return int(data[index + 1 : end]), end + 1
    if token == b"l":
        index += 1
        items: list[Any] = []
        while data[index : index + 1] != b"e":
            item, index = _decode_bencode_value(data, index)
            items.append(item)
        return items, index + 1
    if token == b"d":
        index += 1
        mapping: dict[bytes, Any] = {}
        while data[index : index + 1] != b"e":
            key, index = _decode_bencode_bytes(data, index)
            value, index = _decode_bencode_value(data, index)
            mapping[key] = value
        return mapping, index + 1
    return _decode_bencode_bytes(data, index)


def _decode_bencode_bytes(data: bytes, index: int) -> tuple[bytes, int]:
    colon_index = data.index(b":", index)
    length = int(data[index:colon_index])
    start = colon_index + 1
    end = start + length
    return data[start:end], end


def _extract_torrent_files(info: dict[bytes, Any]) -> list[TorrentFileEntry]:
    if b"files" in info and isinstance(info[b"files"], list):
        files: list[TorrentFileEntry] = []
        for file_id, raw_item in enumerate(info[b"files"]):
            if not isinstance(raw_item, dict):
                continue
            path_segments = raw_item.get(b"path.utf-8") or raw_item.get(b"path")
            if not isinstance(path_segments, list):
                continue
            parts = [_decode_torrent_text(item) for item in path_segments]
            cleaned_parts = [part for part in parts if part]
            if not cleaned_parts:
                continue
            files.append(TorrentFileEntry(file_id=file_id, path="/".join(cleaned_parts)))
        return files

    name_value = info.get(b"name.utf-8") or info.get(b"name")
    filename = _decode_torrent_text(name_value)
    if filename:
        return [TorrentFileEntry(file_id=0, path=filename)]
    return []


def _extract_torrent_tracker_urls(root: dict[bytes, Any]) -> list[str]:
    tracker_urls: list[str] = []
    seen_urls: set[str] = set()

    def _remember_tracker(value: object) -> None:
        tracker_url = _decode_torrent_text(value)
        if not tracker_url:
            return
        normalized = tracker_url.strip()
        if not normalized:
            return
        casefolded = normalized.casefold()
        if not (
            casefolded.startswith("udp://")
            or casefolded.startswith("http://")
            or casefolded.startswith("https://")
        ):
            return
        if casefolded in seen_urls:
            return
        seen_urls.add(casefolded)
        tracker_urls.append(normalized)

    _remember_tracker(root.get(b"announce"))

    announce_list = root.get(b"announce-list")
    if isinstance(announce_list, list):
        for tier in announce_list:
            if isinstance(tier, list):
                for tracker in tier:
                    _remember_tracker(tracker)
            else:
                _remember_tracker(tier)

    return tracker_urls


def _best_torrent_filename(root: dict[bytes, Any], info: dict[bytes, Any], source_name: str) -> str:
    if source_name and source_name.casefold().endswith(".torrent"):
        return source_name
    root_name = _decode_torrent_text(root.get(b"name")) or _decode_torrent_text(
        root.get(b"name.utf-8")
    )
    info_name = _decode_torrent_text(info.get(b"name.utf-8")) or _decode_torrent_text(
        info.get(b"name")
    )
    base_name = root_name or info_name or source_name or "queued-result.torrent"
    if base_name.casefold().endswith(".torrent"):
        return base_name
    return f"{base_name}.torrent"


def _decode_torrent_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value or "").strip()


def _is_video_file(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.casefold()
    return suffix in VIDEO_FILE_EXTENSIONS


def _episode_matches_for_path(path: str) -> list[tuple[int, int, int]]:
    matches: list[tuple[int, int, int]] = []
    for match in SEASON_EPISODE_RANGE_RE.finditer(path):
        season_number = int(match.group("season"))
        start_episode = int(match.group("start"))
        end_raw = match.group("end")
        end_episode = int(end_raw) if end_raw is not None else start_episode
        if end_episode < start_episode:
            start_episode, end_episode = end_episode, start_episode
        matches.append((season_number, start_episode, end_episode))
    return matches


def _selection_plan_accepts_episode_range(
    plan: EpisodeFileSelectionPlan,
    episode_match: tuple[int, int, int],
) -> bool:
    season_number, start_episode, end_episode = episode_match
    floor_season, floor_episode = plan.floor
    for episode_number in range(start_episode, end_episode + 1):
        episode_key = f"S{season_number:02d}E{episode_number:02d}"
        if episode_key in plan.excluded_episode_keys:
            continue
        if (season_number, episode_number) >= (floor_season, floor_episode):
            return True
    return False
