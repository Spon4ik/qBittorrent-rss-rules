from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx

from app.config import ROOT_DIR, get_environment_settings
from app.models import MediaType, Rule
from app.schemas import (
    SEARCH_INDEXER_RE,
    JackettSearchRequest,
    JackettSearchResult,
    JackettSearchRun,
)
from app.services.quality_filters import quality_option_choices, quality_token_group_map
from app.services.rule_builder import (
    looks_like_full_must_contain_override,
    normalize_release_year,
    parse_additional_include_groups,
    parse_manual_must_contain_additions,
)
from app.services.selective_queue import text_matches_episode


class JackettClientError(RuntimeError):
    pass


class JackettConfigError(JackettClientError):
    pass


class JackettTimeoutError(JackettClientError):
    pass


class JackettHTTPError(JackettClientError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


PARENS_RE = re.compile(r"\(([^)]+)\)")
NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")
QUANTIFIER_RE = re.compile(r"\{[0-9]+(?:,[0-9]*)?\}")
YEAR_RE = re.compile(r"\b(\d{4})\b")
SEASON_TOKEN_RE = re.compile(r"^s0*(\d{1,2})$")
EPISODE_TOKEN_RE = re.compile(r"^e0*(\d{1,3})$")
SEASON_EPISODE_TOKEN_RE = re.compile(r"^s0*(\d{1,2})e0*(\d{1,3})$")
SEASON_EPISODE_RANGE_TEXT_RE = re.compile(
    r"(?i)s(?P<season>\d{1,2})[\s._-]*e(?P<start>\d{1,3})(?:[\s._-]*(?:-|to)[\s._-]*(?:e)?(?P<end>\d{1,3}))?"
)
SEASON_ONLY_TEXT_RE = re.compile(
    r"(?i)\b(?:s(?P<season_short>\d{1,2})(?![\s._-]*e\d)|season[\s._-]*(?P<season_long>\d{1,2}))\b"
)
TITLE_SEGMENT_SPLIT_RE = re.compile(r"[|/\[\]\(\)]+")
INDEXER_KEY_STRIP_RE = re.compile(r"[\s._-]+")
X_SEASON_EPISODE_TOKEN_RE = re.compile(r"^\d{1,2}x\d{1,3}$")
SEPARATOR_FRAGMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"[\s._-]*", " "),
    (r"[\s._-]+", " "),
    (r"[\s._-]?", " "),
    (r"\s*", " "),
    (r"\s+", " "),
    (r"\s?", " "),
)
MAX_REQUIRED_KEYWORDS = 24
MAX_OPTIONAL_KEYWORD_GROUPS = 8
MAX_OPTIONAL_KEYWORDS_PER_GROUP = 16
MAX_OPTIONAL_KEYWORDS_TOTAL = 64
MAX_EXCLUDED_KEYWORDS = 48
MAX_QUERY_VARIANTS = 32
MAX_SEARCH_QUERY_LENGTH = 255
TIMEOUT_RETRY_ATTEMPTS = 3
TORZNAB_MEDIA_CATEGORIES: dict[MediaType, tuple[str, ...]] = {
    MediaType.MOVIE: ("2000",),
    MediaType.SERIES: ("5000",),
    MediaType.MUSIC: ("3000",),
    MediaType.AUDIOBOOK: ("3030",),
}
TORZNAB_MODE_BY_MEDIA_TYPE: dict[MediaType, str] = {
    MediaType.MOVIE: "movie",
    MediaType.SERIES: "tvsearch",
    MediaType.MUSIC: "music",
    MediaType.AUDIOBOOK: "book",
}
TORZNAB_CAPABILITY_TAG_BY_MODE = {
    "search": "search",
    "tvsearch": "tv-search",
    "movie": "movie-search",
    "music": "music-search",
    "book": "book-search",
}
TORZNAB_STANDARD_CATEGORY_LABELS: dict[str, tuple[str, ...]] = {
    "1000": ("Console",),
    "1010": ("Console/NDS",),
    "1020": ("Console/PSP",),
    "1030": ("Console/Wii",),
    "1040": ("Console/XBox",),
    "1050": ("Console/XBox 360",),
    "1080": ("Console/PS3",),
    "1090": ("Console/Other",),
    "1120": ("Console/PS Vita",),
    "1180": ("Console/PS4",),
    "2000": ("Movies",),
    "2010": ("Movies/Foreign",),
    "2020": ("Movies/Other",),
    "2040": ("Movies/HD",),
    "2045": ("Movies/UHD",),
    "2060": ("Movies/3D",),
    "2070": ("Movies/DVD",),
    "3000": ("Audio",),
    "3010": ("Audio/MP3",),
    "3020": ("Audio/Video",),
    "3030": ("Audio/Audiobook",),
    "3040": ("Audio/Lossless",),
    "4000": ("PC",),
    "4030": ("PC/Mac",),
    "4040": ("PC/Mobile-Other",),
    "4050": ("PC/Games",),
    "4060": ("PC/Mobile-iOS",),
    "4070": ("PC/Mobile-Android",),
    "5000": ("TV",),
    "5020": ("TV/Foreign",),
    "5030": ("TV/SD",),
    "5040": ("TV/HD",),
    "5045": ("TV/UHD",),
    "5050": ("TV/Other",),
    "5060": ("TV/Sport",),
    "5070": ("TV/Anime",),
    "5080": ("TV/Documentary",),
    "6000": ("XXX",),
    "7000": ("Books",),
    "7010": ("Books/Mags",),
    "7020": ("Books/EBook",),
    "7030": ("Books/Comics",),
    "7040": ("Books/Technical",),
    "7050": ("Books/Other",),
    "8000": ("Other",),
    "8010": ("Other/Misc",),
}
LOGGER = logging.getLogger(__name__)
SEARCH_DEBUG_LOG_PATH = ROOT_DIR / "logs" / "search-debug.log"
PRECISE_TITLE_ALLOWED_POSTFIX_TOKENS = frozenset(
    {
        "aac",
        "ac3",
        "atmos",
        "av1",
        "avc",
        "avo",
        "bdrip",
        "bluray",
        "blu",
        "cam",
        "christmas",
        "complete",
        "criterion",
        "director",
        "dub",
        "dts",
        "dv",
        "dvd",
        "dvdrip",
        "eng",
        "ep",
        "episode",
        "extended",
        "finale",
        "h264",
        "h265",
        "hdtv",
        "hevc",
        "hdr",
        "hdr10",
        "imax",
        "limited",
        "multi",
        "mvo",
        "pack",
        "pilot",
        "proper",
        "ray",
        "remux",
        "repack",
        "rus",
        "season",
        "series",
        "special",
        "sub",
        "telecine",
        "truehd",
        "ts",
        "uhd",
        "uncut",
        "ukr",
        "unrated",
        "web",
        "webdl",
        "webrip",
        "x264",
        "x265",
        "xmas",
    }
)


@dataclass(frozen=True)
class JackettIndexerCapability:
    indexer_id: str
    supported_params: frozenset[str]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_datetime(value: str | None) -> datetime | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_published(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _coerce_int(value: str | None) -> int | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _coerce_float(value: str | None) -> float | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_size(value: int | None) -> str | None:
    if value is None:
        return None
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def _normalize_term(value: str) -> str:
    cleaned = str(value or "").casefold().replace("_", " ")
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _normalize_match_text(value: str) -> str:
    cleaned = str(value or "").casefold().replace("_", " ")
    cleaned = NON_WORD_RE.sub(" ", cleaned)
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _matches_excluded_keyword(text_surface: str, keyword: str) -> bool:
    normalized_keyword = _normalize_match_text(keyword)
    if not normalized_keyword:
        return False
    # Short tokens like "sd"/"ts" are too noisy under substring matching.
    if " " not in normalized_keyword and len(normalized_keyword) <= 2:
        padded_surface = f" {text_surface} "
        return f" {normalized_keyword} " in padded_surface
    return normalized_keyword in text_surface


def _matches_included_keyword(text_surface: str, keyword: str) -> bool:
    normalized_keyword = _normalize_match_text(keyword)
    if not normalized_keyword:
        return False
    text_tokens = [item for item in text_surface.split(" ") if item]
    season_episode_match = SEASON_EPISODE_TOKEN_RE.match(normalized_keyword)
    if season_episode_match:
        season_number = int(season_episode_match.group(1))
        episode_number = int(season_episode_match.group(2))
        variants = {
            f"s{season_number}e{episode_number}",
            f"s{season_number:02d}e{episode_number}",
            f"s{season_number}e{episode_number:02d}",
            f"s{season_number:02d}e{episode_number:02d}",
        }
        return any(token in variants for token in text_tokens)
    season_match = SEASON_TOKEN_RE.match(normalized_keyword)
    if season_match:
        season_number = int(season_match.group(1))
        variants = {f"s{season_number}", f"s{season_number:02d}"}
        for token in text_tokens:
            if token in variants:
                return True
            for variant in variants:
                if (
                    token.startswith(f"{variant}e")
                    and len(token) > len(variant) + 1
                    and token[len(variant) + 1 :].isdigit()
                ):
                    return True
        return False
    episode_match = EPISODE_TOKEN_RE.match(normalized_keyword)
    if episode_match:
        episode_number = int(episode_match.group(1))
        variants = {f"e{episode_number}", f"e{episode_number:02d}"}
        for token in text_tokens:
            if token in variants:
                return True
            if not token.startswith("s") or "e" not in token[1:]:
                continue
            season_token, episode_token = token.split("e", 1)
            if (
                season_token.startswith("s")
                and season_token[1:].isdigit()
                and episode_token.isdigit()
                and int(episode_token) == episode_number
            ):
                return True
        return False
    # Keep short include tokens token-aware so "hdr" does not match "hdrezka".
    if " " not in normalized_keyword and len(normalized_keyword) <= 3:
        padded_surface = f" {text_surface} "
        return f" {normalized_keyword} " in padded_surface
    return normalized_keyword in text_surface


def _matches_query_text(*, title_surface: str, query: str) -> bool:
    normalized_query = _normalize_match_text(query)
    if not normalized_query:
        return True
    if normalized_query in title_surface:
        return True
    query_terms = [item for item in normalized_query.split(" ") if item]
    if not query_terms:
        return True
    title_terms = {item for item in title_surface.split(" ") if item}
    return all(item in title_terms for item in query_terms)


def _precise_title_segments(title: str) -> list[str]:
    segments: list[str] = []
    seen: set[str] = set()
    for raw_segment in TITLE_SEGMENT_SPLIT_RE.split(str(title or "")):
        candidate = raw_segment.strip()
        if not candidate:
            continue
        normalized = _normalize_match_text(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        segments.append(candidate)
    return segments or [str(title or "")]


def _is_allowed_precise_title_suffix_token(token: str) -> bool:
    normalized = _normalize_match_text(token)
    if not normalized:
        return True
    if YEAR_RE.fullmatch(normalized):
        return True
    if SEASON_TOKEN_RE.match(normalized) or EPISODE_TOKEN_RE.match(normalized):
        return True
    if SEASON_EPISODE_TOKEN_RE.match(normalized) or X_SEASON_EPISODE_TOKEN_RE.match(normalized):
        return True
    if normalized in PRECISE_TITLE_ALLOWED_POSTFIX_TOKENS:
        return True
    return normalized in _known_quality_search_terms()


def _segment_matches_precise_title_identity(segment: str, query: str) -> bool:
    normalized_segment = _normalize_match_text(segment)
    normalized_query = _normalize_match_text(query)
    if not normalized_segment or not normalized_query:
        return False
    if normalized_segment == normalized_query:
        return True
    if not normalized_segment.startswith(normalized_query):
        return False
    suffix = normalized_segment[len(normalized_query) :].strip()
    if not suffix:
        return True
    first_token = suffix.split(" ", 1)[0]
    return _is_allowed_precise_title_suffix_token(first_token)


def _matches_precise_title_identity(title: str, query: str) -> bool:
    return any(
        _segment_matches_precise_title_identity(segment, query)
        for segment in _precise_title_segments(title)
    )


def _episode_matches_for_text(text: str) -> list[tuple[int, int, int]]:
    matches: list[tuple[int, int, int]] = []
    for match in SEASON_EPISODE_RANGE_TEXT_RE.finditer(str(text or "")):
        season_number = int(match.group("season"))
        start_episode = int(match.group("start"))
        end_raw = match.group("end")
        end_episode = int(end_raw) if end_raw is not None else start_episode
        if end_episode < start_episode:
            start_episode, end_episode = end_episode, start_episode
        matches.append((season_number, start_episode, end_episode))
    return matches


def _matches_requested_season(text: str, *, season_number: int) -> bool:
    if any(
        matched_season == season_number
        for matched_season, _start_episode, _end_episode in _episode_matches_for_text(text)
    ):
        return True
    for match in SEASON_ONLY_TEXT_RE.finditer(str(text or "")):
        raw_season = match.group("season_short") or match.group("season_long")
        if raw_season is not None and int(raw_season) == season_number:
            return True
    return False


def _matches_requested_season_episode(
    text: str,
    *,
    season_number: int,
    episode_number: int,
) -> bool:
    if text_matches_episode(
        str(text or ""),
        season_number=season_number,
        episode_number=episode_number,
    ):
        return True
    episode_matches = _episode_matches_for_text(text)
    if episode_matches:
        return False
    return _matches_requested_season(text, season_number=season_number)


def _first_nonempty_text(*values: object | None) -> str:
    for value in values:
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return ""


def _coerce_text(value: object | None) -> str:
    return str(value or "").strip()


def _normalize_legacy_optional_text(value: object | None) -> str:
    cleaned = _coerce_text(value)
    if cleaned.casefold() in {"none", "null"}:
        return ""
    return cleaned


def _normalize_release_year_token(value: str | None) -> str | None:
    cleaned = _coerce_text(value)
    if not cleaned:
        return None
    match = YEAR_RE.search(cleaned)
    if not match:
        return None
    return match.group(1)


def _resolved_result_year(*, explicit_year: str | None, title: str) -> str | None:
    return _normalize_release_year_token(explicit_year) or _normalize_release_year_token(title)


def _append_search_debug_event(event: Mapping[str, Any]) -> None:
    try:
        SEARCH_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SEARCH_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), ensure_ascii=True))
            handle.write("\n")
    except OSError:
        LOGGER.exception("Failed to write Jackett search debug log.")


