from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportBatch, QualityProfile, Rule
from app.schemas import ImportMode, ImportPreviewEntry, ImportResult
from app.services.rule_builder import extract_imdb_id_from_category, infer_media_type_from_category


@dataclass(slots=True)
class Importer:
    session: Session

    def preview_import_from_bytes(
        self,
        raw_bytes: bytes,
        *,
        mode: ImportMode,
    ) -> list[ImportPreviewEntry]:
        export = self._parse_export(raw_bytes)
        entries: list[ImportPreviewEntry] = []
        for rule_name, payload in export.items():
            action, resolved_name = self._resolve_action(rule_name, mode)
            category = str(payload.get("assignedCategory", "") or "")
            entries.append(
                ImportPreviewEntry(
                    rule_name=rule_name,
                    resolved_name=resolved_name,
                    action=action,
                    media_type=infer_media_type_from_category(category),
                    assigned_category=category,
                    imdb_id=extract_imdb_id_from_category(category),
                )
            )
        return entries

    def apply_import_from_bytes(
        self,
        raw_bytes: bytes,
        *,
        mode: ImportMode,
        source_name: str,
    ) -> ImportResult:
        export = self._parse_export(raw_bytes)
        preview = self.preview_import_from_bytes(raw_bytes, mode=mode)
        batch = ImportBatch(source_name=source_name, mode=mode.value)
        self.session.add(batch)

        imported_count = 0
        skipped_count = 0

        for entry in preview:
            payload = export[entry.rule_name]
            if entry.action == "skip":
                skipped_count += 1
                continue

            if entry.action == "overwrite":
                rule = self.session.scalar(select(Rule).where(Rule.rule_name == entry.rule_name))
                assert rule is not None
            else:
                rule = Rule(rule_name=entry.resolved_name, content_name=entry.rule_name, normalized_title=entry.rule_name)
                self.session.add(rule)

            self._apply_payload(rule, entry.rule_name, entry.resolved_name, payload)
            imported_count += 1

        batch.imported_count = imported_count
        batch.skipped_count = skipped_count
        self.session.commit()
        self.session.refresh(batch)

        return ImportResult(
            imported_count=imported_count,
            skipped_count=skipped_count,
            batch_id=batch.id,
            entries=preview,
        )

    @staticmethod
    def _parse_export(raw_bytes: bytes) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError("The uploaded file is not a valid JSON export.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Expected a top-level object keyed by rule name.")
        normalized: dict[str, dict[str, object]] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("Each export entry must be an object keyed by rule name.")
            normalized[key] = value
        return normalized

    def _resolve_action(self, rule_name: str, mode: ImportMode) -> tuple[str, str]:
        existing = self.session.scalar(select(Rule).where(Rule.rule_name == rule_name))
        if existing is None:
            return "create", rule_name
        if mode == ImportMode.SKIP:
            return "skip", rule_name
        if mode == ImportMode.OVERWRITE:
            return "overwrite", rule_name
        return "rename", self._next_available_name(rule_name)

    def _next_available_name(self, rule_name: str) -> str:
        suffix = 1
        candidate = f"{rule_name} (imported {suffix})"
        existing_names = {
            name
            for name in self.session.scalars(select(Rule.rule_name)).all()
        }
        while candidate in existing_names:
            suffix += 1
            candidate = f"{rule_name} (imported {suffix})"
        return candidate

    @staticmethod
    def _infer_quality_profile(pattern: str, use_regex: bool) -> QualityProfile:
        lowered = pattern.lower()
        if "2160p" in lowered or "4k" in lowered or "hdr" in lowered:
            return QualityProfile.UHD_2160P_HDR
        if "1080p" in lowered:
            return QualityProfile.HD_1080P
        if use_regex and pattern:
            return QualityProfile.CUSTOM
        return QualityProfile.PLAIN

    def _apply_payload(
        self,
        rule: Rule,
        source_name: str,
        resolved_name: str,
        payload: dict[str, object],
    ) -> None:
        category = str(payload.get("assignedCategory", "") or "")
        must_contain = str(payload.get("mustContain", "") or "")
        use_regex = bool(payload.get("useRegex", False))
        rule.rule_name = resolved_name
        rule.content_name = resolved_name
        rule.normalized_title = resolved_name
        rule.assigned_category = category
        rule.save_path = str(payload.get("savePath", "") or "")
        rule.release_year = ""
        rule.include_release_year = False
        rule.additional_includes = ""
        rule.quality_include_tokens = []
        rule.quality_exclude_tokens = []
        rule.feed_urls = self._clean_feeds(payload.get("affectedFeeds"))
        rule.enabled = bool(payload.get("enabled", True))
        rule.must_contain_override = must_contain or None
        rule.must_not_contain = str(payload.get("mustNotContain", "") or "")
        rule.use_regex = use_regex
        rule.episode_filter = str(payload.get("episodeFilter", "") or "")
        rule.ignore_days = self._coerce_int(payload.get("ignoreDays", 0), default=0)
        rule.add_paused = bool(payload.get("addPaused", True))
        rule.smart_filter = bool(payload.get("smartFilter", False))
        rule.media_type = infer_media_type_from_category(category)
        rule.imdb_id = extract_imdb_id_from_category(category)
        rule.quality_profile = self._infer_quality_profile(must_contain, use_regex)
        rule.last_sync_error = None

    @staticmethod
    def _coerce_int(raw_value: object, *, default: int) -> int:
        if isinstance(raw_value, bool):
            return int(raw_value)
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            return int(raw_value)
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
            if not cleaned:
                return default
            try:
                return int(cleaned)
            except ValueError:
                return default
        return default

    @staticmethod
    def _clean_feeds(raw_value: object) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        feeds: list[str] = []
        seen: set[str] = set()
        for item in raw_value:
            if not isinstance(item, str):
                continue
            cleaned = item.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            feeds.append(cleaned)
        return feeds
