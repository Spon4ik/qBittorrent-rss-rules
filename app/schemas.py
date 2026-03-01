from __future__ import annotations

import enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MediaType, MetadataProvider, QualityProfile
from app.services.quality_filters import normalize_quality_tokens

IMDB_ID_RE = re.compile(r"^tt\d+$")
YEAR_TOKEN_RE = re.compile(r"\b(\d{4})\b")


class FeedOption(BaseModel):
    label: str
    url: str


class MetadataLookupRequest(BaseModel):
    imdb_id: str

    @field_validator("imdb_id")
    @classmethod
    def validate_imdb_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not IMDB_ID_RE.match(cleaned):
            raise ValueError("IMDb ID must look like tt1234567.")
        return cleaned


class MetadataResult(BaseModel):
    title: str
    imdb_id: str
    media_type: MediaType
    year: str | None = None


class RuleFormPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rule_name: str = Field(min_length=1, max_length=255)
    content_name: str = Field(min_length=1, max_length=255)
    imdb_id: str | None = None
    normalized_title: str = Field(default="", max_length=255)
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
        if value in {None, ""}:
            return None
        cleaned = value.strip()
        if not IMDB_ID_RE.match(cleaned):
            raise ValueError("IMDb ID must look like tt1234567.")
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
    def remove_quality_overlap(self) -> "RuleFormPayload":
        include_set = set(self.quality_include_tokens)
        self.quality_exclude_tokens = [
            token for token in self.quality_exclude_tokens if token not in include_set
        ]
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
    metadata_provider: MetadataProvider = MetadataProvider.OMDB
    omdb_api_key: str | None = None
    series_category_template: str = "Series/{title} [imdbid-{imdb_id}]"
    movie_category_template: str = "Movies/{title} [imdbid-{imdb_id}]"
    save_path_template: str = ""
    default_add_paused: bool = True
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
    def remove_profile_overlap(self) -> "SettingsFormPayload":
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
    def validate_payload(self) -> "FilterProfileSaveRequest":
        include_set = set(self.include_tokens)
        self.exclude_tokens = [token for token in self.exclude_tokens if token not in include_set]
        if self.mode == "create" and not self.profile_name:
            raise ValueError("A profile name is required.")
        if self.mode == "overwrite" and not self.target_key:
            raise ValueError("Select an existing saved profile to overwrite.")
        return self


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
