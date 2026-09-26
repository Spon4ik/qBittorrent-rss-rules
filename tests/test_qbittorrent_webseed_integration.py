from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from urllib.parse import quote

import pytest

from app.services.qbittorrent import QbittorrentClient

QB_URL = os.getenv("QB_WEBSEED_TEST_URL", "").strip()
QB_USERNAME = os.getenv("QB_WEBSEED_TEST_USERNAME", "").strip()
QB_PASSWORD = os.getenv("QB_WEBSEED_TEST_PASSWORD", "")
QB_SAVE_PATH = os.getenv("QB_WEBSEED_TEST_SAVE_PATH", "").strip()


def _connection() -> tuple[str, str, str, str]:
    return QB_URL, QB_USERNAME, QB_PASSWORD, QB_SAVE_PATH


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, dict):
        entries = sorted(value.items())
        return b"d" + b"".join(
            _bencode(key) + _bencode(item) for key, item in entries
        ) + b"e"
    raise TypeError(f"Unsupported bencode value: {type(value).__name__}")


def _test_torrent() -> tuple[bytes, str]:
    payload = b"test"
    info = {
        b"length": len(payload),
        b"name": b"webseed-api-integration.bin",
        b"piece length": 16384,
        b"pieces": hashlib.sha1(payload).digest(),
    }
    info_bytes = _bencode(info)
    torrent_bytes = _bencode({b"info": info})
    return torrent_bytes, hashlib.sha1(info_bytes).hexdigest()


def _wait_for_torrent(
    get_torrent: Callable[[str], dict[str, object] | None], info_hash: str
) -> dict[str, object] | None:
    deadline = time.monotonic() + 10.0
    while True:
        torrent = get_torrent(info_hash)
        if torrent is not None:
            return torrent
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.25, remaining))


def test_wait_for_torrent_retries_until_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[dict[str, object] | None] = [None, {"hash": "expected"}]
    calls: list[str] = []

    def get_torrent(info_hash: str) -> dict[str, object] | None:
        calls.append(info_hash)
        return responses.pop(0)

    monkeypatch.setattr(time, "sleep", lambda _: None)

    assert _wait_for_torrent(get_torrent, "expected") == {"hash": "expected"}
    assert calls == ["expected", "expected"]


def test_qbittorrent_accepts_and_reads_back_encoded_unicode_webseed() -> None:
    base_url, username, password, save_path = _connection()
    if not (base_url and username and password):
        if os.getenv("QB_WEBSEED_TEST_REQUIRED", "").strip().casefold() == "true":
            pytest.fail("The required real-qBittorrent integration service is not configured")
        pytest.skip("real qBittorrent Web API integration credentials are not configured")
    torrent_bytes, info_hash = _test_torrent()
    filename = "codex-webseed-api-integration.torrent"
    url = (
        "http://127.0.0.1:8000/webseeds/integration-token/"
        f"{quote('Звездные войны Последние джедаи.mkv', safe='/')}"
    )
    client = QbittorrentClient(base_url, username, password, timeout=15)
    torrent_added = False
    try:
        client.add_torrent_file(
            torrent_bytes=torrent_bytes,
            filename=filename,
            save_path=save_path,
            paused=True,
            tags="codex-webseed-api-integration",
        )
        torrent_added = True
        assert _wait_for_torrent(client.get_torrent, info_hash) is not None, (
            f"qBittorrent accepted torrent {info_hash} but did not expose it "
            "through the torrent info API within 10 seconds"
        )

        # Exercise qBittorrent's real POST parser and strict URL validator.
        client.add_webseeds(info_hash, [url])
        assert client.get_webseeds(info_hash) == [url]

        # The removal endpoint uses the same URL parser and must round-trip too.
        client.remove_webseeds(info_hash, [url])
        assert client.get_webseeds(info_hash) == []
    finally:
        if torrent_added:
            client.delete_torrents(info_hash, delete_files=True)
        client.close()
