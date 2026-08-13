from __future__ import annotations

import ntpath
import posixpath
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings, DownloadAccelerationJob, utcnow
from app.services.myjdownloader import MyJDownloaderClient
from app.services.qbittorrent import (
    JDOWNLOADER_FALLBACK_TAG,
    MANAGED_TORRENT_TAG,
    QbittorrentClient,
)
from app.services.real_debrid import RealDebridClient, RealDebridError
from app.services.selective_queue import _decode_bencode_value, parse_torrent_info
from app.services.settings_service import SettingsService

TERMINAL_STATES = frozenset({"completed", "skipped", "terminal_error"})
MAX_JOBS_PER_TICK = 5
ACTIVE_DOWNLOAD_STATES = frozenset(
    {"allocating", "checkingdl", "downloading", "forceddl", "metadl", "queueddl", "stalleddl"}
)


def sanitize_error(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return message[:1000] or exc.__class__.__name__


def tracker_free_magnet(info_hash: str, name: str = "") -> str:
    magnet = f"magnet:?xt=urn:btih:{info_hash.lower()}"
    if name.strip():
        magnet += f"&dn={quote(name.strip())}"
    return magnet


def metainfo_is_sensitive(torrent_bytes: bytes) -> bool:
    try:
        decoded, end = _decode_bencode_value(torrent_bytes, 0)
    except Exception:
        return True
    if end != len(torrent_bytes) or not isinstance(decoded, dict):
        return True
    info = decoded.get(b"info")
    if isinstance(info, dict) and int(info.get(b"private") or 0) == 1:
        return True
    parsed = parse_torrent_info(torrent_bytes)
    return any(_tracker_url_is_sensitive(url) for url in parsed.tracker_urls)


def _tracker_url_is_sensitive(url: str) -> bool:
    raw = str(url or "")
    lowered = raw.casefold()
    if any(marker in lowered for marker in ("passkey", "apikey", "authkey", "token=")):
        return True
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return True
    if parsed.username or parsed.password:
        return True
    sensitive_keys = {"key", "token", "auth", "pass", "password", "uid"}
    if any(key.casefold() in sensitive_keys for key, _value in parse_qsl(parsed.query)):
        return True
    return any(
        len(segment) >= 24 and segment.isalnum()
        for segment in parsed.path.split("/")
    )


def safe_relative_path(value: object) -> str | None:
    raw = str(value or "").replace("\\", "/").lstrip("/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return "/".join(path.parts)


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def match_selected_files(
    qb_files: list[dict[str, object]], rd_files: list[dict[str, object]]
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    used_ids: set[int] = set()
    for qb_file in qb_files:
        if _as_int(qb_file.get("priority") or 0) <= 0:
            continue
        qb_path = safe_relative_path(qb_file.get("name"))
        qb_size = _as_int(qb_file.get("size") or 0)
        if not qb_path:
            continue
        candidates: list[tuple[int, dict[str, object], str]] = []
        for rd_file in rd_files:
            rd_id = _as_int(rd_file.get("id") or 0)
            rd_path = safe_relative_path(rd_file.get("path"))
            rd_size = _as_int(rd_file.get("bytes") or 0)
            if not rd_id or rd_id in used_ids or not rd_path or rd_size != qb_size:
                continue
            if rd_path.casefold() == qb_path.casefold() or rd_path.casefold().endswith(
                f"/{qb_path.casefold()}"
            ) or qb_path.casefold().endswith(f"/{rd_path.casefold()}"):
                candidates.append((rd_id, rd_file, rd_path))
        if len(candidates) != 1:
            continue
        rd_id, _rd_file, rd_path = candidates[0]
        used_ids.add(rd_id)
        selected.append(
            {
                "qb_id": _as_int(qb_file.get("index") or 0),
                "rd_id": rd_id,
                "path": qb_path,
                "provider_path": rd_path,
                "size": qb_size,
            }
        )
    return selected


class DownloadAccelerationService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings,
        *,
        qb_client: QbittorrentClient,
        real_debrid_client: RealDebridClient,
        myjd_client: MyJDownloaderClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.qb = qb_client
        self.rd = real_debrid_client
        self.myjd = myjd_client or MyJDownloaderClient()

    def run_once(self) -> list[DownloadAccelerationJob]:
        discovered = self.discover_managed_torrents()
        jobs = list(
            self.session.scalars(
                select(DownloadAccelerationJob).where(
                    DownloadAccelerationJob.source_kind == "qbittorrent"
                )
            )
        )
        ready_jobs: list[tuple[tuple[int, int], DownloadAccelerationJob, dict[str, object]]] = []
        for job in jobs:
            if job.state in TERMINAL_STATES:
                continue
            next_retry = job.next_retry_at
            if next_retry is not None:
                if next_retry.tzinfo is None:
                    next_retry = next_retry.replace(tzinfo=UTC)
                if next_retry > datetime.now(UTC):
                    continue
            torrent = discovered.get(str(job.info_hash or "").casefold())
            if torrent is None:
                continue
            ready_jobs.append((self._job_priority(torrent), job, torrent))

        ready_jobs.sort(key=lambda item: item[0])
        for _priority, job, torrent in ready_jobs[:MAX_JOBS_PER_TICK]:
            try:
                self._advance(job, torrent)
            except Exception as exc:
                self.session.rollback()
                current = self.session.get(DownloadAccelerationJob, job.id)
                if current is not None:
                    current.retry_count += 1
                    current.last_error = sanitize_error(exc)
                    current.next_retry_at = utcnow() + timedelta(
                        seconds=min(900, 15 * (2 ** min(current.retry_count, 6)))
                    )
                    current.state = "retry_wait"
                    self.session.add(current)
                    self.session.commit()
        return jobs

    @staticmethod
    def _job_priority(torrent: dict[str, object]) -> tuple[int, int]:
        state = str(torrent.get("state") or "").strip().casefold()
        activity_rank = 0 if state in ACTIVE_DOWNLOAD_STATES else 1
        return activity_rank, -_as_int(torrent.get("added_on") or 0)

    def discover_managed_torrents(self) -> dict[str, dict[str, object]]:
        torrents = self.qb.get_torrents(tag=MANAGED_TORRENT_TAG)
        result: dict[str, dict[str, object]] = {}
        existing = {
            str(job.info_hash or "").casefold(): job
            for job in self.session.scalars(
                select(DownloadAccelerationJob).where(
                    DownloadAccelerationJob.info_hash.is_not(None)
                )
            )
        }
        now = utcnow()
        wait_seconds = SettingsService.resolve_real_debrid(
            self.settings
        ).metadata_wait_seconds
        for torrent in torrents:
            info_hash = str(torrent.get("hash") or "").strip().casefold()
            if not info_hash:
                continue
            result[info_hash] = torrent
            torrent_name = str(torrent.get("name") or "").strip()
            if info_hash not in existing:
                job = DownloadAccelerationJob(
                    identity_key=f"qb:{info_hash}",
                    info_hash=info_hash,
                    state="discovered",
                    metadata_deadline_at=now + timedelta(seconds=wait_seconds),
                    torrent_name=torrent_name,
                )
                self.session.add(job)
                existing[info_hash] = job
            else:
                job = existing[info_hash]
                if torrent_name and job.torrent_name != torrent_name:
                    job.torrent_name = torrent_name
                self.session.add(job)
        self.session.commit()
        return result

    def _advance(self, job: DownloadAccelerationJob, torrent: dict[str, object]) -> None:
        if _as_float(torrent.get("progress") or 0) >= 1:
            job.state = "completed"
            job.completed_at = utcnow()
            job.last_error = ""
            self._save(job)
            return
        qb_files = self.qb.get_torrent_files(str(job.info_hash))
        has_metadata = bool(qb_files)
        if not job.provider_torrent_id:
            response = self._submit_to_real_debrid(job, torrent, has_metadata)
            job.provider_torrent_id = str(response.get("id") or "").strip() or None
            if not job.provider_torrent_id:
                raise RuntimeError("Real-Debrid did not return a torrent ID.")
            job.state = "provider_submitted"
            self._save(job)

        provider = self.rd.get_torrent(str(job.provider_torrent_id))
        status = str(provider.get("status") or "").strip().casefold()
        rd_files = _dict_items(provider.get("files", []))
        if status == "waiting_files_selection":
            selected = match_selected_files(qb_files, rd_files) if has_metadata else []
            if not selected and has_metadata:
                raise RuntimeError("Real-Debrid files could not be matched safely to qBittorrent.")
            if selected:
                self.rd.select_files(
                    str(job.provider_torrent_id),
                    [_as_int(item["rd_id"]) for item in selected],
                )
                job.selected_files = selected
                job.state = "provider_downloading"
                self._save(job)
                return
        if status == "downloaded":
            if not has_metadata:
                if self._metadata_deadline_passed(job):
                    self._fallback_to_myjd(job, torrent, provider)
                else:
                    job.state = "metadata_wait"
                    job.last_error = ""
                    self._save(job)
                return
            self._attach_webseed(job, qb_files, provider)
            return
        if status in {"magnet_error", "error", "virus", "dead"}:
            job.state = "terminal_error"
            job.last_error = f"Real-Debrid torrent entered terminal state {status}."
            self._save(job)
            return
        if not has_metadata and self._metadata_deadline_passed(job):
            links = _string_items(provider.get("links", []))
            if links:
                self._fallback_to_myjd(job, torrent, provider)
                return
        job.state = "metadata_wait" if not has_metadata else "provider_downloading"
        job.last_error = ""
        self._save(job)

    def _submit_to_real_debrid(
        self,
        job: DownloadAccelerationJob,
        torrent: dict[str, object],
        has_metadata: bool,
    ) -> dict[str, Any]:
        info_hash = str(job.info_hash or "")
        name = str(torrent.get("name") or "")
        if not has_metadata:
            return self.rd.add_magnet(tracker_free_magnet(info_hash, name))
        metainfo = self.qb.export_torrent(info_hash)
        if metainfo_is_sensitive(metainfo):
            return self.rd.add_magnet(tracker_free_magnet(info_hash, name))
        try:
            return self.rd.add_torrent(metainfo, filename=f"{info_hash}.torrent")
        except RealDebridError as exc:
            if "torrent_file_invalid" not in str(exc).casefold():
                raise
            return self.rd.add_magnet(tracker_free_magnet(info_hash, name))

    def _attach_webseed(
        self,
        job: DownloadAccelerationJob,
        qb_files: list[dict[str, object]],
        provider: dict[str, object],
    ) -> None:
        rd_files = _dict_items(provider.get("files", []))
        selected = list(job.selected_files or match_selected_files(qb_files, rd_files))
        provider_selected = [
            item for item in rd_files if _as_int(item.get("selected") or 0) == 1
        ]
        links = _string_items(provider.get("links", []))
        link_index_by_id = {
            _as_int(item.get("id") or 0): index for index, item in enumerate(provider_selected)
        }
        mappings: list[dict[str, object]] = []
        for item in selected:
            link_index = link_index_by_id.get(_as_int(item.get("rd_id") or 0))
            if link_index is None or link_index >= len(links):
                continue
            mappings.append({**item, "link_index": link_index})
        if len(mappings) != len(selected) or not mappings:
            raise RuntimeError("Real-Debrid download links did not match the selected torrent files.")
        if not job.webseed_token:
            job.webseed_token = secrets.token_urlsafe(32)
        base_url = SettingsService.resolve_real_debrid(self.settings).webseed_base_url.rstrip("/")
        webseed_path = ""
        if len(qb_files) == 1 and len(mappings) == 1:
            webseed_path = quote(str(mappings[0]["path"]), safe="/")
        webseed_url = f"{base_url}/webseeds/real-debrid/{job.webseed_token}/{webseed_path}"
        job.selected_files = selected
        job.webseed_files = mappings
        job.app_webseed_urls = [webseed_url]
        job.last_error = ""
        self._save(job)
        if webseed_url not in self.qb.get_webseeds(str(job.info_hash)):
            self.qb.add_webseeds(str(job.info_hash), [webseed_url])
        job.state = "webseed_attached"
        self._save(job)

    def _fallback_to_myjd(
        self,
        job: DownloadAccelerationJob,
        torrent: dict[str, object],
        provider: dict[str, object],
    ) -> None:
        if job.myjd_job_ids:
            job.state = "fallback_progress"
            self._save(job)
            return
        config = SettingsService.resolve_myjd(self.settings)
        if not (config.enabled and config.is_configured):
            job.state = "metadata_unavailable"
            job.last_error = "Torrent metadata is unavailable and MyJDownloader is not configured."
            self._save(job)
            return
        restricted = _string_items(provider.get("links", []))
        unrestricted = [
            str(self.rd.unrestrict_link(link).get("download") or "").strip()
            for link in restricted
        ]
        unrestricted = [link for link in unrestricted if link]
        if not unrestricted:
            job.state = "metadata_unavailable"
            job.last_error = "Real-Debrid did not expose downloadable files for fallback."
            self._save(job)
            return
        groups = _fallback_link_groups(provider, unrestricted)
        root_destination = str(torrent.get("save_path") or "")
        package_root = str(torrent.get("name") or job.info_hash or "Real-Debrid")
        job_ids: list[str] = []
        for parent, group_links in groups:
            destination = _join_destination(root_destination, parent)
            package_name = PurePosixPath(parent).name if parent else package_root
            job_ids.append(
                self.myjd.add_links(
                    email=str(config.email),
                    password=str(config.password),
                    device_id=str(config.device_id),
                    links=group_links,
                    package_name=package_name,
                    destination_folder=destination,
                    autostart=True,
                )
            )
        job.myjd_job_ids = job_ids
        job.state = "fallback_progress"
        job.last_error = ""
        self._save(job)
        self.qb.stop_torrents(str(job.info_hash))
        self.qb.add_tags(str(job.info_hash), [JDOWNLOADER_FALLBACK_TAG])

    @staticmethod
    def _metadata_deadline_passed(job: DownloadAccelerationJob) -> bool:
        deadline = job.metadata_deadline_at
        if deadline is None:
            return False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return deadline <= datetime.now(UTC)

    def _save(self, job: DownloadAccelerationJob) -> None:
        job.next_retry_at = None
        self.session.add(job)
        self.session.commit()


def _fallback_link_groups(
    provider: dict[str, object], unrestricted: list[str]
) -> list[tuple[str, list[str]]]:
    files = [
        item
        for item in _dict_items(provider.get("files", []))
        if _as_int(item.get("selected") or 0) == 1
    ]
    grouped: dict[str, list[str]] = {}
    for index, link in enumerate(unrestricted):
        path = safe_relative_path(files[index].get("path")) if index < len(files) else None
        parent = str(PurePosixPath(path).parent) if path else ""
        if parent == ".":
            parent = ""
        grouped.setdefault(parent, []).append(link)
    return sorted(grouped.items(), key=lambda item: item[0].casefold())


def _join_destination(root: str, relative_parent: str) -> str:
    if not relative_parent:
        return root
    parts = list(PurePosixPath(relative_parent).parts)
    if "\\" in root or (len(root) >= 2 and root[1] == ":"):
        return ntpath.join(root, *parts)
    return posixpath.join(root, *parts)
