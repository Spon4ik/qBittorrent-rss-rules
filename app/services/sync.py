from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings, Rule, SyncEvent, SyncStatus, utcnow
from app.schemas import BatchSyncResult, SyncResult
from app.services.qbittorrent import QbittorrentClient, QbittorrentClientError
from app.services.rule_builder import RuleBuilder
from app.services.settings_service import SettingsService


class SyncServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class SyncService:
    session: Session
    app_settings: AppSettings | None

    def sync_rule(self, rule_id: str) -> SyncResult:
        rule = self.session.get(Rule, rule_id)
        if rule is None:
            raise SyncServiceError("Rule not found.")

        action = "create" if not rule.remote_rule_name_last_synced else "update"
        if rule.remote_rule_name_last_synced and rule.remote_rule_name_last_synced != rule.rule_name:
            action = "rename"

        builder = RuleBuilder(self.app_settings)

        try:
            with self._qb_client() as client:
                category = builder.render_category(rule)
                if category:
                    client.create_category(category)
                if (
                    rule.remote_rule_name_last_synced
                    and rule.remote_rule_name_last_synced != rule.rule_name
                ):
                    client.remove_rule(rule.remote_rule_name_last_synced)
                client.set_rule(rule.rule_name, builder.build_qb_rule(rule))
        except (QbittorrentClientError, SyncServiceError) as exc:
            rule.last_sync_status = SyncStatus.ERROR
            rule.last_sync_error = str(exc)
            self._record_event(rule, action=action, status="error", error_message=str(exc))
            self.session.commit()
            return SyncResult(
                success=False,
                action=action,
                rule_id=rule.id,
                rule_name=rule.rule_name,
                message=str(exc),
            )

        rule.remote_rule_name_last_synced = rule.rule_name
        rule.last_sync_status = SyncStatus.OK
        rule.last_sync_error = None
        rule.last_synced_at = utcnow()
        self._record_event(rule, action=action, status="ok", error_message=None)
        self.session.commit()
        return SyncResult(
            success=True,
            action=action,
            rule_id=rule.id,
            rule_name=rule.rule_name,
            message="Rule synced to qBittorrent.",
        )

    def sync_all(self) -> BatchSyncResult:
        result = BatchSyncResult()
        rules = self.session.scalars(select(Rule).order_by(Rule.rule_name.asc())).all()
        remote_rules = self._safe_remote_rules()

        for rule in rules:
            if remote_rules is not None and rule.rule_name in remote_rules:
                expected = RuleBuilder(self.app_settings).build_qb_rule(rule)
                if remote_rules[rule.rule_name] != expected:
                    result.drift_detected += 1
            sync_result = self.sync_rule(rule.id)
            if sync_result.success:
                result.success_count += 1
            else:
                result.error_count += 1
                result.messages.append(sync_result.message)
        return result

    def delete_rule(self, rule_id: str) -> SyncResult:
        rule = self.session.get(Rule, rule_id)
        if rule is None:
            raise SyncServiceError("Rule not found.")

        remote_name = rule.remote_rule_name_last_synced or rule.rule_name
        try:
            with self._qb_client() as client:
                client.remove_rule(remote_name)
        except (QbittorrentClientError, SyncServiceError) as exc:
            rule.last_sync_status = SyncStatus.ERROR
            rule.last_sync_error = str(exc)
            self._record_event(rule, action="delete", status="error", error_message=str(exc))
            self.session.commit()
            return SyncResult(
                success=False,
                action="delete",
                rule_id=rule.id,
                rule_name=rule.rule_name,
                message=str(exc),
            )

        self._record_event(rule, action="delete", status="ok", error_message=None)
        deleted_name = rule.rule_name
        deleted_id = rule.id
        self.session.delete(rule)
        self.session.commit()
        return SyncResult(
            success=True,
            action="delete",
            rule_id=deleted_id,
            rule_name=deleted_name,
            message="Rule deleted locally and remotely.",
        )

    def delete_remote_rule(self, rule_name: str) -> None:
        with self._qb_client() as client:
            client.remove_rule(rule_name)

    def _record_event(
        self,
        rule: Rule,
        *,
        action: str,
        status: str,
        error_message: str | None,
    ) -> None:
        self.session.add(
            SyncEvent(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                action=action,
                status=status,
                error_message=error_message,
            )
        )

    def _qb_client(self) -> QbittorrentClient:
        connection = SettingsService.resolve_qb_connection(self.app_settings)
        if not connection.is_configured:
            raise SyncServiceError("qBittorrent connection is not configured.")
        return QbittorrentClient(
            connection.base_url,
            connection.username,
            connection.password,
        )

    def _safe_remote_rules(self) -> dict[str, dict[str, object]] | None:
        try:
            with self._qb_client() as client:
                return client.get_rules()
        except (QbittorrentClientError, SyncServiceError):
            return None
