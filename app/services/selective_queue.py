from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
import threading
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import SplitResult, parse_qs, quote, urljoin, urlsplit, urlunsplit

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
    size_bytes: int | None = None


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
        if _file_path_matches_episode(
            entry.path,
            season_number=season_number,
            episode_number=episode_number,
        ):
            candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(
        key=lambda entry: (
            _episode_file_match_rank(
                entry.path,
                season_number=season_number,
                episode_number=episode_number,
            ),
            entry.file_id,
            entry.path.casefold(),
        )
    )
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
    jackett_api_url: str | None = None,
    jackett_qb_url: str | None = None,
    category: str,
    save_path: str,
    paused: bool,
    sequential_download: bool,
    first_last_piece_prio: bool,
    rule: Rule | None,
) -> QueueResult:
    selection_plan = build_episode_file_selection_plan(rule) if rule is not None else None
    magnet_info_hash = parse_magnet_info_hash(link)
    effective_link = _rewrite_jackett_download_link_for_app_fetch(
        link,
        app_base_url=jackett_api_url,
        qb_base_url=jackett_qb_url,
    )
    if magnet_info_hash is None and _should_require_app_side_torrent_fetch(effective_link):
        redirected_magnet_link = _resolve_local_jackett_redirect_magnet_link(effective_link)
        if redirected_magnet_link is not None:
            link = redirected_magnet_link
            effective_link = redirected_magnet_link
            magnet_info_hash = parse_magnet_info_hash(redirected_magnet_link)
    if selection_plan is None and magnet_info_hash is None:
        try:
            torrent_bytes, source_name = _download_torrent_bytes(effective_link)
            parse_torrent_info(torrent_bytes, source_name=source_name)
        except (SelectiveQueueError, httpx.HTTPError) as exc:
            if _should_require_app_side_torrent_fetch(effective_link):
                if _can_qb_remote_fetch_local_url(effective_link, qb_base_url=qb_base_url):
                    torrent_bytes = None
                    source_name = None
                else:
                    raise SelectiveQueueError(
                        "Could not fetch a valid torrent file from the local Jackett-style URL, "
                        "so the app did not hand it off to qBittorrent for remote fetching."
                    ) from exc
            else:
                torrent_bytes = None
                source_name = None
        if torrent_bytes is not None and source_name is not None:
            with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
                client.add_torrent_file(
                    torrent_bytes=torrent_bytes,
                    filename=source_name,
                    category=category,
                    save_path=save_path,
                    paused=paused,
                    sequential_download=sequential_download,
                    first_last_piece_prio=first_last_piece_prio,
                )
            return QueueResult(queued_via_torrent_file=True)

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
        torrent_bytes, source_name = _download_torrent_bytes(effective_link)
        parsed_torrent = parse_torrent_info(torrent_bytes, source_name=source_name)
        selection_result = select_missing_episode_file_ids(parsed_torrent.files, selection_plan)
    except (SelectiveQueueError, httpx.HTTPError) as exc:
        if _should_require_app_side_torrent_fetch(effective_link):
            if not _can_qb_remote_fetch_local_url(effective_link, qb_base_url=qb_base_url):
                raise SelectiveQueueError(
                    "Could not fetch a valid torrent file from the local Jackett-style URL, "
                    "so the app did not hand it off to qBittorrent for remote fetching."
                ) from exc
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


def _dedupe_tracker_urls(tracker_urls: list[str]) -> list[str]:
    normalized_urls: list[str] = []
    seen_urls: set[str] = set()
    for raw_url in tracker_urls:
        candidate = str(raw_url or "").strip()
        key = candidate.casefold()
        if not candidate or key in seen_urls:
            continue
        seen_urls.add(key)
        normalized_urls.append(candidate)
    return normalized_urls


def _tracker_urls_from_magnet(link: str) -> list[str]:
    parsed = urlsplit(link)
    if parsed.scheme.casefold() != "magnet":
        return []
    return _dedupe_tracker_urls(parse_qs(parsed.query).get("tr", []))


def _inspect_same_hash_link(
    link: str,
    *,
    jackett_api_url: str | None = None,
    jackett_qb_url: str | None = None,
) -> tuple[str | None, list[str]]:
    magnet_info_hash = parse_magnet_info_hash(link)
    if magnet_info_hash:
        return magnet_info_hash, _tracker_urls_from_magnet(link)
    try:
        torrent_bytes, source_name = _download_torrent_bytes(
            _rewrite_jackett_download_link_for_app_fetch(
                link,
                app_base_url=jackett_api_url,
                qb_base_url=jackett_qb_url,
            )
        )
        parsed_torrent = parse_torrent_info(torrent_bytes, source_name=source_name)
    except (SelectiveQueueError, httpx.HTTPError):
        return None, []
    return parsed_torrent.info_hash, _dedupe_tracker_urls(parsed_torrent.tracker_urls)


