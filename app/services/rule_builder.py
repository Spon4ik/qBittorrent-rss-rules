from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import AppSettings, MediaType, Rule
from app.services.quality_filters import (
    grouped_tokens_to_regex,
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


def parse_additional_include_groups(value: str | None) -> list[list[str]]:
    if not (value or "").strip():
        return []

    groups: list[list[str]] = []
    seen_groups: set[str] = set()
    for part in EXTRA_INCLUDE_SPLIT_RE.split(value or ""):
        candidate = part.strip()
        if not candidate:
            continue
        alternatives: list[str] = []
        seen_alternatives: set[str] = set()
        for item in candidate.split("|"):
            option = item.strip()
            if not option:
                continue
            key = option.casefold()
            if key in seen_alternatives:
                continue
            seen_alternatives.add(key)
            alternatives.append(option)
        if not alternatives:
            continue
        group_key = "||".join(option.casefold() for option in alternatives)
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        groups.append(alternatives)
    return groups


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


def build_keyword_group_fragments(groups: list[list[str]]) -> list[str]:
    fragments: list[str] = []
    for group in groups:
        group_fragments = [build_title_regex_fragment(item) for item in group if item.strip()]
        if not group_fragments:
            continue
        if len(group_fragments) == 1:
            fragments.append(group_fragments[0])
            continue
        fragments.append(f"(?:{'|'.join(group_fragments)})")
    return fragments


def _build_min_numeric_pattern_1_to_99(value: int) -> str:
    bounded_value = max(1, min(99, int(value)))
    if bounded_value == 99:
        return "0*99"
    if bounded_value <= 9:
        return rf"(?:0*[{bounded_value}-9]|0*[1-9]\d)"

    tens, ones = divmod(bounded_value, 10)
    parts: list[str] = []
    if ones == 0:
        parts.append(rf"0*{tens}\d")
    elif ones == 9:
        parts.append(rf"0*{tens}9")
    else:
        parts.append(rf"0*{tens}[{ones}-9]")

    if tens < 9:
        parts.append(rf"0*[{tens + 1}-9]\d")
    if len(parts) == 1:
        return parts[0]
    return f"(?:{'|'.join(parts)})"


def build_episode_progress_fragment(start_season: int | None, start_episode: int | None) -> str:
    if start_season is None or start_episode is None:
        return ""

    season_value = max(1, min(99, int(start_season)))
    episode_value = max(1, min(99, int(start_episode)))
    season_exact = rf"0*{season_value}"
    episode_any = r"0*[1-9]\d?"
    episode_ge = _build_min_numeric_pattern_1_to_99(episode_value)
    separators = r"[\s._-]*"
    season_prefix = r"(?:s(?:eason)?[\s._:-]*)"
    episode_prefix = r"(?:e(?:p(?:isode)?)?[\s._:-]*)"

    fragments = [
        rf"{season_prefix}{season_exact}(?!\d){separators}{episode_prefix}{episode_ge}",
        rf"{season_prefix}{season_exact}(?!\d){separators}{episode_prefix}{episode_any}{separators}-{separators}(?:{episode_prefix})?{episode_ge}",
        rf"{season_prefix}{season_exact}(?!\d)(?:\b|$)",
    ]
    if season_value < 99:
        season_after = _build_min_numeric_pattern_1_to_99(season_value + 1)
        fragments.insert(0, rf"{season_prefix}{season_after}(?!\d){separators}{episode_prefix}{episode_any}")
        fragments.insert(1, rf"{season_prefix}{season_after}(?!\d)(?:\b|$)")
    return f"(?:{'|'.join(fragments)})"


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
        save_path_template = ""
        if self.settings is not None:
            save_path_template = (self.settings.save_path_template or "").strip()
        if not save_path_template:
            return ""
        rendered = save_path_template.format(
            title=sanitize_path_fragment(self._resolved_title(rule)),
            imdb_id=rule.imdb_id or "unknown",
            media_type=rule.media_type.value,
            category=sanitize_path_fragment(self.render_category(rule)),
        )
        return sanitize_path_fragment(rendered)

    def build_generated_pattern(self, rule: Rule) -> str:
        if looks_like_full_must_contain_override(rule.must_contain_override):
            return str(rule.must_contain_override or "").strip()

        title = self._resolved_title(rule)
        if not rule.use_regex and not self._has_generated_regex_conditions(rule):
            return title

        positive_fragments = [build_title_regex_fragment(title)]

        release_year = normalize_release_year(rule.release_year)
        if rule.include_release_year and release_year:
            positive_fragments.append(re.escape(release_year))

        positive_fragments.extend(
            build_keyword_group_fragments(parse_additional_include_groups(rule.additional_includes))
        )
        episode_progress_fragment = build_episode_progress_fragment(rule.start_season, rule.start_episode)
        if episode_progress_fragment:
            positive_fragments.append(episode_progress_fragment)

        quality_include_fragments, quality_exclude = self._resolve_quality_filters(rule)
        if quality_include_fragments:
            positive_fragments.extend(quality_include_fragments)
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
        quality_include_fragments, quality_exclude = self._resolve_quality_filters(rule)
        return bool(
            (rule.include_release_year and normalize_release_year(rule.release_year))
            or parse_additional_include_groups(rule.additional_includes)
            or build_episode_progress_fragment(rule.start_season, rule.start_episode)
            or quality_include_fragments
            or quality_exclude
            or build_manual_must_contain_fragments(rule.must_contain_override)
        )

    def _resolve_quality_filters(self, rule: Rule) -> tuple[list[str], str]:
        include_tokens = normalize_quality_tokens(rule.quality_include_tokens)
        exclude_tokens = normalize_quality_tokens(rule.quality_exclude_tokens)
        include_set = set(include_tokens)
        exclude_tokens = [token for token in exclude_tokens if token not in include_set]
        return grouped_tokens_to_regex(include_tokens), tokens_to_regex(exclude_tokens)
