from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from app.services.qbittorrent import QbittorrentAuthError, QbittorrentClient


def test_flatten_feed_tree_handles_nested_nodes() -> None:
    payload = {
        "Shows": {"English": {"url": "http://feed.example/shows"}},
        "Movies": {"url": "http://feed.example/movies"},
    }

    feeds = QbittorrentClient.flatten_feed_tree(payload)

    assert [item.url for item in feeds] == [
        "http://feed.example/movies",
        "http://feed.example/shows",
    ]


def test_login_rejects_bad_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Fails.")

    transport = httpx.MockTransport(handler)
    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "bad-password",
        transport=transport,
    )

    with pytest.raises(QbittorrentAuthError):
        client.login()


def test_create_category_ignores_conflict_for_existing_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/createCategory":
            return httpx.Response(409, text="Category already exists")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=transport,
    )

    client.create_category("Series/Pluribus [imdbid-tt0000000]")


def test_add_torrent_url_sends_paused_and_stopped_for_compatibility() -> None:
    captured_body: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/add":
            captured_body = parse_qs(request.content.decode())
            return httpx.Response(200, text="Ok.")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=transport,
    )

    client.add_torrent_url(
        link="https://example.com/queued.torrent",
        category="Series/Shrinking [imdbid-tt15153834]",
        save_path="/data/shrinking",
        paused=True,
        sequential_download=True,
        first_last_piece_prio=True,
    )

    assert captured_body["urls"] == ["https://example.com/queued.torrent"]
    assert captured_body["paused"] == ["true"]
    assert captured_body["stopped"] == ["true"]
    assert captured_body["sequentialDownload"] == ["true"]
    assert captured_body["firstLastPiecePrio"] == ["true"]
    assert captured_body["category"] == ["Series/Shrinking [imdbid-tt15153834]"]
    assert captured_body["savepath"] == ["/data/shrinking"]


def test_add_torrent_file_posts_multipart_payload() -> None:
    captured_body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/add":
            captured_body = request.content
            return httpx.Response(200, text="Ok.")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=transport,
    )

    client.add_torrent_file(
        torrent_bytes=b"d4:infod4:name8:test.mkv6:lengthi1eee",
        filename="queued-result.torrent",
        category="Series/Shrinking [imdbid-tt15153834]",
        save_path="/data/shrinking",
        paused=False,
        sequential_download=True,
        first_last_piece_prio=True,
    )

    body_text = captured_body.decode(errors="ignore")
    assert 'name="torrents"; filename="queued-result.torrent"' in body_text
    assert 'name="category"' in body_text
    assert "Series/Shrinking [imdbid-tt15153834]" in body_text
    assert 'name="paused"' in body_text
    assert "false" in body_text


def test_get_torrent_files_reads_files_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/files":
            assert request.url.params["hash"] == "abc123"
            return httpx.Response(
                200,
                json=[
                    {"index": 0, "name": "Shrinking.S03E08.mkv"},
                    {"index": 1, "name": "Shrinking.S03E09.mkv"},
                ],
            )
        return httpx.Response(404)

    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=httpx.MockTransport(handler),
    )

    files = client.get_torrent_files("abc123")

    assert files == [
        {"index": 0, "name": "Shrinking.S03E08.mkv"},
        {"index": 1, "name": "Shrinking.S03E09.mkv"},
    ]


def test_get_torrent_reads_single_hash_from_info_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/info":
            assert request.url.params["hashes"] == "abc123"
            return httpx.Response(
                200,
                json=[
                    {"hash": "abc123", "name": "Shrinking.S03", "progress": 1},
                ],
            )
        return httpx.Response(404)

    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=httpx.MockTransport(handler),
    )

    torrent = client.get_torrent("abc123")

    assert torrent == {"hash": "abc123", "name": "Shrinking.S03", "progress": 1}


def test_set_file_priority_posts_pipe_delimited_ids() -> None:
    captured_body: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/filePrio":
            captured_body = parse_qs(request.content.decode())
            return httpx.Response(200, text="Ok.")
        return httpx.Response(404)

    client = QbittorrentClient(
        "http://127.0.0.1:8080",
        "admin",
        "adminadmin",
        transport=httpx.MockTransport(handler),
    )

    client.set_file_priority("abc123", [1, 3, 5], 0)

    assert captured_body["hash"] == ["abc123"]
    assert captured_body["id"] == ["1|3|5"]
    assert captured_body["priority"] == ["0"]
