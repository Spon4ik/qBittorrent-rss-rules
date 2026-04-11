from __future__ import annotations

import json
import platform
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.config import get_environment_settings, obfuscate_secret, reveal_secret
from app.models import AppSettings, MetadataProvider, QualityProfile
from app.schemas import SettingsFormPayload
from app.services.quality_filters import (
    DEFAULT_QUALITY_PROFILE_RULES,
    LEGACY_DEFAULT_QUALITY_PROFILE_RULES,
    builtin_filter_profile_keys,
    canonicalize_quality_tokens,
    normalize_saved_quality_profiles,
    resolve_quality_profile_rules,
)

SEARCH_RESULT_VIEW_MODES = frozenset({"cards", "table"})
SEARCH_SORT_FIELDS = frozenset(
    {
        "published_at",
        "seeders",
        "peers",
        "leechers",
        "grabs",
        "size_bytes",
        "year",
        "indexer",
        "title",
    }
)
DEFAULT_SEARCH_RESULT_VIEW_MODE = "table"
DEFAULT_SEARCH_SORT_CRITERIA = [{"field": "published_at", "direction": "desc"}]
RULES_PAGE_VIEW_MODES = frozenset({"table", "cards"})
RULES_PAGE_SORT_FIELDS = frozenset(
    {
        "updated_at",
        "rule_name",
        "media_type",
        "last_sync_status",
        "enabled",
        "release_state",
        "exact_filtered_count",
        "combined_filtered_count",
        "combined_fetched_count",
        "last_snapshot_at",
    }
)
RULES_PAGE_SORT_DIRECTIONS = frozenset({"asc", "desc"})
DEFAULT_RULES_PAGE_VIEW_MODE = "table"
DEFAULT_RULES_PAGE_SORT_FIELD = "updated_at"
DEFAULT_RULES_PAGE_SORT_DIRECTION = "desc"
RULE_FETCH_SCHEDULE_SCOPES = frozenset({"enabled", "all"})
DEFAULT_RULE_FETCH_SCHEDULE_SCOPE = "enabled"
DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 360
MIN_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 5
MAX_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES = 10080
DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED = True
DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS = 30
MIN_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS = 5
MAX_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS = 3600
DEFAULT_STREMIO_AUTO_SYNC_ENABLED = True
DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS = 30
MIN_STREMIO_AUTO_SYNC_INTERVAL_SECONDS = 5
MAX_STREMIO_AUTO_SYNC_INTERVAL_SECONDS = 3600
STREMIO_LANGUAGE_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "en": ("en", "eng", "english"),
    "ru": ("ru", "rus", "russian"),
    "he": ("he", "heb", "hebrew"),
    "multi": ("multi",),
}
STREMIO_STREAM_PROVIDER_ENTRY_START_RE = re.compile(
    r"(?:^|,)\s*(?:(?P<label>[^,\n|]+)\|)?https?://",
    re.IGNORECASE,
)


def _is_wsl_runtime() -> bool:
    release = platform.release().casefold()
    version = platform.version().casefold()
    return "microsoft" in release or "wsl" in release or "microsoft" in version or "wsl" in version


def _rewrite_localhost_url_for_wsl(base_url: str | None) -> str | None:
    cleaned = str(base_url or "").strip()
    if not cleaned:
        return None
    if not _is_wsl_runtime():
        return cleaned

    parsed = urlsplit(cleaned)
    hostname = (parsed.hostname or "").casefold()
    if hostname not in {"localhost", "127.0.0.1"}:
        return cleaned

    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        auth += "@"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{auth}host.docker.internal{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_search_result_view_mode(value: object | None) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in SEARCH_RESULT_VIEW_MODES:
        return cleaned
    return DEFAULT_SEARCH_RESULT_VIEW_MODE


def normalize_search_sort_criteria(value: object | None) -> list[dict[str, str]]:
    raw_items: list[object]
    if value is None or value == "":
        raw_items = []
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raw_items = []
        else:
            try:
                loaded = json.loads(cleaned)
            except ValueError:
                raw_items = []
            else:
                raw_items = loaded if isinstance(loaded, list) else []
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    normalized: list[dict[str, str]] = []
    seen_fields: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        field = str(raw_item.get("field", "")).strip()
        if field not in SEARCH_SORT_FIELDS or field in seen_fields:
            continue
        direction = str(raw_item.get("direction", "asc")).strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "asc"
        normalized.append({"field": field, "direction": direction})
        seen_fields.add(field)
        if len(normalized) >= 3:
            break

    if normalized:
        return normalized
    return [dict(item) for item in DEFAULT_SEARCH_SORT_CRITERIA]


def normalize_rules_page_view_mode(value: object | None) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in RULES_PAGE_VIEW_MODES:
        return cleaned
    return DEFAULT_RULES_PAGE_VIEW_MODE


def normalize_rules_page_sort_field(value: object | None) -> str:
    cleaned = str(value or "").strip()
    if cleaned in RULES_PAGE_SORT_FIELDS:
        return cleaned
    return DEFAULT_RULES_PAGE_SORT_FIELD


def normalize_rules_page_sort_direction(value: object | None) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in RULES_PAGE_SORT_DIRECTIONS:
        return cleaned
    return DEFAULT_RULES_PAGE_SORT_DIRECTION


def normalize_rule_fetch_schedule_scope(value: object | None) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in RULE_FETCH_SCHEDULE_SCOPES:
        return cleaned
    return DEFAULT_RULE_FETCH_SCHEDULE_SCOPE


def normalize_rule_fetch_schedule_interval_minutes(value: object | None) -> int:
    if value is None:
        return DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES
    return max(
        MIN_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
        min(MAX_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES, numeric),
    )


def normalize_jellyfin_auto_sync_interval_seconds(value: object | None) -> int:
    if value is None:
        return DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS
    return max(
        MIN_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
        min(MAX_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS, numeric),
    )


def normalize_stremio_auto_sync_interval_seconds(value: object | None) -> int:
    if value is None:
        return DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS
    return max(
        MIN_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
        min(MAX_STREMIO_AUTO_SYNC_INTERVAL_SECONDS, numeric),
    )


@dataclass(frozen=True, slots=True)
class ResolvedQbConnection:
    base_url: str | None
    username: str | None
    password: str | None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)


