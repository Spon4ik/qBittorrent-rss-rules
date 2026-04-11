from __future__ import annotations

import enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MediaType, MetadataProvider, QualityProfile
from app.services.quality_filters import normalize_quality_tokens

IMDB_ID_RE = re.compile(r"^tt\d+$")
YEAR_TOKEN_RE = re.compile(r"\b(\d{4})\b")
KEYWORD_SPLIT_RE = re.compile(r"[\n,;]+")
SEARCH_INDEXER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SEARCH_VIEW_MODE_OPTIONS = {"cards", "table"}
SEARCH_SORT_FIELDS = {
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
RULES_PAGE_VIEW_MODE_OPTIONS = {"table", "cards"}
RULES_PAGE_SORT_FIELDS = {
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
RULES_FETCH_SCHEDULE_SCOPES = {"enabled", "all"}


class FeedOption(BaseModel):
    label: str
    url: str


class MetadataLookupProvider(str, enum.Enum):
    OMDB = "omdb"
    MUSICBRAINZ = "musicbrainz"
    OPENLIBRARY = "openlibrary"
    GOOGLE_BOOKS = "google_books"


class SearchSourceKind(str, enum.Enum):
    RSS_FEED = "rss_feed"
    JACKETT_ACTIVE_SEARCH = "jackett_active_search"
    JACKETT_RULE_SOURCE = "jackett_rule_source"


class MetadataLookupRequest(BaseModel):
    provider: MetadataLookupProvider = MetadataLookupProvider.OMDB
    lookup_value: str = ""
    media_type: MediaType = MediaType.SERIES
    imdb_id: str | None = None

    @field_validator("lookup_value")
    @classmethod
    def normalize_lookup_value(cls, value: str) -> str:
        return value.strip()

    @field_validator("imdb_id")
    @classmethod
    def normalize_lookup_id(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value.strip()

    @model_validator(mode="after")
    def validate_lookup(self) -> MetadataLookupRequest:
        if self.imdb_id and not self.lookup_value:
            if not IMDB_ID_RE.match(self.imdb_id):
                raise ValueError("IMDb ID must look like tt1234567.")
            self.lookup_value = self.imdb_id
            self.provider = MetadataLookupProvider.OMDB
            return self
        if not self.lookup_value:
            raise ValueError("Enter a title or source ID first.")
        return self


class MetadataResult(BaseModel):
    title: str
    provider: MetadataLookupProvider
    imdb_id: str | None = None
    source_id: str | None = None
    media_type: MediaType
    year: str | None = None
    poster_url: str | None = None


class JackettSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=255)
    media_type: MediaType = MediaType.SERIES
    indexer: str = "all"
    imdb_id: str | None = None
    imdb_id_only: bool = False
    season_number: int | None = Field(default=None, ge=0, le=99)
    episode_number: int | None = Field(default=None, ge=0, le=999)
    release_year: str | None = None
    keywords_all: list[str] = Field(default_factory=list)
    keywords_any: list[str] = Field(default_factory=list)
    keywords_any_groups: list[list[str]] = Field(default_factory=list)
    keywords_not: list[str] = Field(default_factory=list)
    primary_keywords_all: list[str] = Field(default_factory=list)
    primary_keywords_any: list[str] = Field(default_factory=list)
    primary_keywords_any_groups: list[list[str]] = Field(default_factory=list)
    primary_keywords_not: list[str] = Field(default_factory=list)
    artist: str | None = Field(default=None, max_length=255)
    album: str | None = Field(default=None, max_length=255)
    track: str | None = Field(default=None, max_length=255)
    label: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    author: str | None = Field(default=None, max_length=255)
    publisher: str | None = Field(default=None, max_length=255)
    genre: str | None = Field(default=None, max_length=255)
    size_min_mb: float | None = Field(default=None, ge=0)
    size_max_mb: float | None = Field(default=None, ge=0)
    filter_indexers: list[str] = Field(default_factory=list)
    filter_category_ids: list[str] = Field(default_factory=list)

    @field_validator("indexer")
    @classmethod
    def normalize_indexer(cls, value: str) -> str:
        cleaned = value.strip()
        return cleaned or "all"

    @field_validator("imdb_id")
    @classmethod
    def normalize_search_imdb_id(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        cleaned = value.strip().lower()
        if cleaned.isdigit():
            cleaned = f"tt{cleaned}"
        if not IMDB_ID_RE.match(cleaned):
            raise ValueError("IMDb ID must look like tt1234567.")
        return cleaned

    @field_validator("release_year")
    @classmethod
    def normalize_search_release_year(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        cleaned = value.strip()
        match = YEAR_TOKEN_RE.search(cleaned)
        if not match:
            raise ValueError("Release year must include four digits.")
        return match.group(1)

    @field_validator(
        "artist",
        "album",
        "track",
        "label",
        "title",
        "author",
        "publisher",
        "genre",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator(
        "keywords_all",
        "keywords_any",
        "keywords_not",
        "primary_keywords_all",
        "primary_keywords_any",
        "primary_keywords_not",
        mode="before",
    )
    @classmethod
    def normalize_keyword_list(cls, value: list[str] | str | None) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            raw_value = KEYWORD_SPLIT_RE.split(value)
        else:
            raw_value = list(value)

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_value:
            candidate = str(item).strip()
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(candidate)
        return cleaned

    @field_validator("keywords_any_groups", "primary_keywords_any_groups", mode="before")
    @classmethod
    def normalize_keywords_any_groups(
        cls,
        value: list[list[str] | str] | None,
    ) -> list[list[str]]:
        if not value:
            return []

        normalized_groups: list[list[str]] = []
        for item in value:
            normalized_group = cls.normalize_keyword_list(item)
            if normalized_group:
                normalized_groups.append(normalized_group)
        return normalized_groups

    @field_validator("size_min_mb", "size_max_mb", mode="before")
    @classmethod
    def normalize_size_bounds(cls, value: float | int | str | None) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Size filters must be numeric.") from exc

    @field_validator("filter_indexers", mode="before")
    @classmethod
    def normalize_filter_indexers(cls, value: list[str] | str | None) -> list[str]:
        return cls.normalize_keyword_list(value)

    @field_validator("filter_category_ids", mode="before")
    @classmethod
    def normalize_filter_category_ids(cls, value: list[str] | str | None) -> list[str]:
        raw_items = cls.normalize_keyword_list(value)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            candidate = item.strip()
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(candidate)
        return cleaned

    @model_validator(mode="after")
    def validate_request(self) -> JackettSearchRequest:
        if self.indexer != "all" and not SEARCH_INDEXER_RE.match(self.indexer):
            raise ValueError("Indexer must use letters, numbers, dots, dashes, or underscores.")
        if self.imdb_id_only:
            if not self.imdb_id:
                raise ValueError("IMDb-first search requires an IMDb ID.")
            if self.media_type not in {MediaType.MOVIE, MediaType.SERIES}:
                raise ValueError("IMDb-first search is only available for movies and series.")
        if self.episode_number is not None and self.season_number is None:
            raise ValueError("Episode number requires a season number.")
        if (
            self.season_number is not None or self.episode_number is not None
        ) and self.media_type != MediaType.SERIES:
            raise ValueError("Season and episode narrowing is only available for series.")
        if len(self.keywords_all) > 24:
            raise ValueError("Use up to 24 required keywords per search.")
        if not self.keywords_any_groups and self.keywords_any:
            self.keywords_any_groups = [list(self.keywords_any)]
        if not self.primary_keywords_any_groups and self.primary_keywords_any:
            self.primary_keywords_any_groups = [list(self.primary_keywords_any)]
        if self.keywords_any_groups:
            flattened_any: list[str] = []
            seen_any: set[str] = set()
            for group in self.keywords_any_groups:
                if len(group) > 16:
                    raise ValueError("Use up to 16 optional keywords per keyword group.")
                for item in group:
                    if item in seen_any:
                        continue
                    seen_any.add(item)
                    flattened_any.append(item)
            self.keywords_any = flattened_any
        if self.primary_keywords_any_groups:
            flattened_primary_any: list[str] = []
            seen_primary_any: set[str] = set()
            for group in self.primary_keywords_any_groups:
                if len(group) > 16:
                    raise ValueError("Use up to 16 optional keywords per keyword group.")
                for item in group:
                    if item in seen_primary_any:
                        continue
                    seen_primary_any.add(item)
                    flattened_primary_any.append(item)
            self.primary_keywords_any = flattened_primary_any
        if len(self.keywords_any) > 64:
            raise ValueError("Use up to 64 optional keywords total per search.")
        if len(self.primary_keywords_all) > 24:
            raise ValueError("Use up to 24 required primary keywords per search.")
        if len(self.primary_keywords_any) > 64:
            raise ValueError("Use up to 64 optional primary keywords total per search.")
        if len(self.keywords_any_groups) > 8:
            raise ValueError("Use up to 8 optional keyword groups per search.")
        if len(self.primary_keywords_any_groups) > 8:
            raise ValueError("Use up to 8 optional primary keyword groups per search.")
        if len(self.keywords_not) > 48:
            raise ValueError("Use up to 48 excluded keywords per search.")
        if len(self.primary_keywords_not) > 48:
            raise ValueError("Use up to 48 excluded primary keywords per search.")
        if (
            self.size_min_mb is not None
            and self.size_max_mb is not None
            and self.size_min_mb > self.size_max_mb
        ):
            raise ValueError("Minimum size cannot be greater than maximum size.")
        return self


class JackettSearchResult(BaseModel):
    merge_key: str = ""
    title: str
    link: str
    indexer: str | None = None
    details_url: str | None = None
    guid: str | None = None
    info_hash: str | None = None
    imdb_id: str | None = None
    size_bytes: int | None = None
    size_label: str | None = None
    published_at: str | None = None
    published_label: str | None = None
    category_ids: list[str] = Field(default_factory=list)
    category_labels: list[str] = Field(default_factory=list)
    year: str | None = None
    seeders: int | None = None
    peers: int | None = None
    leechers: int | None = None
    grabs: int | None = None
    download_volume_factor: float | None = None
    upload_volume_factor: float | None = None
    torznab_attrs: dict[str, str] = Field(default_factory=dict)
    text_surface: str = ""
    source_kind: SearchSourceKind = SearchSourceKind.JACKETT_ACTIVE_SEARCH
    grouped_links: list[str] = Field(default_factory=list)
    grouped_indexers: list[str] = Field(default_factory=list)
    grouped_trackers: list[str] = Field(default_factory=list)
    duplicate_count: int = 1


class JackettSearchRun(BaseModel):
    source_kind: SearchSourceKind = SearchSourceKind.JACKETT_ACTIVE_SEARCH
    source_label: str = "Jackett active search"
    query_variants: list[str] = Field(default_factory=list)
    request_variants: list[str] = Field(default_factory=list)
    warning_messages: list[str] = Field(default_factory=list)
    raw_results: list[JackettSearchResult] = Field(default_factory=list)
    results: list[JackettSearchResult] = Field(default_factory=list)
    fallback_request_variants: list[str] = Field(default_factory=list)
    raw_fallback_results: list[JackettSearchResult] = Field(default_factory=list)
    fallback_results: list[JackettSearchResult] = Field(default_factory=list)


class SearchSortPreference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    field: str
    direction: str = "asc"

    @field_validator("field")
    @classmethod
    def validate_field(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in SEARCH_SORT_FIELDS:
            raise ValueError("Unsupported sort field.")
        return cleaned

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"asc", "desc"}:
            raise ValueError("Sort direction must be asc or desc.")
        return cleaned


class SearchViewPreferencesPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    view_mode: str = "table"
    sort_criteria: list[SearchSortPreference] = Field(default_factory=list)
    default_sequential_download: bool | None = None
    default_first_last_piece_prio: bool | None = None

    @field_validator("view_mode")
    @classmethod
    def validate_view_mode(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in SEARCH_VIEW_MODE_OPTIONS:
            raise ValueError("View mode must be cards or table.")
        return cleaned

    @model_validator(mode="after")
    def normalize_sort_criteria(self) -> SearchViewPreferencesPayload:
        normalized: list[SearchSortPreference] = []
        seen_fields: set[str] = set()
        for item in self.sort_criteria:
            if item.field in seen_fields:
                continue
            normalized.append(item)
            seen_fields.add(item.field)
            if len(normalized) >= 3:
                break
        self.sort_criteria = normalized or [
            SearchSortPreference(field="published_at", direction="desc")
        ]
        return self


class SearchQueueRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    link: str = Field(min_length=1)
    links: list[str] = Field(default_factory=list)
    info_hash: str | None = None
    tracker_urls: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    add_paused: bool | None = None
    sequential_download: bool = False
    first_last_piece_prio: bool = False

    @field_validator("links", "tracker_urls", mode="before")
    @classmethod
    def normalize_string_list(cls, value: list[str] | str | None) -> list[str]:
        return JackettSearchRequest.normalize_keyword_list(value)

    @field_validator("info_hash", mode="before")
    @classmethod
    def normalize_info_hash(cls, value: object | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip().casefold()
        return cleaned or None

    @model_validator(mode="after")
    def normalize_queue_links(self) -> SearchQueueRequest:
        normalized_links: list[str] = []
        seen_links: set[str] = set()
        seed_links = [self.link, *list(self.links or [])]
        for raw_link in seed_links:
            candidate = str(raw_link or "").strip()
            if not candidate or candidate in seen_links:
                continue
            seen_links.add(candidate)
            normalized_links.append(candidate)
        self.link = normalized_links[0]
        self.links = normalized_links
        return self


class RuleFormPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rule_name: str = Field(min_length=1, max_length=255)
    content_name: str = Field(min_length=1, max_length=255)
    imdb_id: str | None = None
    normalized_title: str = Field(default="", max_length=255)
    poster_url: str | None = Field(default=None, max_length=512)
    media_type: MediaType = MediaType.SERIES
    quality_profile: QualityProfile = QualityProfile.PLAIN
    release_year: str = Field(default="", max_length=16)
    include_release_year: bool = False
    additional_includes: str = ""
    quality_include_tokens: list[str] = Field(default_factory=list)
    quality_exclude_tokens: list[str] = Field(default_factory=list)
    use_regex: bool = False
    must_contain_override: str | None = None
    must_not_contain: str = ""
    start_season: int | None = Field(default=None, ge=1, le=99)
    start_episode: int | None = Field(default=None, ge=0, le=99)
    jellyfin_search_existing_unseen: bool = False
    episode_filter: str = ""
    ignore_days: int = Field(default=0, ge=0)
    add_paused: bool = True
    enabled: bool = True
    smart_filter: bool = False
    assigned_category: str = ""
    save_path: str = ""
    feed_urls: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("imdb_id")
    @classmethod
    def normalize_imdb_id(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        cleaned = value.strip()
        if not IMDB_ID_RE.match(cleaned):
            raise ValueError("IMDb ID must look like tt1234567.")
        return cleaned

    @field_validator("poster_url")
    @classmethod
    def normalize_poster_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @field_validator("release_year")
    @classmethod
    def normalize_release_year(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return ""
        match = YEAR_TOKEN_RE.search(cleaned)
        if match:
            return match.group(1)
        return cleaned

    @field_validator("quality_include_tokens", "quality_exclude_tokens", mode="before")
    @classmethod
    def normalize_quality_token_lists(cls, value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_value = [value]
        else:
            raw_value = list(value)
        return normalize_quality_tokens(raw_value)

    @model_validator(mode="after")
    def remove_quality_overlap(self) -> RuleFormPayload:
        include_set = set(self.quality_include_tokens)
        self.quality_exclude_tokens = [
            token for token in self.quality_exclude_tokens if token not in include_set
        ]
        return self

    @model_validator(mode="after")
    def validate_episode_progress_floor(self) -> RuleFormPayload:
        if (self.start_season is None) ^ (self.start_episode is None):
            raise ValueError("Set both Start Season and Start Episode, or leave both empty.")
        return self

    @field_validator("feed_urls")
    @classmethod
    def dedupe_feeds(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = item.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        if not cleaned:
            raise ValueError("Select at least one feed.")
        return cleaned


class SettingsFormPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    qb_base_url: str | None = None
    qb_username: str | None = None
    qb_password: str | None = None
    jackett_api_url: str | None = None
    jackett_qb_url: str | None = None
    jackett_api_key: str | None = None
    jellyfin_db_path: str | None = None
    jellyfin_user_name: str | None = None
    jellyfin_auto_sync_enabled: bool = True
    jellyfin_auto_sync_interval_seconds: int = Field(default=30, ge=5, le=3600)
    stremio_local_storage_path: str | None = None
    stremio_preferred_languages: str | None = None
    stremio_stream_provider_manifests: str | None = None
    stremio_auto_sync_enabled: bool = True
    stremio_auto_sync_interval_seconds: int = Field(default=30, ge=5, le=3600)
    metadata_provider: MetadataProvider = MetadataProvider.OMDB
    omdb_api_key: str | None = None
    series_category_template: str = "Series/{title} [imdbid-{imdb_id}]"
    movie_category_template: str = "Movies/{title} [imdbid-{imdb_id}]"
    save_path_template: str = ""
    default_add_paused: bool = True
    default_sequential_download: bool = True
    default_first_last_piece_prio: bool = True
    default_enabled: bool = True
    profile_1080p_include_tokens: list[str] = Field(default_factory=list)
    profile_1080p_exclude_tokens: list[str] = Field(default_factory=list)
    profile_2160p_hdr_include_tokens: list[str] = Field(default_factory=list)
    profile_2160p_hdr_exclude_tokens: list[str] = Field(default_factory=list)
    default_quality_profile: QualityProfile = QualityProfile.UHD_2160P_HDR

    @field_validator(
        "profile_1080p_include_tokens",
        "profile_1080p_exclude_tokens",
        "profile_2160p_hdr_include_tokens",
        "profile_2160p_hdr_exclude_tokens",
        mode="before",
    )
    @classmethod
    def normalize_profile_token_lists(cls, value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_value = [value]
        else:
            raw_value = list(value)
        return normalize_quality_tokens(raw_value)

    @model_validator(mode="after")
    def remove_profile_overlap(self) -> SettingsFormPayload:
        include_1080 = set(self.profile_1080p_include_tokens)
        self.profile_1080p_exclude_tokens = [
            token for token in self.profile_1080p_exclude_tokens if token not in include_1080
        ]
        include_2160 = set(self.profile_2160p_hdr_include_tokens)
        self.profile_2160p_hdr_exclude_tokens = [
            token for token in self.profile_2160p_hdr_exclude_tokens if token not in include_2160
        ]
        return self


class FilterProfileSaveRequest(BaseModel):
    mode: Literal["create", "overwrite"]
    profile_name: str = ""
    target_key: str = ""
    media_type: MediaType | None = None
    include_tokens: list[str] = Field(default_factory=list)
    exclude_tokens: list[str] = Field(default_factory=list)

    @field_validator("profile_name", "target_key")
    @classmethod
    def normalize_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("include_tokens", "exclude_tokens", mode="before")
    @classmethod
    def normalize_profile_tokens(cls, value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_value = [value]
        else:
            raw_value = list(value)
        return normalize_quality_tokens(raw_value)

    @model_validator(mode="after")
    def validate_payload(self) -> FilterProfileSaveRequest:
        include_set = set(self.include_tokens)
        self.exclude_tokens = [token for token in self.exclude_tokens if token not in include_set]
        if self.mode == "create" and not self.profile_name:
            raise ValueError("A profile name is required.")
        if self.mode == "overwrite" and not self.target_key:
            raise ValueError("Select an existing saved profile to overwrite.")
        return self


class RulesPagePreferencesPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    view_mode: str = "table"
    sort_field: str = "updated_at"
    sort_direction: str = "desc"

    @field_validator("view_mode")
    @classmethod
    def validate_view_mode(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in RULES_PAGE_VIEW_MODE_OPTIONS:
            raise ValueError("Rules page view mode must be table or cards.")
        return cleaned

    @field_validator("sort_field")
    @classmethod
    def validate_sort_field(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in RULES_PAGE_SORT_FIELDS:
            raise ValueError("Unsupported rules page sort field.")
        return cleaned

    @field_validator("sort_direction")
    @classmethod
    def validate_sort_direction(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"asc", "desc"}:
            raise ValueError("Sort direction must be asc or desc.")
        return cleaned


class RuleBatchFetchRequest(BaseModel):
    run_all: bool = False
    rule_ids: list[str] = Field(default_factory=list)
    include_disabled: bool = False

    @field_validator("rule_ids")
    @classmethod
    def normalize_rule_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = str(item or "").strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        return cleaned

    @model_validator(mode="after")
    def validate_scope(self) -> RuleBatchFetchRequest:
        if not self.run_all and not self.rule_ids:
            raise ValueError("Select one or more rules, or choose Run all.")
        return self


class RuleFetchSchedulePayload(BaseModel):
    enabled: bool
    interval_minutes: int = Field(default=360, ge=5, le=10080)
    scope: Literal["enabled", "all"] = "enabled"

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in RULES_FETCH_SCHEDULE_SCOPES:
            raise ValueError("Schedule scope must be enabled or all.")
        return cleaned


class SyncResult(BaseModel):
    success: bool
    action: str
    rule_id: str | None = None
    rule_name: str | None = None
    message: str


class BatchSyncResult(BaseModel):
    success_count: int = 0
    error_count: int = 0
    drift_detected: int = 0
    messages: list[str] = Field(default_factory=list)


class ImportMode(str, enum.Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"


class ImportPreviewEntry(BaseModel):
    rule_name: str
    resolved_name: str
    action: str
    media_type: MediaType
    assigned_category: str
    imdb_id: str | None = None


class ImportResult(BaseModel):
    imported_count: int
    skipped_count: int
    batch_id: str | None = None
    entries: list[ImportPreviewEntry] = Field(default_factory=list)
