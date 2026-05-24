from __future__ import annotations

import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AppSettings
from app.services.jellyfin import JellyfinRuleSyncOutcome, JellyfinRuleSyncSummary, JellyfinService
from app.services.operation_status import (
    complete_operation,
    fail_operation,
    start_operation,
    update_operation,
)
from app.services.settings_service import SettingsService
from app.services.sync import SyncService, SyncServiceError


class JellyfinSyncBusyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JellyfinSyncExecution:
    summary: JellyfinRuleSyncSummary
    qb_sync_success_count: int
    qb_sync_error_messages: list[str]
    qb_sync_skipped: bool

    @property
    def synced_outcomes(self) -> list[JellyfinRuleSyncOutcome]:
        return [outcome for outcome in self.summary.outcomes if outcome.status == "synced"]

    @property
    def message_level(self) -> str:
        if (
            self.summary.error_count > 0
            or self.qb_sync_skipped
            or self.qb_sync_error_messages
            or (self.summary.synced_count == 0 and self.summary.skipped_count > 0)
        ):
            return "warning"
        return "success"

    def detail_fragments(self) -> list[str]:
        fragments = [
            f"{self.summary.synced_count} updated",
            f"{self.summary.unchanged_count} unchanged",
            f"{self.summary.skipped_count} skipped",
            f"{self.summary.error_count} errors",
        ]
        if self.synced_outcomes and not self.qb_sync_skipped:
            fragments.append(f"{self.qb_sync_success_count} pushed to qB")
        if self.qb_sync_skipped:
            fragments.append("qB push skipped (qBittorrent not configured)")
        if self.qb_sync_error_messages:
            fragments.append(f"{len(self.qb_sync_error_messages)} qB push errors")
        return fragments

    def render_message(self, prefix: str = "Jellyfin sync completed for") -> str:
        return f'{prefix} "{self.summary.user_name}" ({", ".join(self.detail_fragments())}).'

    def top_errors(self, *, limit: int = 5) -> list[str]:
        errors = [
            f"{outcome.rule_name}: {outcome.message}"
            for outcome in self.summary.outcomes
            if outcome.status == "error"
        ]
        errors.extend(self.qb_sync_error_messages)
        return errors[:limit]


_SYNC_LOCK = threading.Lock()


def execute_jellyfin_sync(
    session: Session,
    *,
    settings: AppSettings | None,
    allow_metadata_requests: bool = True,
) -> JellyfinSyncExecution:
    if not _SYNC_LOCK.acquire(blocking=False):
        raise JellyfinSyncBusyError("Jellyfin sync is already in progress.")

    operation = start_operation(
        operation_type="jellyfin_sync",
        label="Syncing Jellyfin progress",
        message="Reading Jellyfin watch state.",
    )
    try:
        summary = JellyfinService(
            settings,
            allow_metadata_requests=allow_metadata_requests,
        ).sync_rules(session)
        qb_sync_success_count = 0
        qb_sync_error_messages: list[str] = []
        qb_sync_skipped = False

        synced_outcomes = [outcome for outcome in summary.outcomes if outcome.status == "synced"]
        if synced_outcomes:
            connection = SettingsService.resolve_qb_connection(settings)
            if connection.is_configured:
                sync_service = SyncService(session, settings)
                for outcome in synced_outcomes:
                    try:
                        sync_result = sync_service.sync_rule(outcome.rule_id)
                    except SyncServiceError as exc:
                        qb_sync_error_messages.append(f"{outcome.rule_name}: {exc}")
                        continue
                    if sync_result.success:
                        qb_sync_success_count += 1
                    else:
                        qb_sync_error_messages.append(f"{outcome.rule_name}: {sync_result.message}")
            else:
                qb_sync_skipped = True

        execution = JellyfinSyncExecution(
            summary=summary,
            qb_sync_success_count=qb_sync_success_count,
            qb_sync_error_messages=qb_sync_error_messages,
            qb_sync_skipped=qb_sync_skipped,
        )
        total = (
            summary.synced_count
            + summary.unchanged_count
            + summary.skipped_count
            + summary.error_count
        )
        if execution.message_level == "success":
            complete_operation(
                operation.operation_id,
                message=execution.render_message(),
            )
        else:
            complete_operation(
                operation.operation_id,
                status="warning",
                message=execution.render_message(),
            )
        update_operation(operation.operation_id, current=total, total=total)
        return execution
    except Exception as exc:
        fail_operation(
            operation.operation_id,
            message="Jellyfin sync failed.",
            error=str(exc),
        )
        raise
    finally:
        _SYNC_LOCK.release()
