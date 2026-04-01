from __future__ import annotations

import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AppSettings
from app.services.settings_service import SettingsService
from app.services.stremio import StremioRuleSyncOutcome, StremioRuleSyncSummary, StremioService
from app.services.sync import SyncService, SyncServiceError


class StremioSyncBusyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StremioSyncExecution:
    summary: StremioRuleSyncSummary
    qb_sync_success_count: int
    qb_sync_error_messages: list[str]
    qb_sync_skipped: bool

    @property
    def synced_outcomes(self) -> list[StremioRuleSyncOutcome]:
        return [outcome for outcome in self.summary.outcomes if outcome.changed]

    @property
    def message_level(self) -> str:
        if (
            self.summary.error_count > 0
            or self.qb_sync_skipped
            or self.qb_sync_error_messages
            or (not self.synced_outcomes and self.summary.skipped_count > 0)
        ):
            return "warning"
        return "success"

    def detail_fragments(self) -> list[str]:
        fragments = [
            f"{self.summary.created_count} created",
            f"{self.summary.linked_count} linked",
            f"{self.summary.updated_count} updated",
            f"{self.summary.disabled_count} disabled",
            f"{self.summary.reenabled_count} re-enabled",
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

    def render_message(self, prefix: str = "Stremio sync completed") -> str:
        return (
            f"{prefix} for {self.summary.active_item_count} active title(s) "
            f"({', '.join(self.detail_fragments())})."
        )

    def top_errors(self, *, limit: int = 5) -> list[str]:
        errors = [
            f"{outcome.rule_name}: {outcome.message}"
            for outcome in self.summary.outcomes
            if outcome.status == "error"
        ]
        errors.extend(self.qb_sync_error_messages)
        return errors[:limit]


_SYNC_LOCK = threading.Lock()


def execute_stremio_sync(
    session: Session,
    *,
    settings: AppSettings | None,
) -> StremioSyncExecution:
    if not _SYNC_LOCK.acquire(blocking=False):
        raise StremioSyncBusyError("Stremio sync is already in progress.")

    try:
        summary = StremioService(settings).sync_rules(session)
        qb_sync_success_count = 0
        qb_sync_error_messages: list[str] = []
        qb_sync_skipped = False

        synced_outcomes = [
            outcome for outcome in summary.outcomes if outcome.changed and outcome.rule_id
        ]
        if synced_outcomes:
            connection = SettingsService.resolve_qb_connection(settings)
            if connection.is_configured:
                sync_service = SyncService(session, settings)
                for outcome in synced_outcomes:
                    try:
                        sync_result = sync_service.sync_rule(str(outcome.rule_id))
                    except SyncServiceError as exc:
                        qb_sync_error_messages.append(f"{outcome.rule_name}: {exc}")
                        continue
                    if sync_result.success:
                        qb_sync_success_count += 1
                    else:
                        qb_sync_error_messages.append(f"{outcome.rule_name}: {sync_result.message}")
            else:
                qb_sync_skipped = True

        return StremioSyncExecution(
            summary=summary,
            qb_sync_success_count=qb_sync_success_count,
            qb_sync_error_messages=qb_sync_error_messages,
            qb_sync_skipped=qb_sync_skipped,
        )
    finally:
        _SYNC_LOCK.release()