def queue_grouped_search_results(
    *,
    qb_base_url: str,
    qb_username: str,
    qb_password: str,
    links: list[str],
    jackett_api_url: str | None = None,
    jackett_qb_url: str | None = None,
    info_hash: str | None,
    tracker_urls: list[str],
    category: str,
    save_path: str,
    paused: bool,
    sequential_download: bool,
    first_last_piece_prio: bool,
    rule: Rule | None,
) -> QueueResult:
    normalized_links = _dedupe_tracker_urls(links)
    if not normalized_links:
        raise SelectiveQueueError("No queueable result links were provided.")

    primary_result = queue_result_with_optional_file_selection(
        qb_base_url=qb_base_url,
        qb_username=qb_username,
        qb_password=qb_password,
        link=normalized_links[0],
        jackett_api_url=jackett_api_url,
        jackett_qb_url=jackett_qb_url,
        category=category,
        save_path=save_path,
        paused=paused,
        sequential_download=sequential_download,
        first_last_piece_prio=first_last_piece_prio,
        rule=rule,
    )

    effective_info_hash = str(info_hash or "").strip().casefold() or None
    merged_tracker_urls = list(_dedupe_tracker_urls(list(tracker_urls or [])))
    inspected_variant_count = 0
    for link in normalized_links:
        candidate_hash, candidate_trackers = _inspect_same_hash_link(
            link,
            jackett_api_url=jackett_api_url,
            jackett_qb_url=jackett_qb_url,
        )
        if candidate_hash:
            inspected_variant_count += 1
        if effective_info_hash is None and candidate_hash:
            effective_info_hash = candidate_hash
        if candidate_hash and effective_info_hash and candidate_hash != effective_info_hash:
            continue
        merged_tracker_urls = _dedupe_tracker_urls([*merged_tracker_urls, *candidate_trackers])

    added_tracker_count = 0
    if effective_info_hash and merged_tracker_urls:
        with QbittorrentClient(qb_base_url, qb_username, qb_password) as client:
            torrent = client.get_torrent(effective_info_hash)
            if torrent is not None:
                existing_tracker_urls = _dedupe_tracker_urls(
                    [str(item.get("url") or "") for item in client.get_torrent_trackers(effective_info_hash)]
                )
                existing_tracker_keys = {item.casefold() for item in existing_tracker_urls}
                missing_trackers = [
                    tracker_url
                    for tracker_url in merged_tracker_urls
                    if tracker_url.casefold() not in existing_tracker_keys
                ]
                if missing_trackers:
                    client.add_trackers(effective_info_hash, missing_trackers)
                    added_tracker_count = len(missing_trackers)

    message_parts = []
    if primary_result.message:
        message_parts.append(primary_result.message)
    if len(normalized_links) > 1:
        message_parts.append(
            f"Processed {len(normalized_links)} same-hash variants for tracker merge."
        )
    if added_tracker_count:
        message_parts.append(f"Added {added_tracker_count} missing trackers to the qB torrent.")
    elif len(normalized_links) > 1 and merged_tracker_urls:
        message_parts.append("No new trackers needed to be added to the qB torrent.")
    elif len(normalized_links) > 1 and inspected_variant_count == 0:
        message_parts.append("Additional variants could not be inspected for tracker metadata.")

    return QueueResult(
        message=" ".join(message_parts).strip(),
        selected_file_count=primary_result.selected_file_count,
        skipped_file_count=primary_result.skipped_file_count,
        deferred_file_selection=primary_result.deferred_file_selection,
        queued_via_torrent_file=primary_result.queued_via_torrent_file,
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
        raw_size = item.get("size")
        file_size_bytes = None
        if isinstance(raw_size, int):
            file_size_bytes = raw_size
        elif isinstance(raw_size, str):
            try:
                file_size_bytes = int(raw_size)
            except ValueError:
                file_size_bytes = None
        files.append(
            TorrentFileEntry(
                file_id=file_id,
                path=file_path,
                size_bytes=file_size_bytes,
            )
        )
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


def _resolve_local_jackett_redirect_magnet_link(link: str) -> str | None:
    current_link = str(link or "").strip()
    parsed = urlsplit(current_link)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None

    timeout = get_environment_settings().request_timeout
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _ in range(5):
                response = client.get(current_link)
                if not response.is_redirect:
                    return None
                location = str(response.headers.get("location") or "").strip()
                if not location:
                    return None
                if parse_magnet_info_hash(location):
                    return location
                next_link = urljoin(current_link, location)
                next_parsed = urlsplit(next_link)
                if next_parsed.scheme.casefold() not in {"http", "https"}:
                    return None
                current_link = next_link
    except httpx.HTTPError:
        return None
    return None


def _should_require_app_side_torrent_fetch(link: str) -> bool:
    parsed = urlsplit(str(link or "").strip())
    if parsed.scheme.casefold() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip()
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
    )


