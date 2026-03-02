from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import AppSettings, MediaType, Rule
from app.services.quality_filters import (
    normalize_quality_tokens,
    tokens_to_regex,
)

INVALID_PATH_CHARS_RE = re.compile(r'[<>:"|?*]')
IMDB_IN_CATEGORY_RE = re.compile(r"\[imdbid-(tt\d+)\]", re.IGNORECASE)
TOKEN_RE = re.compile(r"\w+", re.UNICODE)
YEAR_TOKEN_RE = re.compile(r"\b(\d{4})\b")
EXTRA_INCLUDE_SPLIT_RE = re.compile(r"[\n,;]+")
MANUAL_MUST_CONTAIN_SPLIT_RE = re.compile(r"\r?\n")
REGEX_META_RE = re.compile(r"[\\.^$*+?{}\[\]|()]")
FULL_MUST_CONTAIN_OVERRIDE_PREFIXES: tuple[str, ...] = (
    "(?i",
    "(?m",
    "(?s",
    "(?x",
    "(?-",
    "(?=",
    "(?!",
    "(?<=",
    "(?<!",
    "(?P",
)


def sanitize_path_fragment(value: str) -> str:
    return INVALID_PATH_CHARS_RE.sub("_", value).strip()


def infer_media_type_from_category(category: str) -> MediaType:
    root_category = category.strip().lower().split("/", 1)[0]
    if root_category in {"movies", "movie"}:
        return MediaType.MOVIE
    if root_category in {"audiobooks", "audiobook"}:
        return MediaType.AUDIOBOOK
    if root_category == "music":
        return MediaType.MUSIC
    if root_category in {"series", "shows", "tv"}:
        return MediaType.SERIES
    return MediaType.OTHER


def extract_imdb_id_from_category(category: str) -> str | None:
    match = IMDB_IN_CATEGORY_RE.search(category)
    if not match:
        return None
    return match.group(1)


def build_title_regex_fragment(value: str) -> str:
    tokens = TOKEN_RE.findall(value.casefold())
    if not tokens:
        return re.escape(value.casefold().strip())
    return r"[\s._-]*".join(tokens)


