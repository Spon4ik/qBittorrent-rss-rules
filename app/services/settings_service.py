from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_environment_settings, obfuscate_secret, reveal_secret
from app.models import AppSettings, MetadataProvider, QualityProfile
from app.schemas import SettingsFormPayload
from app.services.quality_filters import (
    BUILTIN_AT_LEAST_UHD_PROFILE_KEY,
    DEFAULT_QUALITY_PROFILE_RULES,
    LEGACY_DEFAULT_QUALITY_PROFILE_RULES,
    canonicalize_quality_tokens,
    normalize_saved_quality_profiles,
    resolve_quality_profile_rules,
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


class SettingsService:
    @staticmethod
    def get_or_create(session: Session) -> AppSettings:
        settings = session.get(AppSettings, "default")
        if settings is None:
            settings = AppSettings(
                id="default",
                quality_profile_rules=deepcopy(DEFAULT_QUALITY_PROFILE_RULES),
                saved_quality_profiles={},
                default_quality_profile=QualityProfile.UHD_2160P_HDR,
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
                normalized_profile_rules[profile_key] = deepcopy(DEFAULT_QUALITY_PROFILE_RULES[profile_key])
                changed = True
            if changed:
                settings.quality_profile_rules = normalized_profile_rules
        normalized_saved_profiles = normalize_saved_quality_profiles(settings.saved_quality_profiles)
        if normalized_saved_profiles != settings.saved_quality_profiles:
            settings.saved_quality_profiles = normalized_saved_profiles
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
        settings.metadata_provider = payload.metadata_provider
        settings.series_category_template = payload.series_category_template
        settings.movie_category_template = payload.movie_category_template
        settings.save_path_template = payload.save_path_template
        settings.default_add_paused = payload.default_add_paused
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
        if payload.omdb_api_key:
            settings.omdb_api_key_encrypted = obfuscate_secret(payload.omdb_api_key)
        return settings

    @staticmethod
    def resolve_qb_connection(settings: AppSettings | None) -> ResolvedQbConnection:
        env = get_environment_settings()
        return ResolvedQbConnection(
            base_url=env.qb_base_url or (settings.qb_base_url if settings else None),
            username=env.qb_username or (settings.qb_username if settings else None),
            password=env.qb_password or reveal_secret(settings.qb_password_encrypted if settings else None),
        )

    @staticmethod
    def resolve_metadata(settings: AppSettings | None) -> ResolvedMetadataConfig:
        env = get_environment_settings()
        provider = settings.metadata_provider if settings else MetadataProvider.OMDB
        return ResolvedMetadataConfig(
            provider=provider,
            api_key=env.omdb_api_key or reveal_secret(settings.omdb_api_key_encrypted if settings else None),
        )

    @staticmethod
    def to_form_dict(settings: AppSettings) -> dict[str, object]:
        profile_rules = resolve_quality_profile_rules(settings)
        saved_profiles = normalize_saved_quality_profiles(settings.saved_quality_profiles)
        saved_profiles.pop(BUILTIN_AT_LEAST_UHD_PROFILE_KEY, None)
        return {
            "qb_base_url": settings.qb_base_url or "",
            "qb_username": settings.qb_username or "",
            "metadata_provider": settings.metadata_provider.value,
            "series_category_template": settings.series_category_template,
            "movie_category_template": settings.movie_category_template,
            "save_path_template": settings.save_path_template,
            "default_add_paused": settings.default_add_paused,
            "default_enabled": settings.default_enabled,
            "profile_1080p_include_tokens": profile_rules[QualityProfile.HD_1080P.value]["include_tokens"],
            "profile_1080p_exclude_tokens": profile_rules[QualityProfile.HD_1080P.value]["exclude_tokens"],
            "profile_2160p_hdr_include_tokens": profile_rules[QualityProfile.UHD_2160P_HDR.value]["include_tokens"],
            "profile_2160p_hdr_exclude_tokens": profile_rules[QualityProfile.UHD_2160P_HDR.value]["exclude_tokens"],
            "default_quality_profile": settings.default_quality_profile.value,
            "saved_quality_profile_count": len(saved_profiles),
            "has_saved_qb_password": bool(settings.qb_password_encrypted),
            "has_saved_omdb_key": bool(settings.omdb_api_key_encrypted),
            "has_env_qb_password": bool(get_environment_settings().qb_password),
            "has_env_omdb_key": bool(get_environment_settings().omdb_api_key),
        }