def _extract_category_ids(value: str | None) -> list[str]:
    cleaned = _coerce_text(value)
    if not cleaned:
        return []
    categories: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"[\s,|;]+", cleaned):
        token = candidate.strip()
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        categories.append(token)
    return categories


def _result_merge_key(
    *,
    info_hash: str | None,
    guid: str | None,
    title: str,
    size_bytes: int | None,
) -> str:
    if info_hash:
        return f"hash:{info_hash.casefold()}"
    if guid:
        return f"guid:{guid.casefold()}"
    size_key = size_bytes if size_bytes is not None else "none"
    return f"title:{title.casefold()}:{size_key}"


def _result_text_surface(
    *,
    title: str,
    indexer: str | None,
    imdb_id: str | None,
    year: str | None,
    category_ids: list[str],
    category_labels: list[str],
    torznab_attrs: dict[str, str],
) -> str:
    parts: list[str] = [title]
    if indexer:
        parts.append(indexer)
    if imdb_id:
        parts.append(imdb_id)
    if year:
        parts.append(year)
    parts.extend(category_ids)
    parts.extend(category_labels)
    parts.extend(value for value in torznab_attrs.values() if value)
    return _normalize_match_text(" ".join(parts))


def _normalize_category_filter_token(value: str) -> str:
    return _normalize_match_text(value)


def _indexer_key_variants(value: str | None) -> set[str]:
    raw = _coerce_text(value).casefold()
    if not raw:
        return set()
    cleaned = raw[4:] if raw.startswith("www.") else raw
    compact = INDEXER_KEY_STRIP_RE.sub("", cleaned)
    variants = {item for item in (cleaned, compact) if item}
    if "." in cleaned:
        host_without_tld = cleaned.rsplit(".", 1)[0].strip()
        if host_without_tld:
            variants.add(host_without_tld)
            compact_host = INDEXER_KEY_STRIP_RE.sub("", host_without_tld)
            if compact_host:
                variants.add(compact_host)
    return variants


