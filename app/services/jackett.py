from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

import httpx

from app.config import ROOT_DIR, get_environment_settings
from app.models import MediaType, Rule
from app.schemas import JackettSearchRequest, JackettSearchResult, JackettSearchRun
from app.services.quality_filters import quality_option_choices
from app.services.rule_builder import (
    looks_like_full_must_contain_override,
    normalize_release_year,
    parse_additional_includes,
    parse_manual_must_contain_additions,
)


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
LOGGER = logging.getLogger(__name__)
SEARCH_DEBUG_LOG_PATH = ROOT_DIR / "logs" / "search-debug.log"


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
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _append_search_debug_event(event: dict[str, object]) -> None:
    try:
        SEARCH_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SEARCH_DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True))
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
    parts.extend(value for value in torznab_attrs.values() if value)
    return _normalize_match_text(" ".join(parts))


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
    if payload.imdb_id or payload.release_year:
        return TORZNAB_MODE_BY_MEDIA_TYPE.get(payload.media_type, "search")
    return "search"


def _request_variant_label(params: dict[str, object]) -> str:
    ordered_keys = ("t", "q", "imdbid", "year", "cat")
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

    extra_keys = sorted(
        key
        for key in params
        if key not in {"apikey", *ordered_keys}
    )
    for key in extra_keys:
        value = _coerce_text(params.get(key))
        if value:
            parts.append(f"{key}={value}")

    return " ".join(parts)


def _request_error_context(url: str, params: dict[str, object]) -> str:
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
        terms: list[str] = [token]
        label_without_parens = PARENS_RE.sub("", label).strip()
        if label_without_parens:
            terms.append(label_without_parens)
        for match in PARENS_RE.findall(label):
            if match.strip():
                terms.append(match.strip())
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
    groups = [group[:MAX_OPTIONAL_KEYWORDS_PER_GROUP] for group in raw_groups[:MAX_OPTIONAL_KEYWORD_GROUPS] if group]
    total_keywords = sum(len(group) for group in groups)
    while total_keywords > MAX_OPTIONAL_KEYWORDS_TOTAL and groups:
        widest_index = max(range(len(groups)), key=lambda index: len(groups[index]))
        if len(groups[widest_index]) <= 1:
            break
        groups[widest_index] = groups[widest_index][:-1]
        total_keywords = sum(len(group) for group in groups)
    while groups and _capped_product([len(group) for group in groups], MAX_QUERY_VARIANTS) > MAX_QUERY_VARIANTS:
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


