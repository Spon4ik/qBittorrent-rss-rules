from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest

from app.models import MediaType, QualityProfile, Rule
from app.services.qbittorrent import QbittorrentClient
from app.services.selective_queue import (
    ParsedTorrentInfo,
    QueueResult,
    SelectiveQueueError,
    TorrentFileEntry,
    build_episode_file_selection_plan,
    build_magnet_link,
    find_episode_file_entry,
    parse_torrent_info,
    queue_grouped_search_results,
    queue_result_with_optional_file_selection,
    select_missing_episode_file_ids,
    text_matches_episode,
)


def _bencode(value: object) -> bytes:
    if isinstance(value, int):
        return f"i{value}e".encode()
    if isinstance(value, bytes):
        return f"{len(value)}:".encode() + value
    if isinstance(value, str):
        encoded = value.encode()
        return f"{len(encoded)}:".encode() + encoded
    if isinstance(value, list):
        return b"l" + b"".join(_bencode(item) for item in value) + b"e"
    if isinstance(value, Mapping):
        items = sorted(
            value.items(),
            key=lambda item: bytes(
                item[0] if isinstance(item[0], bytes) else str(item[0]).encode()
            ),
        )
        payload = b"d"
        for key, item_value in items:
            payload += _bencode(key)
            payload += _bencode(item_value)
        return payload + b"e"
    raise TypeError(f"Unsupported bencode value: {type(value)!r}")


def _build_multi_file_torrent_bytes(*file_names: str) -> bytes:
    info = {
        b"name": b"Shrinking.S03",
        b"piece length": 16384,
        b"pieces": b"01234567890123456789",
        b"files": [
            {
                b"length": 1,
                b"path": [file_name.encode()],
            }
            for file_name in file_names
        ],
    }
    torrent = {
        b"announce": b"https://tracker.example/announce",
        b"info": info,
    }
    return _bencode(torrent)


def test_build_episode_file_selection_plan_uses_remembered_rule_state() -> None:
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        jellyfin_known_episode_numbers=["S03E07", "S03E08"],
        jellyfin_existing_episode_numbers=["S03E08"],
        feed_urls=["http://feed.example/shrinking"],
    )

    plan = build_episode_file_selection_plan(rule)

    assert plan is not None
    assert plan.floor == (3, 8)
    assert plan.excluded_episode_keys == {"S03E07", "S03E08"}


def test_parse_torrent_info_and_select_missing_episode_file_ids() -> None:
    torrent_bytes = _build_multi_file_torrent_bytes(
        "Shrinking.S03E07.mkv",
        "Shrinking.S03E08.mkv",
        "Shrinking.S03E09.mkv",
    )
    parsed = parse_torrent_info(torrent_bytes, source_name="shrinking-s03.torrent")
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        jellyfin_known_episode_numbers=["S03E07"],
        feed_urls=["http://feed.example/shrinking"],
    )
    plan = build_episode_file_selection_plan(rule)

    assert plan is not None
    selection = select_missing_episode_file_ids(parsed.files, plan)

    assert selection.selected_file_ids == [1, 2]
    assert selection.parsed_episode_file_count == 3
    assert selection.skipped_episode_file_count == 1
    assert parsed.tracker_urls == ["https://tracker.example/announce"]


def test_text_matches_episode_and_find_episode_file_entry_support_ranges() -> None:
    torrent_bytes = _build_multi_file_torrent_bytes(
        "The.Beauty.S01E01-11.2160p.WEB-DL.mkv",
        "The.Beauty.S01E04.1080p.WEB-DL.mkv",
    )
    parsed = parse_torrent_info(torrent_bytes, source_name="the-beauty-s01.torrent")

    assert text_matches_episode(
        "The Beauty - S1E1-11 - 2026 2160p",
        season_number=1,
        episode_number=4,
    )
    entry = find_episode_file_entry(
        parsed.files,
        season_number=1,
        episode_number=4,
    )
    assert entry is not None
    assert entry.file_id == 1


