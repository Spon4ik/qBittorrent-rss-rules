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
    StremioQueueSelection,
    TorrentFileEntry,
    build_episode_file_selection_plan,
    build_magnet_link,
    find_episode_file_entry,
    parse_torrent_info,
    queue_grouped_search_results,
    queue_result_with_optional_file_selection,
    queue_stremio_stream_selection,
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


def test_queue_stremio_stream_selection_queues_exact_variant_and_returns_magnet(
    monkeypatch,
) -> None:
    queued: dict[str, object] = {}
    exact_worker_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        QbittorrentClient,
        "add_torrent_url",
        lambda self, **kwargs: queued.update(kwargs),
    )
    monkeypatch.setattr(
        "app.services.selective_queue._start_exact_file_selection_worker",
        lambda **kwargs: exact_worker_calls.append((kwargs["info_hash"], kwargs["file_idx"])),
    )

    result, magnet_link = queue_stremio_stream_selection(
        qb_base_url="http://127.0.0.1:8080",
        qb_username="admin",
        qb_password="secret",
        selection=StremioQueueSelection(
            info_hash="abcdef1234567890abcdef1234567890abcdef12",
            tracker_urls=["udp://tracker.example:1337/announce"],
            display_name="The Beauty S01E01 2160p",
            file_idx=5,
        ),
        category="Series/The Beauty [imdbid-tt33517752]",
        save_path="/data/the-beauty",
        paused=True,
        sequential_download=True,
        first_last_piece_prio=True,
    )

    assert isinstance(result, QueueResult)
    assert result.deferred_file_selection is True
    assert "prioritized" in result.message
    assert magnet_link == queued["link"]
    assert "tr=udp%3A%2F%2Ftracker.example%3A1337%2Fannounce" in magnet_link
    assert queued["category"] == "Series/The Beauty [imdbid-tt33517752]"
    assert queued["save_path"] == "/data/the-beauty"
    assert queued["paused"] is True
    assert queued["sequential_download"] is True
    assert queued["first_last_piece_prio"] is True
    assert exact_worker_calls == [("abcdef1234567890abcdef1234567890abcdef12", 5)]


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
