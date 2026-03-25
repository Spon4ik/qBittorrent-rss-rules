from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSettings, MediaType, Rule
from app.services.metadata import MetadataClient, MetadataLookupError, MetadataLookupProvider
from app.services.rule_builder import normalize_jellyfin_episode_keys, normalize_release_year
from app.services.settings_service import SettingsService

JELLYFIN_SERIES_TYPE = "MediaBrowser.Controller.Entities.TV.Series"
JELLYFIN_EPISODE_TYPE = "MediaBrowser.Controller.Entities.TV.Episode"
JELLYFIN_MOVIE_TYPE = "MediaBrowser.Controller.Entities.Movies.Movie"
TITLE_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class JellyfinError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JellyfinUser:
    user_id: str
    username: str


@dataclass(frozen=True, slots=True)
class JellyfinConnectionSummary:
    db_path: str
    selected_user: JellyfinUser
    users: list[JellyfinUser]


@dataclass(frozen=True, slots=True)
class JellyfinLibraryRecord:
    item_id: str
    title: str
    normalized_title: str
    normalized_clean_name: str
    production_year: str | None
    imdb_id: str | None


@dataclass(frozen=True, slots=True)
class JellyfinEpisodeProgress:
    season_number: int
    episode_number: int
    is_watched: bool


@dataclass(frozen=True, slots=True)
class JellyfinDerivedFloor:
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
class JellyfinRuleSyncOutcome:
    rule_id: str
    rule_name: str
    status: Literal["synced", "unchanged", "skipped", "error"]
    message: str
    matched_title: str | None = None
    previous_start_season: int | None = None
    previous_start_episode: int | None = None
    new_start_season: int | None = None
    new_start_episode: int | None = None


@dataclass(frozen=True, slots=True)
class JellyfinRuleSyncSummary:
    db_path: str
    user_name: str
    synced_count: int
    unchanged_count: int
    skipped_count: int
    error_count: int
    outcomes: list[JellyfinRuleSyncOutcome]


def _normalize_title(value: str | None) -> str:
    tokens = TITLE_TOKEN_RE.findall(str(value or "").casefold())
    return " ".join(token for token in tokens if token)


