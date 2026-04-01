from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

from sqlalchemy.orm import Session

from app.models import RuleSearchSnapshot, utcnow
from app.schemas import JackettSearchRequest, JackettSearchResult, JackettSearchRun


def _search_result_key(item: JackettSearchResult) -> str:
    merge_key = str(item.merge_key or "").strip()
    if merge_key:
        return merge_key
    info_hash = str(item.info_hash or "").strip().casefold()
    guid = str(item.guid or "").strip().casefold()
    title = str(item.title or "").strip().casefold()
    size_bytes = item.size_bytes
    return f"{info_hash}|{guid}|{title}|{size_bytes}"


def _serialized_result_key(item: Mapping[str, Any]) -> str:
    merge_key = str(item.get("merge_key", "") or "").strip()
    if merge_key:
        return merge_key
    info_hash = str(item.get("info_hash", "") or "").strip().casefold()
    guid = str(item.get("guid", "") or "").strip().casefold()
    title = str(item.get("title", "") or "").strip().casefold()
    size_bytes = item.get("size_bytes")
    return f"{info_hash}|{guid}|{title}|{size_bytes}"


def _primary_label(payload: JackettSearchRequest) -> str:
    if payload.imdb_id_only:
        return "IMDb-first results"
    return "Rule search results"


def _normalized_fallback_label(fallback_label: str) -> str:
    cleaned = str(fallback_label or "").strip()
    if cleaned:
        return cleaned
    return "Title fallback"


def _assign_query_source_labels(
    row: dict[str, Any],
    *,
    sources: set[str],
    primary_label: str,
    fallback_label: str,
) -> None:
    normalized_fallback_label = _normalized_fallback_label(fallback_label)
    if sources == {"primary"}:
        row["query_source_key"] = "primary"
        row["query_source_label"] = primary_label
        return
    if sources == {"fallback"}:
        row["query_source_key"] = "fallback"
        row["query_source_label"] = normalized_fallback_label
        return
    row["query_source_key"] = "primary+fallback"
    row["query_source_label"] = f"{primary_label} + {normalized_fallback_label}"


def _build_unified_raw_results_from_models(
    *,
    raw_primary: list[JackettSearchResult],
    raw_fallback: list[JackettSearchResult],
    visible_primary_keys: set[str],
    visible_fallback_keys: set[str],
    primary_label: str,
    fallback_label: str,
) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    row_sources: dict[str, set[str]] = {}
    row_order: list[str] = []

    for source_name, items, visible_keys in (
        ("primary", raw_primary, visible_primary_keys),
        ("fallback", raw_fallback, visible_fallback_keys),
    ):
        for item in items:
            row_key = _search_result_key(item)
            existing = rows_by_key.get(row_key)
            is_visible = row_key in visible_keys
            if existing is None:
                rows_by_key[row_key] = {
                    **item.model_dump(mode="json"),
                    "visible": is_visible,
                }
                row_sources[row_key] = {source_name}
                row_order.append(row_key)
                continue
            row_sources[row_key].add(source_name)
            if is_visible:
                existing["visible"] = True

    unified_rows: list[dict[str, Any]] = []
    for row_key in row_order:
        row = rows_by_key[row_key]
        _assign_query_source_labels(
            row,
            sources=row_sources[row_key],
            primary_label=primary_label,
            fallback_label=fallback_label,
        )
        unified_rows.append(row)
    return unified_rows


def _coerce_serialized_result_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            rows.append(dict(item))
    return rows


