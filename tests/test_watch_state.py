from __future__ import annotations

from app.services.watch_state import (
    derive_watch_state_floor,
    latest_watch_state_episode_tuple,
    merge_watch_state_episode_key_lists,
    normalize_watch_state_episode_keys,
    select_watch_state_floor,
    sort_watch_state_episode_keys,
    watch_state_episode_key_from_tuple,
)


def test_normalize_watch_state_episode_keys_canonicalizes_and_deduplicates() -> None:
    assert normalize_watch_state_episode_keys(
        ["s1e1", "S01E01", " s00e00 ", "invalid", "S2E3"]
    ) == ["S01E01", "S00E00", "S02E03"]


def test_sort_merge_and_latest_watch_state_episode_keys() -> None:
    merged = merge_watch_state_episode_key_lists(
        ["S01E10", "s01e02"],
        ["S01E01", "S01E10"],
        ["s00e01"],
    )

    assert sort_watch_state_episode_keys(["S01E10", "s01e02", "S01E01"]) == [
        "S01E01",
        "S01E02",
        "S01E10",
    ]
    assert merged == ["S00E01", "S01E01", "S01E02", "S01E10"]
    assert latest_watch_state_episode_tuple(merged) == (1, 10)
    assert watch_state_episode_key_from_tuple((1, 2)) == "S01E02"


def test_derive_and_select_watch_state_floor_preserves_source_label_and_current_floor() -> None:
    def next_floor_after_episode(current_episode: tuple[int, int]) -> tuple[tuple[int, int], str]:
        season_number, episode_number = current_episode
        next_episode = episode_number + 1
        return (
            (season_number, next_episode),
            f"Advanced to S{season_number:02d}E{next_episode:02d} from S{season_number:02d}E{episode_number:02d}.",
        )

    derived_floor = derive_watch_state_floor(
        source_label="Jellyfin",
        current_episode_numbers=["S01E01", "S01E02", "S01E03"],
        current_watched_episode_numbers=["S01E01"],
        remembered_known_episode_numbers=[],
        remembered_watched_episode_numbers=[],
        next_floor_after_episode=next_floor_after_episode,
    )

    assert derived_floor is not None
    assert (derived_floor.watched_start_season, derived_floor.watched_start_episode) == (1, 2)
    assert (derived_floor.known_start_season, derived_floor.known_start_episode) == (1, 4)
    assert derived_floor.existing_unseen_episode_numbers == ["S01E02", "S01E03"]
    assert derived_floor.watched_floor_reason == (
        "Advanced to S01E02 from Jellyfin progress through S01E01. "
        "This rule keeps searching existing unseen Jellyfin episodes."
    )

    selection = select_watch_state_floor(
        derived_floor=derived_floor,
        current_floor=(1, 5),
        keep_searching_existing_unseen=True,
        source_label="Jellyfin",
    )

    assert selection.effective_floor == (1, 5)
    assert selection.floor_changed is False
    assert selection.floor_detail == "Current rule floor is already ahead of Jellyfin-derived progress."