def test_find_episode_file_entry_prefers_filename_episode_over_parent_pack_range() -> None:
    files = [
        TorrentFileEntry(
            file_id=10,
            path="The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E10.1080p.mkv",
        ),
        TorrentFileEntry(
            file_id=12,
            path="The.Rookie.S08E01-E14.1080p.WEB-DL/The.Rookie.S08E12.1080p.mkv",
        ),
    ]

    entry = find_episode_file_entry(
        files,
        season_number=8,
        episode_number=12,
    )

    assert entry is not None
    assert entry.file_id == 12


def test_queue_result_with_optional_file_selection_applies_qb_file_priorities(monkeypatch) -> None:
    torrent_bytes = _build_multi_file_torrent_bytes(
        "Shrinking.S03E07.mkv",
        "Shrinking.S03E08.mkv",
        "Shrinking.S03E09.mkv",
    )
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        jellyfin_known_episode_numbers=["S03E07"],
        feed_urls=["http://feed.example/shrinking"],
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (torrent_bytes, "shrinking-s03.torrent"),
    )

    def fake_add_torrent_file(
        self,
        *,
        torrent_bytes: bytes,
        filename: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        captured["filename"] = filename
        captured["category"] = category
        captured["save_path"] = save_path
        captured["paused"] = paused
        captured["bytes"] = torrent_bytes

    priority_calls: list[tuple[str, list[int], int]] = []

    monkeypatch.setattr(QbittorrentClient, "add_torrent_file", fake_add_torrent_file)
    monkeypatch.setattr(
        QbittorrentClient,
        "set_file_priority",
        lambda self, info_hash, file_ids, priority: priority_calls.append(
            (info_hash, list(file_ids), priority)
        ),
    )

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link="https://example.com/shrinking-s03.torrent",
        category="Series/Shrinking [imdbid-tt15153834]",
        save_path="/data/shrinking",
        paused=False,
        sequential_download=True,
        first_last_piece_prio=True,
        rule=rule,
    )

    assert isinstance(result, QueueResult)
    assert result.selected_file_count == 2
    assert result.skipped_file_count == 1
    assert result.queued_via_torrent_file is True
    assert captured["filename"] == "shrinking-s03.torrent"
    assert captured["category"] == "Series/Shrinking [imdbid-tt15153834]"
    assert captured["save_path"] == "/data/shrinking"
    assert captured["paused"] is False
    assert captured["bytes"] == torrent_bytes
    assert priority_calls[0][1] == [0, 1, 2]
    assert priority_calls[0][2] == 0
    assert priority_calls[1][1] == [1, 2]
    assert priority_calls[1][2] == 1


def test_queue_result_with_optional_file_selection_uploads_http_torrent_file_without_rule(
    monkeypatch,
) -> None:
    torrent_bytes = _build_multi_file_torrent_bytes("Shrinking.S03E08.mkv")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (torrent_bytes, "shrinking-s03.torrent"),
    )

    def fake_add_torrent_file(
        self,
        *,
        torrent_bytes: bytes,
        filename: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        captured.update(
            {
                "torrent_bytes": torrent_bytes,
                "filename": filename,
                "category": category,
                "save_path": save_path,
                "paused": paused,
                "sequential_download": sequential_download,
                "first_last_piece_prio": first_last_piece_prio,
            }
        )

    def fail_add_torrent_url(self, **kwargs) -> None:
        raise AssertionError(f"Unexpected add_torrent_url call: {kwargs!r}")

    monkeypatch.setattr(QbittorrentClient, "add_torrent_file", fake_add_torrent_file)
    monkeypatch.setattr(QbittorrentClient, "add_torrent_url", fail_add_torrent_url)

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link="http://localhost:9117/dl/bitru/?jackett_apikey=secret&path=abc",
        category="Series/Shrinking [imdbid-tt15153834]",
        save_path="/data/shrinking",
        paused=False,
        sequential_download=True,
        first_last_piece_prio=True,
        rule=None,
    )

    assert result.queued_via_torrent_file is True
    assert captured == {
        "torrent_bytes": torrent_bytes,
        "filename": "shrinking-s03.torrent",
        "category": "Series/Shrinking [imdbid-tt15153834]",
        "save_path": "/data/shrinking",
        "paused": False,
        "sequential_download": True,
        "first_last_piece_prio": True,
    }