def _build_unified_raw_results_from_serialized(
    *,
    raw_primary: list[dict[str, Any]],
    raw_fallback: list[dict[str, Any]],
    visible_primary_keys: set[str],
    visible_fallback_keys: set[str],
    primary_label: str,
    fallback_label: str,
) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    row_sources: dict[str, set[str]] = {}
    row_order: list[str] = []

    for source_name, items, visible_keys in (
        ("primary", raw_primary, visible_primary_keys),
        ("fallback", raw_fallback, visible_fallback_keys),
    ):
        for item in items:
            row = dict(item)
            row_key = _serialized_result_key(row)
            existing = rows_by_key.get(row_key)
            is_visible = (row_key in visible_keys) or bool(row.get("visible"))
            if existing is None:
                row["visible"] = is_visible
                rows_by_key[row_key] = row
                row_sources[row_key] = {source_name}
                row_order.append(row_key)
                continue
            row_sources[row_key].add(source_name)
            if is_visible:
                existing["visible"] = True

    unified_rows: list[dict[str, Any]] = []
    for row_key in row_order:
        row = rows_by_key[row_key]
        _assign_query_source_labels(
            row,
            sources=row_sources[row_key],
            primary_label=primary_label,
            fallback_label=fallback_label,
        )
        unified_rows.append(row)
    return unified_rows