def _normalize_imdb_id(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return cleaned.casefold()


def _normalize_year(value: object | None) -> str | None:
    cleaned = normalize_release_year(str(value or ""))
    return cleaned or None


def _as_nonnegative_int(value: object | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return None
    return numeric


def _increment_floor(season_number: int, episode_number: int) -> tuple[int, int]:
    if episode_number < 99:
        return season_number, episode_number + 1
    if season_number < 99:
        return season_number + 1, 1
    return season_number, episode_number


def _floor_tuple(season_number: int | None, episode_number: int | None) -> tuple[int, int] | None:
    if season_number is None or episode_number is None:
        return None
    return int(season_number), int(episode_number)


def _episode_key_tuple(value: str | None) -> tuple[int, int] | None:
    match = re.match(r"^s(?P<season>\d{1,2})e(?P<episode>\d{1,2})$", str(value or "").strip(), re.IGNORECASE)
    if match is None:
        return None
    return int(match.group("season")), int(match.group("episode"))


def _episode_key_from_tuple(value: tuple[int, int]) -> str:
    return f"S{value[0]:02d}E{value[1]:02d}"


def _sort_episode_keys(values: list[str]) -> list[str]:
    keyed: list[tuple[tuple[int, int], str]] = []
    for item in normalize_jellyfin_episode_keys(values):
        episode_tuple = _episode_key_tuple(item)
        if episode_tuple is None:
            continue
        keyed.append((episode_tuple, item))
    keyed.sort(key=lambda item: item[0])
    return [item[1] for item in keyed]


def _merge_episode_key_lists(*lists: list[str]) -> list[str]:
    return _sort_episode_keys([item for current in lists for item in current])


def _latest_episode_tuple(values: list[str]) -> tuple[int, int] | None:
    latest: tuple[int, int] | None = None
    for item in values:
        episode_tuple = _episode_key_tuple(item)
        if episode_tuple is None:
            continue
        if latest is None or episode_tuple > latest:
            latest = episode_tuple
    return latest


class JellyfinService:
    def __init__(self, settings: AppSettings | None) -> None:
        self.config = SettingsService.resolve_jellyfin(settings)
        self.metadata_config = SettingsService.resolve_metadata(settings)
        self._metadata_client: MetadataClient | None = None
        self._catalog_imdb_id_cache: dict[str, str | None] = {}
        self._catalog_season_cache: dict[tuple[str, int], list[int] | None] = {}

    def test_connection(self) -> JellyfinConnectionSummary:
        db_path = self._resolve_db_path()
        with self._connect(db_path) as connection:
            self._ensure_schema(connection)
            users = self._list_users(connection)
            selected_user = self._resolve_user(users)
        return JellyfinConnectionSummary(
            db_path=str(db_path),
            selected_user=selected_user,
            users=users,
        )

    def sync_rules(self, session: Session) -> JellyfinRuleSyncSummary:
        db_path = self._resolve_db_path()
        with self._connect(db_path) as connection:
            self._ensure_schema(connection)
            users = self._list_users(connection)
            selected_user = self._resolve_user(users)
            series_catalog = self._load_library_catalog(connection, item_type=JELLYFIN_SERIES_TYPE)
            movie_catalog = self._load_library_catalog(connection, item_type=JELLYFIN_MOVIE_TYPE)
            rules = session.scalars(
                select(Rule)
                .where(Rule.media_type.in_((MediaType.SERIES, MediaType.MOVIE)))
                .order_by(Rule.rule_name.asc())
            ).all()

            synced_count = 0
            unchanged_count = 0
            skipped_count = 0
            error_count = 0
            outcomes: list[JellyfinRuleSyncOutcome] = []

            for rule in rules:
                try:
                    outcome = self._sync_rule(
                        connection=connection,
                        user=selected_user,
                        series_catalog=series_catalog,
                        movie_catalog=movie_catalog,
                        session=session,
                        rule=rule,
                    )
                except JellyfinError as exc:
                    outcome = JellyfinRuleSyncOutcome(
                        rule_id=rule.id,
                        rule_name=rule.rule_name,
                        status="error",
                        message=str(exc),
                        previous_start_season=rule.start_season,
                        previous_start_episode=rule.start_episode,
                    )

                outcomes.append(outcome)
                if outcome.status == "synced":
                    synced_count += 1
                elif outcome.status == "unchanged":
                    unchanged_count += 1
                elif outcome.status == "skipped":
                    skipped_count += 1
                else:
                    error_count += 1

        if synced_count:
            session.commit()

        return JellyfinRuleSyncSummary(
            db_path=str(db_path),
            user_name=selected_user.username,
            synced_count=synced_count,
            unchanged_count=unchanged_count,
            skipped_count=skipped_count,
            error_count=error_count,
            outcomes=outcomes,
        )

    # Compatibility shim while the rest of the codebase still uses the older name.
    def sync_series_rules(self, session: Session) -> JellyfinRuleSyncSummary:
        return self.sync_rules(session)

    def _sync_rule(
        self,
        *,
        connection: sqlite3.Connection,
        user: JellyfinUser,
        series_catalog: list[JellyfinLibraryRecord],
        movie_catalog: list[JellyfinLibraryRecord],
        session: Session,
        rule: Rule,
    ) -> JellyfinRuleSyncOutcome:
        if rule.media_type == MediaType.SERIES:
            return self._sync_series_rule(
                connection=connection,
                user=user,
                series_catalog=series_catalog,
                session=session,
                rule=rule,
            )
        if rule.media_type == MediaType.MOVIE:
            return self._sync_movie_rule(
                movie_catalog=movie_catalog,
                session=session,
                rule=rule,
            )
        return JellyfinRuleSyncOutcome(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            status="skipped",
            message="Jellyfin sync only applies to series and movie rules.",
            previous_start_season=rule.start_season,
            previous_start_episode=rule.start_episode,
        )

    def _sync_series_rule(
        self,
        *,
        connection: sqlite3.Connection,
        user: JellyfinUser,
        series_catalog: list[JellyfinLibraryRecord],
        session: Session,
        rule: Rule,
    ) -> JellyfinRuleSyncOutcome:
        matched_series = self._match_library_item(rule, series_catalog, item_label="series")
        if matched_series is None:
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="skipped",
                message="No Jellyfin series match found.",
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        derived_floor = self._derive_next_floor(
            connection=connection,
            user=user,
            matched_series=matched_series,
            rule=rule,
            series_id=matched_series.item_id,
        )
        if derived_floor is None:
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="skipped",
                message=f'No Jellyfin episode inventory found for "{matched_series.title}".',
                matched_title=matched_series.title,
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        current_floor = _floor_tuple(rule.start_season, rule.start_episode)
        current_existing_episode_numbers = normalize_jellyfin_episode_keys(
            list(getattr(rule, "jellyfin_existing_episode_numbers", []) or [])
        )
        current_known_episode_numbers = normalize_jellyfin_episode_keys(
            list(getattr(rule, "jellyfin_known_episode_numbers", []) or [])
        )
        current_watched_episode_numbers = normalize_jellyfin_episode_keys(
            list(getattr(rule, "jellyfin_watched_episode_numbers", []) or [])
        )
        watched_next_floor = _floor_tuple(
            derived_floor.watched_start_season,
            derived_floor.watched_start_episode,
        )
        known_next_floor = _floor_tuple(
            derived_floor.known_start_season,
            derived_floor.known_start_episode,
        )
        next_existing_episode_numbers = normalize_jellyfin_episode_keys(
            derived_floor.existing_unseen_episode_numbers
        )
        next_known_episode_numbers = normalize_jellyfin_episode_keys(
            derived_floor.known_episode_numbers
        )
        next_watched_episode_numbers = normalize_jellyfin_episode_keys(
            derived_floor.watched_episode_numbers
        )
        keep_searching_existing_unseen = bool(
            getattr(rule, "jellyfin_search_existing_unseen", False)
        )

        effective_floor = current_floor
        floor_changed = False
        floor_detail = derived_floor.known_floor_reason
        next_floor: tuple[int, int] | None = known_next_floor
        if keep_searching_existing_unseen:
            next_floor = watched_next_floor
            if next_floor is None:
                next_floor = current_floor
            floor_detail = derived_floor.watched_floor_reason

        if next_floor is not None:
            effective_floor = next_floor
            floor_changed = current_floor != next_floor
            if current_floor is not None and current_floor >= next_floor:
                effective_floor = current_floor
                floor_changed = False
                floor_detail = "Current rule floor already matches Jellyfin-derived progress."
                if current_floor > next_floor:
                    floor_detail = "Current rule floor is already ahead of Jellyfin-derived progress."

        existing_episode_numbers_changed = (
            current_existing_episode_numbers != next_existing_episode_numbers
        )
        known_episode_numbers_changed = current_known_episode_numbers != next_known_episode_numbers
        watched_episode_numbers_changed = current_watched_episode_numbers != next_watched_episode_numbers
        if (
            not floor_changed
            and not existing_episode_numbers_changed
            and not known_episode_numbers_changed
            and not watched_episode_numbers_changed
        ):
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="unchanged",
                message=floor_detail,
                matched_title=matched_series.title,
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
                new_start_season=effective_floor[0] if effective_floor is not None else None,
                new_start_episode=effective_floor[1] if effective_floor is not None else None,
            )

        previous_season = rule.start_season
        previous_episode = rule.start_episode
        if effective_floor is not None:
            rule.start_season = effective_floor[0]
            rule.start_episode = effective_floor[1]
        rule.jellyfin_existing_episode_numbers = next_existing_episode_numbers
        rule.jellyfin_known_episode_numbers = next_known_episode_numbers
        rule.jellyfin_watched_episode_numbers = next_watched_episode_numbers
        session.add(rule)
        message_parts = [floor_detail]
        if existing_episode_numbers_changed:
            if next_existing_episode_numbers:
                message_parts.append(
                    f"Recorded {len(next_existing_episode_numbers)} existing unseen Jellyfin episode(s)."
                )
            elif current_existing_episode_numbers:
                message_parts.append("Cleared previously recorded existing unseen Jellyfin episodes.")
        if known_episode_numbers_changed:
            if next_known_episode_numbers:
                message_parts.append(
                    f"Remembered {len(next_known_episode_numbers)} Jellyfin episode(s) across sync history."
                )
            elif current_known_episode_numbers:
                message_parts.append("Cleared previously remembered Jellyfin episode history.")
        if watched_episode_numbers_changed and next_watched_episode_numbers:
            message_parts.append(
                f"Remembered watched progress across {len(next_watched_episode_numbers)} episode(s)."
            )
        return JellyfinRuleSyncOutcome(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            status="synced",
            message=" ".join(message_parts),
            matched_title=matched_series.title,
            previous_start_season=previous_season,
            previous_start_episode=previous_episode,
            new_start_season=effective_floor[0] if effective_floor is not None else None,
            new_start_episode=effective_floor[1] if effective_floor is not None else None,
        )

    def _sync_movie_rule(
        self,
        *,
        movie_catalog: list[JellyfinLibraryRecord],
        session: Session,
        rule: Rule,
    ) -> JellyfinRuleSyncOutcome:
        matched_movie = self._match_library_item(rule, movie_catalog, item_label="movie")
        keep_searching_existing = bool(getattr(rule, "jellyfin_search_existing_unseen", False))
        current_auto_disabled = bool(getattr(rule, "jellyfin_auto_disabled", False))
        current_enabled = bool(rule.enabled)

        if matched_movie is None:
            if not current_auto_disabled:
                return JellyfinRuleSyncOutcome(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    status="skipped",
                    message="No Jellyfin movie match found.",
                    previous_start_season=rule.start_season,
                    previous_start_episode=rule.start_episode,
                )
            rule.enabled = True
            rule.jellyfin_auto_disabled = False
            session.add(rule)
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="synced",
                message="Re-enabled because the previous Jellyfin movie match is no longer present.",
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        if keep_searching_existing:
            if current_auto_disabled:
                rule.enabled = True
                rule.jellyfin_auto_disabled = False
                session.add(rule)
                return JellyfinRuleSyncOutcome(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    status="synced",
                    message=(
                        "Movie already exists in Jellyfin, but this rule keeps searching for "
                        "better quality, so it was re-enabled."
                    ),
                    matched_title=matched_movie.title,
                    previous_start_season=rule.start_season,
                    previous_start_episode=rule.start_episode,
                )
            if current_enabled:
                return JellyfinRuleSyncOutcome(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    status="unchanged",
                    message=(
                        "Movie already exists in Jellyfin, but this rule keeps searching for "
                        "better quality."
                    ),
                    matched_title=matched_movie.title,
                    previous_start_season=rule.start_season,
                    previous_start_episode=rule.start_episode,
                )
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="unchanged",
                message=(
                    "Movie already exists in Jellyfin, and keep-search is enabled, so Jellyfin "
                    "sync left the current disabled state unchanged."
                ),
                matched_title=matched_movie.title,
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        if current_enabled:
            rule.enabled = False
            rule.jellyfin_auto_disabled = True
            session.add(rule)
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="synced",
                message="Disabled because the movie already exists in Jellyfin library.",
                matched_title=matched_movie.title,
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        if current_auto_disabled:
            return JellyfinRuleSyncOutcome(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                status="unchanged",
                message="Movie already exists in Jellyfin library and this rule remains auto-disabled.",
                matched_title=matched_movie.title,
                previous_start_season=rule.start_season,
                previous_start_episode=rule.start_episode,
            )

        return JellyfinRuleSyncOutcome(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            status="unchanged",
            message=(
                "Movie already exists in Jellyfin library, and the rule was already disabled "
                "outside Jellyfin sync."
            ),
            matched_title=matched_movie.title,
            previous_start_season=rule.start_season,
            previous_start_episode=rule.start_episode,
        )

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

    def _resolve_catalog_imdb_id(
        self,
        *,
        matched_series: JellyfinLibraryRecord,
        rule: Rule,
    ) -> str | None:
        existing_imdb_id = _normalize_imdb_id(matched_series.imdb_id or rule.imdb_id)
        if existing_imdb_id:
            return existing_imdb_id

        cache_key = matched_series.item_id
        if cache_key in self._catalog_imdb_id_cache:
            return self._catalog_imdb_id_cache[cache_key]

        client = self._metadata_client_for_catalog()
        if client is None:
            self._catalog_imdb_id_cache[cache_key] = None
            return None

        lookup_title = str(matched_series.title or rule.normalized_title or rule.content_name or "").strip()
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

    def _released_episode_numbers_for_season(
        self,
        *,
        matched_series: JellyfinLibraryRecord,
        rule: Rule,
        season_number: int,
    ) -> list[int] | None:
        if season_number < 1 or season_number > 99:
            return None

        imdb_id = self._resolve_catalog_imdb_id(matched_series=matched_series, rule=rule)
        if not imdb_id:
            return None

        cache_key = (imdb_id, season_number)
        if cache_key in self._catalog_season_cache:
            return self._catalog_season_cache[cache_key]

        client = self._metadata_client_for_catalog()
        if client is None:
            self._catalog_season_cache[cache_key] = None
            return None

        try:
            listing = client.lookup_omdb_season(imdb_id, season_number)
        except MetadataLookupError:
            self._catalog_season_cache[cache_key] = None
            return None

        now = datetime.now(UTC)
        released_episode_numbers = sorted(
            {
                episode.episode_number
                for episode in listing.released_episodes
                if episode.released_at is not None and episode.released_at <= now
            }
        )
        if not released_episode_numbers:
            self._catalog_season_cache[cache_key] = None
            return None
        self._catalog_season_cache[cache_key] = released_episode_numbers
        return released_episode_numbers

    def _next_floor_after_episode(
        self,
        *,
        matched_series: JellyfinLibraryRecord,
        rule: Rule,
        current_episode: tuple[int, int],
    ) -> tuple[tuple[int, int], str]:
        season_number, episode_number = current_episode
        released_episode_numbers = self._released_episode_numbers_for_season(
            matched_series=matched_series,
            rule=rule,
            season_number=season_number,
        )
        if released_episode_numbers:
            latest_released_episode = max(released_episode_numbers)
            if episode_number >= latest_released_episode and season_number < 99:
                next_floor = (season_number + 1, 0)
                return (
                    next_floor,
                    f'Advanced to S{next_floor[0]:02d}E{next_floor[1]:02d} because OMDb reports '
                    f'S{season_number:02d}E{latest_released_episode:02d} as the latest released '
                    f"episode in season {season_number}.",
                )

        next_floor = _increment_floor(season_number, episode_number)
        return (
            next_floor,
            f"Advanced to S{next_floor[0]:02d}E{next_floor[1]:02d} from "
            f"S{season_number:02d}E{episode_number:02d}.",
        )

    def _resolve_db_path(self) -> Path:
        raw_path = str(self.config.db_path or "").strip()
        if not raw_path:
            raise JellyfinError("Jellyfin DB path is not configured.")

        db_path = Path(raw_path).expanduser()
        if not db_path.is_absolute():
            db_path = (Path.cwd() / db_path).resolve()
        else:
            db_path = db_path.resolve()
        if not db_path.exists():
            raise JellyfinError(f"Jellyfin DB path does not exist: {db_path}")
        if not db_path.is_file():
            raise JellyfinError(f"Jellyfin DB path is not a file: {db_path}")
        return db_path

    @contextmanager
    def _connect(self, db_path: Path) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = 1")
        try:
            yield connection
        except sqlite3.DatabaseError as exc:
            raise JellyfinError(f"Jellyfin DB read failed: {exc}") from exc
        finally:
            connection.close()

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("SELECT 1 FROM Users LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM BaseItems LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM BaseItemProviders LIMIT 1").fetchone()
            connection.execute("SELECT 1 FROM UserData LIMIT 1").fetchone()
        except sqlite3.DatabaseError as exc:
            raise JellyfinError("Configured file is not a readable Jellyfin library database.") from exc

    @staticmethod
    def _list_users(connection: sqlite3.Connection) -> list[JellyfinUser]:
        rows = connection.execute(
            """
            SELECT Id, Username
            FROM Users
            ORDER BY Username COLLATE NOCASE, Id
            """
        ).fetchall()
        users: list[JellyfinUser] = []
        for row in rows:
            username = str(row["Username"] or "").strip()
            user_id = str(row["Id"] or "").strip()
            if not username or not user_id:
                continue
            users.append(JellyfinUser(user_id=user_id, username=username))
        return users

    def _resolve_user(self, users: list[JellyfinUser]) -> JellyfinUser:
        configured_name = str(self.config.user_name or "").strip()
        if configured_name:
            configured_key = configured_name.casefold()
            for user in users:
                if user.username.casefold() == configured_key:
                    return user
            raise JellyfinError(f'Jellyfin user "{configured_name}" was not found in the configured DB.')
        if len(users) == 1:
            return users[0]
        if not users:
            raise JellyfinError("No Jellyfin users were found in the configured DB.")
        raise JellyfinError("Multiple Jellyfin users were found. Set Jellyfin username in Settings.")

    @staticmethod
    def _load_library_catalog(
        connection: sqlite3.Connection,
        *,
        item_type: str,
    ) -> list[JellyfinLibraryRecord]:
        rows = connection.execute(
            """
            SELECT
                b.Id,
                b.Name,
                COALESCE(b.CleanName, '') AS CleanName,
                b.ProductionYear,
                MAX(CASE WHEN p.ProviderId = 'Imdb' THEN p.ProviderValue END) AS ImdbId
            FROM BaseItems b
            LEFT JOIN BaseItemProviders p ON p.ItemId = b.Id
            WHERE b.Type = ?
            GROUP BY b.Id, b.Name, b.CleanName, b.ProductionYear
            ORDER BY b.Name COLLATE NOCASE, b.Id
            """,
            (item_type,),
        ).fetchall()

        catalog: list[JellyfinLibraryRecord] = []
        for row in rows:
            title = str(row["Name"] or "").strip()
            item_id = str(row["Id"] or "").strip()
            if not title or not item_id:
                continue
            catalog.append(
                JellyfinLibraryRecord(
                    item_id=item_id,
                    title=title,
                    normalized_title=_normalize_title(title),
                    normalized_clean_name=_normalize_title(row["CleanName"]),
                    production_year=_normalize_year(row["ProductionYear"]),
                    imdb_id=_normalize_imdb_id(row["ImdbId"]),
                )
            )
        return catalog

    @staticmethod
    def _match_library_item(
        rule: Rule,
        catalog: list[JellyfinLibraryRecord],
        *,
        item_label: str,
    ) -> JellyfinLibraryRecord | None:
        rule_imdb_id = _normalize_imdb_id(rule.imdb_id)
        if rule_imdb_id:
            imdb_matches = [
                item
                for item in catalog
                if item.imdb_id and item.imdb_id == rule_imdb_id
            ]
            if len(imdb_matches) == 1:
                return imdb_matches[0]
            if len(imdb_matches) > 1:
                raise JellyfinError(f'Multiple Jellyfin {item_label} items matched IMDb ID "{rule.imdb_id}".')

        normalized_titles = {
            value
            for value in (
                _normalize_title(rule.normalized_title),
                _normalize_title(rule.content_name),
                _normalize_title(rule.rule_name),
            )
            if value
        }
        if not normalized_titles:
            return None

        title_matches = [
            item
            for item in catalog
            if item.normalized_title in normalized_titles
            or item.normalized_clean_name in normalized_titles
        ]
        if not title_matches:
            return None

        rule_year = _normalize_year(rule.release_year)
        if rule_year:
            year_matches = [item for item in title_matches if item.production_year == rule_year]
            if year_matches:
                title_matches = year_matches

        if rule_imdb_id:
            imdb_safe_matches = [
                item
                for item in title_matches
                if item.imdb_id in {None, rule_imdb_id}
            ]
            if not imdb_safe_matches:
                return None
            title_matches = imdb_safe_matches

        if len(title_matches) == 1:
            return title_matches[0]
        raise JellyfinError(
            f'Multiple Jellyfin {item_label} items matched the title "{rule.content_name}".'
        )

    def _derive_next_floor(
        self,
        *,
        connection: sqlite3.Connection,
        user: JellyfinUser,
        matched_series: JellyfinLibraryRecord,
        rule: Rule,
        series_id: str,
    ) -> JellyfinDerivedFloor | None:
        rows = connection.execute(
            """
            SELECT
                b.ParentIndexNumber AS SeasonNumber,
                b.IndexNumber AS EpisodeNumber,
                MAX(COALESCE(u.Played, 0)) AS Played,
                MAX(COALESCE(u.PlayCount, 0)) AS PlayCount
            FROM BaseItems b
            LEFT JOIN UserData u
              ON u.UserId = ?
             AND (
                u.ItemId = b.Id
                OR lower(COALESCE(u.CustomDataKey, '')) = lower(b.Id)
                OR EXISTS (
                    SELECT 1
                    FROM BaseItemProviders p
                    WHERE p.ItemId = b.Id
                      AND lower(COALESCE(p.ProviderValue, '')) = lower(COALESCE(u.CustomDataKey, ''))
                )
             )
            WHERE b.Type = ?
              AND b.SeriesId = ?
              AND b.ParentIndexNumber IS NOT NULL
              AND b.IndexNumber IS NOT NULL
            GROUP BY b.Id, b.ParentIndexNumber, b.IndexNumber
            ORDER BY b.ParentIndexNumber ASC, b.IndexNumber ASC, b.Id ASC
            """,
            (user.user_id, JELLYFIN_EPISODE_TYPE, series_id),
        ).fetchall()

        episodes: list[JellyfinEpisodeProgress] = []
        for row in rows:
            season_number = _as_nonnegative_int(row["SeasonNumber"])
            episode_number = _as_nonnegative_int(row["EpisodeNumber"])
            if season_number is None or episode_number is None:
                continue
            episodes.append(
                JellyfinEpisodeProgress(
                    season_number=season_number,
                    episode_number=episode_number,
                    is_watched=int(row["Played"] or 0) > 0 or int(row["PlayCount"] or 0) > 0,
                )
            )

        current_episode_numbers = _sort_episode_keys(
            [
                f"S{episode.season_number:02d}E{episode.episode_number:02d}"
                for episode in episodes
            ]
        )
        current_watched_episode_numbers = _sort_episode_keys(
            [
                f"S{episode.season_number:02d}E{episode.episode_number:02d}"
                for episode in episodes
                if episode.is_watched
            ]
        )
        remembered_known_episode_numbers = normalize_jellyfin_episode_keys(
            list(getattr(rule, "jellyfin_known_episode_numbers", []) or [])
        )
        remembered_watched_episode_numbers = normalize_jellyfin_episode_keys(
            list(getattr(rule, "jellyfin_watched_episode_numbers", []) or [])
        )
        known_episode_numbers = _merge_episode_key_lists(
            remembered_known_episode_numbers,
            current_episode_numbers,
        )
        watched_episode_numbers = _merge_episode_key_lists(
            remembered_watched_episode_numbers,
            current_watched_episode_numbers,
        )

        if not known_episode_numbers:
            return None

        last_watched = _latest_episode_tuple(watched_episode_numbers)
        latest_existing = _latest_episode_tuple(current_episode_numbers)
        latest_known = _latest_episode_tuple(known_episode_numbers)
        watched_floor_reason = "No watched Jellyfin episodes were found."
        watched_next_floor: tuple[int, int] | None = None
        if last_watched is not None:
            next_current_after_watched = next(
                (
                    episode_tuple
                    for episode_tuple in (
                        _episode_key_tuple(item) for item in current_episode_numbers
                    )
                    if episode_tuple is not None and episode_tuple > last_watched
                ),
                None,
            )
            if next_current_after_watched is not None:
                watched_next_floor = next_current_after_watched
                watched_floor_reason = (
                    f'Advanced to S{watched_next_floor[0]:02d}E{watched_next_floor[1]:02d} '
                    f'from Jellyfin progress through S{last_watched[0]:02d}E{last_watched[1]:02d}. '
                    "This rule keeps searching existing unseen Jellyfin episodes."
                )
            else:
                watched_next_floor, watched_base_reason = self._next_floor_after_episode(
                    matched_series=matched_series,
                    rule=rule,
                    current_episode=last_watched,
                )
                watched_floor_reason = (
                    f"{watched_base_reason} This rule keeps searching existing unseen Jellyfin episodes."
                )

        existing_unseen_episode_numbers: list[str] = []
        for episode_key in current_episode_numbers:
            if last_watched is None:
                existing_unseen_episode_numbers.append(episode_key)
                continue
            episode_tuple = _episode_key_tuple(episode_key)
            if episode_tuple is not None and episode_tuple > last_watched:
                existing_unseen_episode_numbers.append(episode_key)
        existing_unseen_episode_numbers = _sort_episode_keys(existing_unseen_episode_numbers)
        known_floor_reason = "No remembered Jellyfin episode history was found."
        known_next_floor: tuple[int, int] | None = None
        if latest_known is not None:
            known_next_floor, known_floor_reason = self._next_floor_after_episode(
                matched_series=matched_series,
                rule=rule,
                current_episode=latest_known,
            )

        return JellyfinDerivedFloor(
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
