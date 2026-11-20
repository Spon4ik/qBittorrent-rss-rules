from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote

import pytest

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, Rule
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
        return b"d" + b"".join(_bencode(key) + _bencode(item) for key, item in entries) + b"e"
    raise TypeError(f"Unsupported bencode value: {type(value).__name__}")


def _test_torrent(
    name: bytes = b"webseed-api-integration.bin", *, private: bool = False
) -> tuple[bytes, str]:
    payload = b"test"
    info = {
        b"length": len(payload),
        b"name": name,
        b"piece length": 16384,
        b"pieces": hashlib.sha1(payload).digest(),
    }
    if private:
        info[b"private"] = 1
    info_bytes = _bencode(info)
    torrent_bytes = _bencode({b"info": info})
    return torrent_bytes, hashlib.sha1(info_bytes).hexdigest()


def _required_connection() -> tuple[str, str, str, str]:
    base_url, username, password, save_path = _connection()
    if not (base_url and username and password):
        if os.getenv("QB_WEBSEED_TEST_REQUIRED", "").strip().casefold() == "true":
            pytest.fail("The required real-qBittorrent integration service is not configured")
        pytest.skip("real qBittorrent Web API integration credentials are not configured")
    return base_url, username, password, save_path


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
    base_url, username, password, save_path = _required_connection()
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


@pytest.mark.parametrize(
    ("saved_paused", "override", "expected_state"),
    [
        pytest.param(False, {}, {"stoppedDL"}, id="default-stopped-despite-active-rule"),
        pytest.param(
            True,
            {"add_paused": False},
            {"downloading", "stalledDL", "queuedDL"},
            id="one-time-active-despite-stopped-rule",
        ),
    ],
)
def test_search_queue_request_controls_real_qbittorrent_state(
    app_client,
    db_session,
    tmp_path: Path,
    saved_paused: bool,
    override: dict[str, bool],
    expected_state: set[str],
) -> None:
    base_url, username, password, save_path = _required_connection()
    case = "active" if override else "stopped"
    category = "queue-state-integration"
    db_session.add(
        AppSettings(
            id="default",
            qb_base_url=base_url,
            qb_username=username,
            qb_password_encrypted=obfuscate_secret(password),
        )
    )
    rule = Rule(
        rule_name="Queue state integration",
        content_name="Queue state integration",
        media_type=MediaType.MOVIE,
        assigned_category=category,
        save_path=save_path,
        add_paused=saved_paused,
    )
    db_session.add(rule)
    db_session.commit()

    # Serve synthetic metadata locally; no public tracker or provider is needed.
    torrent_bytes, info_hash = _test_torrent(f"queue-state-{case}.bin".encode(), private=True)
    metadata_dir = tmp_path / "torrent-metadata"
    metadata_dir.mkdir()
    (metadata_dir / "result.torrent").write_bytes(torrent_bytes)
    handler = partial(SimpleHTTPRequestHandler, directory=str(metadata_dir))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with QbittorrentClient(base_url, username, password, timeout=15) as client:
                client.create_category(category)
                assert client.get_torrent(info_hash) is None, "Test torrent already exists"
                try:
                    response = app_client.post(
                        "/api/search/queue",
                        json={
                            "link": f"http://127.0.0.1:{server.server_port}/result.torrent",
                            "rule_id": rule.id,
                            **override,
                        },
                    )
                    assert response.status_code == 200, response.text
                    assert response.json()["queued_via_torrent_file"] is True
                    last_state = None

                    def read_expected_state(hash_value: str) -> dict[str, object] | None:
                        nonlocal last_state
                        torrent = client.get_torrent(hash_value)
                        last_state = torrent.get("state") if torrent else None
                        return torrent if last_state in expected_state else None

                    assert _wait_for_torrent(read_expected_state, info_hash) is not None, (
                        f"Expected qBittorrent state {expected_state}; last state: {last_state}"
                    )
                    assert response.json()["add_paused"] is (not override)
                    db_session.refresh(rule)
                    assert rule.add_paused is saved_paused
                finally:
                    if client.get_torrent(info_hash) is not None:
                        client.delete_torrents(info_hash, delete_files=True)
        finally:
            server.shutdown()
            thread.join(timeout=5)