def _build_source_breakdown(
    *,
    primary_label: str,
    fallback_label: str,
    primary_filtered_count: int,
    primary_fetched_count: int,
    primary_request_variants: list[str],
    fallback_filtered_count: int,
    fallback_fetched_count: int,
    fallback_request_variants: list[str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [
        {
            "key": "primary",
            "label": primary_label,
            "filtered_count": primary_filtered_count,
            "fetched_count": primary_fetched_count,
            "request_variants": list(primary_request_variants),
        }
    ]
    if fallback_request_variants or fallback_fetched_count:
        entries.append(
            {
                "key": "fallback",
                "label": _normalized_fallback_label(fallback_label),
                "filtered_count": fallback_filtered_count,
                "fetched_count": fallback_fetched_count,
                "request_variants": list(fallback_request_variants),
            }
        )
    return entries


def _finalize_unified_payload(payload: dict[str, Any]) -> dict[str, Any]:
    unified_rows = _coerce_serialized_result_rows(payload.get("unified_raw_results"))
    payload["unified_raw_results"] = unified_rows
    payload["combined_fetched_count"] = len(unified_rows)
    payload["combined_filtered_count"] = sum(
        1 for item in unified_rows if bool(item.get("visible"))
    )
    payload["show_peers_column"] = any(item.get("peers") is not None for item in unified_rows)
    payload["show_leechers_column"] = any(item.get("leechers") is not None for item in unified_rows)
    payload["show_grabs_column"] = any(item.get("grabs") is not None for item in unified_rows)
    return payload


def build_inline_search_payload(
    *,
    payload: JackettSearchRequest,
    run: JackettSearchRun,
    ignored_full_regex: bool,
    primary_label_override: str | None = None,
    fallback_label_override: str | None = None,
) -> dict[str, object]:
    primary_label = primary_label_override or _primary_label(payload)
    fallback_label = (
        fallback_label_override
        if fallback_label_override is not None
        else ("Title fallback" if run.fallback_request_variants else "")
    )
    raw_primary = list(run.raw_results or run.results)
    raw_fallback = list(run.raw_fallback_results or run.fallback_results)
    visible_primary_keys = {_search_result_key(item) for item in run.results}
    visible_fallback_keys = {_search_result_key(item) for item in run.fallback_results}
    all_results = [*raw_primary, *raw_fallback]
    unified_raw_results = _build_unified_raw_results_from_models(
        raw_primary=raw_primary,
        raw_fallback=raw_fallback,
        visible_primary_keys=visible_primary_keys,
        visible_fallback_keys=visible_fallback_keys,
        primary_label=primary_label,
        fallback_label=fallback_label,
    )

    payload_dict: dict[str, Any] = {
        "query": payload.query,
        "primary_label": primary_label,
        "request_variants": list(run.request_variants or run.query_variants),
        "raw_results": [
            {
                **item.model_dump(mode="json"),
                "visible": _search_result_key(item) in visible_primary_keys,
            }
            for item in raw_primary
        ],
        "results": [item.model_dump(mode="json") for item in run.results],
        "fallback_label": fallback_label,
        "fallback_request_variants": list(run.fallback_request_variants or []),
        "raw_fallback_results": [
            {
                **item.model_dump(mode="json"),
                "visible": _search_result_key(item) in visible_fallback_keys,
            }
            for item in raw_fallback
        ],
        "fallback_results": [item.model_dump(mode="json") for item in run.fallback_results],
        "unified_raw_results": unified_raw_results,
        "source_breakdown": _build_source_breakdown(
            primary_label=primary_label,
            fallback_label=fallback_label,
            primary_filtered_count=len(run.results),
            primary_fetched_count=len(raw_primary),
            primary_request_variants=list(run.request_variants or run.query_variants),
            fallback_filtered_count=len(run.fallback_results),
            fallback_fetched_count=len(raw_fallback),
            fallback_request_variants=list(run.fallback_request_variants or []),
        ),
        "warning_messages": list(run.warning_messages or []),
        "ignored_full_regex": ignored_full_regex,
        "show_peers_column": any(item.peers is not None for item in all_results),
        "show_leechers_column": any(item.leechers is not None for item in all_results),
        "show_grabs_column": any(item.grabs is not None for item in all_results),
    }
    return cast(dict[str, object], _finalize_unified_payload(payload_dict))


def save_rule_search_snapshot(
    session: Session,
    *,
    rule_id: str,
    payload: JackettSearchRequest,
    run: JackettSearchRun,
    ignored_full_regex: bool,
) -> RuleSearchSnapshot:
    snapshot = session.get(RuleSearchSnapshot, rule_id)
    if snapshot is None:
        snapshot = RuleSearchSnapshot(rule_id=rule_id)

    snapshot.payload = cast(dict[str, object], payload.model_dump(mode="json"))
    snapshot.inline_search = build_inline_search_payload(
        payload=payload,
        run=run,
        ignored_full_regex=ignored_full_regex,
    )
    snapshot.fetched_at = utcnow()
    session.add(snapshot)
    return snapshot


def get_rule_search_snapshot(session: Session, *, rule_id: str) -> RuleSearchSnapshot | None:
    return session.get(RuleSearchSnapshot, rule_id)


def inline_search_from_snapshot(snapshot: RuleSearchSnapshot) -> dict[str, object]:
    inline_search = deepcopy(cast(dict[str, Any], snapshot.inline_search or {}))
    primary_label = str(inline_search.get("primary_label") or "Rule search results")
    fallback_label = str(inline_search.get("fallback_label") or "")
    raw_primary = _coerce_serialized_result_rows(inline_search.get("raw_results"))
    raw_fallback = _coerce_serialized_result_rows(inline_search.get("raw_fallback_results"))
    filtered_primary = _coerce_serialized_result_rows(inline_search.get("results"))
    filtered_fallback = _coerce_serialized_result_rows(inline_search.get("fallback_results"))
    visible_primary_keys = {_serialized_result_key(item) for item in filtered_primary}
    visible_fallback_keys = {_serialized_result_key(item) for item in filtered_fallback}

    if not inline_search.get("unified_raw_results"):
        inline_search["unified_raw_results"] = _build_unified_raw_results_from_serialized(
            raw_primary=raw_primary,
            raw_fallback=raw_fallback,
            visible_primary_keys=visible_primary_keys,
            visible_fallback_keys=visible_fallback_keys,
            primary_label=primary_label,
            fallback_label=fallback_label,
        )

    if not inline_search.get("source_breakdown"):
        inline_search["source_breakdown"] = _build_source_breakdown(
            primary_label=primary_label,
            fallback_label=fallback_label,
            primary_filtered_count=len(filtered_primary),
            primary_fetched_count=len(raw_primary),
            primary_request_variants=[
                str(item)
                for item in (
                    inline_search.get("request_variants")
                    or inline_search.get("query_variants")
                    or []
                )
                if str(item or "").strip()
            ],
            fallback_filtered_count=len(filtered_fallback),
            fallback_fetched_count=len(raw_fallback),
            fallback_request_variants=[
                str(item)
                for item in (inline_search.get("fallback_request_variants") or [])
                if str(item or "").strip()
            ],
        )

    inline_search = _finalize_unified_payload(inline_search)
    inline_search["snapshot_fetched_at"] = snapshot.fetched_at.isoformat()
    return cast(dict[str, object], inline_search)
