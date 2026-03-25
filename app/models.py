from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MediaType(str, enum.Enum):
    SERIES = "series"
    MOVIE = "movie"
    AUDIOBOOK = "audiobook"
    MUSIC = "music"
    OTHER = "other"


MEDIA_TYPE_LABELS: dict[str, str] = {
    MediaType.SERIES.value: "Series",
    MediaType.MOVIE.value: "Movie",
    MediaType.AUDIOBOOK.value: "Audiobook",
    MediaType.MUSIC.value: "Music",
    MediaType.OTHER.value: "Any / custom",
}


def media_type_label(value: MediaType | str) -> str:
    raw_value = value.value if isinstance(value, MediaType) else value
    return MEDIA_TYPE_LABELS.get(raw_value, raw_value)


def media_type_choices() -> list[dict[str, str]]:
    return [{"value": item.value, "label": media_type_label(item)} for item in MediaType]


class QualityProfile(str, enum.Enum):
    PLAIN = "plain"
    HD_1080P = "1080p"
    UHD_2160P_HDR = "2160p_hdr"
    CUSTOM = "custom"


class SyncStatus(str, enum.Enum):
    NEVER = "never"
    OK = "ok"
    ERROR = "error"
    DRIFT = "drift"


class MetadataProvider(str, enum.Enum):
    OMDB = "omdb"
    DISABLED = "disabled"


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content_name: Mapped[str] = mapped_column(String(255), nullable=False)
    imdb_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    normalized_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    poster_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="media_type"),
        nullable=False,
        default=MediaType.SERIES,
    )
    quality_profile: Mapped[QualityProfile] = mapped_column(
        Enum(QualityProfile, name="quality_profile"),
        nullable=False,
        default=QualityProfile.PLAIN,
    )
    release_year: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    include_release_year: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    additional_includes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quality_include_tokens: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    quality_exclude_tokens: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    use_regex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_contain_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_not_contain: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_season: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    start_episode: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    jellyfin_search_existing_unseen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jellyfin_auto_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jellyfin_known_episode_numbers: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    jellyfin_watched_episode_numbers: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    jellyfin_existing_episode_numbers: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    episode_filter: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ignore_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    add_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    smart_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assigned_category: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    save_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    feed_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remote_rule_name_last_synced: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"),
        nullable=False,
        default=SyncStatus.NEVER,
    )
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class RuleSearchSnapshot(Base):
    __tablename__ = "rule_search_snapshots"

    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("rules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    inline_search: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    release_filter_cache_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_filtered_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_fetched_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    qb_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qb_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qb_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    jackett_api_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jackett_qb_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jackett_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    jellyfin_db_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    jellyfin_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jellyfin_auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    jellyfin_auto_sync_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
    )
    jellyfin_auto_sync_last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    jellyfin_auto_sync_last_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="idle",
    )
    jellyfin_auto_sync_last_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_provider: Mapped[MetadataProvider] = mapped_column(
        Enum(MetadataProvider, name="metadata_provider"),
        nullable=False,
        default=MetadataProvider.OMDB,
    )
    omdb_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_category_template: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Series/{title} [imdbid-{imdb_id}]",
    )
    movie_category_template: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="Movies/{title} [imdbid-{imdb_id}]",
    )
    save_path_template: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    default_add_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_sequential_download: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    default_first_last_piece_prio: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality_profile_rules: Mapped[dict[str, dict[str, list[str]]]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    saved_quality_profiles: Mapped[dict[str, dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    default_feed_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    search_result_view_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="table")
    search_sort_criteria: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    rules_fetch_schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rules_fetch_schedule_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=360,
    )
    rules_fetch_schedule_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="enabled")
    rules_fetch_schedule_last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rules_fetch_schedule_next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rules_fetch_schedule_last_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="idle",
    )
    rules_fetch_schedule_last_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rules_page_view_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="table")
    rules_page_sort_field: Mapped[str] = mapped_column(String(64), nullable=False, default="updated_at")
    rules_page_sort_direction: Mapped[str] = mapped_column(String(8), nullable=False, default="desc")
    default_quality_profile: Mapped[QualityProfile] = mapped_column(
        Enum(QualityProfile, name="default_quality_profile"),
        nullable=False,
        default=QualityProfile.UHD_2160P_HDR,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class SyncEvent(Base):
    __tablename__ = "sync_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class IndexerCategoryCatalog(Base):
    __tablename__ = "indexer_category_catalog"

    indexer: Mapped[str] = mapped_column(String(255), primary_key=True)
    category_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="result_attr")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