def _can_qb_remote_fetch_local_url(link: str, *, qb_base_url: str) -> bool:
    if not _should_require_app_side_torrent_fetch(link):
        return False
    parsed_qb = urlsplit(str(qb_base_url or "").strip())
    if parsed_qb.scheme.casefold() not in {"http", "https"}:
        return False
    qb_host = (parsed_qb.hostname or "").strip()
    if not qb_host:
        return False
    if qb_host.casefold() == "localhost":
        return True
    try:
        qb_address = ipaddress.ip_address(qb_host)
    except ValueError:
        return False
    return bool(qb_address.is_loopback)


def _rewrite_jackett_download_link_for_app_fetch(
    link: str,
    *,
    app_base_url: str | None,
    qb_base_url: str | None,
) -> str:
    cleaned_link = str(link or "").strip()
    if not cleaned_link:
        return cleaned_link
    cleaned_app_base = str(app_base_url or "").strip()
    cleaned_qb_base = str(qb_base_url or "").strip()
    if not cleaned_app_base or not cleaned_qb_base:
        return cleaned_link
    parsed_link = urlsplit(cleaned_link)
    if not parsed_link.path.startswith("/api/v2.0/indexers/") and "/dl/" not in parsed_link.path:
        return cleaned_link
    return _rewrite_base_url(
        cleaned_link,
        source_base=cleaned_qb_base,
        target_base=cleaned_app_base,
    )


def _rewrite_base_url(value: str, *, source_base: str, target_base: str) -> str:
    source = urlsplit(source_base.rstrip("/"))
    target = urlsplit(target_base.rstrip("/"))
    candidate = urlsplit(value)
    if not source.scheme or not source.netloc or not target.scheme or not target.netloc:
        return value
    if (
        candidate.scheme.casefold() != source.scheme.casefold()
        or not _hosts_match_for_rewrite(candidate.hostname, source.hostname)
        or _normalized_port(candidate) != _normalized_port(source)
    ):
        return value
    source_path = source.path.rstrip("/")
    candidate_path = candidate.path or ""
    if source_path:
        source_prefix = f"{source_path}/"
        if candidate_path != source_path and not candidate_path.startswith(source_prefix):
            return value
        suffix_path = candidate_path[len(source_path) :]
    else:
        suffix_path = candidate_path
    target_path = target.path.rstrip("/")
    rewritten_path = f"{target_path}{suffix_path}" if target_path else suffix_path
    return urlunsplit(
        (
            target.scheme,
            target.netloc,
            rewritten_path or "/",
            candidate.query,
            candidate.fragment,
        )
    )


def _hosts_match_for_rewrite(candidate_host: str | None, source_host: str | None) -> bool:
    candidate = str(candidate_host or "").strip().casefold()
    source = str(source_host or "").strip().casefold()
    if not candidate or not source:
        return False
    if candidate == source:
        return True
    return {candidate, source} <= {"localhost", "127.0.0.1"}


def _normalized_port(parsed: SplitResult) -> int | None:
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme.casefold() == "https":
        return 443
    if parsed.scheme.casefold() == "http":
        return 80
    return None


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
            file_length = raw_item.get(b"length")
            file_size_bytes = file_length if isinstance(file_length, int) else None
            files.append(
                TorrentFileEntry(
                    file_id=file_id,
                    path="/".join(cleaned_parts),
                    size_bytes=file_size_bytes,
                )
            )
        return files

    name_value = info.get(b"name.utf-8") or info.get(b"name")
    filename = _decode_torrent_text(name_value)
    if filename:
        file_length = info.get(b"length")
        file_size_bytes = file_length if isinstance(file_length, int) else None
        return [TorrentFileEntry(file_id=0, path=filename, size_bytes=file_size_bytes)]
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


def _file_path_matches_episode(
    path: str,
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    return _episode_file_match_rank(
        path,
        season_number=season_number,
        episode_number=episode_number,
    ) < 10


def _episode_file_match_rank(
    path: str,
    *,
    season_number: int,
    episode_number: int,
) -> int:
    normalized_path = PurePosixPath(str(path or "").strip())
    parts = list(normalized_path.parts)
    if not parts:
        return 10

    filename = parts[-1]
    filename_matches = _episode_matches_for_path(filename)
    if any(
        matched_season == season_number
        and start_episode <= episode_number <= end_episode
        for matched_season, start_episode, end_episode in filename_matches
    ):
        if any(
            matched_season == season_number
            and start_episode == episode_number
            and end_episode == episode_number
            for matched_season, start_episode, end_episode in filename_matches
        ):
            return 0
        return 1

    for parent_segment in reversed(parts[:-1]):
        parent_matches = _episode_matches_for_path(parent_segment)
        if any(
            matched_season == season_number
            and start_episode <= episode_number <= end_episode
            for matched_season, start_episode, end_episode in parent_matches
        ):
            return 5
    return 10


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