def _dedupe_category_labels(raw_labels: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in raw_labels:
        candidate = _coerce_text(item)
        if not candidate:
            continue
        key = _normalize_category_filter_token(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        labels.append(candidate)
    return labels


def clamp_search_query_text(value: object | None, *, fallback: str = "") -> str:
    cleaned = _coerce_text(value)
    if not cleaned:
        return _coerce_text(fallback)
    if len(cleaned) <= MAX_SEARCH_QUERY_LENGTH:
        return cleaned

    truncated = cleaned[:MAX_SEARCH_QUERY_LENGTH].rstrip()
    last_space = truncated.rfind(" ")
    if last_space >= 32:
        word_trimmed = truncated[:last_space].rstrip(" ._-")
        if word_trimmed:
            return word_trimmed
    return truncated


def _torznab_imdb_lookup_id(value: str | None) -> str | None:
    cleaned = _coerce_text(value).lower()
    if not cleaned:
        return None
    if cleaned.startswith("tt") and cleaned[2:].isdigit():
        return cleaned
    if cleaned.isdigit():
        return f"tt{cleaned}"
    return None


def _torznab_categories_for_media_type(media_type: MediaType) -> tuple[str, ...]:
    return TORZNAB_MEDIA_CATEGORIES.get(media_type, ())


def _torznab_mode_for_payload(payload: JackettSearchRequest) -> str:
    if payload.media_type == MediaType.OTHER:
        return "search"
    if payload.imdb_id or payload.release_year or payload.season_number is not None:
        return TORZNAB_MODE_BY_MEDIA_TYPE.get(payload.media_type, "search")
    return "search"


def _request_variant_label(params: Mapping[str, Any]) -> str:
    ordered_keys = ("t", "q", "imdbid", "season", "ep", "year", "cat")
    parts: list[str] = []

    for key in ordered_keys:
        if key == "apikey":
            continue
        value = _coerce_text(params.get(key))
        if not value:
            continue
        if key == "q":
            parts.append(f'{key}="{value}"')
            continue
        parts.append(f"{key}={value}")

    extra_keys = sorted(key for key in params if key not in {"apikey", *ordered_keys})
    for key in extra_keys:
        value = _coerce_text(params.get(key))
        if value:
            parts.append(f"{key}={value}")

    return " ".join(parts)


def _request_error_context(url: str, params: Mapping[str, Any]) -> str:
    request_label = _request_variant_label(params)
    if request_label:
        return request_label
    return url


def _coerce_string_list(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                loaded = json.loads(cleaned)
            except ValueError:
                raw_values = [cleaned]
            else:
                if isinstance(loaded, list):
                    raw_values = loaded
                else:
                    raw_values = [cleaned]
        else:
            raw_values = re.split(r"[\n,;]+", cleaned)
    else:
        raw_values = [value]
    return [candidate for candidate in (_coerce_text(item) for item in raw_values) if candidate]


def _coerce_media_type(value: object | None) -> MediaType:
    if isinstance(value, MediaType):
        return value
    raw_value = getattr(value, "value", value)
    try:
        return MediaType(_coerce_text(raw_value))
    except ValueError:
        return MediaType.SERIES


def _dedupe_terms(raw_terms: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_terms:
        candidate = _normalize_term(item)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        cleaned.append(candidate)
    return cleaned


def _dedupe_term_groups(raw_groups: list[list[str]]) -> list[list[str]]:
    cleaned_groups: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in raw_groups:
        cleaned_group = _dedupe_terms(group)
        if not cleaned_group:
            continue
        key = tuple(cleaned_group)
        if key in seen:
            continue
        seen.add(key)
        cleaned_groups.append(cleaned_group)
    return cleaned_groups


def _quality_search_term_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for item in quality_option_choices():
        token = str(item["value"])
        label = str(item["label"])
        pattern = str(item.get("pattern", "")).strip()
        terms: list[str] = [token]
        label_without_parens = PARENS_RE.sub("", label).strip()
        if label_without_parens:
            terms.append(label_without_parens)
        for match in PARENS_RE.findall(label):
            if match.strip():
                terms.append(match.strip())
        if pattern:
            terms.extend(_regex_fragment_to_terms(pattern))
        mapping[token] = _dedupe_terms(terms)
    return mapping


def _known_quality_search_terms() -> set[str]:
    known_terms: set[str] = set()
    for group in _quality_search_term_map().values():
        known_terms.update(group)
    return known_terms


def _quality_terms(tokens: list[str] | None) -> list[str]:
    mapping = _quality_search_term_map()
    terms: list[str] = []
    for token in tokens or []:
        token_terms = mapping.get(str(token).strip())
        if token_terms:
            terms.extend(token_terms)
            continue
        terms.append(str(token))
    return _dedupe_terms(terms)


def _group_quality_terms(tokens: list[str] | None) -> list[list[str]]:
    normalized_tokens = [str(token).strip() for token in (tokens or []) if str(token).strip()]
    if not normalized_tokens:
        return []

    token_groups = quality_token_group_map()
    grouped_terms: dict[str, list[str]] = {}
    ordered_group_keys: list[str] = []
    for token in normalized_tokens:
        group_key = token_groups.get(token, "__ungrouped__")
        if group_key not in grouped_terms:
            grouped_terms[group_key] = []
            ordered_group_keys.append(group_key)
        grouped_terms[group_key].extend(_quality_terms([token]))

    deduped_groups: list[list[str]] = []
    for group_key in ordered_group_keys:
        deduped = _dedupe_terms(grouped_terms[group_key])
        if deduped:
            deduped_groups.append(deduped)
    return deduped_groups


def quality_search_term_map() -> dict[str, list[str]]:
    return {token: list(terms) for token, terms in _quality_search_term_map().items()}


def quality_pattern_map() -> dict[str, str]:
    patterns: dict[str, str] = {}
    for item in quality_option_choices():
        token = _coerce_text(item.get("value"))
        pattern = _coerce_text(item.get("pattern"))
        if token and pattern:
            patterns[token] = pattern
    return patterns


def expand_quality_search_terms(tokens: list[str] | None) -> list[str]:
    return _quality_terms(tokens)


def expand_grouped_quality_search_terms(tokens: list[str] | None) -> list[list[str]]:
    return _group_quality_terms(tokens)


def _capped_product(values: list[int], cap: int) -> int:
    product_value = 1
    for value in values:
        if value <= 0:
            return 0
        product_value *= value
        if product_value > cap:
            return cap + 1
    return product_value


def _limit_optional_groups(raw_groups: list[list[str]]) -> list[list[str]]:
    groups = [
        group[:MAX_OPTIONAL_KEYWORDS_PER_GROUP]
        for group in raw_groups[:MAX_OPTIONAL_KEYWORD_GROUPS]
        if group
    ]
    total_keywords = sum(len(group) for group in groups)
    while total_keywords > MAX_OPTIONAL_KEYWORDS_TOTAL and groups:
        widest_index = max(range(len(groups)), key=lambda index: len(groups[index]))
        if len(groups[widest_index]) <= 1:
            break
        groups[widest_index] = groups[widest_index][:-1]
        total_keywords = sum(len(group) for group in groups)
    while (
        groups
        and _capped_product([len(group) for group in groups], MAX_QUERY_VARIANTS)
        > MAX_QUERY_VARIANTS
    ):
        widest_index = max(range(len(groups)), key=lambda index: len(groups[index]))
        if len(groups[widest_index]) <= 1:
            groups = groups[:-1]
            continue
        groups[widest_index] = groups[widest_index][:-1]
    return [group for group in groups if group]


def _find_matching_paren(text: str, start_index: int) -> int:
    depth = 0
    index = start_index
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            index += 1
            while index < len(text):
                if text[index] == "\\":
                    index += 2
                    continue
                if text[index] == "]":
                    break
                index += 1
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _extract_lookahead_fragments(pattern: str, prefix: str) -> list[str]:
    fragments: list[str] = []
    index = 0
    while True:
        start = pattern.find(prefix, index)
        if start == -1:
            break
        fragment_start = start + len(prefix)
        end = _find_matching_paren(pattern, start)
        if end == -1 or end < fragment_start:
            break
        fragments.append(pattern[fragment_start:end])
        index = end + 1
    return fragments


def _split_top_level_alternatives(fragment: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    index = 0
    while index < len(fragment):
        char = fragment[index]
        if char == "\\":
            current.append(fragment[index : index + 2])
            index += 2
            continue
        if char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth:
            bracket_depth -= 1
        elif char == "(" and not bracket_depth:
            paren_depth += 1
        elif char == ")" and not bracket_depth and paren_depth:
            paren_depth -= 1
        elif char == "|" and not bracket_depth and not paren_depth:
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _unwrap_non_capturing_group(fragment: str) -> str:
    cleaned = fragment.strip()
    while cleaned.startswith("(?:"):
        end = _find_matching_paren(cleaned, 0)
        if end != len(cleaned) - 1:
            break
        cleaned = cleaned[3:end].strip()
    return cleaned


def _regex_fragment_to_term(fragment: str) -> str:
    cleaned = _unwrap_non_capturing_group(fragment.strip())
    if not cleaned:
        return ""
    for raw_value, replacement in SEPARATOR_FRAGMENT_PATTERNS:
        cleaned = cleaned.replace(raw_value, replacement)
    cleaned = cleaned.replace("(?:", "")
    cleaned = cleaned.replace(")", "")
    cleaned = cleaned.replace("(", " ")
    cleaned = QUANTIFIER_RE.sub("", cleaned)
    cleaned = cleaned.replace("*", "")
    cleaned = cleaned.replace("+", "")
    cleaned = cleaned.replace("?", "")
    cleaned = cleaned.replace("[", "")
    cleaned = cleaned.replace("]", "")
    cleaned = re.sub(r"\\([^A-Za-z0-9])", r"\1", cleaned)
    cleaned = cleaned.replace("^", " ").replace("$", " ")
    return _normalize_match_text(cleaned)


def _regex_fragment_to_terms(fragment: str) -> list[str]:
    unwrapped = _unwrap_non_capturing_group(fragment)
    alternatives = _split_top_level_alternatives(unwrapped)
    if len(alternatives) > 1:
        return _dedupe_terms([_regex_fragment_to_term(item) for item in alternatives])
    normalized = _regex_fragment_to_term(unwrapped)
    if not normalized:
        return []
    return [normalized]


def _looks_like_title_candidate(term: str) -> bool:
    if term in _known_quality_search_terms():
        return False
    tokens = [item for item in term.split() if item]
    if len(tokens) < 2:
        return False
    alpha_tokens = [item for item in tokens if any(char.isalpha() for char in item)]
    if len(alpha_tokens) < 2:
        return False
    if len(term) < 8:
        return False
    return True


def _select_search_title(fallback_title: str, regex_title: str) -> str:
    fallback = _normalize_term(fallback_title)
    derived = _normalize_term(regex_title)
    if not derived:
        return fallback_title.strip()
    if not fallback:
        return regex_title.strip()

    fallback_words = len(fallback.split())
    derived_words = len(derived.split())
    if fallback_words > derived_words:
        return fallback_title.strip()
    if derived_words > fallback_words:
        return regex_title.strip()
    if len(fallback) >= len(derived):
        return fallback_title.strip()
    return regex_title.strip()


def _regex_search_terms(pattern: str) -> tuple[str, list[str], list[list[str]], list[str]]:
    title_candidates: list[str] = []
    required_terms: list[str] = []
    any_groups: list[list[str]] = []
    excluded_terms: list[str] = []

    for fragment in _extract_lookahead_fragments(pattern, "(?=.*"):
        terms = _regex_fragment_to_terms(fragment)
        if not terms:
            continue
        if len(terms) > 1:
            any_groups.append(terms)
            continue
        term = terms[0]
        if _looks_like_title_candidate(term):
            title_candidates.append(term)
            continue
        required_terms.append(term)

    for fragment in _extract_lookahead_fragments(pattern, "(?!.*"):
        excluded_terms.extend(_regex_fragment_to_terms(fragment))

    derived_title = ""
    if title_candidates:
        derived_title = max(
            title_candidates,
            key=lambda item: (len(item.split()), len(item)),
        )
        required_terms = [item for item in required_terms if item != derived_title]

    return (
        derived_title,
        _dedupe_terms(required_terms),
        _dedupe_term_groups(any_groups),
        _dedupe_terms(excluded_terms),
    )


def _search_request_data_from_rule(rule: Rule) -> tuple[dict[str, Any], bool]:
    fallback_title = _first_nonempty_text(
        rule.normalized_title,
        rule.content_name,
        rule.rule_name,
    )
    media_type = _coerce_media_type(rule.media_type)
    rule_start_season = getattr(rule, "start_season", None)
    rule_start_episode = getattr(rule, "start_episode", None)
    keywords_all: list[str] = []
    keywords_any_groups: list[list[str]] = []
    primary_keywords_all: list[str] = []
    primary_keywords_any_groups: list[list[str]] = []
    for group in parse_additional_include_groups(_coerce_text(rule.additional_includes)):
        if len(group) == 1:
            keywords_all.append(group[0])
            continue
        keywords_any_groups.append(group)
    keywords_not = _quality_terms(_coerce_string_list(rule.quality_exclude_tokens))
    primary_keywords_not = list(keywords_not)
    must_contain_override = _normalize_legacy_optional_text(rule.must_contain_override)
    ignored_full_regex = looks_like_full_must_contain_override(must_contain_override)
    if not ignored_full_regex:
        keywords_all.extend(parse_manual_must_contain_additions(must_contain_override))
    regex_title = ""
    if ignored_full_regex:
        regex_title, regex_required, regex_any_groups, regex_not = _regex_search_terms(
            must_contain_override
        )
        keywords_all.extend(regex_required)
        keywords_any_groups.extend(regex_any_groups)
        keywords_not.extend(regex_not)

    quality_any_groups = _group_quality_terms(_coerce_string_list(rule.quality_include_tokens))
    if quality_any_groups:
        keywords_any_groups.extend(quality_any_groups)
        primary_keywords_any_groups.extend(quality_any_groups)

    normalized_groups = _dedupe_term_groups(keywords_any_groups)
    primary_normalized_groups = _dedupe_term_groups(primary_keywords_any_groups)
    flattened_any: list[str] = []
    for group in normalized_groups:
        flattened_any.extend(group)
    normalized_any_terms = set(_dedupe_terms(flattened_any))
    primary_flattened_any: list[str] = []
    for group in primary_normalized_groups:
        primary_flattened_any.extend(group)
    primary_any_terms = set(_dedupe_terms(primary_flattened_any))
    query = _select_search_title(fallback_title, regex_title)
    if not query:
        query = _first_nonempty_text(
            *[item for item in _dedupe_terms(keywords_all) if item not in normalized_any_terms],
            *flattened_any,
            "Search",
        )
    query = clamp_search_query_text(query, fallback="Search")

    return (
        {
            "query": query,
            "media_type": media_type,
            "imdb_id": _coerce_text(rule.imdb_id) or None,
            "season_number": (
                int(cast(int, rule_start_season))
                if media_type == MediaType.SERIES and rule_start_season is not None
                else None
            ),
            "episode_number": (
                int(cast(int, rule_start_episode))
                if media_type == MediaType.SERIES and rule_start_episode is not None
                else None
            ),
            "release_year": (
                normalize_release_year(_coerce_text(rule.release_year)) or None
                if bool(getattr(rule, "include_release_year", False))
                else None
            ),
            "keywords_all": [
                item for item in _dedupe_terms(keywords_all) if item not in normalized_any_terms
            ],
            "keywords_any": _dedupe_terms(flattened_any),
            "keywords_any_groups": normalized_groups,
            "keywords_not": [
                item for item in _dedupe_terms(keywords_not) if item not in normalized_any_terms
            ],
            "primary_keywords_all": [
                item
                for item in _dedupe_terms(primary_keywords_all)
                if item not in primary_any_terms
            ],
            "primary_keywords_any": _dedupe_terms(primary_flattened_any),
            "primary_keywords_any_groups": primary_normalized_groups,
            "primary_keywords_not": [
                item
                for item in _dedupe_terms(primary_keywords_not)
                if item not in primary_any_terms
            ],
        },
        ignored_full_regex,
    )


def build_search_request_from_rule(rule: Rule) -> tuple[JackettSearchRequest, bool]:
    payload_data, ignored_full_regex = _search_request_data_from_rule(rule)
    payload = JackettSearchRequest(**payload_data)
    return payload, ignored_full_regex


def build_reduced_search_request_from_rule(rule: Rule) -> tuple[JackettSearchRequest, bool]:
    payload_data, ignored_full_regex = _search_request_data_from_rule(rule)
    keywords_all = list(cast(list[str], payload_data["keywords_all"]))[:MAX_REQUIRED_KEYWORDS]
    keywords_any_groups = _limit_optional_groups(
        list(cast(list[list[str]], payload_data["keywords_any_groups"]))
    )
    primary_keywords_all = list(cast(list[str], payload_data["primary_keywords_all"]))[
        :MAX_REQUIRED_KEYWORDS
    ]
    primary_keywords_any_groups = _limit_optional_groups(
        list(cast(list[list[str]], payload_data["primary_keywords_any_groups"]))
    )
    flattened_any: list[str] = []
    for group in keywords_any_groups:
        flattened_any.extend(group)
    normalized_any_terms = set(_dedupe_terms(flattened_any))
    primary_flattened_any: list[str] = []
    for group in primary_keywords_any_groups:
        primary_flattened_any.extend(group)
    primary_any_terms = set(_dedupe_terms(primary_flattened_any))
    keywords_all = [item for item in keywords_all if item not in normalized_any_terms]
    keywords_not = [
        item
        for item in list(cast(list[str], payload_data["keywords_not"]))[:MAX_EXCLUDED_KEYWORDS]
        if item not in normalized_any_terms
    ]
    primary_keywords_all = [
        item for item in primary_keywords_all if item not in primary_any_terms
    ]
    primary_keywords_not = [
        item
        for item in list(cast(list[str], payload_data["primary_keywords_not"]))[
            :MAX_EXCLUDED_KEYWORDS
        ]
        if item not in primary_any_terms
    ]
    query = clamp_search_query_text(str(payload_data["query"]), fallback="Search")
    payload = JackettSearchRequest(
        query=query,
        media_type=_coerce_media_type(payload_data.get("media_type")),
        imdb_id=_coerce_text(payload_data.get("imdb_id")) or None,
        season_number=cast(int | None, payload_data.get("season_number")),
        episode_number=cast(int | None, payload_data.get("episode_number")),
        release_year=normalize_release_year(_coerce_text(payload_data.get("release_year"))) or None,
        keywords_all=keywords_all,
        keywords_any=flattened_any,
        keywords_any_groups=keywords_any_groups,
        keywords_not=keywords_not,
        primary_keywords_all=primary_keywords_all,
        primary_keywords_any=primary_flattened_any,
        primary_keywords_any_groups=primary_keywords_any_groups,
        primary_keywords_not=primary_keywords_not,
    )
    return payload, ignored_full_regex


class JackettClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip() or None
        self.timeout = (
            timeout if timeout is not None else get_environment_settings().request_timeout
        )
        self.transport = transport
        self._indexer_category_label_map: dict[str, dict[str, list[str]]] | None = None

    def test_connection(self) -> None:
        self._ensure_ready()
        self._request_xml(
            self._torznab_endpoint("all"),
            params={"t": "caps", "apikey": self.api_key or ""},
        )

    def search(self, payload: JackettSearchRequest) -> JackettSearchRun:
        self._ensure_ready()
        if payload.imdb_id_only:
            return self._search_imdb_first(payload)

        remote_payload = self._remote_payload_for_standard_search(payload)
        remote_indexer_groups = self._remote_indexer_groups_for_standard_search(payload)
        query_variants = self._build_query_variants(remote_payload)
        request_variants: list[str] = []
        seen_request_variants: set[str] = set()
        warning_messages: list[str] = []
        seen_warning_messages: set[str] = set()
        merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
        last_timeout_error: JackettTimeoutError | None = None
        last_http_error: JackettHTTPError | None = None
        for variant in query_variants:
            request_params = self._search_params_for_variant(remote_payload, variant)
            fallback_params = self._fallback_search_params_for_variant(
                remote_payload, variant, request_params
            )
            for indexer_group in remote_indexer_groups:
                group_had_success = False
                for indexer in indexer_group:
                    try:
                        variant_results, successful_params, _, timeout_messages = (
                            self._search_variant(
                                indexer,
                                request_params,
                                fallback_params=fallback_params,
                            )
                        )
                    except JackettTimeoutError as exc:
                        last_timeout_error = exc
                        self._add_warning(warning_messages, seen_warning_messages, str(exc))
                        continue
                    except JackettHTTPError as exc:
                        if len(remote_indexer_groups) == 1 and len(indexer_group) == 1:
                            raise
                        last_http_error = exc
                        self._add_warning(warning_messages, seen_warning_messages, str(exc))
                        continue
                    group_had_success = True
                    self._add_request_label(
                        request_variants, seen_request_variants, successful_params
                    )
                    for message in timeout_messages:
                        self._add_warning(warning_messages, seen_warning_messages, message)
                    self._merge_results(merged, variant_results)
                if group_had_success:
                    break

        if not request_variants and last_timeout_error is not None:
            raise last_timeout_error
        if not request_variants and last_http_error is not None:
            raise last_http_error
        ordered_raw_results = self._ordered_results_from_merged(merged)
        self._apply_dynamic_category_labels_if_needed(
            payload,
            result_sets=[ordered_raw_results],
        )
        filtered_results = self._filter_results(
            ordered_raw_results,
            payload,
            section_label="primary",
        )
        run = JackettSearchRun(
            query_variants=query_variants,
            request_variants=request_variants,
            warning_messages=warning_messages,
            raw_results=ordered_raw_results,
            results=filtered_results,
        )
        self._log_search_run(payload, run)
        return run

    def enrich_result_category_labels(self, results: list[JackettSearchResult]) -> None:
        candidates = [result for result in results if list(result.category_ids or [])]
        if not candidates:
            return
        self._configured_indexer_category_labels()
        for result in candidates:
            self._refresh_result_category_labels(result)

    def configured_indexer_category_labels(self) -> dict[str, dict[str, list[str]]]:
        discovered = self._configured_indexer_category_labels()
        return {
            indexer_key: {
                category_id: list(labels) for category_id, labels in category_labels.items()
            }
            for indexer_key, category_labels in discovered.items()
        }

    @staticmethod
    def _remote_payload_for_standard_search(payload: JackettSearchRequest) -> JackettSearchRequest:
        return payload.model_copy(
            update={
                "imdb_id_only": False,
                "imdb_id": None,
                "release_year": None,
                "keywords_all": [],
                "keywords_any": [],
                "keywords_any_groups": [],
                "keywords_not": [],
                "size_min_mb": None,
                "size_max_mb": None,
                "filter_category_ids": [],
            }
        )

    @staticmethod
    def _remote_indexers_for_standard_search(payload: JackettSearchRequest) -> list[str]:
        if payload.indexer and payload.indexer != "all":
            return [payload.indexer]

        scoped_indexers: list[str] = []
        seen_indexers: set[str] = set()
        for raw_indexer in payload.filter_indexers:
            candidate = str(raw_indexer or "").strip().casefold()
            if not candidate:
                continue
            if candidate == "all":
                return ["all"]
            if not SEARCH_INDEXER_RE.match(candidate):
                return ["all"]
            if candidate in seen_indexers:
                continue
            seen_indexers.add(candidate)
            scoped_indexers.append(candidate)

        return scoped_indexers or ["all"]

    @classmethod
    def _remote_indexer_groups_for_standard_search(
        cls,
        payload: JackettSearchRequest,
    ) -> list[list[str]]:
        if payload.indexer and payload.indexer != "all":
            return [[payload.indexer]]

        scoped_indexers = cls._remote_indexers_for_standard_search(payload)
        if scoped_indexers == ["all"]:
            return [["all"]]

        return [["all"], scoped_indexers]

    def _build_query_variants(self, payload: JackettSearchRequest) -> list[str]:
        query = payload.query.strip()
        if not query:
            return [clamp_search_query_text(payload.query, fallback="Search")]
        return [query]

    def _build_fallback_query_variants(self, payload: JackettSearchRequest) -> list[str]:
        return self._build_query_variants(payload)

    def _search_imdb_first(self, payload: JackettSearchRequest) -> JackettSearchRun:
        primary_query = payload.query.strip()
        request_variants: list[str] = []
        seen_request_variants: set[str] = set()
        warning_messages: list[str] = []
        seen_warning_messages: set[str] = set()
        primary_merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
        last_timeout_error: JackettTimeoutError | None = None
        direct_probe_attempted = False

        request_params = self._search_params_for_variant(payload, primary_query)
        fallback_params = self._fallback_search_params_for_variant(
            payload, primary_query, request_params
        )
        aggregate_attempts = [request_params, *fallback_params]

        try:
            variant_results, _, attempted_requests, timeout_messages = self._search_variant(
                payload.indexer,
                request_params,
                fallback_params=fallback_params,
                continue_on_empty=True,
            )
            for attempted_request in attempted_requests:
                self._add_request_label(request_variants, seen_request_variants, attempted_request)
            for message in timeout_messages:
                self._add_warning(warning_messages, seen_warning_messages, message)
            self._merge_results(primary_merged, variant_results)
        except JackettHTTPError as exc:
            if exc.status_code != 400:
                raise
            for attempted_request in aggregate_attempts:
                self._add_request_label(request_variants, seen_request_variants, attempted_request)
            if payload.indexer == "all":
                try:
                    direct_probe_attempted = True
                    variant_results, _, attempted_requests, timeout_messages = (
                        self._search_variant_across_capable_indexers(
                            payload,
                            primary_query,
                        )
                    )
                except (JackettHTTPError, JackettClientError):
                    variant_results = []
                    attempted_requests = []
                    timeout_messages = []
                for attempted_request in attempted_requests:
                    self._add_request_label(
                        request_variants, seen_request_variants, attempted_request
                    )
                for message in timeout_messages:
                    self._add_warning(warning_messages, seen_warning_messages, message)
                self._merge_results(primary_merged, variant_results)
        except JackettTimeoutError as exc:
            last_timeout_error = exc
            self._add_warning(warning_messages, seen_warning_messages, str(exc))

        if payload.indexer == "all" and not primary_merged and not direct_probe_attempted:
            try:
                direct_probe_attempted = True
                variant_results, _, attempted_requests, timeout_messages = (
                    self._search_variant_across_capable_indexers(
                        payload,
                        primary_query,
                    )
                )
            except (JackettHTTPError, JackettClientError):
                variant_results = []
                attempted_requests = []
                timeout_messages = []
            for attempted_request in attempted_requests:
                self._add_request_label(request_variants, seen_request_variants, attempted_request)
            for message in timeout_messages:
                self._add_warning(warning_messages, seen_warning_messages, message)
            self._merge_results(primary_merged, variant_results)

        precise_title_results, precise_title_requests, precise_title_warnings = (
            self._search_precise_title_primary(
                payload,
                existing_merge_keys=set(primary_merged),
            )
        )
        for precise_request in precise_title_requests:
            self._add_request_label(request_variants, seen_request_variants, precise_request)
        for message in precise_title_warnings:
            self._add_warning(warning_messages, seen_warning_messages, message)
        self._merge_results(primary_merged, precise_title_results)

        fallback_request_variants: list[str] = []
        seen_fallback_request_variants: set[str] = set()
        fallback_merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
        if self._needs_broad_fallback(payload):
            fallback_results, fallback_requests, fallback_warnings = self._search_title_fallback(
                payload,
                existing_merge_keys=set(primary_merged),
            )
            for fallback_request in fallback_requests:
                self._add_request_label(
                    fallback_request_variants,
                    seen_fallback_request_variants,
                    fallback_request,
                )
            for message in fallback_warnings:
                self._add_warning(warning_messages, seen_warning_messages, message)
            self._merge_results(fallback_merged, fallback_results)

        if (
            not request_variants
            and not fallback_request_variants
            and last_timeout_error is not None
        ):
            raise last_timeout_error
        primary_raw_results = self._ordered_results_from_merged(primary_merged)
        fallback_raw_results = self._ordered_results_from_merged(fallback_merged)
        self._apply_dynamic_category_labels_if_needed(
            payload,
            result_sets=[primary_raw_results, fallback_raw_results],
        )
        primary_filtered_results = self._filter_results(
            primary_raw_results,
            payload,
            section_label="primary",
        )
        fallback_filtered_results = self._filter_results(
            fallback_raw_results,
            payload,
            section_label="fallback",
        )
        run = JackettSearchRun(
            query_variants=[primary_query],
            request_variants=request_variants,
            warning_messages=warning_messages,
            raw_results=primary_raw_results,
            results=primary_filtered_results,
            fallback_request_variants=fallback_request_variants,
            raw_fallback_results=fallback_raw_results,
            fallback_results=fallback_filtered_results,
        )
        self._log_search_run(payload, run)
        return run

    @staticmethod
    def _add_request_label(
        request_variants: list[str],
        seen_request_variants: set[str],
        params: dict[str, object],
    ) -> None:
        request_label = _request_variant_label(params)
        if not request_label or request_label in seen_request_variants:
            return
        seen_request_variants.add(request_label)
        request_variants.append(request_label)

    @staticmethod
    def _add_warning(
        warning_messages: list[str],
        seen_warning_messages: set[str],
        message: str,
    ) -> None:
        cleaned = str(message or "").strip()
        if not cleaned or cleaned in seen_warning_messages:
            return
        seen_warning_messages.add(cleaned)
        warning_messages.append(cleaned)

    def _merge_results(
        self,
        merged: dict[str, tuple[datetime | None, JackettSearchResult]],
        variant_results: list[tuple[datetime | None, JackettSearchResult]],
    ) -> None:
        for published_at, result in variant_results:
            merge_key = self._merge_key(result)
            if merge_key in merged:
                continue
            merged[merge_key] = (published_at, result)

    def _filter_results(
        self,
        results: list[JackettSearchResult],
        payload: JackettSearchRequest,
        *,
        section_label: str,
    ) -> list[JackettSearchResult]:
        effective_payload = self._local_filter_payload(payload, section_label=section_label)
        kept_results: list[JackettSearchResult] = []
        drop_reasons: dict[str, int] = {}
        for result in results:
            matches, drop_reason = self._matches_payload_terms_with_reason(result, effective_payload)
            if matches:
                kept_results.append(result)
                continue
            if drop_reason:
                drop_reasons[drop_reason] = drop_reasons.get(drop_reason, 0) + 1
        if drop_reasons:
            LOGGER.debug(
                "Jackett local filter diagnostics section=%s query=%r raw=%d kept=%d dropped=%d reasons=%s",
                section_label,
                effective_payload.query,
                len(results),
                len(kept_results),
                len(results) - len(kept_results),
                drop_reasons,
            )
        return kept_results

    @staticmethod
    def _local_filter_payload(
        payload: JackettSearchRequest,
        *,
        section_label: str,
    ) -> JackettSearchRequest:
        if section_label == "fallback" and payload.imdb_id_only:
            return payload.model_copy(update={"imdb_id_only": False})
        if section_label != "primary" or not payload.imdb_id_only:
            return payload
        if not (
            payload.primary_keywords_all
            or payload.primary_keywords_any
            or payload.primary_keywords_any_groups
            or payload.primary_keywords_not
        ):
            return payload
        return payload.model_copy(
            update={
                "keywords_all": list(payload.primary_keywords_all),
                "keywords_any": list(payload.primary_keywords_any),
                "keywords_any_groups": [
                    list(group) for group in payload.primary_keywords_any_groups
                ],
                "keywords_not": list(payload.primary_keywords_not),
            }
        )

    @classmethod
    def _needs_broad_fallback(cls, payload: JackettSearchRequest) -> bool:
        primary_payload = cls._local_filter_payload(payload, section_label="primary")
        return (
            list(primary_payload.keywords_all) != list(payload.keywords_all)
            or [list(group) for group in primary_payload.keywords_any_groups]
            != [list(group) for group in payload.keywords_any_groups]
            or list(primary_payload.keywords_not) != list(payload.keywords_not)
        )

    @staticmethod
    def _log_search_run(payload: JackettSearchRequest, run: JackettSearchRun) -> None:
        keywords_any_groups = payload.keywords_any_groups or (
            [payload.keywords_any] if payload.keywords_any else []
        )
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "query": payload.query,
            "media_type": payload.media_type.value,
            "indexer": payload.indexer,
            "imdb_id_only": payload.imdb_id_only,
            "release_year": payload.release_year or "",
            "keywords_all": list(payload.keywords_all),
            "keywords_any_groups": keywords_any_groups,
            "keywords_not": list(payload.keywords_not),
            "size_min_mb": payload.size_min_mb,
            "size_max_mb": payload.size_max_mb,
            "filter_indexers": list(payload.filter_indexers),
            "filter_category_ids": list(payload.filter_category_ids),
            "raw_results": len(run.raw_results),
            "filtered_results": len(run.results),
            "raw_fallback_results": len(run.raw_fallback_results),
            "filtered_fallback_results": len(run.fallback_results),
            "request_variants": len(run.request_variants) + len(run.fallback_request_variants),
            "warning_count": len(run.warning_messages),
        }
        LOGGER.info(
            "Jackett search debug query=%r media=%s indexer=%s imdb_only=%s release_year=%s "
            "keywords_all=%s keywords_any_groups=%s keywords_not=%s raw=%d filtered=%d "
            "fallback_raw=%d fallback_filtered=%d request_variants=%d warnings=%d",
            event["query"],
            event["media_type"],
            event["indexer"],
            event["imdb_id_only"],
            event["release_year"],
            event["keywords_all"],
            event["keywords_any_groups"],
            event["keywords_not"],
            event["raw_results"],
            event["filtered_results"],
            event["raw_fallback_results"],
            event["filtered_fallback_results"],
            event["request_variants"],
            event["warning_count"],
        )
        _append_search_debug_event(event)

    @staticmethod
    def _ordered_results_from_merged(
        merged: dict[str, tuple[datetime | None, JackettSearchResult]],
    ) -> list[JackettSearchResult]:
        return [
            result
            for _, result in sorted(
                merged.values(),
                key=lambda item: (
                    item[0] is None,
                    -(item[0].timestamp()) if item[0] is not None else 0.0,
                    item[1].title.casefold(),
                ),
            )
        ]

    def _parse_results_from_root(
        self,
        root: ET.Element,
    ) -> list[tuple[datetime | None, JackettSearchResult]]:
        parsed_results: list[tuple[datetime | None, JackettSearchResult]] = []
        for item in root.iter():
            if _local_name(item.tag) != "item":
                continue
            parsed = self._parse_item(item)
            if parsed is None:
                continue
            parsed_results.append(parsed)
        return parsed_results

    def _search_variant(
        self,
        indexer: str,
        params: dict[str, object],
        *,
        fallback_params: list[dict[str, object]] | None = None,
        continue_on_empty: bool = False,
    ) -> tuple[
        list[tuple[datetime | None, JackettSearchResult]],
        dict[str, object],
        list[dict[str, object]],
        list[str],
    ]:
        endpoint = self._torznab_endpoint(indexer)
        request_attempts = [params, *(fallback_params or [])]
        last_bad_request_error: JackettHTTPError | None = None
        last_timeout_error: JackettTimeoutError | None = None
        successful_params = params
        successful_results: list[tuple[datetime | None, JackettSearchResult]] = []
        had_success = False
        attempted_requests: list[dict[str, object]] = []
        warning_messages: list[str] = []
        for attempt_index, request_params in enumerate(request_attempts):
            attempted_requests.append(request_params)
            try:
                root = self._request_xml(
                    endpoint,
                    params=request_params,
                )
            except JackettTimeoutError as exc:
                last_timeout_error = exc
                warning_messages.append(str(exc))
                continue
            except JackettHTTPError as exc:
                if exc.status_code != 400:
                    raise
                last_bad_request_error = exc
                continue
            parsed_results = self._parse_results_from_root(root)
            successful_params = request_params
            successful_results = parsed_results
            had_success = True
            if (
                parsed_results
                or not continue_on_empty
                or attempt_index == len(request_attempts) - 1
            ):
                return parsed_results, successful_params, attempted_requests, warning_messages

        if had_success:
            return successful_results, successful_params, attempted_requests, warning_messages
        if last_bad_request_error is not None:
            raise last_bad_request_error
        if last_timeout_error is not None:
            raise last_timeout_error
        raise JackettClientError("Jackett request failed.")

    def _search_params_for_variant(
        self,
        payload: JackettSearchRequest,
        query: str,
    ) -> dict[str, object]:
        search_mode = _torznab_mode_for_payload(payload)
        params: dict[str, object] = {
            "apikey": self.api_key or "",
            "t": search_mode,
        }
        if not payload.imdb_id_only:
            params["q"] = query

        category_param = self._category_param_for_payload(payload)
        if category_param:
            params["cat"] = category_param

        imdb_lookup_id = _torznab_imdb_lookup_id(payload.imdb_id)
        if imdb_lookup_id and search_mode in {"movie", "tvsearch"}:
            params["imdbid"] = imdb_lookup_id
        if search_mode == "tvsearch" and payload.season_number is not None:
            params["season"] = int(payload.season_number)
            if payload.episode_number is not None:
                params["ep"] = int(payload.episode_number)

        return params

    def _fallback_search_params_for_variant(
        self,
        payload: JackettSearchRequest,
        query: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        if params.get("t") == "search":
            return []

        fallback_variants: list[dict[str, object]] = []
        seen_variants = {
            tuple(sorted((str(key), _coerce_text(value)) for key, value in params.items()))
        }
        category_param = self._category_param_for_payload(payload)

        def add_candidate(candidate: dict[str, object]) -> None:
            candidate_key = tuple(
                sorted((str(key), _coerce_text(value)) for key, value in candidate.items())
            )
            if candidate_key in seen_variants:
                return
            seen_variants.add(candidate_key)
            fallback_variants.append(candidate)

        if "ep" in params:
            candidate = dict(params)
            candidate.pop("ep", None)
            add_candidate(candidate)

        if "season" in params:
            candidate = dict(params)
            candidate.pop("ep", None)
            candidate.pop("season", None)
            add_candidate(candidate)

        if payload.imdb_id_only:
            return fallback_variants

        if "year" in params:
            candidate = dict(params)
            candidate.pop("year", None)
            add_candidate(candidate)

        imdb_lookup_id = _coerce_text(params.get("imdbid"))
        if imdb_lookup_id:
            candidate = {
                "apikey": self.api_key or "",
                "t": _coerce_text(params.get("t")) or "search",
                "imdbid": imdb_lookup_id,
            }
            if "season" in params:
                candidate["season"] = params["season"]
            if "ep" in params:
                candidate["ep"] = params["ep"]
            if category_param:
                candidate["cat"] = category_param
            add_candidate(candidate)

        if payload.season_number is not None or payload.episode_number is not None:
            return fallback_variants

        candidate = {
            "apikey": self.api_key or "",
            "t": "search",
            "q": query,
        }
        if category_param:
            candidate["cat"] = category_param
        add_candidate(candidate)

        return fallback_variants

    def _search_variant_across_capable_indexers(
        self,
        payload: JackettSearchRequest,
        query: str,
    ) -> tuple[
        list[tuple[datetime | None, JackettSearchResult]],
        list[dict[str, object]],
        list[dict[str, object]],
        list[str],
    ]:
        search_mode = _torznab_mode_for_payload(payload)
        indexers = self._configured_indexers_for_mode(search_mode)
        successful_requests: list[dict[str, object]] = []
        attempted_requests: list[dict[str, object]] = []
        warning_messages: list[str] = []
        parsed_results: list[tuple[datetime | None, JackettSearchResult]] = []
        last_bad_request_error: JackettHTTPError | None = None
        last_timeout_error: JackettTimeoutError | None = None

        for indexer in indexers:
            request_attempts = self._imdb_enforced_params_for_indexer(
                payload,
                search_mode,
                indexer=indexer.indexer_id,
                supported_params=indexer.supported_params,
            )
            if not request_attempts:
                continue
            try:
                indexer_results, successful_params, indexer_attempts, indexer_warnings = (
                    self._search_variant(
                        indexer.indexer_id,
                        request_attempts[0],
                        fallback_params=request_attempts[1:],
                        continue_on_empty=True,
                    )
                )
            except JackettTimeoutError as exc:
                attempted_requests.extend(request_attempts)
                warning_messages.append(str(exc))
                last_timeout_error = exc
                continue
            except JackettHTTPError as exc:
                attempted_requests.extend(request_attempts)
                if exc.status_code != 400:
                    raise
                last_bad_request_error = exc
                continue
            attempted_requests.extend(indexer_attempts)
            warning_messages.extend(indexer_warnings)
            parsed_results.extend(indexer_results)
            successful_requests.append(successful_params)

        if successful_requests:
            return parsed_results, successful_requests, attempted_requests, warning_messages
        if last_bad_request_error is not None:
            raise last_bad_request_error
        if last_timeout_error is not None:
            raise last_timeout_error
        raise JackettClientError(
            "Jackett could not find a configured indexer that supports IMDb-enforced search for this media type."
        )

    @staticmethod
    def _category_family_root(category_id: str) -> str | None:
        cleaned = _coerce_text(category_id)
        if not cleaned.isdigit():
            return None
        try:
            numeric_value = int(cleaned)
        except ValueError:
            return None
        if numeric_value < 1000:
            return None
        return str((numeric_value // 1000) * 1000)

    @staticmethod
    def _scoped_indexers_for_category_narrowing(
        payload: JackettSearchRequest,
        *,
        indexer_hint: str | None = None,
    ) -> list[str]:
        hinted_indexer = _coerce_text(indexer_hint).casefold()
        if hinted_indexer and hinted_indexer != "all":
            return [hinted_indexer]

        selected_indexer = _coerce_text(payload.indexer).casefold()
        if selected_indexer and selected_indexer != "all":
            return [selected_indexer]

        scoped_indexers: list[str] = []
        seen_indexers: set[str] = set()
        for raw_indexer in payload.filter_indexers:
            candidate = _coerce_text(raw_indexer).casefold()
            if not candidate:
                continue
            if candidate == "all":
                return []
            if not SEARCH_INDEXER_RE.match(candidate):
                return []
            if candidate in seen_indexers:
                continue
            seen_indexers.add(candidate)
            scoped_indexers.append(candidate)
        return scoped_indexers

    @classmethod
    def _indexer_supports_category_roots(
        cls,
        *,
        indexer: str,
        target_roots: set[str],
        indexer_category_labels: Mapping[str, Mapping[str, Sequence[str]]],
    ) -> bool | None:
        indexer_keys = _indexer_key_variants(indexer)
        if not indexer_keys:
            return None

        category_ids: set[str] = set()
        for indexer_key in indexer_keys:
            category_ids.update(indexer_category_labels.get(indexer_key, {}).keys())
        if not category_ids:
            return None

        for raw_category_id in category_ids:
            category_id = _coerce_text(raw_category_id)
            if not category_id:
                continue
            if category_id in target_roots:
                return True
            root_id = cls._category_family_root(category_id)
            if root_id and root_id in target_roots:
                return True
        return False

    def _category_param_for_payload(
        self,
        payload: JackettSearchRequest,
        *,
        indexer_hint: str | None = None,
    ) -> str | None:
        categories = _torznab_categories_for_media_type(payload.media_type)
        if not categories:
            return None

        scoped_indexers = self._scoped_indexers_for_category_narrowing(
            payload,
            indexer_hint=indexer_hint,
        )
        if not scoped_indexers:
            return ",".join(categories)

        discovered_categories = self._indexer_category_label_map or {}
        if not discovered_categories:
            return None

        target_roots = {item for item in categories if item}
        for indexer in scoped_indexers:
            supports_root = self._indexer_supports_category_roots(
                indexer=indexer,
                target_roots=target_roots,
                indexer_category_labels=discovered_categories,
            )
            if supports_root is not True:
                return None

        return ",".join(categories)

    def _search_title_fallback(
        self,
        payload: JackettSearchRequest,
        *,
        existing_merge_keys: set[str] | None = None,
    ) -> tuple[
        list[tuple[datetime | None, JackettSearchResult]], list[dict[str, object]], list[str]
    ]:
        fallback_payload = payload.model_copy(
            update={
                "imdb_id_only": False,
                "imdb_id": None,
                "release_year": None,
                "season_number": None,
                "episode_number": None,
                "keywords_all": [],
                "keywords_any": [],
                "keywords_any_groups": [],
                "keywords_not": [],
                "size_min_mb": None,
                "size_max_mb": None,
                "filter_category_ids": [],
            }
        )
        query_variants = self._build_fallback_query_variants(fallback_payload)
        if not query_variants:
            return [], [], []

        seen_merge_keys = set(existing_merge_keys or ())
        request_variants: list[dict[str, object]] = []
        fallback_results: list[tuple[datetime | None, JackettSearchResult]] = []
        warning_messages: list[str] = []
        remote_indexer_groups = self._remote_indexer_groups_for_standard_search(fallback_payload)

        for query in query_variants:
            params = self._search_params_for_variant(fallback_payload, query)
            forced_mode = TORZNAB_MODE_BY_MEDIA_TYPE.get(payload.media_type)
            if forced_mode:
                params["t"] = forced_mode
            continue_on_empty = (
                fallback_payload.season_number is not None
                or fallback_payload.episode_number is not None
            )
            fallback_params = (
                self._fallback_search_params_for_variant(
                    fallback_payload,
                    query,
                    params,
                )
                if continue_on_empty
                else []
            )

            query_had_success = False
            for indexer_group in remote_indexer_groups:
                group_had_success = False
                for indexer in indexer_group:
                    try:
                        parsed_results, successful_params, _, timeout_messages = (
                            self._search_variant(
                                indexer,
                                params,
                                fallback_params=fallback_params,
                                continue_on_empty=continue_on_empty,
                            )
                        )
                    except JackettTimeoutError as exc:
                        warning_messages.append(str(exc))
                        continue
                    except JackettHTTPError as exc:
                        if exc.status_code != 400:
                            raise
                        warning_messages.append(str(exc))
                        continue
                    group_had_success = True
                    query_had_success = True
                    request_variants.append(successful_params)
                    warning_messages.extend(timeout_messages)
                    fallback_results.extend(
                        item
                        for item in parsed_results
                        if self._merge_key(item[1]) not in seen_merge_keys
                    )
                    seen_merge_keys.update(self._merge_key(item[1]) for item in parsed_results)
                if group_had_success:
                    break
            if not query_had_success:
                continue

        return fallback_results, request_variants, warning_messages

    def _search_precise_title_primary(
        self,
        payload: JackettSearchRequest,
        *,
        existing_merge_keys: set[str] | None = None,
    ) -> tuple[
        list[tuple[datetime | None, JackettSearchResult]], list[dict[str, object]], list[str]
    ]:
        title_payload = payload.model_copy(
            update={
                "imdb_id_only": False,
                "imdb_id": None,
                "keywords_all": [],
                "keywords_any": [],
                "keywords_any_groups": [],
                "keywords_not": [],
                "size_min_mb": None,
                "size_max_mb": None,
                "filter_category_ids": [],
            }
        )
        query_variants = self._build_fallback_query_variants(title_payload)
        if not query_variants:
            return [], [], []

        effective_payload = self._local_filter_payload(payload, section_label="primary")
        seen_merge_keys = set(existing_merge_keys or ())
        request_variants: list[dict[str, object]] = []
        precise_results: list[tuple[datetime | None, JackettSearchResult]] = []
        warning_messages: list[str] = []
        remote_indexer_groups = self._remote_indexer_groups_for_standard_search(title_payload)

        for query in query_variants:
            params = self._search_params_for_variant(title_payload, query)
            forced_mode = TORZNAB_MODE_BY_MEDIA_TYPE.get(payload.media_type)
            if forced_mode:
                params["t"] = forced_mode
            continue_on_empty = (
                title_payload.season_number is not None or title_payload.episode_number is not None
            )
            fallback_params = (
                self._fallback_search_params_for_variant(
                    title_payload,
                    query,
                    params,
                )
                if continue_on_empty
                else []
            )

            query_had_success = False
            for indexer_group in remote_indexer_groups:
                group_had_success = False
                for indexer in indexer_group:
                    try:
                        parsed_results, successful_params, _, timeout_messages = (
                            self._search_variant(
                                indexer,
                                params,
                                fallback_params=fallback_params,
                                continue_on_empty=continue_on_empty,
                            )
                        )
                    except JackettTimeoutError as exc:
                        warning_messages.append(str(exc))
                        continue
                    except JackettHTTPError as exc:
                        if exc.status_code != 400:
                            raise
                        warning_messages.append(str(exc))
                        continue
                    group_had_success = True
                    query_had_success = True
                    request_variants.append(successful_params)
                    warning_messages.extend(timeout_messages)
                    for item in parsed_results:
                        merge_key = self._merge_key(item[1])
                        if merge_key in seen_merge_keys:
                            continue
                        matches, _drop_reason = self._matches_payload_terms_with_reason(
                            item[1],
                            effective_payload,
                        )
                        if not matches:
                            continue
                        precise_results.append(item)
                        seen_merge_keys.add(merge_key)
                if group_had_success:
                    break
            if not query_had_success:
                continue

        return precise_results, request_variants, warning_messages

    def _configured_indexers_for_mode(self, search_mode: str) -> list[JackettIndexerCapability]:
        capability_tag = TORZNAB_CAPABILITY_TAG_BY_MODE.get(search_mode)
        if not capability_tag:
            return []

        root = self._request_xml(
            self._torznab_endpoint("all"),
            params={
                "t": "indexers",
                "apikey": self.api_key or "",
                "configured": "true",
            },
        )

        indexers: list[JackettIndexerCapability] = []
        for indexer in root.iter():
            if _local_name(indexer.tag) != "indexer":
                continue
            indexer_id = indexer.attrib.get("id", "").strip()
            if not indexer_id or indexer_id == "all":
                continue

            supported_params: frozenset[str] = frozenset()
            for item in indexer.iter():
                if _local_name(item.tag) != capability_tag:
                    continue
                available = item.attrib.get("available", "").strip().casefold()
                if available not in {"yes", "true", "1"}:
                    break
                supported = (
                    item.attrib.get("supportedParams") or item.attrib.get("supportedparams") or ""
                )
                supported_params = frozenset(
                    param.strip().casefold() for param in supported.split(",") if param.strip()
                )
                break

            if "imdbid" not in supported_params:
                continue
            indexers.append(
                JackettIndexerCapability(
                    indexer_id=indexer_id,
                    supported_params=supported_params,
                )
            )
        return indexers

    def _imdb_enforced_params_for_indexer(
        self,
        payload: JackettSearchRequest,
        search_mode: str,
        *,
        indexer: str,
        supported_params: frozenset[str],
    ) -> list[dict[str, object]]:
        imdb_lookup_id = _torznab_imdb_lookup_id(payload.imdb_id)
        if not imdb_lookup_id:
            return []

        category_param = self._category_param_for_payload(payload, indexer_hint=indexer)
        base_params: dict[str, object] = {
            "apikey": self.api_key or "",
            "t": search_mode,
            "imdbid": imdb_lookup_id,
        }
        if category_param:
            base_params["cat"] = category_param

        request_attempts: list[dict[str, object]] = []
        seen_attempts: set[tuple[tuple[str, str], ...]] = set()

        def add_attempt(
            *,
            season_number: int | None,
            episode_number: int | None,
        ) -> None:
            candidate = dict(base_params)
            if season_number is not None and "season" in supported_params:
                candidate["season"] = int(season_number)
            if (
                episode_number is not None
                and "season" in supported_params
                and "ep" in supported_params
            ):
                candidate["ep"] = int(episode_number)
            candidate_key = tuple(
                sorted((str(key), _coerce_text(value)) for key, value in candidate.items())
            )
            if candidate_key in seen_attempts:
                return
            seen_attempts.add(candidate_key)
            request_attempts.append(candidate)

        add_attempt(
            season_number=payload.season_number,
            episode_number=payload.episode_number,
        )
        if payload.season_number is not None:
            add_attempt(
                season_number=payload.season_number,
                episode_number=None,
            )
        add_attempt(
            season_number=None,
            episode_number=None,
        )

        return request_attempts

    @classmethod
    def _collect_indexer_category_labels(
        cls,
        node: ET.Element,
        *,
        parent_path: list[str] | None = None,
        category_map: dict[str, list[str]] | None = None,
    ) -> dict[str, list[str]]:
        path = list(parent_path or [])
        categories = category_map if category_map is not None else {}
        local_tag = _local_name(node.tag)
        next_path = path
        if local_tag in {"category", "subcat", "subcategory"}:
            category_id = _coerce_text(node.attrib.get("id"))
            category_name = _coerce_text(node.attrib.get("name")) or _coerce_text(node.text)
            if category_name:
                next_path = [*path, category_name]
            labels: list[str] = []
            if category_name:
                labels.append(category_name)
            if len(next_path) > 1:
                labels.append("/".join(next_path))
            if category_id and labels:
                categories.setdefault(category_id.casefold(), []).extend(labels)
        for child in node:
            cls._collect_indexer_category_labels(
                child,
                parent_path=next_path,
                category_map=categories,
            )
        return categories

    def _configured_indexer_category_labels(self) -> dict[str, dict[str, list[str]]]:
        if self._indexer_category_label_map is not None:
            return self._indexer_category_label_map

        try:
            root = self._request_xml(
                self._torznab_endpoint("all"),
                params={
                    "t": "indexers",
                    "apikey": self.api_key or "",
                    "configured": "true",
                },
            )
        except JackettClientError:
            LOGGER.debug(
                "Jackett indexer category discovery failed; proceeding with standard category labels only.",
                exc_info=True,
            )
            self._indexer_category_label_map = {}
            return self._indexer_category_label_map

        discovered: dict[str, dict[str, list[str]]] = {}
        for indexer in root.iter():
            if _local_name(indexer.tag) != "indexer":
                continue
            category_labels = self._collect_indexer_category_labels(indexer)
            if not category_labels:
                continue
            identity_keys: set[str] = set()
            identity_keys.update(_indexer_key_variants(indexer.attrib.get("id")))
            identity_keys.update(_indexer_key_variants(indexer.attrib.get("title")))
            identity_keys.update(_indexer_key_variants(indexer.attrib.get("name")))
            for identity_key in identity_keys:
                target_map = discovered.setdefault(identity_key, {})
                for category_id, labels in category_labels.items():
                    target_map.setdefault(category_id, []).extend(labels)

        self._indexer_category_label_map = {
            indexer_key: {
                category_id: _dedupe_category_labels(labels)
                for category_id, labels in category_labels.items()
            }
            for indexer_key, category_labels in discovered.items()
        }
        return self._indexer_category_label_map

    def _category_labels_for_result(
        self,
        *,
        indexer: str | None,
        category_ids: list[str],
    ) -> list[str]:
        if not category_ids:
            return []

        category_labels: list[str] = []
        indexer_maps = self._indexer_category_label_map or {}
        indexer_keys = _indexer_key_variants(indexer)

        for raw_category_id in category_ids:
            category_id = _coerce_text(raw_category_id)
            if not category_id:
                continue
            category_key = category_id.casefold()
            for indexer_key in indexer_keys:
                category_labels.extend(indexer_maps.get(indexer_key, {}).get(category_key, []))
            category_labels.extend(TORZNAB_STANDARD_CATEGORY_LABELS.get(category_id, ()))
            if category_id.isdigit() and len(category_id) == 4:
                parent_id = f"{(int(category_id) // 1000) * 1000}"
                if parent_id != category_id:
                    category_labels.extend(TORZNAB_STANDARD_CATEGORY_LABELS.get(parent_id, ()))

        return _dedupe_category_labels(category_labels)

    @staticmethod
    def _payload_uses_category_label_filter(payload: JackettSearchRequest) -> bool:
        return any(not _coerce_text(item).isdigit() for item in payload.filter_category_ids)

    def _refresh_result_category_labels(self, result: JackettSearchResult) -> None:
        category_labels = self._category_labels_for_result(
            indexer=result.indexer,
            category_ids=list(result.category_ids or []),
        )
        result.category_labels = category_labels
        result.text_surface = _result_text_surface(
            title=result.title,
            indexer=result.indexer,
            imdb_id=result.imdb_id,
            year=result.year,
            category_ids=list(result.category_ids or []),
            category_labels=category_labels,
            torznab_attrs=dict(result.torznab_attrs or {}),
        )

    def _apply_dynamic_category_labels_if_needed(
        self,
        payload: JackettSearchRequest,
        *,
        result_sets: list[list[JackettSearchResult]],
    ) -> None:
        if not self._payload_uses_category_label_filter(payload):
            return
        self._configured_indexer_category_labels()
        for results in result_sets:
            for result in results:
                self._refresh_result_category_labels(result)

    def _parse_item(self, item: ET.Element) -> tuple[datetime | None, JackettSearchResult] | None:
        title = ""
        link = ""
        guid: str | None = None
        details_url: str | None = None
        published_at: datetime | None = None
        size_bytes: int | None = None
        info_hash: str | None = None
        imdb_id: str | None = None
        indexer: str | None = None
        category_ids: list[str] = []
        category_labels: list[str] = []
        seen_category_ids: set[str] = set()
        year: str | None = None
        seeders: int | None = None
        peers: int | None = None
        leechers: int | None = None
        grabs: int | None = None
        download_volume_factor: float | None = None
        upload_volume_factor: float | None = None
        torznab_attrs: dict[str, str] = {}

        for child in item:
            tag = _local_name(child.tag)
            text = (child.text or "").strip()
            if tag == "title":
                title = text
            elif tag == "guid":
                guid = text or None
            elif tag == "link":
                link = text
            elif tag == "comments":
                details_url = text or None
            elif tag == "pubDate":
                published_at = _parse_datetime(text)
            elif tag == "enclosure" and size_bytes is None:
                size_bytes = _coerce_int(child.attrib.get("length"))
            elif tag == "category":
                category_value = child.attrib.get("value", "").strip() or text
                for category_id in _extract_category_ids(category_value):
                    key = category_id.casefold()
                    if key in seen_category_ids:
                        continue
                    seen_category_ids.add(key)
                    category_ids.append(category_id)
            elif tag == "attr":
                attr_name_raw = child.attrib.get("name", "").strip()
                attr_name = attr_name_raw.casefold().replace("-", "").replace("_", "")
                attr_value = child.attrib.get("value", "").strip()
                if attr_name_raw and attr_value:
                    torznab_attrs.setdefault(attr_name_raw.casefold(), attr_value)
                if attr_name == "size" and size_bytes is None:
                    size_bytes = _coerce_int(attr_value)
                elif attr_name in {"imdbid", "imdb"} and imdb_id is None:
                    imdb_id = _torznab_imdb_lookup_id(attr_value)
                elif attr_name in {"infohash", "info_hash"}:
                    info_hash = attr_value or None
                elif attr_name in {"jackettindexer", "indexer", "tracker", "trackername"}:
                    indexer = attr_value or None
                elif attr_name in {"category", "categories", "cat"}:
                    for category_id in _extract_category_ids(attr_value):
                        key = category_id.casefold()
                        if key in seen_category_ids:
                            continue
                        seen_category_ids.add(key)
                        category_ids.append(category_id)
                elif attr_name in {"year", "releaseyear", "publishyear"} and year is None:
                    year = _normalize_release_year_token(attr_value)
                elif attr_name in {"seeders", "seed", "seedercount"} and seeders is None:
                    seeders = _coerce_int(attr_value)
                elif attr_name in {"peers", "peer", "peercount"} and peers is None:
                    peers = _coerce_int(attr_value)
                elif attr_name in {"leechers", "leech", "leechercount"} and leechers is None:
                    leechers = _coerce_int(attr_value)
                elif attr_name in {"grabs", "downloads", "downloadcount"} and grabs is None:
                    grabs = _coerce_int(attr_value)
                elif (
                    attr_name in {"downloadvolumefactor", "downloadfactor"}
                    and download_volume_factor is None
                ):
                    download_volume_factor = _coerce_float(attr_value)
                elif (
                    attr_name in {"uploadvolumefactor", "uploadfactor"}
                    and upload_volume_factor is None
                ):
                    upload_volume_factor = _coerce_float(attr_value)

            elif tag in {"jackettindexer", "indexer"} and not indexer:
                indexer = text or None

        if not title or not link:
            return None

        if peers is None and seeders is not None and leechers is not None:
            peers = seeders + leechers

        year = _resolved_result_year(explicit_year=year, title=title)
        category_labels = self._category_labels_for_result(
            indexer=indexer,
            category_ids=category_ids,
        )
        merge_key = _result_merge_key(
            info_hash=info_hash,
            guid=guid,
            title=title,
            size_bytes=size_bytes,
        )
        published_iso = published_at.isoformat() if published_at is not None else None
        text_surface = _result_text_surface(
            title=title,
            indexer=indexer,
            imdb_id=imdb_id,
            year=year,
            category_ids=category_ids,
            category_labels=category_labels,
            torznab_attrs=torznab_attrs,
        )

        return (
            published_at,
            JackettSearchResult(
                merge_key=merge_key,
                title=title,
                link=link,
                indexer=indexer,
                details_url=details_url,
                guid=guid,
                info_hash=info_hash,
                imdb_id=imdb_id,
                size_bytes=size_bytes,
                size_label=_format_size(size_bytes),
                published_at=published_iso,
                published_label=_format_published(published_at),
                category_ids=category_ids,
                category_labels=category_labels,
                year=year,
                seeders=seeders,
                peers=peers,
                leechers=leechers,
                grabs=grabs,
                download_volume_factor=download_volume_factor,
                upload_volume_factor=upload_volume_factor,
                torznab_attrs=torznab_attrs,
                text_surface=text_surface,
            ),
        )

    def _request_xml(
        self,
        url: str,
        *,
        params: dict[str, Any],
    ) -> ET.Element:
        if not self.base_url:
            raise JackettConfigError("Jackett app URL is not configured.")

        request_context = _request_error_context(url, params)
        timeout_error: httpx.TimeoutException | None = None
        for _ in range(TIMEOUT_RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.get(url, params=cast(Any, params))
                    response.raise_for_status()
                break
            except httpx.TimeoutException as exc:
                timeout_error = exc
                continue
            except httpx.HTTPStatusError as exc:
                raise JackettHTTPError(
                    f"Jackett request failed for {request_context}: {exc}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.HTTPError as exc:
                raise JackettClientError(
                    f"Jackett request failed for {request_context}: {exc}"
                ) from exc
        else:
            raise JackettTimeoutError(
                "Jackett request failed after "
                f"{TIMEOUT_RETRY_ATTEMPTS} timeout attempts for {request_context}: {timeout_error}"
            ) from timeout_error

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise JackettClientError("Jackett returned invalid XML.") from exc
        if _local_name(root.tag) == "error":
            error_code = _coerce_int(root.attrib.get("code"))
            description = root.attrib.get("description", "").strip() or "Jackett returned an error."
            detail = f"[{error_code}] {description}" if error_code is not None else description
            if error_code is not None and 200 <= error_code < 300:
                raise JackettHTTPError(
                    f"Jackett request failed for {request_context}: {detail}",
                    status_code=400,
                )
            raise JackettClientError(f"Jackett request failed for {request_context}: {detail}")
        return root

    def _torznab_endpoint(self, indexer: str) -> str:
        resolved_indexer = (indexer or "all").strip() or "all"
        return f"{self.base_url}/api/v2.0/indexers/{resolved_indexer}/results/torznab/api"

    def _ensure_ready(self) -> None:
        if not self.base_url:
            raise JackettConfigError("Jackett app URL is not configured.")
        if not self.api_key:
            raise JackettConfigError("Jackett API key is not configured.")

    @staticmethod
    def _matches_payload_terms_with_reason(
        result: JackettSearchResult,
        payload: JackettSearchRequest,
    ) -> tuple[bool, str | None]:
        title_surface = _normalize_match_text(result.title)
        payload_imdb_id = _torznab_imdb_lookup_id(payload.imdb_id)
        result_imdb_id = _torznab_imdb_lookup_id(result.imdb_id)
        imdb_exact_match = (
            payload_imdb_id is not None
            and result_imdb_id is not None
            and payload_imdb_id == result_imdb_id
        )
        if (
            payload_imdb_id is not None
            and result_imdb_id is not None
            and payload_imdb_id != result_imdb_id
        ):
            return False, "imdb_id_mismatch"
        if not imdb_exact_match and not _matches_query_text(
            title_surface=title_surface, query=payload.query
        ):
            return False, "query"
        if payload.imdb_id_only and not imdb_exact_match:
            if not _matches_precise_title_identity(result.title, payload.query):
                return False, "precise_title_mismatch"
        text_surface = result.text_surface or title_surface
        for keyword in payload.keywords_all:
            if not _matches_included_keyword(text_surface, keyword):
                return False, "keywords_all"
        any_groups = payload.keywords_any_groups or (
            [payload.keywords_any] if payload.keywords_any else []
        )
        for group_index, group in enumerate(any_groups):
            if not any(_matches_included_keyword(text_surface, keyword) for keyword in group):
                return False, f"keywords_any_group_{group_index + 1}"
        for keyword in payload.keywords_not:
            if _matches_excluded_keyword(text_surface, keyword):
                return False, "keywords_not"
        if payload.release_year:
            result_year = _resolved_result_year(explicit_year=result.year, title=result.title)
            if not result_year:
                return False, "release_year_missing"
            if result_year != payload.release_year:
                return False, "release_year_mismatch"
        if payload.media_type == MediaType.SERIES and payload.season_number is not None:
            if payload.episode_number is not None:
                if not _matches_requested_season_episode(
                    result.title,
                    season_number=int(payload.season_number),
                    episode_number=int(payload.episode_number),
                ):
                    return False, "season_episode_mismatch"
            elif not _matches_requested_season(
                result.title,
                season_number=int(payload.season_number),
            ):
                return False, "season_mismatch"
        if payload.size_min_mb is not None or payload.size_max_mb is not None:
            if result.size_bytes is None:
                return False, "size_missing"
            size_mb = result.size_bytes / (1024 * 1024)
            if payload.size_min_mb is not None and size_mb < payload.size_min_mb:
                return False, "size_min_mb"
            if payload.size_max_mb is not None and size_mb > payload.size_max_mb:
                return False, "size_max_mb"
        if payload.filter_indexers:
            if not result.indexer:
                return False, "filter_indexers_missing"
            allowed_indexers = {item.casefold() for item in payload.filter_indexers}
            if result.indexer.casefold() not in allowed_indexers:
                return False, "filter_indexers"
        if payload.filter_category_ids:
            item_categories = {
                normalized
                for normalized in (
                    _normalize_category_filter_token(item)
                    for item in [*(result.category_ids or []), *(result.category_labels or [])]
                )
                if normalized
            }
            if not item_categories:
                return False, "filter_categories_missing"
            allowed_categories = {
                normalized
                for normalized in (
                    _normalize_category_filter_token(item) for item in payload.filter_category_ids
                )
                if normalized
            }
            if item_categories.isdisjoint(allowed_categories):
                return False, "filter_categories"
        return True, None

    @classmethod
    def _matches_payload_terms(
        cls,
        result: JackettSearchResult,
        payload: JackettSearchRequest,
    ) -> bool:
        matches, _ = cls._matches_payload_terms_with_reason(result, payload)
        return matches

    @staticmethod
    def _merge_key(result: JackettSearchResult) -> str:
        if result.merge_key:
            return result.merge_key
        return _result_merge_key(
            info_hash=result.info_hash,
            guid=result.guid,
            title=result.title,
            size_bytes=result.size_bytes,
        )
