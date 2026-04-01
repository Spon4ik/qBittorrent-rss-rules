from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

WATCH_STATE_EPISODE_KEY_RE = re.compile(
    r"^s(?P<season>\d{1,2})e(?P<episode>\d{1,2})$",
    re.IGNORECASE,
)
WATCH_STATE_SOURCE_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)

WatchStateNextFloorResolver = Callable[[tuple[int, int]], tuple[tuple[int, int], str]]


def _bounded_season_number(value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    return max(minimum, min(99, int(value)))


def _bounded_episode_number(value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    return max(minimum, min(99, int(value)))


def _format_episode_key(season_number: int, episode_number: int) -> str:
    return f"S{season_number:02d}E{episode_number:02d}"


def normalize_watch_state_episode_keys(value: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in list(value or []):
        match = WATCH_STATE_EPISODE_KEY_RE.match(str(raw_item or "").strip())
        if not match:
            continue
        season_number = _bounded_season_number(int(match.group("season")), allow_zero=True)
        episode_number = _bounded_episode_number(int(match.group("episode")), allow_zero=True)
        episode_key = _format_episode_key(season_number, episode_number)
        if episode_key in seen:
            continue
        seen.add(episode_key)
        normalized.append(episode_key)
    return normalized


def watch_state_episode_key_tuple(value: str | None) -> tuple[int, int] | None:
    match = WATCH_STATE_EPISODE_KEY_RE.match(str(value or "").strip())
    if match is None:
        return None
    return int(match.group("season")), int(match.group("episode"))


def watch_state_episode_key_from_tuple(value: tuple[int, int]) -> str:
    return _format_episode_key(value[0], value[1])


def sort_watch_state_episode_keys(values: list[str]) -> list[str]:
    keyed: list[tuple[tuple[int, int], str]] = []
    for item in normalize_watch_state_episode_keys(values):
        episode_tuple = watch_state_episode_key_tuple(item)
        if episode_tuple is None:
            continue
        keyed.append((episode_tuple, item))
    keyed.sort(key=lambda item: item[0])
    return [item[1] for item in keyed]


def merge_watch_state_episode_key_lists(*lists: list[str]) -> list[str]:
    return sort_watch_state_episode_keys([item for current in lists for item in current])


def latest_watch_state_episode_tuple(values: list[str]) -> tuple[int, int] | None:
    latest: tuple[int, int] | None = None
    for item in values:
        episode_tuple = watch_state_episode_key_tuple(item)
        if episode_tuple is None:
            continue
        if latest is None or episode_tuple > latest:
            latest = episode_tuple
    return latest


def floor_tuple(season_number: int | None, episode_number: int | None) -> tuple[int, int] | None:
    if season_number is None or episode_number is None:
        return None
    return int(season_number), int(episode_number)


def increment_floor(season_number: int, episode_number: int) -> tuple[int, int]:
    if episode_number < 99:
        return season_number, episode_number + 1
    if season_number < 99:
        return season_number + 1, 1
    return season_number, episode_number


def _normalize_watch_state_source_label(value: str | None) -> str | None:
    cleaned = WATCH_STATE_SOURCE_RE.sub("_", str(value or "").strip().casefold()).strip("_")
    return cleaned or None


def normalize_watch_state_source_labels(value: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in list(value or []):
        normalized_label = _normalize_watch_state_source_label(raw_item)
        if normalized_label is None or normalized_label in seen:
            continue
        seen.add(normalized_label)
        normalized.append(normalized_label)
    normalized.sort()
    return normalized


def format_watch_state_source_labels(value: list[str] | None) -> str:
    normalized = normalize_watch_state_source_labels(value)
    return ", ".join(label.replace("_", " ").title() for label in normalized)


@dataclass(frozen=True, slots=True)
class WatchStateDerivedFloor:
    watched_start_season: int | None
    watched_start_episode: int | None
    known_start_season: int | None
    known_start_episode: int | None
    last_watched_season: int | None
    last_watched_episode: int | None
    latest_existing_season: int | None
    latest_existing_episode: int | None
    latest_known_season: int | None
    latest_known_episode: int | None
    existing_unseen_episode_numbers: list[str]
    known_episode_numbers: list[str]
    watched_episode_numbers: list[str]
    watched_floor_reason: str
    known_floor_reason: str


@dataclass(frozen=True, slots=True)
class WatchStateFloorSelection:
    effective_floor: tuple[int, int] | None
    floor_changed: bool
    floor_detail: str


@dataclass(frozen=True, slots=True)
class MovieWatchStateSelection:
    completed_sources: list[str]
    completion_changed: bool
    effective_enabled: bool
    enabled_changed: bool
    effective_auto_disabled: bool
    auto_disabled_changed: bool
    detail: str

    @property
    def changed(self) -> bool:
        return self.completion_changed or self.enabled_changed or self.auto_disabled_changed


def derive_watch_state_floor(
    *,
    source_label: str,
    current_episode_numbers: list[str],
    current_watched_episode_numbers: list[str],
    remembered_known_episode_numbers: list[str],
    remembered_watched_episode_numbers: list[str],
    next_floor_after_episode: WatchStateNextFloorResolver,
) -> WatchStateDerivedFloor | None:
    current_episode_numbers = sort_watch_state_episode_keys(current_episode_numbers)
    current_watched_episode_numbers = sort_watch_state_episode_keys(current_watched_episode_numbers)
    remembered_known_episode_numbers = normalize_watch_state_episode_keys(
        remembered_known_episode_numbers
    )
    remembered_watched_episode_numbers = normalize_watch_state_episode_keys(
        remembered_watched_episode_numbers
    )
    known_episode_numbers = merge_watch_state_episode_key_lists(
        remembered_known_episode_numbers,
        current_episode_numbers,
    )
    watched_episode_numbers = merge_watch_state_episode_key_lists(
        remembered_watched_episode_numbers,
        current_watched_episode_numbers,
    )

    if not known_episode_numbers:
        return None

    last_watched = latest_watch_state_episode_tuple(watched_episode_numbers)
    latest_existing = latest_watch_state_episode_tuple(current_episode_numbers)
    latest_known = latest_watch_state_episode_tuple(known_episode_numbers)
    watched_floor_reason = f"No watched {source_label} episodes were found."
    watched_next_floor: tuple[int, int] | None = None
    if last_watched is not None:
        next_current_after_watched = next(
            (
                episode_tuple
                for episode_tuple in (
                    watch_state_episode_key_tuple(item) for item in current_episode_numbers
                )
                if episode_tuple is not None and episode_tuple > last_watched
            ),
            None,
        )
        if next_current_after_watched is not None:
            watched_next_floor = next_current_after_watched
            watched_floor_reason = (
                f"Advanced to S{watched_next_floor[0]:02d}E{watched_next_floor[1]:02d} "
                f"from {source_label} progress through S{last_watched[0]:02d}E{last_watched[1]:02d}. "
                f"This rule keeps searching existing unseen {source_label} episodes."
            )
        else:
            watched_next_floor, watched_base_reason = next_floor_after_episode(last_watched)
            watched_floor_reason = f"{watched_base_reason} This rule keeps searching existing unseen {source_label} episodes."

    existing_unseen_episode_numbers: list[str] = []
    for episode_key in current_episode_numbers:
        if last_watched is None:
            existing_unseen_episode_numbers.append(episode_key)
            continue
        episode_tuple = watch_state_episode_key_tuple(episode_key)
        if episode_tuple is not None and episode_tuple > last_watched:
            existing_unseen_episode_numbers.append(episode_key)
    existing_unseen_episode_numbers = sort_watch_state_episode_keys(existing_unseen_episode_numbers)
    known_floor_reason = f"No remembered {source_label} episode history was found."
    known_next_floor: tuple[int, int] | None = None
    if latest_known is not None:
        known_next_floor, known_floor_reason = next_floor_after_episode(latest_known)

    return WatchStateDerivedFloor(
        watched_start_season=watched_next_floor[0] if watched_next_floor is not None else None,
        watched_start_episode=watched_next_floor[1] if watched_next_floor is not None else None,
        known_start_season=known_next_floor[0] if known_next_floor is not None else None,
        known_start_episode=known_next_floor[1] if known_next_floor is not None else None,
        last_watched_season=last_watched[0] if last_watched is not None else None,
        last_watched_episode=last_watched[1] if last_watched is not None else None,
        latest_existing_season=latest_existing[0] if latest_existing is not None else None,
        latest_existing_episode=latest_existing[1] if latest_existing is not None else None,
        latest_known_season=latest_known[0] if latest_known is not None else None,
        latest_known_episode=latest_known[1] if latest_known is not None else None,
        existing_unseen_episode_numbers=existing_unseen_episode_numbers,
        known_episode_numbers=known_episode_numbers,
        watched_episode_numbers=watched_episode_numbers,
        watched_floor_reason=watched_floor_reason,
        known_floor_reason=known_floor_reason,
    )


def select_watch_state_floor(
    *,
    derived_floor: WatchStateDerivedFloor,
    current_floor: tuple[int, int] | None,
    keep_searching_existing_unseen: bool,
    source_label: str,
) -> WatchStateFloorSelection:
    floor_detail = derived_floor.known_floor_reason
    next_floor: tuple[int, int] | None = floor_tuple(
        derived_floor.known_start_season,
        derived_floor.known_start_episode,
    )
    if keep_searching_existing_unseen:
        next_floor = floor_tuple(
            derived_floor.watched_start_season,
            derived_floor.watched_start_episode,
        )
        if next_floor is None:
            next_floor = current_floor
        floor_detail = derived_floor.watched_floor_reason

    effective_floor = current_floor
    floor_changed = False
    if next_floor is not None:
        effective_floor = next_floor
        floor_changed = current_floor != next_floor
        if current_floor is not None and current_floor >= next_floor:
            effective_floor = current_floor
            floor_changed = False
            floor_detail = f"Current rule floor already matches {source_label}-derived progress."
            if current_floor > next_floor:
                floor_detail = (
                    f"Current rule floor is already ahead of {source_label}-derived progress."
                )

    return WatchStateFloorSelection(
        effective_floor=effective_floor,
        floor_changed=floor_changed,
        floor_detail=floor_detail,
    )


def select_movie_watch_state(
    *,
    source_label: str,
    source_present: bool,
    source_completed: bool,
    current_completed_sources: list[str],
    current_enabled: bool,
    current_auto_disabled: bool,
    keep_searching: bool,
) -> MovieWatchStateSelection:
    normalized_source_label = _normalize_watch_state_source_label(source_label)
    previous_completed_sources = normalize_watch_state_source_labels(current_completed_sources)
    next_completed_sources = [
        label for label in previous_completed_sources if label != normalized_source_label
    ]
    if normalized_source_label and source_present and source_completed:
        next_completed_sources.append(normalized_source_label)
    next_completed_sources = normalize_watch_state_source_labels(next_completed_sources)
    completion_changed = next_completed_sources != previous_completed_sources
    completion_sources_display = format_watch_state_source_labels(next_completed_sources)

    if keep_searching:
        effective_enabled = True if current_auto_disabled else current_enabled
        effective_auto_disabled = False
        if next_completed_sources:
            detail = (
                f"Completed watch state is reported by {completion_sources_display}. "
                "Keep-search is enabled, so watch-state sync leaves this rule active."
                if effective_enabled
                else f"Completed watch state is reported by {completion_sources_display}. "
                "Keep-search is enabled, so watch-state sync leaves the current disabled state unchanged."
            )
        else:
            detail = "No connected source currently reports this movie as completed."
    elif next_completed_sources:
        if current_enabled:
            effective_enabled = False
            effective_auto_disabled = True
            detail = f"Disabled because completed watch state is reported by {completion_sources_display}."
        elif current_auto_disabled:
            effective_enabled = current_enabled
            effective_auto_disabled = True
            detail = (
                f"Movie remains auto-disabled because completed watch state is reported by "
                f"{completion_sources_display}."
            )
        else:
            effective_enabled = current_enabled
            effective_auto_disabled = False
            detail = (
                f"Completed watch state is reported by {completion_sources_display}, "
                "but the current disabled state was not set by watch-state sync."
            )
    else:
        effective_auto_disabled = False
        if current_auto_disabled:
            effective_enabled = True
            detail = (
                "Re-enabled because no connected source currently reports this movie as completed."
            )
        else:
            effective_enabled = current_enabled
            detail = "No connected source currently reports this movie as completed."

    return MovieWatchStateSelection(
        completed_sources=next_completed_sources,
        completion_changed=completion_changed,
        effective_enabled=effective_enabled,
        enabled_changed=effective_enabled != current_enabled,
        effective_auto_disabled=effective_auto_disabled,
        auto_disabled_changed=effective_auto_disabled != current_auto_disabled,
        detail=detail,
    )