def normalize_release_year(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    match = YEAR_TOKEN_RE.search(cleaned)
    if match:
        return match.group(1)
    return cleaned


def parse_additional_includes(value: str | None) -> list[str]:
    if not (value or "").strip():
        return []

    items: list[str] = []
    seen: set[str] = set()
    for part in EXTRA_INCLUDE_SPLIT_RE.split(value or ""):
        candidate = part.strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(candidate)
    return items


def looks_like_full_must_contain_override(value: str | None) -> bool:
    candidate = (value or "").strip()
    if not candidate:
        return False
    if any(candidate.startswith(prefix) for prefix in FULL_MUST_CONTAIN_OVERRIDE_PREFIXES):
        return True
    return any(token in candidate for token in ("(?=", "(?!", "(?<=", "(?<!"))


def parse_manual_must_contain_additions(value: str | None) -> list[str]:
    if not (value or "").strip():
        return []

    items: list[str] = []
    seen: set[str] = set()
    for part in MANUAL_MUST_CONTAIN_SPLIT_RE.split(value or ""):
        candidate = part.strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(candidate)
    return items


def build_manual_must_contain_fragments(value: str | None) -> list[str]:
    fragments: list[str] = []
    for item in parse_manual_must_contain_additions(value):
        if REGEX_META_RE.search(item):
            fragments.append(f"(?:{item})")
            continue
        fragments.append(build_title_regex_fragment(item))
    return fragments


@dataclass(slots=True)
class RuleBuilder:
    settings: AppSettings | None

    def render_category(self, rule: Rule) -> str:
        if rule.assigned_category.strip():
            return rule.assigned_category.strip()
        template = "Other/{title} [imdbid-{imdb_id}]"
        if self.settings is not None:
            if rule.media_type == MediaType.MOVIE:
                template = self.settings.movie_category_template or "Movies/{title} [imdbid-{imdb_id}]"
            elif rule.media_type == MediaType.SERIES:
                template = self.settings.series_category_template or "Series/{title} [imdbid-{imdb_id}]"
            elif rule.media_type == MediaType.AUDIOBOOK:
                template = "Audiobooks/{title}"
            elif rule.media_type == MediaType.MUSIC:
                template = "Music/{title}"
        elif rule.media_type == MediaType.MOVIE:
            template = "Movies/{title} [imdbid-{imdb_id}]"
        elif rule.media_type == MediaType.SERIES:
            template = "Series/{title} [imdbid-{imdb_id}]"
        elif rule.media_type == MediaType.AUDIOBOOK:
            template = "Audiobooks/{title}"
        elif rule.media_type == MediaType.MUSIC:
            template = "Music/{title}"
        return template.format(
            title=sanitize_path_fragment(self._resolved_title(rule)),
            imdb_id=rule.imdb_id or "unknown",
            media_type=rule.media_type.value,
            category=rule.assigned_category,
        )

    def render_save_path(self, rule: Rule) -> str:
        if rule.save_path.strip():
            return sanitize_path_fragment(rule.save_path)
        if self.settings is None or not self.settings.save_path_template.strip():
            return ""
        rendered = self.settings.save_path_template.format(
            title=sanitize_path_fragment(self._resolved_title(rule)),
            imdb_id=rule.imdb_id or "unknown",
            media_type=rule.media_type.value,
            category=sanitize_path_fragment(self.render_category(rule)),
        )
        return sanitize_path_fragment(rendered)

    def build_generated_pattern(self, rule: Rule) -> str:
        if looks_like_full_must_contain_override(rule.must_contain_override):
            return rule.must_contain_override.strip()

        title = self._resolved_title(rule)
        if not rule.use_regex and not self._has_generated_regex_conditions(rule):
            return title

        positive_fragments = [build_title_regex_fragment(title)]

        release_year = normalize_release_year(rule.release_year)
        if rule.include_release_year and release_year:
            positive_fragments.append(re.escape(release_year))

        for item in parse_additional_includes(rule.additional_includes):
            positive_fragments.append(build_title_regex_fragment(item))

        quality_include, quality_exclude = self._resolve_quality_filters(rule)
        if quality_include:
            positive_fragments.append(quality_include)
        positive_fragments.extend(build_manual_must_contain_fragments(rule.must_contain_override))

        pattern = "(?i)"
        pattern += "".join(f"(?=.*{fragment})" for fragment in positive_fragments if fragment)
        if quality_exclude:
            pattern += f"(?!.*{quality_exclude})"
        return pattern

    def build_qb_rule(self, rule: Rule) -> dict[str, object]:
        generated_pattern = self.build_generated_pattern(rule)
        effective_use_regex = bool(
            rule.use_regex
            or (rule.must_contain_override and rule.must_contain_override.strip())
            or self._has_generated_regex_conditions(rule)
        )
        return {
            "enabled": rule.enabled,
            "mustContain": generated_pattern,
            "mustNotContain": rule.must_not_contain or "",
            "useRegex": effective_use_regex,
            "episodeFilter": rule.episode_filter or "",
            "smartFilter": rule.smart_filter,
            "affectedFeeds": rule.feed_urls,
            "ignoreDays": rule.ignore_days,
            "addPaused": rule.add_paused,
            "assignedCategory": self.render_category(rule),
            "savePath": self.render_save_path(rule),
        }

    @staticmethod
    def _resolved_title(rule: Rule) -> str:
        title = rule.normalized_title.strip() or rule.content_name.strip() or rule.rule_name.strip()
        return title

    def _has_generated_regex_conditions(self, rule: Rule) -> bool:
        if looks_like_full_must_contain_override(rule.must_contain_override):
            return True
        quality_include, quality_exclude = self._resolve_quality_filters(rule)
        return bool(
            (rule.include_release_year and normalize_release_year(rule.release_year))
            or parse_additional_includes(rule.additional_includes)
            or quality_include
            or quality_exclude
            or build_manual_must_contain_fragments(rule.must_contain_override)
        )

    def _resolve_quality_filters(self, rule: Rule) -> tuple[str, str]:
        include_tokens = normalize_quality_tokens(rule.quality_include_tokens)
        exclude_tokens = normalize_quality_tokens(rule.quality_exclude_tokens)
        include_set = set(include_tokens)
        exclude_tokens = [token for token in exclude_tokens if token not in include_set]
        return tokens_to_regex(include_tokens), tokens_to_regex(exclude_tokens)
