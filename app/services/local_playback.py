from __future__ import annotations

import mimetypes
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Protocol

from app.services.selective_queue import VIDEO_FILE_EXTENSIONS, text_matches_episode

LOCAL_PLAYBACK_TOKEN_TTL_SECONDS = 86400.0
_LOCAL_PLAYBACK_LOCK = threading.Lock()
_LOCAL_PLAYBACK_TOKENS: dict[str, tuple[float, LocalPlaybackFile]] = {}


class QbPlaybackClient(Protocol):
    def get_torrent(self, info_hash: str) -> dict[str, object] | None: ...
    def get_torrents(self, *, hashes: str | None = None) -> list[dict[str, object]]: ...
    def get_torrent_files(self, info_hash: str) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class LocalPlaybackFile:
    file_path: Path
    filename: str
    media_type: str | None


@dataclass(frozen=True, slots=True)
class QbLocalPlaybackMatch:
    info_hash: str
    torrent_name: str
    playback_file: LocalPlaybackFile


def reset_local_playback_tokens() -> None:
    with _LOCAL_PLAYBACK_LOCK:
        _LOCAL_PLAYBACK_TOKENS.clear()


def register_local_playback_file(playback_file: LocalPlaybackFile) -> str:
    _cleanup_expired_local_playback_tokens()
    token = uuid.uuid4().hex
    with _LOCAL_PLAYBACK_LOCK:
        _LOCAL_PLAYBACK_TOKENS[token] = (monotonic(), playback_file)
    return token


def resolve_local_playback_token(token: str) -> LocalPlaybackFile | None:
    cleaned_token = str(token or "").strip()
    if not cleaned_token:
        return None
    _cleanup_expired_local_playback_tokens()
    with _LOCAL_PLAYBACK_LOCK:
        cached_entry = _LOCAL_PLAYBACK_TOKENS.get(cleaned_token)
        if cached_entry is None:
            return None
        _, playback_file = cached_entry
    if not playback_file.file_path.is_file():
        with _LOCAL_PLAYBACK_LOCK:
            _LOCAL_PLAYBACK_TOKENS.pop(cleaned_token, None)
        return None
    return playback_file


def resolve_qb_local_playback_file(
    client: QbPlaybackClient,
    *,
    info_hash: str,
    file_idx: int | None = None,
    filename_hint: str | None = None,
) -> LocalPlaybackFile | None:
    cleaned_hash = str(info_hash or "").strip().casefold()
    if not cleaned_hash:
        return None

    torrent = client.get_torrent(cleaned_hash)
    if torrent is None or not _torrent_is_complete(torrent):
        return None

    torrent_files = client.get_torrent_files(cleaned_hash)
    matched_file = _match_qb_file_entry(
        torrent_files,
        file_idx=file_idx,
        filename_hint=filename_hint,
    )
    if matched_file is None or not _qb_file_is_complete(matched_file):
        return None

    resolved_path = _resolve_qb_file_path(torrent, matched_file)
    if resolved_path is None or not resolved_path.is_file():
        return None

    return LocalPlaybackFile(
        file_path=resolved_path,
        filename=resolved_path.name,
        media_type=_guess_media_type(resolved_path),
    )


def find_qb_local_playback_matches(
    client: QbPlaybackClient,
    *,
    imdb_id: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> list[QbLocalPlaybackMatch]:
    cleaned_imdb_id = str(imdb_id or "").strip().casefold()
    if not cleaned_imdb_id:
        return []

    matches: list[QbLocalPlaybackMatch] = []
    seen_hashes: set[str] = set()
    for torrent in client.get_torrents():
        if not _torrent_is_complete(torrent):
            continue
        if not _torrent_matches_imdb_id(torrent, cleaned_imdb_id):
            continue
        info_hash = str(torrent.get("hash") or "").strip().casefold()
        if not info_hash or info_hash in seen_hashes:
            continue
        torrent_files = client.get_torrent_files(info_hash)
        matched_file = _match_qb_library_file_entry(
            torrent_files,
            season_number=season_number,
            episode_number=episode_number,
        )
        if matched_file is None or not _qb_file_is_complete(matched_file):
            continue
        resolved_path = _resolve_qb_file_path(torrent, matched_file)
        if resolved_path is None or not resolved_path.is_file():
            continue
        seen_hashes.add(info_hash)
        matches.append(
            QbLocalPlaybackMatch(
                info_hash=info_hash,
                torrent_name=str(torrent.get("name") or "").strip() or resolved_path.name,
                playback_file=LocalPlaybackFile(
                    file_path=resolved_path,
                    filename=resolved_path.name,
                    media_type=_guess_media_type(resolved_path),
                ),
            )
        )
    return matches


def _cleanup_expired_local_playback_tokens() -> None:
    cutoff = monotonic() - LOCAL_PLAYBACK_TOKEN_TTL_SECONDS
    with _LOCAL_PLAYBACK_LOCK:
        expired_tokens = [
            token
            for token, (created_at, playback_file) in _LOCAL_PLAYBACK_TOKENS.items()
            if created_at < cutoff or not playback_file.file_path.exists()
        ]
        for token in expired_tokens:
            _LOCAL_PLAYBACK_TOKENS.pop(token, None)


def _coerce_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value or "").strip() or 0)
    except ValueError:
        return 0.0


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _torrent_is_complete(torrent: dict[str, object]) -> bool:
    progress = _coerce_float(torrent.get("progress"))
    if progress >= 0.999:
        return True
    completed = _coerce_float(torrent.get("completed"))
    size = _coerce_float(torrent.get("size")) or _coerce_float(torrent.get("total_size"))
    return completed > 0 and size > 0 and completed >= size