def test_queue_result_with_optional_file_selection_does_not_remote_fetch_broken_local_jackett_url(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (_ for _ in ()).throw(httpx.HTTPError("boom")),
    )

    def fail_add_torrent_url(self, **kwargs) -> None:
        raise AssertionError(f"Unexpected add_torrent_url call: {kwargs!r}")

    monkeypatch.setattr(QbittorrentClient, "add_torrent_url", fail_add_torrent_url)

    with pytest.raises(
        SelectiveQueueError,
        match="Could not fetch a valid torrent file from the local Jackett-style URL",
    ):
        queue_result_with_optional_file_selection(
            qb_base_url="http://docker-host:8080",
            qb_username="admin",
            qb_password="secret",
            link="http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
            category="",
            save_path="",
            paused=True,
            sequential_download=False,
            first_last_piece_prio=False,
            rule=None,
        )


def test_queue_result_with_optional_file_selection_rewrites_jackett_qb_url_for_app_fetch(
    monkeypatch,
) -> None:
    torrent_bytes = _build_multi_file_torrent_bytes("Shrinking.S03E08.mkv")
    seen_links: list[str] = []

    def fake_download(link):
        seen_links.append(link)
        return torrent_bytes, "shrinking-s03.torrent"

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        fake_download,
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_file",
        lambda self, **kwargs: None,
    )

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link="http://docker-host:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        jackett_api_url="http://localhost:9117",
        jackett_qb_url="http://docker-host:9117",
        category="",
        save_path="",
        paused=True,
        sequential_download=False,
        first_last_piece_prio=False,
        rule=None,
    )

    assert result.queued_via_torrent_file is True
    assert seen_links == ["http://localhost:9117/dl/kinozal/?jackett_apikey=secret&path=abc"]


def test_queue_result_with_optional_file_selection_normalizes_unicode_http_url_before_fetch(
    monkeypatch,
) -> None:
    torrent_bytes = _build_multi_file_torrent_bytes("Movie.2025.mkv")
    seen_links: list[str] = []

    def fake_download(link):
        seen_links.append(link)
        return torrent_bytes, "movie-2025.torrent"

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        fake_download,
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_file",
        lambda self, **kwargs: None,
    )

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link=(
            "http://localhost:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
            "&file=C%27\u00e9tait+mieux+demain+2025+MVO%2C+Sub+WEBDL+(AVC)+-+RUSSIAN"
        ),
        category="",
        save_path="",
        paused=True,
        sequential_download=False,
        first_last_piece_prio=False,
        rule=None,
    )

    assert result.queued_via_torrent_file is True
    assert seen_links == [
        (
            "http://localhost:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
            "&file=C%27%C3%A9tait%20mieux%20demain%202025%20MVO%2C%20Sub%20WEBDL%20%28AVC%29%20-%20RUSSIAN"
        )
    ]


def test_queue_result_with_optional_file_selection_uses_redirected_local_jackett_magnet(
    monkeypatch,
) -> None:
    queued_links: list[str] = []

    monkeypatch.setattr(
        "app.services.selective_queue._resolve_local_jackett_redirect_magnet_link",
        lambda link: (
            "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
            "&tr=https://tracker.example/announce"
        ),
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_url",
        lambda self, **kwargs: queued_links.append(str(kwargs["link"])),
    )

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link="http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        category="",
        save_path="",
        paused=True,
        sequential_download=False,
        first_last_piece_prio=False,
        rule=None,
    )

    assert result.queued_via_torrent_file is False
    assert queued_links == [
        "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
        "&tr=https://tracker.example/announce"
    ]


