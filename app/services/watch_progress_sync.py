from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AppSettings
from app.services import operation_status
from app.services.jellyfin import JellyfinService
from app.services.settings_service import SettingsService
from app.services.stremio import StremioService
from app.services.watch_state import WatchProgressRecord, choose_newer_watch_progress

WatchProgressWriter = Callable[[WatchProgressRecord], None]
EPISODE_ITEM_KEY_RE = re.compile(
    r"^(?P<series>[^:]+):S(?P<season>\d{1,2})E(?P<episode>\d{1,2})$",
    re.IGNORECASE,
)


def _match_key(record: WatchProgressRecord) -> str:
    if record.media_type == "episode":
        match = EPISODE_ITEM_KEY_RE.match(record.item_key)
        if match:
            return match.group("series").casefold()
    return record.item_key.casefold()


def _latest_record(records: list[WatchProgressRecord]) -> WatchProgressRecord:
    return max(records, key=lambda record: (record.updated_at is not None, record.updated_at))


def _records_to_write_for_winner(
    records: list[WatchProgressRecord],
    winner: WatchProgressRecord,
) -> list[WatchProgressRecord]:
    if winner.media_type != "episode":
        return [winner]
    selected = {record.item_key: record for record in records if record.completed}
    selected[winner.item_key] = winner
    return sorted(
        selected.values(),
        key=lambda record: (record.updated_at is not None, record.updated_at, record.item_key),
    )


@dataclass(frozen=True, slots=True)
class WatchProgressSyncSummary:
    jellyfin_read_count: int
    stremio_read_count: int
    matched_count: int
    jellyfin_write_count: int
    stremio_write_count: int
    skipped_count: int
    error_count: int
    messages: list[str]


class WatchProgressSyncService:
    def __init__(
        self,
        *,
        jellyfin_records: list[WatchProgressRecord],
        stremio_records: list[WatchProgressRecord],
        jellyfin_writer: WatchProgressWriter,
        stremio_writer: WatchProgressWriter,
        min_delta_ms: int = 30_000,
    ) -> None:
        self.jellyfin_records = jellyfin_records
        self.stremio_records = stremio_records
        self.jellyfin_writer = jellyfin_writer
        self.stremio_writer = stremio_writer
        self.min_delta_ms = min_delta_ms

    def sync(self) -> WatchProgressSyncSummary:
        jellyfin_by_key: dict[str, list[WatchProgressRecord]] = {}
        for record in self.jellyfin_records:
            jellyfin_by_key.setdefault(_match_key(record), []).append(record)
        stremio_by_key: dict[str, list[WatchProgressRecord]] = {}
        for record in self.stremio_records:
            stremio_by_key.setdefault(_match_key(record), []).append(record)
        matched_keys = sorted(set(jellyfin_by_key).intersection(stremio_by_key))

        jellyfin_write_count = 0
        stremio_write_count = 0
        skipped_count = 0
        error_count = 0
        messages: list[str] = []

        for item_key in matched_keys:
            jellyfin_record = _latest_record(jellyfin_by_key[item_key])
            stremio_record = _latest_record(stremio_by_key[item_key])
            selection = choose_newer_watch_progress(
                jellyfin_record,
                stremio_record,
                min_delta_ms=self.min_delta_ms,
            )
            if selection is None:
                skipped_count += 1
                continue
            try:
                if selection.winner.source == "stremio":
                    for record_to_write in _records_to_write_for_winner(
                        stremio_by_key[item_key],
                        selection.winner,
                    ):
                        self.jellyfin_writer(record_to_write)
                        jellyfin_write_count += 1
                    messages.append(f"Updated Jellyfin from Stremio for {item_key}.")
                elif selection.winner.source == "jellyfin":
                    for record_to_write in _records_to_write_for_winner(
                        jellyfin_by_key[item_key],
                        selection.winner,
                    ):
                        self.stremio_writer(record_to_write)
                        stremio_write_count += 1
                    messages.append(f"Updated Stremio from Jellyfin for {item_key}.")
                else:
                    skipped_count += 1
            except Exception as exc:  # pragma: no cover - defensive summary boundary.
                error_count += 1
                messages.append(f"Failed to sync {item_key}: {exc}")

        return WatchProgressSyncSummary(
            jellyfin_read_count=len(self.jellyfin_records),
            stremio_read_count=len(self.stremio_records),
            matched_count=len(matched_keys),
            jellyfin_write_count=jellyfin_write_count,
            stremio_write_count=stremio_write_count,
            skipped_count=skipped_count,
            error_count=error_count,
            messages=messages,
        )


def sync_watch_progress(
    session: Session,
    *,
    settings: AppSettings | None = None,
) -> WatchProgressSyncSummary:
    resolved_settings = settings or SettingsService.get_or_create(session)
    operation = operation_status.start_operation(
        operation_type="watch_progress_sync",
        label="Syncing watch progress",
        total=4,
        message="Reading Jellyfin and Stremio watch progress.",
    )
    try:
        jellyfin_service = JellyfinService(resolved_settings)
        stremio_service = StremioService(resolved_settings)
        jellyfin_records = jellyfin_service.collect_watch_progress()
        operation_status.update_operation(
            operation.operation_id,
            current=1,
            message=f"Read {len(jellyfin_records)} Jellyfin progress item(s).",
        )
        stremio_records = stremio_service.collect_watch_progress()
        operation_status.update_operation(
            operation.operation_id,
            current=2,
            message=f"Read {len(stremio_records)} Stremio progress item(s).",
        )
        service = WatchProgressSyncService(
            jellyfin_records=jellyfin_records,
            stremio_records=stremio_records,
            jellyfin_writer=jellyfin_service.write_watch_progress,
            stremio_writer=stremio_service.write_watch_progress,
        )
        summary = service.sync()
        operation_status.update_operation(
            operation.operation_id,
            current=3,
            message=(
                f"Matched {summary.matched_count}; wrote {summary.jellyfin_write_count} "
                f"to Jellyfin and {summary.stremio_write_count} to Stremio."
            ),
        )
        if summary.error_count:
            operation_status.fail_operation(
                operation.operation_id,
                message="Watch progress sync finished with errors.",
                error="; ".join(summary.messages[-3:]) or "Watch progress sync failed.",
            )
        else:
            operation_status.complete_operation(
                operation.operation_id,
                message="Watch progress sync complete.",
            )
        return summary
    except Exception as exc:
        operation_status.fail_operation(
            operation.operation_id,
            message="Watch progress sync failed.",
            error=str(exc),
        )
        raise


def can_sync_watch_progress(settings: AppSettings | None) -> bool:
    if settings is None:
        return False
    jellyfin_config = SettingsService.resolve_jellyfin(settings)
    if not jellyfin_config.is_configured:
        return False
    try:
        return StremioService(settings).can_resolve_auth()
    except OSError:
        return False