@dataclass(frozen=True, slots=True)
class ResolvedMetadataConfig:
    provider: MetadataProvider
    api_key: str | None

    @property
    def enabled(self) -> bool:
        return self.provider != MetadataProvider.DISABLED


@dataclass(frozen=True, slots=True)
class ResolvedJackettConfig:
    api_url: str | None
    qb_url: str | None
    api_key: str | None

    @property
    def app_ready(self) -> bool:
        return bool(self.api_url and self.api_key)

    @property
    def rule_ready(self) -> bool:
        return bool((self.qb_url or self.api_url) and self.api_key)


@dataclass(frozen=True, slots=True)
class ResolvedJellyfinConfig:
    db_path: str | None
    user_name: str | None
    auto_sync_enabled: bool
    auto_sync_interval_seconds: int

    @property
    def is_configured(self) -> bool:
        return bool(self.db_path)


@dataclass(frozen=True, slots=True)
class ResolvedStremioConfig:
    local_storage_path: str | None
    auth_key: str | None
    preferred_languages: tuple[str, ...]
    auto_sync_enabled: bool
    auto_sync_interval_seconds: int

    @property
    def has_explicit_auth_key(self) -> bool:
        return bool(self.auth_key)

    @property
    def is_configured(self) -> bool:
        return bool(self.auth_key or self.local_storage_path)


@dataclass(frozen=True, slots=True)
class ResolvedStremioStreamProvider:
    manifest_url: str
    label: str | None = None


