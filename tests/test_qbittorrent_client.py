from __future__ import annotations

import httpx
import pytest

from app.services.qbittorrent import QbittorrentAuthError, QbittorrentClient


def test_flatten_feed_tree_handles_nested_nodes() -> None:
    payload = {
        "Shows": {
            "English": {
                "url": "http://feed.example/shows"
            }
        },
        "Movies": {
            "url": "http://feed.example/movies"
        },
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
