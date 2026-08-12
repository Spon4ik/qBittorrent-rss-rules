from __future__ import annotations

import httpx
import pytest

from app.models import DownloadAccelerationJob
from app.services.real_debrid_webseed import WebseedError, fetch_webseed_file


class FakeRd:
    def get_torrent(self, torrent_id):
        assert torrent_id == "rd-1"
        return {"links": ["restricted"]}

    def unrestrict_link(self, link):
        assert link == "restricted"
        return {"download": "https://cdn.test/file"}


def _job(db_session):
    job = DownloadAccelerationJob(
        identity_key="qb:abc",
        info_hash="a" * 40,
        provider_torrent_id="rd-1",
        webseed_token="opaque-token",
        webseed_files=[
            {
                "path": "folder/file.bin",
                "provider_path": "root/folder/file.bin",
                "size": 10,
                "link_index": 0,
            }
        ],
    )
    db_session.add(job)
    db_session.commit()


def test_webseed_forwards_bounded_range(db_session) -> None:
    _job(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=2-5"
        return httpx.Response(206, content=b"2345", headers={"Content-Range": "bytes 2-5/10"})

    result = fetch_webseed_file(
        db_session,
        token="opaque-token",
        relative_path="folder/file.bin",
        range_header="bytes=2-5",
        head_only=False,
        real_debrid_client=FakeRd(),
        transport=httpx.MockTransport(handler),
    )
    assert result.status_code == 206
    assert result.content == b"2345"
    assert result.headers["Content-Length"] == "4"


def test_webseed_stops_after_range_when_provider_streams_the_rest_of_file(db_session) -> None:
    _job(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=2-5"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            206,
            content=b"23456789",
            headers={"Content-Range": "bytes 2-5/10", "Content-Length": "10"},
        )

    result = fetch_webseed_file(
        db_session,
        token="opaque-token",
        relative_path="folder/file.bin",
        range_header="bytes=2-5",
        head_only=False,
        real_debrid_client=FakeRd(),
        transport=httpx.MockTransport(handler),
    )

    assert result.content == b"2345"
    assert result.headers["Content-Length"] == "4"


def test_webseed_rejects_traversal_and_multi_range(db_session) -> None:
    _job(db_session)
    with pytest.raises(WebseedError):
        fetch_webseed_file(
            db_session,
            token="opaque-token",
            relative_path="../file.bin",
            range_header=None,
            head_only=False,
            real_debrid_client=FakeRd(),
        )
    with pytest.raises(WebseedError):
        fetch_webseed_file(
            db_session,
            token="opaque-token",
            relative_path="folder/file.bin",
            range_header="bytes=0-1,3-4",
            head_only=False,
            real_debrid_client=FakeRd(),
        )


def test_single_file_webseed_accepts_token_root_for_legacy_sources(db_session) -> None:
    _job(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, content=b"0", headers={"Content-Range": "bytes 0-0/10"})

    result = fetch_webseed_file(
        db_session,
        token="opaque-token",
        relative_path="",
        range_header="bytes=0-0",
        head_only=False,
        real_debrid_client=FakeRd(),
        transport=httpx.MockTransport(handler),
    )

    assert result.status_code == 206
    assert result.content == b"0"
