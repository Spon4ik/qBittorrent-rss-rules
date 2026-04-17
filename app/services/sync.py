from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_environment_settings
from app.models import AppSettings, Rule, RuleSearchSnapshot, SyncEvent, SyncStatus, utcnow
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
        if (
            rule.remote_rule_name_last_synced
            and rule.remote_rule_name_last_synced != rule.rule_name
        ):
            action = "rename"

        builder = RuleBuilder(self.app_settings)
        qb_rule = builder.build_qb_rule(rule)
        qb_rule, feed_warnings = self._filter_unhealthy_jackett_feeds(qb_rule)

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
                client.set_rule(rule.rule_name, qb_rule)
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
        message = "Rule synced to qBittorrent."
        if feed_warnings:
            message = f"{message} {' '.join(feed_warnings)}"
        return SyncResult(
            success=True,
            action=action,
            rule_id=rule.id,
            rule_name=rule.rule_name,
            message=message,
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
        snapshot = self.session.get(RuleSearchSnapshot, rule_id)
        if snapshot is not None:
            self.session.delete(snapshot)
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

    def _filter_unhealthy_jackett_feeds(
        self,
        rule_def: dict[str, object],
    ) -> tuple[dict[str, object], list[str]]:
        raw_feed_urls = rule_def.get("affectedFeeds")
        if not isinstance(raw_feed_urls, list):
            return rule_def, []
        feed_urls = [
            str(item or "").strip()
            for item in raw_feed_urls
            if str(item or "").strip()
        ]
        if not feed_urls:
            return rule_def, []

        healthy_feed_urls: list[str] = []
        skipped_hosts: list[str] = []
        for feed_url in feed_urls:
            if self._jackett_feed_sample_download_works(feed_url):
                healthy_feed_urls.append(feed_url)
                continue
            skipped_hosts.append(self._feed_label(feed_url))

        if not skipped_hosts:
            return rule_def, []
        if healthy_feed_urls:
            updated_rule_def = dict(rule_def)
            updated_rule_def["affectedFeeds"] = healthy_feed_urls
            skipped_label = ", ".join(skipped_hosts[:5])
            extra = len(skipped_hosts) - min(len(skipped_hosts), 5)
            if extra > 0:
                skipped_label = f"{skipped_label} (+{extra} more)"
            return updated_rule_def, [
                f"Skipped Jackett feeds with broken sample downloads: {skipped_label}."
            ]
        return rule_def, []

    def _jackett_feed_sample_download_works(self, feed_url: str) -> bool:
        timeout = min(float(get_environment_settings().request_timeout), 15.0)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.get(feed_url)
                response.raise_for_status()
                root = ET.fromstring(response.text)
                item = root.find("./channel/item")
                if item is None:
                    return True
                enclosure = item.find("enclosure")
                download_url = ""
                if enclosure is not None:
                    download_url = str(enclosure.attrib.get("url") or "").strip()
                if not download_url:
                    download_url = str(item.findtext("link") or "").strip()
                if not download_url:
                    return True
                download_response = client.get(download_url)
                return download_response.status_code < 400
        except (httpx.HTTPError, ET.ParseError):
            return False

    @staticmethod
    def _feed_label(feed_url: str) -> str:
        parsed = httpx.URL(feed_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        try:
            index = segments.index("indexers")
        except ValueError:
            return feed_url
        if index + 1 < len(segments):
            return segments[index + 1]
        return feed_url
