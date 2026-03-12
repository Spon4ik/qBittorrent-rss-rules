from __future__ import annotations

from sqlalchemy import select

from app.models import IndexerCategoryCatalog
from app.schemas import JackettSearchResult
from app.services.category_catalog import (
    resolve_category_labels,
    sync_category_catalog_from_indexer_map,
    sync_category_catalog_from_results,
)


def test_category_catalog_sync_from_indexer_map_and_resolve_labels(db_session) -> None:
    changed = sync_category_catalog_from_indexer_map(
        db_session,
        {
            "RuTracker": {
                "101279": ["Audiobooks", "Audio/Audiobooks"],
                "5000": ["TV"],
            }
        },
    )
    db_session.commit()

    assert changed == 2
    labels = resolve_category_labels(
        db_session,
        indexer="rutracker",
        category_ids=["101279", "5000"],
    )
    assert labels == ["Audiobooks", "TV"]


def test_category_catalog_prefers_indexer_caps_over_result_fallback(db_session) -> None:
    changed_from_results = sync_category_catalog_from_results(
        db_session,
        [
            JackettSearchResult(
                title="Example",
                link="magnet:?xt=urn:btih:EXAMPLE1",
                indexer="Book Tracker",
                category_ids=["22222"],
                category_labels=[],
            )
        ],
    )
    changed_from_caps = sync_category_catalog_from_indexer_map(
        db_session,
        {"booktracker": {"22222": ["Audiobooks"]}},
    )
    db_session.commit()

    assert changed_from_results == 1
    assert changed_from_caps == 1
    row = db_session.get(IndexerCategoryCatalog, ("booktracker", "22222"))
    assert row is not None
    assert row.category_name == "Audiobooks"
    assert row.source == "indexer_caps"


def test_category_catalog_sync_from_search_results_writes_indexer_category_rows(db_session) -> None:
    changed = sync_category_catalog_from_results(
        db_session,
        [
            JackettSearchResult(
                title="Movie UHD",
                link="magnet:?xt=urn:btih:ABC123",
                indexer="RUTRACKER",
                category_ids=["2045"],
                category_labels=["Movies/UHD"],
            )
        ],
    )
    db_session.commit()

    assert changed == 1
    rows = db_session.scalars(select(IndexerCategoryCatalog)).all()
    assert len(rows) == 1
    assert rows[0].indexer == "rutracker"
    assert rows[0].category_id == "2045"
    assert rows[0].category_name == "Movies/UHD"


def test_category_catalog_resolve_respects_indexer_scope_for_same_category_id(db_session) -> None:
    changed = sync_category_catalog_from_indexer_map(
        db_session,
        {
            "RuTracker": {"5000": ["TV"]},
            "booktracker": {"5000": ["Books"]},
        },
    )
    db_session.commit()

    assert changed == 2
    assert resolve_category_labels(db_session, indexer="rutracker", category_ids=["5000"]) == ["TV"]
    assert resolve_category_labels(db_session, indexer="book-tracker", category_ids=["5000"]) == ["Books"]


def test_category_catalog_uses_category_id_fallback_for_ambiguous_result_labels(db_session) -> None:
    changed = sync_category_catalog_from_results(
        db_session,
        [
            JackettSearchResult(
                title="Example",
                link="magnet:?xt=urn:btih:EXAMPLE2",
                indexer="alpha",
                category_ids=["5000", "5070"],
                category_labels=["TV"],
            )
        ],
    )
    db_session.commit()

    assert changed == 2
    assert resolve_category_labels(db_session, indexer="alpha", category_ids=["5000", "5070"]) == [
        "Category #5000",
        "Category #5070",
    ]


def test_category_catalog_normalizes_legacy_unknown_labels(db_session) -> None:
    db_session.add(
        IndexerCategoryCatalog(
            indexer="legacyindexer",
            category_id="100119",
            category_name="Unknown (#100119)",
            source="manual_fallback",
        )
    )
    db_session.commit()

    assert resolve_category_labels(
        db_session,
        indexer="legacyindexer",
        category_ids=["100119"],
    ) == ["Category #100119"]