def test_queue_result_with_optional_file_selection_allows_local_remote_fetch_when_qb_is_loopback(
    monkeypatch,
) -> None:
    queued_links: list[str] = []
    torrent_snapshots = [
        [{"hash": "existing"}],
        [{"hash": "existing"}, {"hash": "new-hash"}],
    ]

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (_ for _ in ()).throw(httpx.ReadTimeout("slow jackett")),
    )
    monkeypatch.setattr(
        "app.services.selective_queue.time.sleep",
        lambda seconds: None,
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_url",
        lambda self, **kwargs: queued_links.append(str(kwargs["link"])),
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "get_torrents",
        lambda self: torrent_snapshots.pop(0),
    )

    result = queue_result_with_optional_file_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        link="http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        category="",
        save_path="",
        paused=True,
        sequential_download=False,
        first_last_piece_prio=False,
        rule=None,
    )

    assert result.queued_via_torrent_file is False
    assert queued_links == [
        "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
    ]


def test_queue_result_with_optional_file_selection_reports_when_remote_fetch_materializes_nothing(
    monkeypatch,
) -> None:
    queued_links: list[str] = []
    torrent_snapshots = [
        [{"hash": "existing"}],
        [{"hash": "existing"}],
        [{"hash": "existing"}],
        [{"hash": "existing"}],
        [{"hash": "existing"}],
        [{"hash": "existing"}],
        [{"hash": "existing"}],
    ]

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (_ for _ in ()).throw(httpx.ReadTimeout("slow jackett")),
    )
    monkeypatch.setattr(
        "app.services.selective_queue.time.sleep",
        lambda seconds: None,
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_url",
        lambda self, **kwargs: queued_links.append(str(kwargs["link"])),
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "get_torrents",
        lambda self: torrent_snapshots.pop(0),
    )

    with pytest.raises(
        SelectiveQueueError,
        match="no torrent appeared in the list",
    ):
        queue_result_with_optional_file_selection(
            qb_base_url="http://127.0.0.1:8080",
            qb_username="admin",
            qb_password="secret",
            link="http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
            category="",
            save_path="",
            paused=True,
            sequential_download=False,
            first_last_piece_prio=False,
            rule=None,
        )

    assert queued_links == [
        "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
    ]


def test_resolve_local_jackett_redirect_magnet_link_follows_http_redirect_chain(
    monkeypatch,
) -> None:
    seen_links: list[str] = []

    class FakeResponse:
        def __init__(self, *, is_redirect: bool, location: str | None = None) -> None:
            self.is_redirect = is_redirect
            self.headers = {"location": location} if location is not None else {}

    class FakeClient:
        def __init__(self, *, timeout, follow_redirects) -> None:
            assert follow_redirects is False

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, link: str) -> FakeResponse:
            seen_links.append(link)
            if len(seen_links) == 1:
                return FakeResponse(
                    is_redirect=True,
                    location="/download/intermediate?id=123",
                )
            return FakeResponse(
                is_redirect=True,
                location=(
                    "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
                    "&tr=https://tracker.example/announce"
                ),
            )

    monkeypatch.setattr("app.services.selective_queue.httpx.Client", FakeClient)

    from app.services.selective_queue import _resolve_local_jackett_redirect_magnet_link

    magnet_link = _resolve_local_jackett_redirect_magnet_link(
        "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
    )

    assert magnet_link == (
        "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
        "&tr=https://tracker.example/announce"
    )
    assert seen_links == [
        "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        "http://127.0.0.1:9117/download/intermediate?id=123",
    ]


