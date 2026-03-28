from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.models import MediaType, QualityProfile, Rule
from app.services.qbittorrent import QbittorrentClient
from app.services.selective_queue import (
    QueueResult,
    SelectiveQueueError,
    build_episode_file_selection_plan,
    find_episode_file_entry,
    parse_torrent_info,
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
        items = sorted(value.items(), key=lambda item: bytes(item[0] if isinstance(item[0], bytes) else str(item[0]).encode()))
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
    assert entry.file_id == 0


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
        lambda self, info_hash, file_ids, priority: priority_calls.append((info_hash, list(file_ids), priority)),
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


def test_queue_result_with_optional_file_selection_rejects_torrents_without_missing_files(monkeypatch) -> None:
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
