from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_environment_settings
from app.models import AppSettings, MediaType, Rule
from app.services.metadata import MetadataClient, MetadataLookupError, MetadataLookupProvider
from app.services.quality_filters import resolve_quality_profile_rules
from app.services.rule_builder import RuleBuilder
from app.services.settings_service import SettingsService
from app.services.watch_state import (
    MovieWatchStateSelection,
    WatchStateDerivedFloor,
    derive_watch_state_floor,
    normalize_watch_state_source_labels,
    select_movie_watch_state,
    select_watch_state_floor,
)
from app.services.watch_state import (
    floor_tuple as _floor_tuple,
)
from app.services.watch_state import (
    increment_floor as _increment_floor,
)
from app.services.watch_state import (
    normalize_watch_state_episode_keys as normalize_stremio_episode_keys,
)

STREMIO_API_BASE_URL = "https://api.strem.io/api"
STREMIO_LIBRARY_COLLECTION = "libraryItem"
SUPPORTED_STREMIO_ITEM_TYPES = frozenset({"movie", "series"})
TITLE_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
IMDB_ID_RE = re.compile(r"(tt\d{5,12})", re.IGNORECASE)
STREMIO_AUTH_KEY_RE = re.compile(r'"auth".*?key.*?"([^"]+)"', re.IGNORECASE | re.DOTALL)
STREMIO_USER_ID_RE = re.compile(
    r'"auth".*?"user".*?_id.*?([0-9a-f]{16,})',
    re.IGNORECASE | re.DOTALL,
)
CHANGED_OUTCOME_STATUSES = frozenset({"created", "linked", "updated", "disabled", "reenabled"})
StremioOutcomeStatus = Literal[
    "created",
    "linked",
    "updated",
    "disabled",
    "reenabled",
    "unchanged",
    "skipped",
    "error",
]


class StremioError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StremioAuthContext:
    auth_key: str
    source: str
    local_storage_path: str | None = None
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class StremioLibraryItem:
    item_id: str
    title: str
    normalized_title: str
    item_type: str
    media_type: MediaType
    imdb_id: str | None
    removed: bool
    temp: bool
    completed: bool
    latest_watched_episode_key: str | None = None


@dataclass(frozen=True, slots=True)
class StremioConnectionSummary:
    auth_source: str
    local_storage_path: str | None
    user_id: str | None
    total_item_count: int
    active_item_count: int


@dataclass(frozen=True, slots=True)
class StremioRuleSyncOutcome:
    status: StremioOutcomeStatus
    rule_id: str | None
    rule_name: str
    message: str
    item_id: str | None = None
    item_title: str | None = None

    @property
    def changed(self) -> bool:
        return self.status in CHANGED_OUTCOME_STATUSES


@dataclass(frozen=True, slots=True)
class StremioRuleSyncSummary:
    auth_source: str
    local_storage_path: str | None
    user_id: str | None
    total_item_count: int
    active_item_count: int
    outcomes: list[StremioRuleSyncOutcome]

    @property
    def changed_outcomes(self) -> list[StremioRuleSyncOutcome]:
        return [outcome for outcome in self.outcomes if outcome.changed]

    @property
    def created_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "created")

    @property
    def linked_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "linked")

    @property
    def updated_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "updated")

    @property
    def disabled_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "disabled")

    @property
    def reenabled_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "reenabled")

    @property
    def unchanged_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "unchanged")

    @property
    def skipped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "skipped")

    @property
    def error_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "error")


def _normalize_title(value: str | None) -> str:
    tokens = TITLE_TOKEN_RE.findall(str(value or "").casefold())
    return " ".join(token for token in tokens if token)


def _normalize_storage_text(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="ignore").replace("\x00", "")
    return "".join(
        character if character.isprintable() or character in "\r\n\t " else " "
        for character in text
    )


def _normalize_stremio_item_type(value: str | None) -> str | None:
    cleaned = str(value or "").strip().lower()
    if cleaned in SUPPORTED_STREMIO_ITEM_TYPES:
        return cleaned
    return None


def _stremio_item_imdb_id(value: str | None) -> str | None:
    match = IMDB_ID_RE.search(str(value or ""))
    if not match:
        return None
    return match.group(1).lower()


def _stremio_item_media_type(item_type: str | None) -> MediaType | None:
    normalized_type = _normalize_stremio_item_type(item_type)
    if normalized_type == "movie":
        return MediaType.MOVIE
    if normalized_type == "series":
        return MediaType.SERIES
    return None


def _stremio_int(value: object | None) -> int:
    if value is None:
        return 0
    cleaned = str(value).strip()
    if not cleaned:
        return 0
    try:
        return max(0, int(cleaned))
    except (TypeError, ValueError):
        return 0