def _search_request_data_from_rule(rule: Rule) -> tuple[dict[str, object], bool]:
    fallback_title = _first_nonempty_text(
        rule.normalized_title,
        rule.content_name,
        rule.rule_name,
    )
    keywords_all = parse_additional_includes(_coerce_text(rule.additional_includes))
    keywords_any_groups: list[list[str]] = []
    keywords_not = _quality_terms(_coerce_string_list(rule.quality_exclude_tokens))
    must_contain_override = _normalize_legacy_optional_text(rule.must_contain_override)
    ignored_full_regex = looks_like_full_must_contain_override(must_contain_override)
    if not ignored_full_regex:
        keywords_all.extend(parse_manual_must_contain_additions(must_contain_override))
    regex_title = ""
    if ignored_full_regex:
        regex_title, regex_required, regex_any_groups, regex_not = _regex_search_terms(must_contain_override)
        keywords_all.extend(regex_required)
        keywords_any_groups.extend(regex_any_groups)
        keywords_not.extend(regex_not)

    quality_any = _quality_terms(_coerce_string_list(rule.quality_include_tokens))
    if quality_any:
        keywords_any_groups.append(quality_any)

    normalized_groups = _dedupe_term_groups(keywords_any_groups)
    flattened_any: list[str] = []
    for group in normalized_groups:
        flattened_any.extend(group)
    normalized_any_terms = set(_dedupe_terms(flattened_any))
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
            "media_type": _coerce_media_type(rule.media_type),
            "imdb_id": _coerce_text(rule.imdb_id) or None,
            "release_year": normalize_release_year(_coerce_text(rule.release_year)) or None,
            "keywords_all": [
                item
                for item in _dedupe_terms(keywords_all)
                if item not in normalized_any_terms
            ],
            "keywords_any": _dedupe_terms(flattened_any),
            "keywords_any_groups": normalized_groups,
            "keywords_not": [
                item
                for item in _dedupe_terms(keywords_not)
                if item not in normalized_any_terms
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
    keywords_all = list(payload_data["keywords_all"])[:MAX_REQUIRED_KEYWORDS]
    keywords_any_groups = _limit_optional_groups(list(payload_data["keywords_any_groups"]))
    flattened_any: list[str] = []
    for group in keywords_any_groups:
        flattened_any.extend(group)
    normalized_any_terms = set(_dedupe_terms(flattened_any))
    keywords_all = [item for item in keywords_all if item not in normalized_any_terms]
    keywords_not = [
        item
        for item in list(payload_data["keywords_not"])[:MAX_EXCLUDED_KEYWORDS]
        if item not in normalized_any_terms
    ]
    query = clamp_search_query_text(payload_data["query"], fallback="Search")
    payload = JackettSearchRequest(
        query=query,
        media_type=_coerce_media_type(payload_data["media_type"]),
        imdb_id=payload_data["imdb_id"],
        release_year=payload_data["release_year"],
        keywords_all=keywords_all,
        keywords_any=flattened_any,
        keywords_any_groups=keywords_any_groups,
        keywords_not=keywords_not,
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
        self.timeout = timeout if timeout is not None else get_environment_settings().request_timeout
        self.transport = transport

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
        query_variants = self._build_query_variants(remote_payload)
        request_variants: list[str] = []
        seen_request_variants: set[str] = set()
        warning_messages: list[str] = []
        seen_warning_messages: set[str] = set()
        merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
        last_timeout_error: JackettTimeoutError | None = None
        for variant in query_variants:
            request_params = self._search_params_for_variant(remote_payload, variant)
            fallback_params = self._fallback_search_params_for_variant(remote_payload, variant, request_params)
            try:
                variant_results, successful_params, _, timeout_messages = self._search_variant(
                    remote_payload.indexer,
                    request_params,
                    fallback_params=fallback_params,
                )
            except JackettTimeoutError as exc:
                last_timeout_error = exc
                self._add_warning(warning_messages, seen_warning_messages, str(exc))
                continue
            self._add_request_label(request_variants, seen_request_variants, successful_params)
            for message in timeout_messages:
                self._add_warning(warning_messages, seen_warning_messages, message)
            self._merge_results(merged, variant_results)

        if not request_variants and last_timeout_error is not None:
            raise last_timeout_error
        ordered_raw_results = self._ordered_results_from_merged(merged)
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
                "filter_indexers": [],
                "filter_category_ids": [],
            }
        )

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

        request_params = self._search_params_for_variant(payload, primary_query)
        fallback_params = self._fallback_search_params_for_variant(payload, primary_query, request_params)
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
                    variant_results, _, attempted_requests, timeout_messages = self._search_variant_across_capable_indexers(
                        payload,
                        primary_query,
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
        except JackettTimeoutError as exc:
            last_timeout_error = exc
            self._add_warning(warning_messages, seen_warning_messages, str(exc))

        fallback_request_variants: list[str] = []
        seen_fallback_request_variants: set[str] = set()
        fallback_merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
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

        if not request_variants and not fallback_request_variants and last_timeout_error is not None:
            raise last_timeout_error
        primary_raw_results = self._ordered_results_from_merged(primary_merged)
        fallback_raw_results = self._ordered_results_from_merged(fallback_merged)
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
        kept_results: list[JackettSearchResult] = []
        drop_reasons: dict[str, int] = {}
        for result in results:
            matches, drop_reason = self._matches_payload_terms_with_reason(result, payload)
            if matches:
                kept_results.append(result)
                continue
            if drop_reason:
                drop_reasons[drop_reason] = drop_reasons.get(drop_reason, 0) + 1
        if drop_reasons:
            LOGGER.debug(
                "Jackett local filter diagnostics section=%s query=%r raw=%d kept=%d dropped=%d reasons=%s",
                section_label,
                payload.query,
                len(results),
                len(kept_results),
                len(results) - len(kept_results),
                drop_reasons,
            )
        return kept_results

    @staticmethod
    def _log_search_run(payload: JackettSearchRequest, run: JackettSearchRun) -> None:
        keywords_any_groups = payload.keywords_any_groups or ([payload.keywords_any] if payload.keywords_any else [])
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            if parsed_results or not continue_on_empty or attempt_index == len(request_attempts) - 1:
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

        categories = _torznab_categories_for_media_type(payload.media_type)
        if categories:
            params["cat"] = ",".join(categories)

        imdb_lookup_id = _torznab_imdb_lookup_id(payload.imdb_id)
        if imdb_lookup_id and search_mode in {"movie", "tvsearch"}:
            params["imdbid"] = imdb_lookup_id

        return params

    def _fallback_search_params_for_variant(
        self,
        payload: JackettSearchRequest,
        query: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        if params.get("t") == "search":
            return []

        if payload.imdb_id_only:
            imdb_lookup_id = _coerce_text(params.get("imdbid"))
            if not imdb_lookup_id:
                return []

            fallback_params: dict[str, object] = {
                "apikey": self.api_key or "",
                "t": _coerce_text(params.get("t")) or "search",
                "imdbid": imdb_lookup_id,
            }
            categories = _torznab_categories_for_media_type(payload.media_type)
            if categories:
                fallback_params["cat"] = ",".join(categories)
            if query:
                fallback_params["q"] = query
            if fallback_params == params:
                return []
            return [fallback_params]

        fallback_params: list[dict[str, object]] = []
        seen_variants = {
            tuple(sorted((str(key), _coerce_text(value)) for key, value in params.items()))
        }
        categories = _torznab_categories_for_media_type(payload.media_type)

        def add_candidate(candidate: dict[str, object]) -> None:
            candidate_key = tuple(
                sorted((str(key), _coerce_text(value)) for key, value in candidate.items())
            )
            if candidate_key in seen_variants:
                return
            seen_variants.add(candidate_key)
            fallback_params.append(candidate)

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
            if categories:
                candidate["cat"] = ",".join(categories)
            add_candidate(candidate)

        candidate = {
            "apikey": self.api_key or "",
            "t": "search",
            "q": query,
        }
        if categories:
            candidate["cat"] = ",".join(categories)
        add_candidate(candidate)

        return fallback_params

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
            request_attempts = self._imdb_enforced_params_for_indexer(payload, query, search_mode, indexer)
            if not request_attempts:
                continue
            try:
                indexer_results, successful_params, indexer_attempts, indexer_warnings = self._search_variant(
                    indexer.indexer_id,
                    request_attempts[0],
                    fallback_params=request_attempts[1:],
                    continue_on_empty=True,
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

    def _search_title_fallback(
        self,
        payload: JackettSearchRequest,
        *,
        existing_merge_keys: set[str] | None = None,
    ) -> tuple[list[tuple[datetime | None, JackettSearchResult]], list[dict[str, object]], list[str]]:
        fallback_payload = payload.model_copy(
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
                "filter_indexers": [],
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

        for query in query_variants:
            try:
                params = self._search_params_for_variant(fallback_payload, query)
                forced_mode = TORZNAB_MODE_BY_MEDIA_TYPE.get(payload.media_type)
                if forced_mode:
                    params["t"] = forced_mode
                fallback_params = self._fallback_search_params_for_variant(
                    fallback_payload,
                    query,
                    params,
                )
                parsed_results, successful_params, _, timeout_messages = self._search_variant(
                    fallback_payload.indexer,
                    params,
                    fallback_params=fallback_params,
                )
            except JackettTimeoutError as exc:
                warning_messages.append(str(exc))
                continue
            except JackettHTTPError as exc:
                if exc.status_code != 400:
                    raise
                continue
            request_variants.append(successful_params)
            warning_messages.extend(timeout_messages)

            fallback_results.extend(
                item
                for item in parsed_results
                if self._merge_key(item[1]) not in seen_merge_keys
            )
            seen_merge_keys.update(self._merge_key(item[1]) for item in parsed_results)

        return fallback_results, request_variants, warning_messages

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
                supported = item.attrib.get("supportedParams") or item.attrib.get("supportedparams") or ""
                supported_params = frozenset(
                    param.strip().casefold()
                    for param in supported.split(",")
                    if param.strip()
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
        query: str,
        search_mode: str,
        indexer: JackettIndexerCapability,
    ) -> list[dict[str, object]]:
        imdb_lookup_id = _torznab_imdb_lookup_id(payload.imdb_id)
        if not imdb_lookup_id:
            return []

        categories = _torznab_categories_for_media_type(payload.media_type)
        base_params = {
            "apikey": self.api_key or "",
            "t": search_mode,
            "imdbid": imdb_lookup_id,
        }
        if categories:
            base_params["cat"] = ",".join(categories)

        request_attempts: list[dict[str, object]] = []
        if "q" in indexer.supported_params and query:
            request_attempts.append(
                {
                    **base_params,
                    "q": query,
                }
            )
        request_attempts.append(base_params)
        return request_attempts

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
                elif attr_name in {"jackettindexer", "indexer"}:
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

        if not title or not link:
            return None

        year = _resolved_result_year(explicit_year=year, title=title)
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
        params: dict[str, object],
    ) -> ET.Element:
        if not self.base_url:
            raise JackettConfigError("Jackett app URL is not configured.")

        request_context = _request_error_context(url, params)
        timeout_error: httpx.TimeoutException | None = None
        for _ in range(TIMEOUT_RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.get(url, params=params)
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
        if not imdb_exact_match and not _matches_query_text(title_surface=title_surface, query=payload.query):
            return False, "query"
        text_surface = result.text_surface or title_surface
        for keyword in payload.keywords_all:
            if not _matches_included_keyword(text_surface, keyword):
                return False, "keywords_all"
        any_groups = payload.keywords_any_groups or ([payload.keywords_any] if payload.keywords_any else [])
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
            if not result.category_ids:
                return False, "filter_categories_missing"
            allowed_categories = {item.casefold() for item in payload.filter_category_ids}
            item_categories = {item.casefold() for item in result.category_ids}
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
