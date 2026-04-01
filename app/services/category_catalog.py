from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IndexerCategoryCatalog
from app.schemas import JackettSearchResult

INDEXER_KEY_STRIP_RE = re.compile(r"[\s._-]+")
PLACEHOLDER_CATEGORY_NAME_RE = re.compile(r"^(?:Unknown \(#[^)]+\)|Category #.+)$")
CATEGORY_SOURCE_PRIORITY: dict[str, int] = {
    "manual_fallback": 1,
    "result_attr": 2,
    "indexer_caps": 3,
}


def normalize_indexer_key(value: object | None) -> str:
    cleaned = str(value or "").strip().casefold()
    if not cleaned:
        return ""
    return INDEXER_KEY_STRIP_RE.sub("", cleaned)


def indexer_key_candidates(value: object | None) -> list[str]:
    raw = str(value or "").strip().casefold()
    candidates: list[str] = []
    for candidate in (raw, normalize_indexer_key(value)):
        if not candidate or candidate in candidates:
            continue
        candidates.append(candidate)
    if raw.startswith("www."):
        raw = raw[4:]
    if "." in raw:
        host_without_tld = raw.rsplit(".", 1)[0].strip()
        for candidate in (host_without_tld, normalize_indexer_key(host_without_tld)):
            if not candidate or candidate in candidates:
                continue
            candidates.append(candidate)
    return candidates


def normalize_category_id(value: object | None) -> str:
    return str(value or "").strip()


def _normalize_category_name(value: object | None) -> str:
    return str(value or "").strip()


def _source_priority(source: str) -> int:
    return CATEGORY_SOURCE_PRIORITY.get(str(source or "").strip().casefold(), 0)


def _fallback_category_name(category_id: str) -> str:
    return f"Category #{category_id}"


def _is_placeholder_category_name(value: str) -> bool:
    return bool(PLACEHOLDER_CATEGORY_NAME_RE.match(_normalize_category_name(value)))


def _canonical_category_name(value: object | None, category_id: str) -> str:
    cleaned = _normalize_category_name(value)
    if not cleaned:
        return _fallback_category_name(category_id)
    if _is_placeholder_category_name(cleaned):
        return _fallback_category_name(category_id)
    return cleaned


def _first_label(labels: Sequence[str] | None, category_id: str) -> str:
    for item in labels or ():
        candidate = _normalize_category_name(item)
        if candidate:
            return candidate
    return _fallback_category_name(category_id)


def _upsert_catalog_row(
    session: Session,
    *,
    indexer: str,
    category_id: str,
    category_name: str,
    source: str,
) -> bool:
    existing = next(
        (
            item
            for item in session.new
            if isinstance(item, IndexerCategoryCatalog)
            and item.indexer == indexer
            and item.category_id == category_id
        ),
        None,
    )
    if existing is None:
        existing = session.get(IndexerCategoryCatalog, (indexer, category_id))
    normalized_name = _canonical_category_name(category_name, category_id)
    normalized_source = str(source or "result_attr").strip() or "result_attr"
    if existing is None:
        session.add(
            IndexerCategoryCatalog(
                indexer=indexer,
                category_id=category_id,
                category_name=normalized_name,
                source=normalized_source,
                updated_at=datetime.now(UTC),
            )
        )
        return True

    current_priority = _source_priority(existing.source)
    incoming_priority = _source_priority(normalized_source)
    existing_is_unknown = _is_placeholder_category_name(existing.category_name)
    should_replace_name = (
        incoming_priority > current_priority
        or existing_is_unknown
        or not existing.category_name.strip()
    )
    if should_replace_name:
        existing.category_name = normalized_name
        existing.source = normalized_source
        existing.updated_at = datetime.now(UTC)
        return True
    existing.updated_at = datetime.now(UTC)
    return False


def sync_category_catalog_from_indexer_map(
    session: Session,
    indexer_category_labels: Mapping[str, Mapping[str, Sequence[str]]],
    *,
    source: str = "indexer_caps",
) -> int:
    changed_rows = 0
    for raw_indexer, category_map in indexer_category_labels.items():
        indexer = normalize_indexer_key(raw_indexer)
        if not indexer:
            continue
        for raw_category_id, labels in category_map.items():
            category_id = normalize_category_id(raw_category_id)
            if not category_id:
                continue
            if _upsert_catalog_row(
                session,
                indexer=indexer,
                category_id=category_id,
                category_name=_first_label(list(labels), category_id),
                source=source,
            ):
                changed_rows += 1
    return changed_rows


def sync_category_catalog_from_results(
    session: Session,
    results: Iterable[JackettSearchResult],
    *,
    source: str = "result_attr",
) -> int:
    changed_rows = 0
    for result in results:
        indexer = normalize_indexer_key(result.indexer)
        if not indexer:
            continue
        category_ids = [normalize_category_id(item) for item in list(result.category_ids or [])]
        category_ids = [item for item in category_ids if item]
        if not category_ids:
            continue
        labels = [_normalize_category_name(item) for item in list(result.category_labels or [])]
        labels = [item for item in labels if item]
        for category_id in category_ids:
            if len(category_ids) == 1 and labels:
                label = labels[0]
            else:
                label = _fallback_category_name(category_id)
            if _upsert_catalog_row(
                session,
                indexer=indexer,
                category_id=category_id,
                category_name=label,
                source=source,
            ):
                changed_rows += 1
    return changed_rows


def resolve_category_labels(
    session: Session,
    *,
    indexer: str | None,
    category_ids: Sequence[str],
) -> list[str]:
    normalized_ids = [
        normalize_category_id(item) for item in category_ids if normalize_category_id(item)
    ]
    if not normalized_ids:
        return []
    indexer_candidates = indexer_key_candidates(indexer)
    if not indexer_candidates:
        return [_fallback_category_name(category_id) for category_id in normalized_ids]

    rows = session.scalars(
        select(IndexerCategoryCatalog).where(
            IndexerCategoryCatalog.indexer.in_(indexer_candidates),
            IndexerCategoryCatalog.category_id.in_(normalized_ids),
        )
    ).all()
    rank_by_indexer = {candidate: rank for rank, candidate in enumerate(indexer_candidates)}
    selected: dict[str, tuple[int, int, str]] = {}
    for row in rows:
        indexer_rank = rank_by_indexer.get(row.indexer, len(indexer_candidates))
        source_rank = _source_priority(row.source)
        score = (indexer_rank, -source_rank)
        current = selected.get(row.category_id)
        if current is None or score < (current[0], current[1]):
            selected[row.category_id] = (score[0], score[1], row.category_name)

    labels: list[str] = []
    seen: set[str] = set()
    for category_id in normalized_ids:
        label = selected.get(category_id, (0, 0, _fallback_category_name(category_id)))[2]
        normalized_label = _canonical_category_name(label, category_id)
        if not normalized_label or normalized_label in seen:
            continue
        seen.add(normalized_label)
        labels.append(normalized_label)
    return labels