def _stremio_state_indicates_completion(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if _stremio_int(value.get("flaggedWatched")) > 0:
        return True
    if _stremio_int(value.get("timesWatched")) > 0:
        return True
    watched_marker = str(value.get("watched") or "").strip()
    if watched_marker:
        return True
    duration = _stremio_int(value.get("duration"))
    if duration <= 0:
        return False
    watched_time = max(
        _stremio_int(value.get("overallTimeWatched")),
        _stremio_int(value.get("timeWatched")),
    )
    return watched_time >= int(duration * 0.95)


def _resolved_rule_title(rule: Rule) -> str:
    return (
        str(rule.normalized_title or "").strip()
        or str(rule.content_name or "").strip()
        or str(rule.rule_name or "").strip()
    )


class StremioService:
    def __init__(self, settings: AppSettings | None) -> None:
        self.settings = settings
        self.config = SettingsService.resolve_stremio(settings)
        self.metadata_config = SettingsService.resolve_metadata(settings)
        self._request_timeout = get_environment_settings().request_timeout
        self._metadata_client: MetadataClient | None = None
        self._catalog_imdb_id_cache: dict[str, str | None] = {}
        self._catalog_season_cache: dict[tuple[str, int], list[int] | None] = {}

    def can_resolve_auth(self) -> bool:
        if self.config.has_explicit_auth_key:
            return True
        if str(self.config.local_storage_path or "").strip():
            try:
                self._normalize_local_storage_path(self.config.local_storage_path)
            except StremioError:
                return False
            return True
        return self._autodiscovered_local_storage_path() is not None

    def test_connection(self) -> StremioConnectionSummary:
        auth_context = self._resolve_auth_context()
        items = self._fetch_library_items(auth_context.auth_key)
        active_items = self._active_sync_items(items)
        return StremioConnectionSummary(
            auth_source=auth_context.source,
            local_storage_path=auth_context.local_storage_path,
            user_id=auth_context.user_id,
            total_item_count=len(items),
            active_item_count=len(active_items),
        )

    def fetch_library_signature(self) -> str:
        auth_context = self._resolve_auth_context()
        meta_items = self._fetch_library_meta(auth_context.auth_key)
        library_signature = self._library_signature(meta_items)
        owner_signature = auth_context.user_id or auth_context.source
        return f"{owner_signature}:{library_signature}"

    def sync_rules(self, session: Session) -> StremioRuleSyncSummary:
        settings = self.settings or SettingsService.get_or_create(session)
        auth_context = self._resolve_auth_context()
        items = self._fetch_library_items(auth_context.auth_key)
        active_items = self._active_sync_items(items)
        rules = list(
            session.scalars(
                select(Rule)
                .where(Rule.media_type.in_((MediaType.SERIES, MediaType.MOVIE)))
                .order_by(Rule.rule_name.asc())
            ).all()
        )

        active_item_ids = {item.item_id for item in active_items}
        outcomes: list[StremioRuleSyncOutcome] = []

        for item in active_items:
            matched_rule, matched_by, skip_message = self._match_rule(item, rules)
            if skip_message:
                outcomes.append(
                    StremioRuleSyncOutcome(
                        status="skipped",
                        rule_id=None,
                        rule_name=item.title,
                        message=skip_message,
                        item_id=item.item_id,
                        item_title=item.title,
                    )
                )
                continue
            if matched_rule is None:
                outcome = self._create_rule_for_item(session, item, rules, settings)
            else:
                outcome = self._sync_existing_rule(
                    session,
                    matched_rule,
                    item,
                    matched_by=matched_by,
                )
            outcomes.append(outcome)

        for rule in rules:
            linked_item_id = str(getattr(rule, "stremio_library_item_id", "") or "").strip()
            linked_item_type = _normalize_stremio_item_type(
                getattr(rule, "stremio_library_item_type", None)
            )
            if linked_item_type not in SUPPORTED_STREMIO_ITEM_TYPES or not linked_item_id:
                continue
            if linked_item_id in active_item_ids:
                continue
            message_parts: list[str] = []
            status: StremioOutcomeStatus | None = None
            if rule.media_type == MediaType.MOVIE:
                selection, completion_message_parts = self._movie_completion_selection(
                    rule=rule,
                    source_present=False,
                    source_completed=False,
                )
                if selection.changed:
                    self._apply_movie_completion_selection(
                        session,
                        rule=rule,
                        selection=selection,
                    )
                    message_parts.extend(completion_message_parts)
                    message_parts.append(selection.detail)
                    status = self._movie_completion_status(selection)

            if bool(getattr(rule, "stremio_managed", False)):
                if not bool(getattr(rule, "stremio_auto_disabled", False)) and bool(rule.enabled):
                    rule.enabled = False
                    rule.stremio_auto_disabled = True
                    session.add(rule)
                    message_parts.append(
                        "Disabled because the title is no longer in the Stremio library."
                    )
                    status = "disabled"

            if status is None:
                continue

            outcomes.append(
                StremioRuleSyncOutcome(
                    status=status,
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    message=" ".join(message_parts),
                    item_id=linked_item_id,
                    item_title=_resolved_rule_title(rule),
                )
            )

        if any(outcome.changed for outcome in outcomes):
            session.commit()

        return StremioRuleSyncSummary(
            auth_source=auth_context.source,
            local_storage_path=auth_context.local_storage_path,
            user_id=auth_context.user_id,
            total_item_count=len(items),
            active_item_count=len(active_items),
            outcomes=outcomes,
        )

    def _resolve_auth_context(self) -> StremioAuthContext:
        if self.config.has_explicit_auth_key:
            return StremioAuthContext(
                auth_key=str(self.config.auth_key or "").strip(),
                source="environment auth key",
            )
        return self._discover_auth_from_local_storage()

    def _discover_auth_from_local_storage(self) -> StremioAuthContext:
        storage_path = self._resolve_local_storage_path()
        candidate_files = sorted(
            [
                path
                for path in storage_path.iterdir()
                if path.is_file() and path.suffix.lower() in {".ldb", ".log"}
            ],
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for candidate in candidate_files:
            try:
                normalized_text = _normalize_storage_text(candidate.read_bytes())
            except OSError:
                continue
            auth_match = STREMIO_AUTH_KEY_RE.search(normalized_text)
            if not auth_match:
                continue
            auth_key = str(auth_match.group(1) or "").strip()
            if not auth_key:
                continue
            user_match = STREMIO_USER_ID_RE.search(normalized_text)
            user_id = str(user_match.group(1) or "").strip() if user_match else None
            return StremioAuthContext(
                auth_key=auth_key,
                source="local storage",
                local_storage_path=str(storage_path),
                user_id=user_id or None,
            )
        raise StremioError(
            "Could not find a signed-in Stremio auth key in the local desktop storage."
        )

    def _resolve_local_storage_path(self) -> Path:
        configured_path = str(self.config.local_storage_path or "").strip()
        if configured_path:
            return self._normalize_local_storage_path(configured_path)
        autodiscovered_path = self._autodiscovered_local_storage_path()
        if autodiscovered_path is not None:
            return autodiscovered_path
        raise StremioError(
            "Could not auto-discover the Stremio local storage path. Set it in Settings."
        )

    def _autodiscovered_local_storage_path(self) -> Path | None:
        for candidate in self._default_local_storage_candidates():
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        return None

    @staticmethod
    def _default_local_storage_candidates() -> list[Path]:
        local_appdata = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if not local_appdata:
            return []
        base = Path(local_appdata)
        return [
            base
            / "Programs"
            / "Stremio"
            / "stremio-shell-ng.exe.WebView2"
            / "EBWebView"
            / "Default"
            / "Local Storage"
            / "leveldb",
            base
            / "Programs"
            / "Stremio"
            / "stremio-runtime.exe.WebView2"
            / "EBWebView"
            / "Default"
            / "Local Storage"
            / "leveldb",
        ]

    def _normalize_local_storage_path(self, raw_path: str | None) -> Path:
        cleaned = str(raw_path or "").strip()
        if not cleaned:
            raise StremioError("Stremio local storage path is not configured.")

        storage_path = Path(cleaned).expanduser()
        if not storage_path.is_absolute():
            storage_path = (Path.cwd() / storage_path).resolve()
        else:
            storage_path = storage_path.resolve()

        if storage_path.is_file():
            if storage_path.suffix.lower() in {".ldb", ".log"}:
                storage_path = storage_path.parent
            else:
                raise StremioError(
                    "Stremio local storage path must point to the LevelDB directory or a LevelDB file."
                )
        else:
            name = storage_path.name.casefold()
            if name == "local storage":
                storage_path = storage_path / "leveldb"
            elif name == "default":
                storage_path = storage_path / "Local Storage" / "leveldb"
            elif name.endswith(".webview2"):
                storage_path = storage_path / "EBWebView" / "Default" / "Local Storage" / "leveldb"

        if not storage_path.exists():
            raise StremioError(f"Stremio local storage path does not exist: {storage_path}")
        if not storage_path.is_dir():
            raise StremioError(f"Stremio local storage path is not a directory: {storage_path}")
        return storage_path

    def _fetch_library_items(self, auth_key: str) -> list[StremioLibraryItem]:
        payload = {
            "authKey": auth_key,
            "collection": STREMIO_LIBRARY_COLLECTION,
            "ids": [],
            "all": True,
        }
        result = self._post_api("datastoreGet", payload)
        if not isinstance(result, list):
            raise StremioError("Unexpected Stremio library response.")

        items: list[StremioLibraryItem] = []
        for entry in result:
            item = self._library_item_from_payload(entry)
            if item is not None:
                items.append(item)
        return items

    def _fetch_library_meta(self, auth_key: str) -> list[tuple[str, int]]:
        payload = {
            "authKey": auth_key,
            "collection": STREMIO_LIBRARY_COLLECTION,
        }
        result = self._post_api("datastoreMeta", payload)
        if not isinstance(result, list):
            raise StremioError("Unexpected Stremio library metadata response.")

        meta_items: list[tuple[str, int]] = []
        for entry in result:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            item_id = str(entry[0] or "").strip()
            if not item_id:
                continue
            try:
                modified_at = int(entry[1])
            except (TypeError, ValueError):
                continue
            meta_items.append((item_id, modified_at))
        return meta_items

    def _post_api(self, endpoint: str, payload: Mapping[str, object]) -> object:
        url = f"{STREMIO_API_BASE_URL}/{endpoint.lstrip('/')}"
        try:
            response = httpx.post(
                url,
                json=dict(payload),
                timeout=self._request_timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise StremioError(f"Stremio request failed: {exc}") from exc

        try:
            raw_payload = response.json()
        except ValueError as exc:
            raise StremioError("Stremio returned a non-JSON response.") from exc

        if not isinstance(raw_payload, dict):
            raise StremioError("Unexpected Stremio API response shape.")
        if "error" in raw_payload:
            error_payload = raw_payload.get("error")
            if isinstance(error_payload, dict):
                message = str(error_payload.get("message") or "unknown error")
            else:
                message = str(error_payload or "unknown error")
            raise StremioError(f"Stremio API {endpoint} failed: {message}")
        if "result" not in raw_payload:
            raise StremioError("Stremio API response did not include a result payload.")
        return raw_payload["result"]

    def _library_item_from_payload(self, payload: object) -> StremioLibraryItem | None:
        if not isinstance(payload, dict):
            return None
        item_id = str(payload.get("_id") or "").strip()
        title = str(payload.get("name") or "").strip()
        item_type = _normalize_stremio_item_type(payload.get("type"))
        media_type = _stremio_item_media_type(item_type)
        if not item_id or not title or item_type is None or media_type is None:
            return None
        completed = False
        latest_watched_episode_key = None
        state = payload.get("state")
        if isinstance(state, dict):
            if media_type == MediaType.MOVIE:
                completed = _stremio_state_indicates_completion(state)
            elif media_type == MediaType.SERIES:
                video_id_str = str(state.get("video_id") or "").strip()
                watched_str = str(state.get("watched") or "").strip()
                match_str = video_id_str or watched_str
                if match_str and ":" in match_str:
                    parts = match_str.split(":")
                    if len(parts) >= 3:
                        try:
                            season_num = int(parts[1])
                            episode_num = int(parts[2])
                            latest_watched_episode_key = f"S{season_num:02d}E{episode_num:02d}"
                        except ValueError:
                            pass

        return StremioLibraryItem(
            item_id=item_id,
            title=title,
            normalized_title=_normalize_title(title),
            item_type=item_type,
            media_type=media_type,
            imdb_id=_stremio_item_imdb_id(item_id),
            removed=bool(payload.get("removed", False)),
            temp=bool(payload.get("temp", False)),
            completed=completed,
            latest_watched_episode_key=latest_watched_episode_key,
        )

    @staticmethod
    def _active_sync_items(items: list[StremioLibraryItem]) -> list[StremioLibraryItem]:
        active_items = [
            item
            for item in items
            if item.item_type in SUPPORTED_STREMIO_ITEM_TYPES and not item.removed and not item.temp
        ]
        active_items.sort(key=lambda item: (item.title.casefold(), item.item_id))
        return active_items

    @staticmethod
    def _library_signature(meta_items: list[tuple[str, int]]) -> str:
        if not meta_items:
            return ""
        return "|".join(
            f"{item_id}:{modified_at}"
            for item_id, modified_at in sorted(meta_items, key=lambda item: (item[0], item[1]))
        )

    def _match_rule(
        self,
        item: StremioLibraryItem,
        rules: list[Rule],
    ) -> tuple[Rule | None, str | None, str | None]:
        exact_candidates = [
            rule
            for rule in rules
            if str(getattr(rule, "stremio_library_item_id", "") or "").strip() == item.item_id
        ]
        if len(exact_candidates) == 1:
            return exact_candidates[0], "Stremio item ID", None
        if len(exact_candidates) > 1:
            return (
                None,
                None,
                f'Multiple rules are already linked to the Stremio title "{item.title}".',
            )

        if item.imdb_id:
            imdb_candidates = [
                rule
                for rule in rules
                if rule.media_type == item.media_type
                and str(rule.imdb_id or "").strip().lower() == item.imdb_id
            ]
            candidate, skip_message = self._select_link_candidate(
                imdb_candidates,
                item_id=item.item_id,
                item_title=item.title,
                match_label="IMDb ID",
            )
            if candidate is not None or skip_message is not None:
                return candidate, "IMDb ID", skip_message

        normalized_titles = {
            value
            for value in (
                item.normalized_title,
                _normalize_title(item.imdb_id),
            )
            if value
        }
        title_candidates = [
            rule
            for rule in rules
            if rule.media_type == item.media_type
            and _normalize_title(_resolved_rule_title(rule)) in normalized_titles
        ]
        candidate, skip_message = self._select_link_candidate(
            title_candidates,
            item_id=item.item_id,
            item_title=item.title,
            match_label="title",
        )
        if candidate is not None or skip_message is not None:
            return candidate, "title", skip_message

        return None, None, None

    @staticmethod
    def _select_link_candidate(
        candidates: list[Rule],
        *,
        item_id: str,
        item_title: str,
        match_label: str,
    ) -> tuple[Rule | None, str | None]:
        eligible_candidates = [
            rule
            for rule in candidates
            if not str(getattr(rule, "stremio_library_item_id", "") or "").strip()
            or str(getattr(rule, "stremio_library_item_id", "") or "").strip() == item_id
        ]
        if len(eligible_candidates) == 1:
            return eligible_candidates[0], None
        if len(eligible_candidates) > 1:
            return (
                None,
                f'Ambiguous Stremio {match_label} match for "{item_title}".',
            )
        return None, None

    def _create_rule_for_item(
        self,
        session: Session,
        item: StremioLibraryItem,
        rules: list[Rule],
        settings: AppSettings,
    ) -> StremioRuleSyncOutcome:
        resolved_quality_rules = resolve_quality_profile_rules(settings)
        quality_profile_key = settings.default_quality_profile.value
        quality_filters = resolved_quality_rules.get(
            quality_profile_key,
            {"include_tokens": [], "exclude_tokens": []},
        )
        rule = Rule(
            rule_name=self._next_available_rule_name(item.title, item.item_type, rules),
            content_name=item.title,
            imdb_id=item.imdb_id,
            normalized_title=item.title,
            media_type=item.media_type,
            quality_profile=settings.default_quality_profile,
            quality_include_tokens=list(quality_filters.get("include_tokens", [])),
            quality_exclude_tokens=list(quality_filters.get("exclude_tokens", [])),
            use_regex=True,
            add_paused=bool(settings.default_add_paused),
            enabled=bool(settings.default_enabled),
            feed_urls=list(settings.default_feed_urls or []),
            assigned_category="",
            save_path="",
            stremio_library_item_id=item.item_id,
            stremio_library_item_type=item.item_type,
            stremio_managed=True,
            stremio_auto_disabled=False,
        )

        builder = RuleBuilder(settings)
        rule.assigned_category = builder.render_category(rule)
        rule.save_path = builder.render_save_path(rule)
        session.add(rule)
        session.flush()
        rules.append(rule)
        outcome = StremioRuleSyncOutcome(
            status="created",
            rule_id=rule.id,
            rule_name=rule.rule_name,
            message="Created a new Stremio-managed rule.",
            item_id=item.item_id,
            item_title=item.title,
        )
        if item.media_type == MediaType.SERIES:
            return self._apply_series_watch_state_outcome(
                session,
                rule=rule,
                item=item,
                base_outcome=outcome,
            )
        return self._apply_movie_completion_outcome(
            session,
            rule=rule,
            item=item,
            base_outcome=outcome,
        )

    @staticmethod
    def _next_available_rule_name(item_name: str, item_type: str, rules: list[Rule]) -> str:
        base_name = str(item_name or "").strip() or "Stremio Rule"
        existing_names = {str(rule.rule_name or "").strip().casefold() for rule in rules}
        if base_name.casefold() not in existing_names:
            return base_name

        type_suffix = "Movie" if item_type == "movie" else "Series"
        typed_name = f"{base_name} ({type_suffix})"
        if typed_name.casefold() not in existing_names:
            return typed_name

        counter = 2
        while True:
            candidate = f"{typed_name} {counter}"
            if candidate.casefold() not in existing_names:
                return candidate
            counter += 1

    @staticmethod
    def _movie_completion_status(selection: MovieWatchStateSelection) -> StremioOutcomeStatus:
        if selection.enabled_changed:
            if selection.effective_enabled:
                return "reenabled"
            if selection.effective_auto_disabled:
                return "disabled"
        return "updated"

    @staticmethod
    def _select_movie_completion_messages(
        *,
        previous_completed_sources: list[str],
        selection: MovieWatchStateSelection,
        source_present: bool,
        source_completed: bool,
    ) -> list[str]:
        had_stremio_completion = "stremio" in previous_completed_sources
        has_stremio_completion = "stremio" in selection.completed_sources
        message_parts: list[str] = []
        if source_present and source_completed and not had_stremio_completion:
            message_parts.append("Stremio reports this movie as completed.")
        elif source_present and not source_completed and had_stremio_completion:
            message_parts.append("Stremio no longer reports this movie as completed.")
        elif not source_present and had_stremio_completion and not has_stremio_completion:
            message_parts.append(
                "Cleared Stremio completion evidence because the title is no longer active in the Stremio library."
            )
        return message_parts

    def _movie_completion_selection(
        self,
        *,
        rule: Rule,
        source_present: bool,
        source_completed: bool,
    ) -> tuple[MovieWatchStateSelection, list[str]]:
        previous_completed_sources = normalize_watch_state_source_labels(
            list(getattr(rule, "movie_completion_sources", []) or [])
        )
        selection = select_movie_watch_state(
            source_label="Stremio",
            source_present=source_present,
            source_completed=source_completed,
            current_completed_sources=previous_completed_sources,
            current_enabled=bool(rule.enabled),
            current_auto_disabled=bool(getattr(rule, "movie_completion_auto_disabled", False)),
            keep_searching=bool(getattr(rule, "jellyfin_search_existing_unseen", False)),
        )
        message_parts = self._select_movie_completion_messages(
            previous_completed_sources=previous_completed_sources,
            selection=selection,
            source_present=source_present,
            source_completed=source_completed,
        )
        return selection, message_parts

    @staticmethod
    def _apply_movie_completion_selection(
        session: Session,
        *,
        rule: Rule,
        selection: MovieWatchStateSelection,
    ) -> None:
        rule.movie_completion_sources = selection.completed_sources
        rule.movie_completion_auto_disabled = selection.effective_auto_disabled
        rule.enabled = selection.effective_enabled
        session.add(rule)

    def _apply_movie_completion_outcome(
        self,
        session: Session,
        *,
        rule: Rule,
        item: StremioLibraryItem,
        base_outcome: StremioRuleSyncOutcome,
    ) -> StremioRuleSyncOutcome:
        if item.media_type != MediaType.MOVIE:
            return base_outcome

        selection, message_parts = self._movie_completion_selection(
            rule=rule,
            source_present=True,
            source_completed=item.completed,
        )
        if not selection.changed:
            return base_outcome

        self._apply_movie_completion_selection(
            session,
            rule=rule,
            selection=selection,
        )
        if base_outcome.message:
            message_parts.insert(0, base_outcome.message)
        message_parts.append(selection.detail)
        status: StremioOutcomeStatus = (
            base_outcome.status
            if base_outcome.status != "unchanged"
            else self._movie_completion_status(selection)
        )
        return StremioRuleSyncOutcome(
            status=status,
            rule_id=base_outcome.rule_id,
            rule_name=base_outcome.rule_name,
            message=" ".join(message_parts),
            item_id=base_outcome.item_id,
            item_title=base_outcome.item_title,
        )

    def _derive_stremio_floor(
        self,
        *,
        item: StremioLibraryItem,
        rule: Rule,
    ) -> WatchStateDerivedFloor | None:
        episode_keys = [item.latest_watched_episode_key] if item.latest_watched_episode_key else []
        remembered_known = normalize_stremio_episode_keys(
            list(getattr(rule, "stremio_known_episode_numbers", []) or [])
        )
        remembered_watched = normalize_stremio_episode_keys(
            list(getattr(rule, "stremio_watched_episode_numbers", []) or [])
        )
        return derive_watch_state_floor(
            source_label="Stremio",
            current_episode_numbers=episode_keys,
            current_watched_episode_numbers=episode_keys,
            remembered_known_episode_numbers=remembered_known,
            remembered_watched_episode_numbers=remembered_watched,
            next_floor_after_episode=lambda current_episode: self._next_floor_after_episode(
                item=item,
                rule=rule,
                current_episode=current_episode,
            ),
        )

    def _apply_series_watch_state_outcome(
        self,
        session: Session,
        *,
        rule: Rule,
        item: StremioLibraryItem,
        base_outcome: StremioRuleSyncOutcome,
    ) -> StremioRuleSyncOutcome:
        if item.media_type != MediaType.SERIES:
            return base_outcome

        derived_floor = self._derive_stremio_floor(item=item, rule=rule)
        if derived_floor is None:
            return base_outcome

        selection = select_watch_state_floor(
            derived_floor=derived_floor,
            current_floor=_floor_tuple(rule.start_season, rule.start_episode),
            keep_searching_existing_unseen=bool(
                getattr(rule, "jellyfin_search_existing_unseen", False)
            ),
            source_label="Stremio",
        )

        rule.stremio_known_episode_numbers = derived_floor.known_episode_numbers
        rule.stremio_watched_episode_numbers = derived_floor.watched_episode_numbers
        if selection.effective_floor is not None:
            rule.start_season = selection.effective_floor[0]
            rule.start_episode = selection.effective_floor[1]
        session.add(rule)

        status = base_outcome.status
        message_parts = [base_outcome.message] if base_outcome.message else []
        if selection.floor_changed:
            if status == "unchanged":
                status = "updated"
            message_parts.append(selection.floor_detail)

        return StremioRuleSyncOutcome(
            status=status,
            rule_id=base_outcome.rule_id,
            rule_name=base_outcome.rule_name,
            message=" ".join(message_parts),
            item_id=base_outcome.item_id,
            item_title=base_outcome.item_title,
        )

    def _resolve_catalog_imdb_id(
        self,
        *,
        item: StremioLibraryItem,
        rule: Rule,
    ) -> str | None:
        def _normalize_imdb_id(value: str | None) -> str | None:
            match = IMDB_ID_RE.search(str(value or "").strip())
            return match.group(1).lower() if match else None

        existing_imdb_id = _normalize_imdb_id(item.imdb_id or rule.imdb_id)
        if existing_imdb_id:
            return existing_imdb_id

        cache_key = item.item_id
        if cache_key in self._catalog_imdb_id_cache:
            return self._catalog_imdb_id_cache[cache_key]

        client = self._metadata_client_for_catalog()
        if client is None:
            self._catalog_imdb_id_cache[cache_key] = None
            return None

        lookup_title = str(item.title or rule.normalized_title or rule.content_name or "").strip()
        if not lookup_title:
            self._catalog_imdb_id_cache[cache_key] = None
            return None

        try:
            result = client.lookup(
                MetadataLookupProvider.OMDB,
                lookup_title,
                MediaType.SERIES,
            )
        except MetadataLookupError:
            self._catalog_imdb_id_cache[cache_key] = None
            return None

        normalized_imdb_id = _normalize_imdb_id(result.imdb_id)
        self._catalog_imdb_id_cache[cache_key] = normalized_imdb_id
        return normalized_imdb_id

    def _metadata_client_for_catalog(self) -> MetadataClient | None:
        if self.metadata_config.provider.value == "disabled":
            return None
        if not self.metadata_config.api_key:
            return None
        if self._metadata_client is None:
            self._metadata_client = MetadataClient(
                self.metadata_config.provider,
                self.metadata_config.api_key,
            )
        return self._metadata_client

    def _released_episode_numbers_for_season(
        self,
        *,
        item: StremioLibraryItem,
        rule: Rule,
        season_number: int,
    ) -> list[int] | None:
        if season_number < 1 or season_number > 99:
            return None

        imdb_id = self._resolve_catalog_imdb_id(item=item, rule=rule)
        if not imdb_id:
            return None

        cache_key = (imdb_id, season_number)
        if cache_key in self._catalog_season_cache:
            return self._catalog_season_cache[cache_key]

        client = httpx.Client(timeout=self._request_timeout)
        try:
            with client:
                response = client.get(f"https://v3-cinemeta.strem.io/meta/series/{imdb_id}.json")
                response.raise_for_status()
                payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            self._catalog_season_cache[cache_key] = None
            return None

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            self._catalog_season_cache[cache_key] = None
            return None
            
        videos = meta.get("videos")
        if not isinstance(videos, list):
            self._catalog_season_cache[cache_key] = None
            return None

        now = datetime.now(UTC)
        released_episode_numbers: set[int] = set()

        for v in videos:
            if not isinstance(v, dict):
                continue
            v_season = v.get("season")
            if v_season != season_number:
                continue
            try:
                ep_num = int(str(v.get("episode", "")))
            except ValueError:
                continue
            
            released_str = str(v.get("released", "")).strip()
            if released_str:
                try:
                    released_at = datetime.fromisoformat(released_str.replace("Z", "+00:00"))
                    if released_at > now:
                        continue
                except ValueError:
                    pass
            
            released_episode_numbers.add(ep_num)

        if not released_episode_numbers:
            self._catalog_season_cache[cache_key] = None
            return None
        
        sorted_episodes = sorted(released_episode_numbers)
        self._catalog_season_cache[cache_key] = sorted_episodes
        return sorted_episodes

    def _next_floor_after_episode(
        self,
        *,
        item: StremioLibraryItem,
        rule: Rule,
        current_episode: tuple[int, int],
    ) -> tuple[tuple[int, int], str]:
        season_number, episode_number = current_episode
        released_episode_numbers = self._released_episode_numbers_for_season(
            item=item,
            rule=rule,
            season_number=season_number,
        )
        if released_episode_numbers:
            latest_released_episode = max(released_episode_numbers)
            if episode_number >= latest_released_episode and season_number < 99:
                next_floor = (season_number + 1, 0)
                return (
                    next_floor,
                    f"Advanced to S{next_floor[0]:02d}E{next_floor[1]:02d} because Stremio Cinemeta reports "
                    f"S{season_number:02d}E{latest_released_episode:02d} as the latest released "
                    f"episode in season {season_number}.",
                )

        next_floor = _increment_floor(season_number, episode_number)
        return (
            next_floor,
            f"Advanced to S{next_floor[0]:02d}E{next_floor[1]:02d} from "
            f"S{season_number:02d}E{episode_number:02d}.",
        )

    def _sync_existing_rule(
        self,
        session: Session,
        rule: Rule,
        item: StremioLibraryItem,
        *,
        matched_by: str | None,
    ) -> StremioRuleSyncOutcome:
        previous_item_id = str(getattr(rule, "stremio_library_item_id", "") or "").strip() or None
        previous_item_type = _normalize_stremio_item_type(
            getattr(rule, "stremio_library_item_type", None)
        )
        previous_auto_disabled = bool(getattr(rule, "stremio_auto_disabled", False))
        previous_managed = bool(getattr(rule, "stremio_managed", False))
        previous_imdb_id = str(rule.imdb_id or "").strip().lower() or None
        previous_title = _resolved_rule_title(rule)
        previous_media_type = rule.media_type

        link_changed = previous_item_id != item.item_id or previous_item_type != item.item_type
        managed_changed = False
        status: StremioOutcomeStatus = "unchanged"

        rule.stremio_library_item_id = item.item_id
        rule.stremio_library_item_type = item.item_type

        if previous_managed:
            if rule.content_name != item.title:
                rule.content_name = item.title
                managed_changed = True
            if rule.normalized_title != item.title:
                rule.normalized_title = item.title
                managed_changed = True
            if rule.media_type != item.media_type:
                rule.media_type = item.media_type
                managed_changed = True
            if (item.imdb_id or None) != previous_imdb_id:
                rule.imdb_id = item.imdb_id
                managed_changed = True
        elif not previous_imdb_id and item.imdb_id:
            rule.imdb_id = item.imdb_id
            managed_changed = True

        message_parts: list[str] = []
        if link_changed:
            link_detail = f"Linked by {matched_by.lower()}." if matched_by else "Linked to Stremio."
            message_parts.append(link_detail)
            status = "linked"
        if previous_managed and managed_changed:
            message_parts.append("Updated Stremio-managed rule details.")
            status = "updated"
        elif not previous_managed and previous_imdb_id != (
            str(rule.imdb_id or "").strip().lower() or None
        ):
            message_parts.append("Filled the missing IMDb ID from Stremio.")
            if status == "unchanged":
                status = "updated"

        if previous_auto_disabled:
            rule.enabled = True
            rule.stremio_auto_disabled = False
            session.add(rule)
            message_parts.append("Re-enabled because the title is back in the Stremio library.")
            status = "reenabled"

        if link_changed or managed_changed or previous_auto_disabled:
            session.add(rule)

        base_outcome = StremioRuleSyncOutcome(
            status=status,
            rule_id=rule.id,
            rule_name=rule.rule_name,
            message=(
                " ".join(message_parts)
                if message_parts
                else (
                    f'Already linked to the Stremio title "{item.title}" and up to date.'
                    if previous_item_id == item.item_id
                    and previous_title == item.title
                    and previous_media_type == item.media_type
                    else f'Already linked to the Stremio title "{item.title}".'
                )
            ),
            item_id=item.item_id,
            item_title=item.title,
        )
        if item.media_type == MediaType.SERIES:
            return self._apply_series_watch_state_outcome(
                session,
                rule=rule,
                item=item,
                base_outcome=base_outcome,
            )
        return self._apply_movie_completion_outcome(
            session,
            rule=rule,
            item=item,
            base_outcome=base_outcome,
        )
