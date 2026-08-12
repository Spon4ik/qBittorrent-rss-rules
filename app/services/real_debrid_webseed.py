from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DownloadAccelerationJob
from app.services.download_acceleration import safe_relative_path
from app.services.real_debrid import RealDebridClient

RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


class WebseedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WebseedResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes


def _as_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def resolve_webseed_file(
    session: Session, *, token: str, relative_path: str
) -> tuple[DownloadAccelerationJob, dict[str, object]]:
    job = session.scalar(
        select(DownloadAccelerationJob).where(
            DownloadAccelerationJob.webseed_token == token
        )
    )
    if job is None or not job.provider_torrent_id:
        raise WebseedError("Unknown web-seed token.")
    mappings = list(job.webseed_files or [])
    requested = safe_relative_path(relative_path)
    if requested is None and not str(relative_path or "").strip() and len(mappings) == 1:
        return job, mappings[0]
    if requested is None:
        raise WebseedError("Invalid web-seed path.")
    matches = [
        item
        for item in mappings
        if safe_relative_path(item.get("path")) == requested
        or safe_relative_path(item.get("provider_path")) == requested
    ]
    if len(matches) != 1:
        raise WebseedError("Unknown web-seed path.")
    return job, matches[0]


def fetch_webseed_file(
    session: Session,
    *,
    token: str,
    relative_path: str,
    range_header: str | None,
    head_only: bool,
    real_debrid_client: RealDebridClient,
    transport: httpx.BaseTransport | None = None,
) -> WebseedResponse:
    job, mapping = resolve_webseed_file(
        session, token=token, relative_path=relative_path
    )
    provider = real_debrid_client.get_torrent(str(job.provider_torrent_id))
    links = [str(item).strip() for item in provider.get("links", []) if str(item).strip()]
    link_index = _as_int(mapping.get("link_index") or 0)
    if link_index >= len(links):
        raise WebseedError("Real-Debrid file link is no longer available.")
    unrestricted = real_debrid_client.unrestrict_link(links[link_index])
    download_url = str(unrestricted.get("download") or "").strip()
    if not download_url:
        raise WebseedError("Real-Debrid did not return a download URL.")
    requested_range = _parse_range(range_header, _as_int(mapping.get("size") or 0))
    request_headers = {}
    if requested_range is not None:
        request_headers["Range"] = f"bytes={requested_range[0]}-{requested_range[1]}"
        request_headers["Accept-Encoding"] = "identity"
    with httpx.Client(follow_redirects=True, timeout=60.0, transport=transport) as client:
        with client.stream(
            "HEAD" if head_only else "GET", download_url, headers=request_headers
        ) as response:
            response.raise_for_status()
            response_status = response.status_code
            response_headers = dict(response.headers)
            content = _read_response_content(
                response,
                requested_range=requested_range,
                head_only=head_only,
            )
    size = _as_int(mapping.get("size") or 0)
    status_code = response_status
    if requested_range is not None and response_status == 200:
        status_code = 206
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": response_headers.get("content-type", "application/octet-stream"),
    }
    if requested_range is not None:
        start, end = requested_range
        headers["Content-Range"] = response_headers.get(
            "content-range", f"bytes {start}-{end}/{size}"
        )
        headers["Content-Length"] = str(end - start + 1)
        status_code = 206
    else:
        headers["Content-Length"] = str(size or len(content))
    return WebseedResponse(status_code=status_code, headers=headers, content=content)


def _read_response_content(
    response: httpx.Response,
    *,
    requested_range: tuple[int, int] | None,
    head_only: bool,
) -> bytes:
    if head_only:
        return b""
    if requested_range is None:
        return response.read()
    start, end = requested_range
    read_limit = end - start + 1 if response.status_code == 206 else end + 1
    buffered = bytearray()
    for chunk in response.iter_bytes():
        remaining = read_limit - len(buffered)
        if remaining <= 0:
            break
        buffered.extend(chunk[:remaining])
        if len(buffered) >= read_limit:
            break
    if len(buffered) != read_limit:
        raise WebseedError("Real-Debrid returned fewer bytes than the requested range.")
    return bytes(buffered if response.status_code == 206 else buffered[start : end + 1])


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    match = RANGE_RE.fullmatch(value.strip())
    if match is None or size <= 0:
        raise WebseedError("Only one bounded byte range is supported.")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else size - 1
    if start < 0 or end < start or end >= size:
        raise WebseedError("Requested byte range is outside the file.")
    return start, end