class SettingsService:
    @staticmethod
    def _split_stream_provider_entries(raw_value: str) -> tuple[str, ...]:
        normalized_lines = [
            str(line or "").strip()
            for line in str(raw_value or "").replace("\r", "\n").split("\n")
            if str(line or "").strip()
        ]
        entries: list[str] = []
        for line in normalized_lines:
            start_matches = list(STREMIO_STREAM_PROVIDER_ENTRY_START_RE.finditer(line))
            if len(start_matches) <= 1:
                entries.append(line)
                continue
            for index, match in enumerate(start_matches):
                entry_start = match.start()
                if line[entry_start] == ",":
                    entry_start += 1
                entry_end = (
                    start_matches[index + 1].start() if index + 1 < len(start_matches) else len(line)
                )
                candidate = line[entry_start:entry_end].strip().strip(",").strip()
                if candidate:
                    entries.append(candidate)
        return tuple(entries)

    @staticmethod
    def normalize_stremio_preferred_languages(value: object | None) -> tuple[str, ...]:
        cleaned_value = str(value or "").strip()
        if not cleaned_value:
            return ()
        normalized_languages: list[str] = []
        seen_languages: set[str] = set()
        for raw_token in (
            cleaned_value.replace("\r", "\n").replace(",", "\n").replace(";", "\n").split("\n")
        ):
            token = str(raw_token or "").strip().casefold()
            if not token:
                continue
            normalized_token = token
            for language_code, aliases in STREMIO_LANGUAGE_TOKEN_ALIASES.items():
                if token == language_code or token in aliases:
                    normalized_token = language_code
                    break
            if normalized_token in seen_languages:
                continue
            seen_languages.add(normalized_token)
            normalized_languages.append(normalized_token)
        return tuple(normalized_languages)

    @staticmethod
    def resolve_stremio_stream_providers(
        settings: AppSettings | None = None,
    ) -> tuple[ResolvedStremioStreamProvider, ...]:
        raw_value = str(
            get_environment_settings().stremio_stream_provider_manifests
            or getattr(settings, "stremio_stream_provider_manifests", None)
            or ""
        ).strip()
        if not raw_value:
            return ()
        providers: list[ResolvedStremioStreamProvider] = []
        seen_manifest_urls: set[str] = set()
        normalized_entries = SettingsService._split_stream_provider_entries(raw_value)
        for raw_entry in normalized_entries:
            cleaned_entry = str(raw_entry or "").strip()
            if not cleaned_entry:
                continue
            label: str | None = None
            manifest_url = cleaned_entry
            if "|" in cleaned_entry:
                raw_label, raw_manifest_url = cleaned_entry.split("|", 1)
                label = str(raw_label or "").strip() or None
                manifest_url = str(raw_manifest_url or "").strip()
            if not manifest_url:
                continue
            normalized_manifest_url = manifest_url.rstrip("/")
            dedupe_key = normalized_manifest_url.casefold()
            if dedupe_key in seen_manifest_urls:
                continue
            seen_manifest_urls.add(dedupe_key)
            providers.append(
                ResolvedStremioStreamProvider(
                    manifest_url=normalized_manifest_url,
                    label=label,
                )
            )
        return tuple(providers)

    @staticmethod
    def get_or_create(session: Session) -> AppSettings:
        settings = session.get(AppSettings, "default")
        if settings is None:
            settings = AppSettings(
                id="default",
                quality_profile_rules=deepcopy(DEFAULT_QUALITY_PROFILE_RULES),
                saved_quality_profiles={},
                default_quality_profile=QualityProfile.UHD_2160P_HDR,
                jellyfin_auto_sync_enabled=DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED,
                jellyfin_auto_sync_interval_seconds=DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
                jellyfin_auto_sync_last_status="idle",
                jellyfin_auto_sync_last_message="",
                stremio_auto_sync_enabled=DEFAULT_STREMIO_AUTO_SYNC_ENABLED,
                stremio_auto_sync_interval_seconds=DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
                stremio_auto_sync_last_status="idle",
                stremio_auto_sync_last_message="",
                default_sequential_download=True,
                default_first_last_piece_prio=True,
                search_result_view_mode=DEFAULT_SEARCH_RESULT_VIEW_MODE,
                search_sort_criteria=[dict(item) for item in DEFAULT_SEARCH_SORT_CRITERIA],
                rules_fetch_schedule_enabled=False,
                rules_fetch_schedule_interval_minutes=DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
                rules_fetch_schedule_scope=DEFAULT_RULE_FETCH_SCHEDULE_SCOPE,
                rules_fetch_schedule_last_status="idle",
                rules_fetch_schedule_last_message="",
                rules_page_view_mode=DEFAULT_RULES_PAGE_VIEW_MODE,
                rules_page_sort_field=DEFAULT_RULES_PAGE_SORT_FIELD,
                rules_page_sort_direction=DEFAULT_RULES_PAGE_SORT_DIRECTION,
            )
            session.add(settings)
            session.commit()
            session.refresh(settings)
            return settings

        legacy_profile_defaults = not settings.quality_profile_rules
        changed = False
        if legacy_profile_defaults:
            settings.quality_profile_rules = deepcopy(DEFAULT_QUALITY_PROFILE_RULES)
            changed = True
            if settings.default_quality_profile == QualityProfile.PLAIN:
                settings.default_quality_profile = QualityProfile.UHD_2160P_HDR
                changed = True
        else:
            normalized_profile_rules = resolve_quality_profile_rules(settings)
            for profile_key in (QualityProfile.HD_1080P.value, QualityProfile.UHD_2160P_HDR.value):
                if canonicalize_quality_tokens(
                    normalized_profile_rules[profile_key]["include_tokens"]
                ) != canonicalize_quality_tokens(
                    LEGACY_DEFAULT_QUALITY_PROFILE_RULES[profile_key]["include_tokens"]
                ):
                    continue
                if canonicalize_quality_tokens(
                    normalized_profile_rules[profile_key]["exclude_tokens"]
                ) != canonicalize_quality_tokens(
                    LEGACY_DEFAULT_QUALITY_PROFILE_RULES[profile_key]["exclude_tokens"]
                ):
                    continue
                normalized_profile_rules[profile_key] = deepcopy(
                    DEFAULT_QUALITY_PROFILE_RULES[profile_key]
                )
                changed = True
            if changed:
                settings.quality_profile_rules = normalized_profile_rules
        normalized_saved_profiles = normalize_saved_quality_profiles(
            settings.saved_quality_profiles
        )
        if normalized_saved_profiles != settings.saved_quality_profiles:
            settings.saved_quality_profiles = normalized_saved_profiles
            changed = True
        normalized_default_feeds = [
            str(url).strip() for url in (settings.default_feed_urls or []) if str(url).strip()
        ]
        if normalized_default_feeds != (settings.default_feed_urls or []):
            settings.default_feed_urls = normalized_default_feeds
            changed = True
        normalized_jellyfin_db_path = (
            str(getattr(settings, "jellyfin_db_path", "") or "").strip() or None
        )
        if normalized_jellyfin_db_path != getattr(settings, "jellyfin_db_path", None):
            settings.jellyfin_db_path = normalized_jellyfin_db_path
            changed = True
        normalized_jellyfin_user_name = (
            str(getattr(settings, "jellyfin_user_name", "") or "").strip() or None
        )
        if normalized_jellyfin_user_name != getattr(settings, "jellyfin_user_name", None):
            settings.jellyfin_user_name = normalized_jellyfin_user_name
            changed = True
        normalized_jellyfin_auto_sync_enabled = bool(
            getattr(settings, "jellyfin_auto_sync_enabled", DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED)
        )
        if normalized_jellyfin_auto_sync_enabled != getattr(
            settings, "jellyfin_auto_sync_enabled", None
        ):
            settings.jellyfin_auto_sync_enabled = normalized_jellyfin_auto_sync_enabled
            changed = True
        normalized_jellyfin_auto_sync_interval = normalize_jellyfin_auto_sync_interval_seconds(
            getattr(
                settings,
                "jellyfin_auto_sync_interval_seconds",
                DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
            )
        )
        if normalized_jellyfin_auto_sync_interval != getattr(
            settings,
            "jellyfin_auto_sync_interval_seconds",
            None,
        ):
            settings.jellyfin_auto_sync_interval_seconds = normalized_jellyfin_auto_sync_interval
            changed = True
        normalized_jellyfin_auto_sync_status = (
            str(getattr(settings, "jellyfin_auto_sync_last_status", "idle") or "idle")
            .strip()
            .lower()
        )
        if not normalized_jellyfin_auto_sync_status:
            normalized_jellyfin_auto_sync_status = "idle"
        if normalized_jellyfin_auto_sync_status != getattr(
            settings,
            "jellyfin_auto_sync_last_status",
            None,
        ):
            settings.jellyfin_auto_sync_last_status = normalized_jellyfin_auto_sync_status
            changed = True
        normalized_jellyfin_auto_sync_message = str(
            getattr(settings, "jellyfin_auto_sync_last_message", "") or ""
        )
        if normalized_jellyfin_auto_sync_message != getattr(
            settings,
            "jellyfin_auto_sync_last_message",
            None,
        ):
            settings.jellyfin_auto_sync_last_message = normalized_jellyfin_auto_sync_message
            changed = True
        normalized_stremio_storage_path = (
            str(getattr(settings, "stremio_local_storage_path", "") or "").strip() or None
        )
        if normalized_stremio_storage_path != getattr(settings, "stremio_local_storage_path", None):
            settings.stremio_local_storage_path = normalized_stremio_storage_path
            changed = True
        normalized_stremio_preferred_languages = (
            ",".join(
                SettingsService.normalize_stremio_preferred_languages(
                    getattr(settings, "stremio_preferred_languages", None)
                )
            )
            or None
        )
        if normalized_stremio_preferred_languages != getattr(
            settings, "stremio_preferred_languages", None
        ):
            settings.stremio_preferred_languages = normalized_stremio_preferred_languages
            changed = True
        normalized_stream_provider_manifests = (
            str(getattr(settings, "stremio_stream_provider_manifests", "") or "").strip() or None
        )
        if normalized_stream_provider_manifests != getattr(
            settings, "stremio_stream_provider_manifests", None
        ):
            settings.stremio_stream_provider_manifests = normalized_stream_provider_manifests
            changed = True
        normalized_stremio_auto_sync_enabled = bool(
            getattr(settings, "stremio_auto_sync_enabled", DEFAULT_STREMIO_AUTO_SYNC_ENABLED)
        )
        if normalized_stremio_auto_sync_enabled != getattr(
            settings,
            "stremio_auto_sync_enabled",
            None,
        ):
            settings.stremio_auto_sync_enabled = normalized_stremio_auto_sync_enabled
            changed = True
        normalized_stremio_auto_sync_interval = normalize_stremio_auto_sync_interval_seconds(
            getattr(
                settings,
                "stremio_auto_sync_interval_seconds",
                DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
            )
        )
        if normalized_stremio_auto_sync_interval != getattr(
            settings,
            "stremio_auto_sync_interval_seconds",
            None,
        ):
            settings.stremio_auto_sync_interval_seconds = normalized_stremio_auto_sync_interval
            changed = True
        normalized_stremio_auto_sync_status = (
            str(getattr(settings, "stremio_auto_sync_last_status", "idle") or "idle")
            .strip()
            .lower()
        )
        if not normalized_stremio_auto_sync_status:
            normalized_stremio_auto_sync_status = "idle"
        if normalized_stremio_auto_sync_status != getattr(
            settings,
            "stremio_auto_sync_last_status",
            None,
        ):
            settings.stremio_auto_sync_last_status = normalized_stremio_auto_sync_status
            changed = True
        normalized_stremio_auto_sync_message = str(
            getattr(settings, "stremio_auto_sync_last_message", "") or ""
        )
        if normalized_stremio_auto_sync_message != getattr(
            settings,
            "stremio_auto_sync_last_message",
            None,
        ):
            settings.stremio_auto_sync_last_message = normalized_stremio_auto_sync_message
            changed = True
        default_sequential_value = getattr(settings, "default_sequential_download", True)
        normalized_default_sequential = (
            True if default_sequential_value is None else bool(default_sequential_value)
        )
        if normalized_default_sequential != default_sequential_value:
            settings.default_sequential_download = normalized_default_sequential
            changed = True
        default_first_last_value = getattr(settings, "default_first_last_piece_prio", True)
        normalized_default_first_last = (
            True if default_first_last_value is None else bool(default_first_last_value)
        )
        if normalized_default_first_last != default_first_last_value:
            settings.default_first_last_piece_prio = normalized_default_first_last
            changed = True
        normalized_view_mode = normalize_search_result_view_mode(
            getattr(settings, "search_result_view_mode", DEFAULT_SEARCH_RESULT_VIEW_MODE)
        )
        if normalized_view_mode != settings.search_result_view_mode:
            settings.search_result_view_mode = normalized_view_mode
            changed = True
        normalized_sort_criteria = normalize_search_sort_criteria(
            getattr(settings, "search_sort_criteria", DEFAULT_SEARCH_SORT_CRITERIA)
        )
        if normalized_sort_criteria != list(settings.search_sort_criteria or []):
            settings.search_sort_criteria = normalized_sort_criteria
            changed = True
        normalized_rules_page_view_mode = normalize_rules_page_view_mode(
            getattr(settings, "rules_page_view_mode", DEFAULT_RULES_PAGE_VIEW_MODE)
        )
        if normalized_rules_page_view_mode != getattr(settings, "rules_page_view_mode", None):
            settings.rules_page_view_mode = normalized_rules_page_view_mode
            changed = True
        normalized_rules_page_sort_field = normalize_rules_page_sort_field(
            getattr(settings, "rules_page_sort_field", DEFAULT_RULES_PAGE_SORT_FIELD)
        )
        if normalized_rules_page_sort_field != getattr(settings, "rules_page_sort_field", None):
            settings.rules_page_sort_field = normalized_rules_page_sort_field
            changed = True
        normalized_rules_page_sort_direction = normalize_rules_page_sort_direction(
            getattr(settings, "rules_page_sort_direction", DEFAULT_RULES_PAGE_SORT_DIRECTION)
        )
        if normalized_rules_page_sort_direction != getattr(
            settings, "rules_page_sort_direction", None
        ):
            settings.rules_page_sort_direction = normalized_rules_page_sort_direction
            changed = True
        normalized_schedule_scope = normalize_rule_fetch_schedule_scope(
            getattr(settings, "rules_fetch_schedule_scope", DEFAULT_RULE_FETCH_SCHEDULE_SCOPE)
        )
        if normalized_schedule_scope != getattr(settings, "rules_fetch_schedule_scope", None):
            settings.rules_fetch_schedule_scope = normalized_schedule_scope
            changed = True
        normalized_schedule_interval = normalize_rule_fetch_schedule_interval_minutes(
            getattr(
                settings,
                "rules_fetch_schedule_interval_minutes",
                DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
            )
        )
        if normalized_schedule_interval != getattr(
            settings, "rules_fetch_schedule_interval_minutes", None
        ):
            settings.rules_fetch_schedule_interval_minutes = normalized_schedule_interval
            changed = True
        normalized_schedule_enabled = bool(getattr(settings, "rules_fetch_schedule_enabled", False))
        if normalized_schedule_enabled != getattr(settings, "rules_fetch_schedule_enabled", None):
            settings.rules_fetch_schedule_enabled = normalized_schedule_enabled
            changed = True
        normalized_schedule_status = (
            str(getattr(settings, "rules_fetch_schedule_last_status", "idle") or "idle")
            .strip()
            .lower()
        )
        if not normalized_schedule_status:
            normalized_schedule_status = "idle"
        if normalized_schedule_status != getattr(
            settings, "rules_fetch_schedule_last_status", None
        ):
            settings.rules_fetch_schedule_last_status = normalized_schedule_status
            changed = True
        normalized_schedule_message = str(
            getattr(settings, "rules_fetch_schedule_last_message", "") or ""
        )
        if normalized_schedule_message != getattr(
            settings, "rules_fetch_schedule_last_message", None
        ):
            settings.rules_fetch_schedule_last_message = normalized_schedule_message
            changed = True
        if changed:
            session.add(settings)
            session.commit()
            session.refresh(settings)
        return settings

    @staticmethod
    def apply_payload(settings: AppSettings, payload: SettingsFormPayload) -> AppSettings:
        settings.qb_base_url = payload.qb_base_url or None
        settings.qb_username = payload.qb_username or None
        settings.jackett_api_url = payload.jackett_api_url or None
        settings.jackett_qb_url = payload.jackett_qb_url or None
        settings.jellyfin_db_path = payload.jellyfin_db_path or None
        settings.jellyfin_user_name = payload.jellyfin_user_name or None
        settings.jellyfin_auto_sync_enabled = payload.jellyfin_auto_sync_enabled
        settings.jellyfin_auto_sync_interval_seconds = payload.jellyfin_auto_sync_interval_seconds
        settings.stremio_local_storage_path = payload.stremio_local_storage_path or None
        settings.stremio_preferred_languages = (
            ",".join(SettingsService.normalize_stremio_preferred_languages(payload.stremio_preferred_languages))
            or None
        )
        settings.stremio_stream_provider_manifests = (
            str(payload.stremio_stream_provider_manifests or "").strip() or None
        )
        settings.stremio_auto_sync_enabled = payload.stremio_auto_sync_enabled
        settings.stremio_auto_sync_interval_seconds = payload.stremio_auto_sync_interval_seconds
        settings.metadata_provider = payload.metadata_provider
        settings.series_category_template = payload.series_category_template
        settings.movie_category_template = payload.movie_category_template
        settings.save_path_template = payload.save_path_template
        settings.default_add_paused = payload.default_add_paused
        settings.default_sequential_download = payload.default_sequential_download
        settings.default_first_last_piece_prio = payload.default_first_last_piece_prio
        settings.default_enabled = payload.default_enabled
        settings.quality_profile_rules = {
            QualityProfile.HD_1080P.value: {
                "include_tokens": payload.profile_1080p_include_tokens,
                "exclude_tokens": payload.profile_1080p_exclude_tokens,
            },
            QualityProfile.UHD_2160P_HDR.value: {
                "include_tokens": payload.profile_2160p_hdr_include_tokens,
                "exclude_tokens": payload.profile_2160p_hdr_exclude_tokens,
            },
        }
        settings.default_quality_profile = payload.default_quality_profile

        if payload.qb_password:
            settings.qb_password_encrypted = obfuscate_secret(payload.qb_password)
        if payload.jackett_api_key:
            settings.jackett_api_key_encrypted = obfuscate_secret(payload.jackett_api_key)
        if payload.omdb_api_key:
            settings.omdb_api_key_encrypted = obfuscate_secret(payload.omdb_api_key)
        return settings

    @staticmethod
    def resolve_qb_connection(settings: AppSettings | None) -> ResolvedQbConnection:
        env = get_environment_settings()
        resolved_base_url = env.qb_base_url or (settings.qb_base_url if settings else None)
        return ResolvedQbConnection(
            base_url=_rewrite_localhost_url_for_wsl(resolved_base_url),
            username=env.qb_username or (settings.qb_username if settings else None),
            password=env.qb_password
            or reveal_secret(settings.qb_password_encrypted if settings else None),
        )

    @staticmethod
    def resolve_metadata(settings: AppSettings | None) -> ResolvedMetadataConfig:
        env = get_environment_settings()
        provider = settings.metadata_provider if settings else MetadataProvider.OMDB
        return ResolvedMetadataConfig(
            provider=provider,
            api_key=env.omdb_api_key
            or reveal_secret(settings.omdb_api_key_encrypted if settings else None),
        )

    @staticmethod
    def resolve_jackett(settings: AppSettings | None) -> ResolvedJackettConfig:
        env = get_environment_settings()
        api_url = env.jackett_api_url or (settings.jackett_api_url if settings else None)
        qb_url = env.jackett_qb_url or (settings.jackett_qb_url if settings else None) or api_url
        return ResolvedJackettConfig(
            api_url=api_url,
            qb_url=qb_url,
            api_key=env.jackett_api_key
            or reveal_secret(settings.jackett_api_key_encrypted if settings else None),
        )

    @staticmethod
    def resolve_jellyfin(settings: AppSettings | None) -> ResolvedJellyfinConfig:
        env = get_environment_settings()
        db_path = env.jellyfin_db_path or (settings.jellyfin_db_path if settings else None)
        user_name = env.jellyfin_user_name or (settings.jellyfin_user_name if settings else None)
        return ResolvedJellyfinConfig(
            db_path=str(db_path).strip() or None if db_path is not None else None,
            user_name=str(user_name).strip() or None if user_name is not None else None,
            auto_sync_enabled=bool(
                getattr(settings, "jellyfin_auto_sync_enabled", DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED)
            )
            if settings is not None
            else DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED,
            auto_sync_interval_seconds=normalize_jellyfin_auto_sync_interval_seconds(
                getattr(
                    settings,
                    "jellyfin_auto_sync_interval_seconds",
                    DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
                )
                if settings is not None
                else DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS
            ),
        )

    @staticmethod
    def resolve_stremio(settings: AppSettings | None) -> ResolvedStremioConfig:
        env = get_environment_settings()
        local_storage_path = env.stremio_local_storage_path or (
            getattr(settings, "stremio_local_storage_path", None) if settings is not None else None
        )
        return ResolvedStremioConfig(
            local_storage_path=(
                str(local_storage_path).strip() or None if local_storage_path is not None else None
            ),
            auth_key=(
                str(env.stremio_auth_key).strip() or None
                if env.stremio_auth_key is not None
                else None
            ),
            preferred_languages=SettingsService.normalize_stremio_preferred_languages(
                env.stremio_preferred_languages
                if env.stremio_preferred_languages is not None
                else getattr(settings, "stremio_preferred_languages", None)
            ),
            auto_sync_enabled=bool(
                getattr(settings, "stremio_auto_sync_enabled", DEFAULT_STREMIO_AUTO_SYNC_ENABLED)
            )
            if settings is not None
            else DEFAULT_STREMIO_AUTO_SYNC_ENABLED,
            auto_sync_interval_seconds=normalize_stremio_auto_sync_interval_seconds(
                getattr(
                    settings,
                    "stremio_auto_sync_interval_seconds",
                    DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
                )
                if settings is not None
                else DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS
            ),
        )

    @staticmethod
    def to_form_dict(settings: AppSettings) -> dict[str, object]:
        profile_rules = resolve_quality_profile_rules(settings)
        saved_profiles = normalize_saved_quality_profiles(settings.saved_quality_profiles)
        for builtin_key in builtin_filter_profile_keys():
            saved_profiles.pop(builtin_key, None)
        return {
            "qb_base_url": settings.qb_base_url or "",
            "qb_username": settings.qb_username or "",
            "jackett_api_url": settings.jackett_api_url or "",
            "jackett_qb_url": settings.jackett_qb_url or "",
            "jellyfin_db_path": getattr(settings, "jellyfin_db_path", None) or "",
            "jellyfin_user_name": getattr(settings, "jellyfin_user_name", None) or "",
            "jellyfin_auto_sync_enabled": bool(
                getattr(settings, "jellyfin_auto_sync_enabled", DEFAULT_JELLYFIN_AUTO_SYNC_ENABLED)
            ),
            "jellyfin_auto_sync_interval_seconds": normalize_jellyfin_auto_sync_interval_seconds(
                getattr(
                    settings,
                    "jellyfin_auto_sync_interval_seconds",
                    DEFAULT_JELLYFIN_AUTO_SYNC_INTERVAL_SECONDS,
                )
            ),
            "jellyfin_auto_sync_last_run_at": getattr(
                settings,
                "jellyfin_auto_sync_last_run_at",
                None,
            ),
            "jellyfin_auto_sync_last_status": str(
                getattr(settings, "jellyfin_auto_sync_last_status", "idle") or "idle"
            ),
            "jellyfin_auto_sync_last_message": str(
                getattr(settings, "jellyfin_auto_sync_last_message", "") or ""
            ),
            "stremio_local_storage_path": getattr(settings, "stremio_local_storage_path", None)
            or "",
            "stremio_preferred_languages": getattr(
                settings, "stremio_preferred_languages", None
            )
            or "",
            "stremio_stream_provider_manifests": getattr(
                settings, "stremio_stream_provider_manifests", None
            )
            or "",
            "stremio_auto_sync_enabled": bool(
                getattr(settings, "stremio_auto_sync_enabled", DEFAULT_STREMIO_AUTO_SYNC_ENABLED)
            ),
            "stremio_auto_sync_interval_seconds": normalize_stremio_auto_sync_interval_seconds(
                getattr(
                    settings,
                    "stremio_auto_sync_interval_seconds",
                    DEFAULT_STREMIO_AUTO_SYNC_INTERVAL_SECONDS,
                )
            ),
            "stremio_auto_sync_last_run_at": getattr(
                settings,
                "stremio_auto_sync_last_run_at",
                None,
            ),
            "stremio_auto_sync_last_status": str(
                getattr(settings, "stremio_auto_sync_last_status", "idle") or "idle"
            ),
            "stremio_auto_sync_last_message": str(
                getattr(settings, "stremio_auto_sync_last_message", "") or ""
            ),
            "metadata_provider": settings.metadata_provider.value,
            "series_category_template": settings.series_category_template,
            "movie_category_template": settings.movie_category_template,
            "save_path_template": settings.save_path_template,
            "default_add_paused": settings.default_add_paused,
            "default_sequential_download": bool(
                getattr(settings, "default_sequential_download", True)
            ),
            "default_first_last_piece_prio": bool(
                getattr(settings, "default_first_last_piece_prio", True)
            ),
            "default_enabled": settings.default_enabled,
            "profile_1080p_include_tokens": profile_rules[QualityProfile.HD_1080P.value][
                "include_tokens"
            ],
            "profile_1080p_exclude_tokens": profile_rules[QualityProfile.HD_1080P.value][
                "exclude_tokens"
            ],
            "profile_2160p_hdr_include_tokens": profile_rules[QualityProfile.UHD_2160P_HDR.value][
                "include_tokens"
            ],
            "profile_2160p_hdr_exclude_tokens": profile_rules[QualityProfile.UHD_2160P_HDR.value][
                "exclude_tokens"
            ],
            "default_feed_urls": list(settings.default_feed_urls or []),
            "default_quality_profile": settings.default_quality_profile.value,
            "saved_quality_profile_count": len(saved_profiles),
            "has_saved_qb_password": bool(settings.qb_password_encrypted),
            "has_saved_jackett_key": bool(settings.jackett_api_key_encrypted),
            "has_saved_omdb_key": bool(settings.omdb_api_key_encrypted),
            "has_env_qb_password": bool(get_environment_settings().qb_password),
            "has_env_jackett_key": bool(get_environment_settings().jackett_api_key),
            "has_env_omdb_key": bool(get_environment_settings().omdb_api_key),
            "has_env_jellyfin_db_path": bool(get_environment_settings().jellyfin_db_path),
            "has_env_jellyfin_user_name": bool(get_environment_settings().jellyfin_user_name),
            "has_env_stremio_local_storage_path": bool(
                get_environment_settings().stremio_local_storage_path
            ),
            "has_env_stremio_auth_key": bool(get_environment_settings().stremio_auth_key),
            "search_result_view_mode": normalize_search_result_view_mode(
                settings.search_result_view_mode
            ),
            "search_sort_criteria": normalize_search_sort_criteria(settings.search_sort_criteria),
            "rules_page_view_mode": normalize_rules_page_view_mode(
                getattr(settings, "rules_page_view_mode", DEFAULT_RULES_PAGE_VIEW_MODE)
            ),
            "rules_page_sort_field": normalize_rules_page_sort_field(
                getattr(settings, "rules_page_sort_field", DEFAULT_RULES_PAGE_SORT_FIELD)
            ),
            "rules_page_sort_direction": normalize_rules_page_sort_direction(
                getattr(settings, "rules_page_sort_direction", DEFAULT_RULES_PAGE_SORT_DIRECTION)
            ),
            "rules_fetch_schedule_enabled": bool(
                getattr(settings, "rules_fetch_schedule_enabled", False)
            ),
            "rules_fetch_schedule_interval_minutes": normalize_rule_fetch_schedule_interval_minutes(
                getattr(
                    settings,
                    "rules_fetch_schedule_interval_minutes",
                    DEFAULT_RULE_FETCH_SCHEDULE_INTERVAL_MINUTES,
                )
            ),
            "rules_fetch_schedule_scope": normalize_rule_fetch_schedule_scope(
                getattr(settings, "rules_fetch_schedule_scope", DEFAULT_RULE_FETCH_SCHEDULE_SCOPE)
            ),
            "rules_fetch_schedule_last_run_at": getattr(
                settings,
                "rules_fetch_schedule_last_run_at",
                None,
            ),
            "rules_fetch_schedule_next_run_at": getattr(
                settings,
                "rules_fetch_schedule_next_run_at",
                None,
            ),
            "rules_fetch_schedule_last_status": str(
                getattr(settings, "rules_fetch_schedule_last_status", "idle") or "idle"
            ),
            "rules_fetch_schedule_last_message": str(
                getattr(settings, "rules_fetch_schedule_last_message", "") or ""
            ),
        }
