from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import product
import re
import xml.etree.ElementTree as ET

import httpx

from app.config import get_environment_settings
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


class JackettHTTPError(JackettClientError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


PARENS_RE = re.compile(r"\(([^)]+)\)")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
SPACE_RE = re.compile(r"\s+")
QUANTIFIER_RE = re.compile(r"\{[0-9]+(?:,[0-9]*)?\}")
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
TORZNAB_YEAR_MODES = {"movie", "tvsearch", "music", "book"}


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
    cleaned = NON_ALNUM_RE.sub(" ", str(value or "").casefold())
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _first_nonempty_text(*values: object | None) -> str:
    for value in values:
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return ""


def _coerce_text(value: object | None) -> str:
    return str(value or "").strip()


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


def _contains_term(text: str, term: str) -> bool:
    normalized_text = _normalize_match_text(text)
    normalized_term = _normalize_match_text(term)
    if not normalized_text or not normalized_term:
        return False
    return normalized_term in normalized_text


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


def _ordered_unique_terms(raw_terms: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_terms:
        candidate = str(item).strip()
        if not candidate:
            continue
        key = _normalize_term(candidate)
        if key in seen:
            continue
        seen.add(key)
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
    must_contain_override = _coerce_text(rule.must_contain_override)
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
        query_variants = self._build_query_variants(payload)
        request_variants: list[str] = []
        seen_request_variants: set[str] = set()
        merged: dict[str, tuple[datetime | None, JackettSearchResult]] = {}
        for variant in query_variants:
            request_params = self._search_params_for_variant(payload, variant)
            fallback_params = self._fallback_search_params_for_variant(payload, variant, request_params)
            variant_results, successful_params = self._search_variant(
                payload.indexer,
                request_params,
                fallback_params=fallback_params,
            )
            request_label = _request_variant_label(successful_params)
            if request_label and request_label not in seen_request_variants:
                seen_request_variants.add(request_label)
                request_variants.append(request_label)
            for published_at, result in variant_results:
                if not self._matches_payload_terms(result, payload):
                    continue
                merge_key = self._merge_key(result)
                if merge_key in merged:
                    continue
                merged[merge_key] = (published_at, result)

        ordered_results = [
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
        return JackettSearchRun(
            query_variants=query_variants,
            request_variants=request_variants,
            results=ordered_results,
        )

    def _build_query_variants(self, payload: JackettSearchRequest) -> list[str]:
        if payload.imdb_id_only:
            return [payload.query.strip()]
        base_parts = _ordered_unique_terms([payload.query.strip(), *payload.keywords_all])
        base_query = " ".join(part for part in base_parts if str(part).strip()).strip()
        any_groups = payload.keywords_any_groups or ([payload.keywords_any] if payload.keywords_any else [])
        if not any_groups:
            return [base_query]
        combinations = list(product(*any_groups))
        if len(combinations) > MAX_QUERY_VARIANTS:
            raise JackettClientError("Search expands into too many keyword combinations.")
        return [
            " ".join(
                _ordered_unique_terms([*base_parts, *combo])
            ).strip()
            for combo in combinations
        ]

    def _search_variant(
        self,
        indexer: str,
        params: dict[str, object],
        *,
        fallback_params: list[dict[str, object]] | None = None,
    ) -> tuple[list[tuple[datetime | None, JackettSearchResult]], dict[str, object]]:
        endpoint = self._torznab_endpoint(indexer)
        request_attempts = [params, *(fallback_params or [])]
        last_bad_request_error: JackettHTTPError | None = None
        successful_params = params
        for request_params in request_attempts:
            try:
                root = self._request_xml(
                    endpoint,
                    params=request_params,
                )
                successful_params = request_params
                break
            except JackettHTTPError as exc:
                if exc.status_code != 400:
                    raise
                last_bad_request_error = exc
                continue
        else:
            if last_bad_request_error is not None:
                raise last_bad_request_error
            raise JackettClientError("Jackett request failed.")

        parsed_results: list[tuple[datetime | None, JackettSearchResult]] = []
        for item in root.iter():
            if _local_name(item.tag) != "item":
                continue
            parsed = self._parse_item(item)
            if parsed is None:
                continue
            parsed_results.append(parsed)
        return parsed_results, successful_params

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

        if payload.release_year and not payload.imdb_id_only and search_mode in TORZNAB_YEAR_MODES:
            params["year"] = payload.release_year

        return params

    def _fallback_search_params_for_variant(
        self,
        payload: JackettSearchRequest,
        query: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        if params.get("t") == "search" or payload.imdb_id_only:
            return []

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

    def _parse_item(self, item: ET.Element) -> tuple[datetime | None, JackettSearchResult] | None:
        title = ""
        link = ""
        guid: str | None = None
        details_url: str | None = None
        published_at: datetime | None = None
        size_bytes: int | None = None
        info_hash: str | None = None
        indexer: str | None = None

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
            elif tag == "attr":
                attr_name = child.attrib.get("name", "").strip().casefold().replace("-", "")
                attr_value = child.attrib.get("value", "").strip()
                if attr_name == "size" and size_bytes is None:
                    size_bytes = _coerce_int(attr_value)
                elif attr_name in {"infohash", "info_hash"}:
                    info_hash = attr_value or None
                elif attr_name in {"jackettindexer", "indexer"}:
                    indexer = attr_value or None

        if not title or not link:
            return None

        return (
            published_at,
            JackettSearchResult(
                title=title,
                link=link,
                indexer=indexer,
                details_url=details_url,
                guid=guid,
                info_hash=info_hash,
                size_bytes=size_bytes,
                size_label=_format_size(size_bytes),
                published_label=_format_published(published_at),
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
                    f"Jackett request failed: {exc}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.HTTPError as exc:
                raise JackettClientError(f"Jackett request failed: {exc}") from exc
        else:
            raise JackettClientError(
                f"Jackett request failed after {TIMEOUT_RETRY_ATTEMPTS} timeout attempts: {timeout_error}"
            ) from timeout_error

        try:
            return ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise JackettClientError("Jackett returned invalid XML.") from exc

    def _torznab_endpoint(self, indexer: str) -> str:
        resolved_indexer = (indexer or "all").strip() or "all"
        return f"{self.base_url}/api/v2.0/indexers/{resolved_indexer}/results/torznab/api"

    def _ensure_ready(self) -> None:
        if not self.base_url:
            raise JackettConfigError("Jackett app URL is not configured.")
        if not self.api_key:
            raise JackettConfigError("Jackett API key is not configured.")

    @staticmethod
    def _matches_payload_terms(
        result: JackettSearchResult,
        payload: JackettSearchRequest,
    ) -> bool:
        title = result.title
        for keyword in payload.keywords_all:
            if not _contains_term(title, keyword):
                return False
        any_groups = payload.keywords_any_groups or ([payload.keywords_any] if payload.keywords_any else [])
        for group in any_groups:
            if not any(_contains_term(title, keyword) for keyword in group):
                return False
        for keyword in payload.keywords_not:
            if _contains_term(title, keyword):
                return False
        return True

    @staticmethod
    def _merge_key(result: JackettSearchResult) -> str:
        if result.info_hash:
            return f"hash:{result.info_hash.casefold()}"
        if result.guid:
            return f"guid:{result.guid.casefold()}"
        size_key = result.size_bytes if result.size_bytes is not None else "none"
        return f"title:{result.title.casefold()}:{size_key}"