def test_queue_result_with_optional_file_selection_rejects_torrents_without_missing_files(
    monkeypatch,
) -> None:
    torrent_bytes = _build_multi_file_torrent_bytes("Shrinking.S03E07.mkv")
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        jellyfin_known_episode_numbers=["S03E07"],
        feed_urls=["http://feed.example/shrinking"],
    )

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (torrent_bytes, "shrinking-s03.torrent"),
    )

    with pytest.raises(SelectiveQueueError, match="No missing/unseen episode files"):
        queue_result_with_optional_file_selection(
            qb_base_url="http://127.0.0.1:8080",
            qb_username="admin",
            qb_password="secret",
            link="https://example.com/shrinking-s03.torrent",
            category="Series/Shrinking [imdbid-tt15153834]",
            save_path="/data/shrinking",
            paused=False,
            sequential_download=True,
            first_last_piece_prio=True,
            rule=rule,
        )


def test_build_magnet_link_includes_display_name_and_unique_trackers() -> None:
    magnet_link = build_magnet_link(
        info_hash="abcdef1234567890abcdef1234567890abcdef12",
        tracker_urls=[
            "udp://tracker.example:1337/announce",
            "udp://tracker.example:1337/announce",
            "https://tracker.example/announce",
        ],
        display_name="The Beauty S01E01 2160p",
    )

    assert magnet_link.startswith("magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12")
    assert "dn=The%20Beauty%20S01E01%202160p" in magnet_link
    assert magnet_link.count("tr=") == 2


def test_queue_grouped_search_results_merges_missing_trackers(monkeypatch) -> None:
    torrent_bytes = _bencode(
        {
            b"announce": b"https://tracker.two/announce",
            b"info": {
                b"name": b"Shrinking.S03",
                b"piece length": 16384,
                b"pieces": b"01234567890123456789",
                b"files": [
                    {
                        b"length": 1,
                        b"path": [b"Shrinking.S03E08.mkv"],
                    }
                ],
            },
        }
    )
    inspected_links: list[str] = []
    add_tracker_calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(
        "app.services.selective_queue.queue_result_with_optional_file_selection",
        lambda **kwargs: QueueResult(message="Queued in qBittorrent."),
    )

    def fake_download_torrent_bytes(link):
        inspected_links.append(link)
        return torrent_bytes, "grouped-variant.torrent"

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        fake_download_torrent_bytes,
    )
    monkeypatch.setattr(
        "app.services.selective_queue.parse_torrent_info",
        lambda torrent_bytes, *, source_name="queued-result.torrent": ParsedTorrentInfo(
            info_hash="0123456789abcdef0123456789abcdef01234567",
            filename=source_name,
            files=[],
            tracker_urls=["https://tracker.two/announce"],
        ),
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "get_torrent",
        lambda self, info_hash: {"hash": info_hash},
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "get_torrent_trackers",
        lambda self, info_hash: [{"url": "https://tracker.example/announce"}],
    )
    monkeypatch.setattr(
        QbittorrentClient,
        "add_trackers",
        lambda self, info_hash, tracker_urls: add_tracker_calls.append(
            (info_hash, list(tracker_urls))
        ),
    )

    result = queue_grouped_search_results(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        links=[
            "magnet:?xt=urn:btih:0123456789ABCDEF0123456789ABCDEF01234567&tr=https://tracker.example/announce",
            "https://example.com/grouped-variant.torrent",
        ],
        info_hash="0123456789abcdef0123456789abcdef01234567",
        tracker_urls=["https://tracker.example/announce"],
        category="",
        save_path="",
        paused=True,
        sequential_download=False,
        first_last_piece_prio=False,
        rule=None,
    )

    assert isinstance(result, QueueResult)
    assert "Processed 2 same-hash variants" in result.message
    assert "Added 1 missing trackers" in result.message
    assert inspected_links == ["https://example.com/grouped-variant.torrent"]
    assert add_tracker_calls == [
        (
            "0123456789abcdef0123456789abcdef01234567",
            ["https://tracker.two/announce"],
        )
    ]