def _qb_file_is_complete(file_entry: dict[str, object]) -> bool:
    return (
        _coerce_bool(file_entry.get("is_seed"))
        or _coerce_float(file_entry.get("progress")) >= 0.999
    )


def _match_qb_file_entry(
    torrent_files: list[dict[str, object]],
    *,
    file_idx: int | None,
    filename_hint: str | None,
) -> dict[str, object] | None:
    cleaned_filename_hint = str(filename_hint or "").strip().casefold()
    video_files = [item for item in torrent_files if _is_video_path(str(item.get("name") or ""))]
    if not video_files:
        return None

    if file_idx is not None:
        for item in video_files:
            if _coerce_int(item.get("index")) == int(file_idx):
                return item

    if cleaned_filename_hint:
        for item in video_files:
            raw_name = str(item.get("name") or "").strip()
            if not raw_name:
                continue
            if raw_name.casefold() == cleaned_filename_hint:
                return item
            if (
                PurePosixPath(raw_name).name.casefold()
                == PurePosixPath(cleaned_filename_hint).name.casefold()
            ):
                return item

    if len(video_files) == 1:
        return video_files[0]
    return None


def _match_qb_library_file_entry(
    torrent_files: list[dict[str, object]],
    *,
    season_number: int | None,
    episode_number: int | None,
) -> dict[str, object] | None:
    video_files = [item for item in torrent_files if _is_video_path(str(item.get("name") or ""))]
    if not video_files:
        return None

    if season_number is not None and episode_number is not None:
        matching_files = [
            item
            for item in video_files
            if _qb_file_matches_requested_episode(
                str(item.get("name") or ""),
                season_number=season_number,
                episode_number=episode_number,
            )
        ]
        if not matching_files:
            return None
        matching_files.sort(
            key=lambda item: (
                _qb_file_episode_match_rank(
                    str(item.get("name") or ""),
                    season_number=season_number,
                    episode_number=episode_number,
                ),
                _coerce_int(item.get("index"))
                if _coerce_int(item.get("index")) is not None
                else 10_000,
                str(item.get("name") or "").casefold(),
            )
        )
        return matching_files[0]

    ranked_video_files = sorted(
        video_files,
        key=lambda item: (
            _coerce_float(item.get("size")),
            str(item.get("name") or "").casefold(),
        ),
        reverse=True,
    )
    return ranked_video_files[0]


def _resolve_qb_file_path(
    torrent: dict[str, object],
    file_entry: dict[str, object],
) -> Path | None:
    raw_name = str(file_entry.get("name") or "").strip()
    if not raw_name:
        content_path = _coerce_path(torrent.get("content_path"))
        return content_path if content_path and content_path.is_file() else None

    relative_path = _relative_path_from_qb_name(raw_name)
    candidate_paths: list[Path] = []

    save_path = _coerce_path(torrent.get("save_path"))
    if save_path is not None:
        candidate_paths.append(save_path / relative_path)

    root_path = _coerce_path(torrent.get("root_path"))
    if root_path is not None:
        stripped_relative_path = _strip_leading_root_component(relative_path, root_path.name)
        candidate_paths.append(root_path / stripped_relative_path)

    content_path = _coerce_path(torrent.get("content_path"))
    if content_path is not None:
        if content_path.is_file():
            candidate_paths.append(content_path)
        else:
            stripped_relative_path = _strip_leading_root_component(relative_path, content_path.name)
            candidate_paths.append(content_path / stripped_relative_path)

    download_path = _coerce_path(torrent.get("download_path"))
    if download_path is not None:
        candidate_paths.append(download_path / relative_path)

    seen_paths: set[str] = set()
    for candidate in candidate_paths:
        normalized = str(candidate).casefold()
        if not normalized or normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        if candidate.is_file():
            return candidate
    return None


def _torrent_matches_imdb_id(torrent: dict[str, object], imdb_id: str) -> bool:
    token = f"imdbid-{imdb_id}"
    candidate_fields = (
        torrent.get("category"),
        torrent.get("save_path"),
        torrent.get("content_path"),
        torrent.get("name"),
        torrent.get("tags"),
    )
    for value in candidate_fields:
        if token in str(value or "").casefold():
            return True
    return False


def _coerce_path(value: object) -> Path | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return Path(cleaned)


def _relative_path_from_qb_name(value: str) -> Path:
    pure_path = PurePosixPath(str(value or "").strip())
    return Path(*pure_path.parts)


def _strip_leading_root_component(relative_path: Path, root_name: str) -> Path:
    parts = relative_path.parts
    if len(parts) > 1 and parts[0].casefold() == str(root_name or "").strip().casefold():
        return Path(*parts[1:])
    return relative_path


def _qb_file_matches_requested_episode(
    path: str,
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    return _qb_file_episode_match_rank(
        path,
        season_number=season_number,
        episode_number=episode_number,
    ) < 10


def _qb_file_episode_match_rank(
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
    if text_matches_episode(
        filename,
        season_number=season_number,
        episode_number=episode_number,
    ):
        return 0

    for parent_segment in reversed(parts[:-1]):
        if text_matches_episode(
            parent_segment,
            season_number=season_number,
            episode_number=episode_number,
        ):
            return 5
    return 10


def _is_video_path(value: str) -> bool:
    suffix = PurePosixPath(str(value or "").strip()).suffix.casefold()
    return suffix in VIDEO_FILE_EXTENSIONS


def _guess_media_type(file_path: Path) -> str | None:
    guessed_type, _ = mimetypes.guess_type(str(file_path))
    if guessed_type:
        return guessed_type
    if file_path.suffix.casefold() == ".mkv":
        return "video/x-matroska"
    return None
