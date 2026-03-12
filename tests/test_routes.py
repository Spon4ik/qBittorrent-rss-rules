from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import obfuscate_secret
from app.models import (
    AppSettings,
    IndexerCategoryCatalog,
    MediaType,
    QualityProfile,
    Rule,
    SyncStatus,
)
from app.schemas import (
    JackettSearchRequest,
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services import quality_filters
from app.services.jackett import JackettClient, clamp_search_query_text
from app.services.metadata import MetadataClient


def _use_temp_taxonomy(tmp_path: Path, monkeypatch):
    payload = json.loads(quality_filters.QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8"))
    taxonomy_path = tmp_path / "quality_taxonomy.json"
    audit_path = tmp_path / "taxonomy_audit.jsonl"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_PATH", taxonomy_path)
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_AUDIT_PATH", audit_path)
    quality_filters._clear_quality_taxonomy_cache()
    return payload, taxonomy_path, audit_path


@pytest.fixture(autouse=True)
def clear_quality_taxonomy_cache() -> None:
    quality_filters._clear_quality_taxonomy_cache()
    yield
    quality_filters._clear_quality_taxonomy_cache()


def test_health_endpoint(app_client) -> None:
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rules_page_header_includes_create_rule_button(app_client) -> None:
    response = app_client.get("/")

    assert response.status_code == 200
    assert '>Create Rule</a>' in response.text


def test_run_rule_search_route_redirects_to_inline_rule_page(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Search Redirect",
        content_name="Rule Search Redirect",
        normalized_title="Rule Search Redirect",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/redirect"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(f"/rules/{rule.id}/search", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/rules/{rule.id}?run_search=1#inline-search-results"


def test_run_rule_search_route_preserves_feed_url_overrides(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Search Redirect With Feeds",
        content_name="Rule Search Redirect With Feeds",
        normalized_title="Rule Search Redirect With Feeds",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/redirect"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(
        f"/rules/{rule.id}/search",
        params=[
            ("feed_scope_override", "1"),
            ("feed_urls", "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api?apikey=abc"),
            ("feed_urls", "http://jackett:9117/api/v2.0/indexers/kinozal/results/torznab/api?apikey=abc"),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/rules/{rule.id}"
        "?run_search=1"
        "&feed_scope_override=1"
        "&feed_urls=http%3A%2F%2Fjackett%3A9117%2Fapi%2Fv2.0%2Findexers%2Frutracker%2Fresults%2Ftorznab%2Fapi%3Fapikey%3Dabc"
        "&feed_urls=http%3A%2F%2Fjackett%3A9117%2Fapi%2Fv2.0%2Findexers%2Fkinozal%2Fresults%2Ftorznab%2Fapi%3Fapikey%3Dabc"
        "#inline-search-results"
    )


def test_search_page_renders_jackett_as_separate_source(app_client) -> None:
    response = app_client.get("/search")

    assert response.status_code == 200
    assert "Active Jackett search" in response.text
    assert "Not mixed with RSS feeds" in response.text


def test_search_page_prefills_new_rule_from_active_search(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "Dune Part Two"
        assert payload.keywords_all == []
        assert payload.keywords_any == ["4k", "2160p"]
        assert payload.keywords_not == []
        return JackettSearchRun(
            query_variants=["Dune Part Two 4k", "Dune Part Two 2160p"],
            results=[
                JackettSearchResult(
                    title="Dune Part Two 2160p",
                    link="magnet:?xt=urn:btih:ABC123",
                    indexer="rutracker",
                    size_bytes=1073741824,
                    size_label="1.0 GB",
                    published_label="2024-01-01 00:00 UTC",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Dune Part Two",
            "media_type": "movie",
            "keywords_any": "4k, 2160p",
        },
    )

    assert response.status_code == 200
    assert "Dune Part Two 2160p" in response.text
    assert "/rules/new?rule_name=Dune+Part+Two" in response.text
    assert "must_contain_override=%28%3F%3A4k%7C2160p%29" in response.text


def test_search_page_embeds_raw_cache_payload_for_local_refinement(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Dune Part Two"],
            raw_results=[
                JackettSearchResult(
                    merge_key="hash:abc123",
                    title="Dune Part Two 2160p",
                    link="magnet:?xt=urn:btih:ABC123",
                    indexer="rutracker",
                    size_bytes=1073741824,
                    size_label="1.0 GB",
                    year="2024",
                    category_ids=["2000"],
                    text_surface="dune part two 2160p rutracker 2024 2000",
                )
            ],
            results=[
                JackettSearchResult(
                    merge_key="hash:abc123",
                    title="Dune Part Two 2160p",
                    link="magnet:?xt=urn:btih:ABC123",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Dune Part Two",
            "media_type": "movie",
        },
    )

    assert response.status_code == 200
    assert 'id="search-run-cache"' in response.text
    assert 'data-search-card="primary"' in response.text
    assert 'data-search-row="primary"' in response.text
    assert 'data-search-view-mode' in response.text
    assert 'data-search-sort-field="1"' in response.text
    assert 'data-filter-impact-list="primary"' in response.text
    assert 'data-search-filtered-count="primary"' in response.text
    assert 'data-search-fetched-count="primary"' in response.text
    assert "data-search-category-scope-status" in response.text


def test_search_page_persists_indexer_category_catalog_entries(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Classic Audio"],
            raw_results=[
                JackettSearchResult(
                    title="Classic Audio Collection",
                    link="magnet:?xt=urn:btih:AUDIO111",
                    indexer="rutracker",
                    category_ids=["101279"],
                    category_labels=["Audiobooks"],
                )
            ],
            results=[
                JackettSearchResult(
                    title="Classic Audio Collection",
                    link="magnet:?xt=urn:btih:AUDIO111",
                    indexer="rutracker",
                    category_ids=["101279"],
                    category_labels=["Audiobooks"],
                )
            ],
        )

    def fake_configured_indexer_labels(self):
        return {"rutracker": {"101279": ["Audiobooks", "Audio/Audiobooks"]}}

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", fake_configured_indexer_labels)

    response = app_client.get(
        "/search",
        params={
            "query": "Classic Audio",
            "media_type": "audiobook",
        },
    )

    assert response.status_code == 200
    row = db_session.get(IndexerCategoryCatalog, ("rutracker", "101279"))
    assert row is not None
    assert row.category_name == "Audiobooks"
    assert row.source == "indexer_caps"


def test_search_page_resolves_colliding_category_ids_per_indexer(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Classic"],
            raw_results=[
                JackettSearchResult(
                    title="Classic RU",
                    link="magnet:?xt=urn:btih:RU001",
                    indexer="rutracker",
                    category_ids=["5000"],
                    category_labels=[],
                ),
                JackettSearchResult(
                    title="Classic EN",
                    link="magnet:?xt=urn:btih:EN001",
                    indexer="booktracker",
                    category_ids=["5000"],
                    category_labels=[],
                ),
            ],
            results=[
                JackettSearchResult(
                    title="Classic RU",
                    link="magnet:?xt=urn:btih:RU001",
                    indexer="rutracker",
                    category_ids=["5000"],
                    category_labels=[],
                ),
                JackettSearchResult(
                    title="Classic EN",
                    link="magnet:?xt=urn:btih:EN001",
                    indexer="booktracker",
                    category_ids=["5000"],
                    category_labels=[],
                ),
            ],
        )

    def fake_configured_indexer_labels(self):
        return {
            "rutracker": {"5000": ["TV"]},
            "booktracker": {"5000": ["Books"]},
        }

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", fake_configured_indexer_labels)

    response = app_client.get(
        "/search",
        params={
            "query": "Classic",
            "media_type": "series",
        },
    )

    assert response.status_code == 200
    rutracker_row = db_session.get(IndexerCategoryCatalog, ("rutracker", "5000"))
    booktracker_row = db_session.get(IndexerCategoryCatalog, ("booktracker", "5000"))
    assert rutracker_row is not None
    assert booktracker_row is not None
    assert rutracker_row.category_name == "TV"
    assert booktracker_row.category_name == "Books"


def test_search_page_uses_saved_result_view_defaults(app_client, db_session, monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        search_result_view_mode="cards",
        search_sort_criteria=[
            {"field": "seeders", "direction": "desc"},
            {"field": "title", "direction": "asc"},
        ],
    )
    db_session.add(settings)
    db_session.commit()

    def fake_search(self, payload):
        return JackettSearchRun(query_variants=["Dune Part Two"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Dune Part Two",
            "media_type": "movie",
        },
    )

    assert response.status_code == 200
    assert 'data-default-view-mode="cards"' in response.text
    assert '"field": "seeders"' in response.text


def test_search_page_auto_enforces_imdb_and_renders_fallback_section(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "Ghosts"
        assert payload.imdb_id == "tt11379026"
        assert payload.imdb_id_only is True
        assert payload.release_year == "2025"
        assert payload.keywords_any == ["full hd", "1080p"]
        return JackettSearchRun(
            query_variants=["Ghosts"],
            request_variants=["t=tvsearch imdbid=tt11379026 cat=5000"],
            results=[],
            fallback_request_variants=[
                't=tvsearch q="Ghosts full hd" cat=5000'
            ],
            fallback_results=[
                JackettSearchResult(
                    title="Ghosts S03E01 1080p",
                    link="magnet:?xt=urn:btih:GHOSTS123",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Ghosts",
            "media_type": "series",
            "imdb_id": "tt11379026",
            "release_year": "2025",
            "keywords_any": "full hd, 1080p",
        },
    )

    assert response.status_code == 200
    assert "Require IMDb ID" not in response.text
    assert "IMDb-first results" in response.text
    assert "No IMDb-first matches" in response.text
    assert "Title fallback" in response.text
    assert "IMDb-enforced Jackett lookup" in response.text
    assert "t=tvsearch imdbid=tt11379026 cat=5000" in response.text
    assert "Ghosts full hd" in response.text
    assert "Fallback Requests" in response.text
    assert "Ghosts S03E01 1080p" in response.text


def test_search_page_renders_result_view_panels_for_primary_and_fallback(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Ghosts"],
            request_variants=["t=tvsearch imdbid=tt11379026 cat=5000"],
            results=[
                JackettSearchResult(
                    title="Ghosts S03E01 1080p",
                    link="magnet:?xt=urn:btih:GHOSTS111",
                )
            ],
            fallback_request_variants=['t=tvsearch q="Ghosts" cat=5000'],
            fallback_results=[
                JackettSearchResult(
                    title="Ghosts S03E01 720p",
                    link="magnet:?xt=urn:btih:GHOSTS222",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Ghosts",
            "media_type": "series",
            "imdb_id": "tt11379026",
        },
    )

    assert response.status_code == 200
    assert response.text.count('data-search-controls') == 2
    assert response.text.count('data-search-save-defaults') == 2


def test_search_page_hides_primary_filter_impact_when_imdb_first_fetch_is_zero(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Ghosts"],
            request_variants=["t=tvsearch imdbid=tt11379026 cat=5000"],
            results=[],
            fallback_request_variants=['t=tvsearch q="Ghosts" cat=5000'],
            fallback_results=[
                JackettSearchResult(
                    title="Ghosts S03E01 1080p",
                    link="magnet:?xt=urn:btih:GHOSTS123",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Ghosts",
            "media_type": "series",
            "imdb_id": "tt11379026",
        },
    )

    assert response.status_code == 200
    assert "<p class=\"eyebrow\">Query string</p>" in response.text
    assert 'data-filter-impact-list="primary"' not in response.text
    assert 'data-filter-impact-list="fallback"' in response.text


def test_search_page_skips_release_year_when_toggle_is_unchecked(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "Ghosts"
        assert payload.release_year is None
        return JackettSearchRun(query_variants=["Ghosts"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Ghosts",
            "media_type": "series",
            "release_year": "2025",
            "include_release_year": "0",
        },
    )

    assert response.status_code == 200


def test_search_page_hides_availability_columns_when_metrics_absent(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Dune Part Two"],
            raw_results=[
                JackettSearchResult(
                    title="Dune Part Two 2160p",
                    link="magnet:?xt=urn:btih:DUNE123",
                )
            ],
            results=[
                JackettSearchResult(
                    title="Dune Part Two 2160p",
                    link="magnet:?xt=urn:btih:DUNE123",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Dune Part Two",
            "media_type": "movie",
        },
    )

    assert response.status_code == 200
    assert "<th>Peers (all)</th>" not in response.text
    assert "<th>Leechers</th>" not in response.text
    assert "<th>Grabs</th>" not in response.text
    assert "Unknown indexer" in response.text


def test_search_page_parses_pipe_delimited_any_keyword_groups(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "The Rip"
        assert payload.release_year == "2026"
        assert payload.keywords_any_groups == [["uhd", "4k", "ultra hd"], ["hdr", "hdr10"]]
        assert payload.keywords_any == ["uhd", "4k", "ultra hd", "hdr", "hdr10"]
        return JackettSearchRun(
            query_variants=["The Rip"],
            results=[
                JackettSearchResult(
                    title="The Rip (2026) 4K HDR10",
                    link="magnet:?xt=urn:btih:THERIP123",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "The Rip",
            "media_type": "movie",
            "release_year": "2026",
            "keywords_any": "uhd, 4k, ultra hd | hdr, hdr10",
        },
    )

    assert response.status_code == 200
    assert "The Rip (2026) 4K HDR10" in response.text


def test_search_page_expands_quality_token_terms_for_search_payload(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "The Rip"
        assert payload.keywords_any_groups == [["hevc", "x265", "h265"]]
        assert payload.keywords_any == ["hevc", "x265", "h265"]
        assert "tv sync" in payload.keywords_not
        assert "tele sync" in payload.keywords_not
        assert "telesync" in payload.keywords_not
        return JackettSearchRun(
            query_variants=["The Rip"],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "The Rip",
            "media_type": "movie",
            "quality_include_tokens": ["hevc"],
            "quality_exclude_tokens": ["tv_sync"],
        },
    )

    assert response.status_code == 200
    assert "data-quality-search-terms=" in response.text
    assert "data-quality-pattern-map=" in response.text
    assert 'id="search-pattern-preview"' in response.text
    assert "Extra include keywords" in response.text
    assert "mustNotContain" in response.text


def test_search_page_groups_quality_include_tokens_by_quality_group(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "3 Body Problem"
        assert payload.keywords_any_groups == [["4k"], ["hdr", "hdr10"]]
        assert payload.keywords_any == ["4k", "hdr", "hdr10"]
        return JackettSearchRun(
            query_variants=["3 Body Problem"],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "3 Body Problem",
            "media_type": "series",
            "quality_include_tokens": ["4k", "hdr"],
        },
    )

    assert response.status_code == 200


def test_search_page_accepts_legacy_free_text_filter_query_params(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "Legacy Search"
        assert payload.keywords_all == ["remux", "2026"]
        assert payload.keywords_not == ["cam", "ts"]
        return JackettSearchRun(query_variants=["Legacy Search"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Legacy Search",
            "media_type": "movie",
            "keywords_all": "remux, 2026",
            "keywords_not": "cam, ts",
        },
    )

    assert response.status_code == 200
    assert 'textarea name="additional_includes"' in response.text
    assert 'textarea name="must_not_contain"' in response.text


def test_search_page_accepts_repeated_multiselect_filter_params(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.query == "The Rip"
        assert payload.filter_indexers == ["alpha", "beta"]
        assert payload.filter_category_ids == ["tv hd", "audiobooks"]
        return JackettSearchRun(query_variants=["The Rip"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params=[
            ("query", "The Rip"),
            ("media_type", "movie"),
            ("filter_indexers", "alpha"),
            ("filter_indexers", "beta"),
            ("filter_category_ids", "tv hd"),
            ("filter_category_ids", "audiobooks"),
        ],
    )

    assert response.status_code == 200
    assert 'data-search-multiselect="indexers"' in response.text
    assert 'data-search-multiselect="categories"' in response.text


def test_search_page_prefers_include_token_when_quality_token_lists_conflict(
    app_client,
    monkeypatch,
) -> None:
    def fake_search(self, payload):
        assert payload.query == "The Rip"
        assert payload.keywords_any_groups == [["sd"]]
        assert payload.keywords_any == ["sd"]
        assert "sd" not in payload.keywords_not
        return JackettSearchRun(
            query_variants=["The Rip"],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "The Rip",
            "media_type": "movie",
            "quality_include_tokens": ["sd"],
            "quality_exclude_tokens": ["sd"],
        },
    )

    assert response.status_code == 200
    assert "data-quality-search-terms=" in response.text


def test_search_page_renders_search_warnings(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["American Classic uhd"],
            request_variants=['t=tvsearch q="American Classic uhd" cat=5000'],
            warning_messages=[
                'Jackett request failed after 3 timeout attempts for t=tvsearch q="American Classic uhd" year=2025 cat=5000: timed out'
            ],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "American Classic",
            "media_type": "series",
            "release_year": "2025",
            "keywords_any": "uhd",
        },
    )

    assert response.status_code == 200
    assert "Jackett request failed after 3 timeout attempts for" in response.text
    assert "American Classic uhd" in response.text
    assert "No IMDb-first matches" not in response.text


def test_search_page_from_rule_uses_structured_terms_not_raw_regex(app_client, db_session, monkeypatch) -> None:
    rule = Rule(
        rule_name="Andrew Michael Blues Band",
        content_name="Andrew Michael Blues Band",
        normalized_title="Andrew Michael Blues Band",
        imdb_id="tt7654321",
        media_type=MediaType.MUSIC,
        quality_profile=QualityProfile.CUSTOM,
        include_release_year=True,
        release_year="2026",
        additional_includes="2026",
        quality_include_tokens=["mp3"],
        quality_exclude_tokens=["flac"],
        must_contain_override=r"(?i)(?=.*andrew[\s._-]*michael)(?=.*mp3)",
        feed_urls=[
            "http://jackett:9117/api/v2.0/indexers/musictracker/results/torznab/api?apikey=abc&t=search&cat=3000"
        ],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.query == "Andrew Michael Blues Band"
        assert payload.indexer == "musictracker"
        assert payload.filter_indexers == ["musictracker"]
        assert payload.imdb_id == "tt7654321"
        assert payload.release_year == "2026"
        assert payload.keywords_all == ["2026"]
        assert payload.keywords_any == ["mp3"]
        assert "flac" in payload.keywords_not
        return JackettSearchRun(
            query_variants=["Andrew Michael Blues Band 2026 mp3"],
            results=[
                JackettSearchResult(
                    title="Andrew Michael Blues Band (2026) MP3",
                    link="magnet:?xt=urn:btih:AAA111",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "Derived from rule: Andrew Michael Blues Band" in response.text
    assert "Raw regex was intentionally not sent to Jackett." in response.text
    assert "Andrew Michael Blues Band 2026 mp3" in response.text
    assert "Andrew Michael Blues Band (2026) MP3" in response.text
    assert "additional_includes=2026" in response.text


def test_search_page_from_rule_prefills_local_free_text_from_literal_rule_fields(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Free Text Parity",
        content_name="Free Text Parity",
        normalized_title="Free Text Parity",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.CUSTOM,
        additional_includes="remux",
        quality_include_tokens=["hevc"],
        quality_exclude_tokens=["tv_sync"],
        must_not_contain="cam",
        feed_urls=["http://feed.example/parity"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.query == "Free Text Parity"
        assert payload.keywords_all == ["remux"]
        assert "cam" in payload.keywords_not
        assert "tv sync" in payload.keywords_not
        return JackettSearchRun(query_variants=["Free Text Parity"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    include_match = re.search(
        r'<textarea name="additional_includes"[^>]*>(.*?)</textarea>',
        response.text,
        re.DOTALL,
    )
    exclude_match = re.search(
        r'<textarea name="must_not_contain"[^>]*>(.*?)</textarea>',
        response.text,
        re.DOTALL,
    )
    keywords_any_match = re.search(
        r'<input type="text" name="keywords_any" value="([^"]*)"',
        response.text,
    )
    assert include_match is not None
    assert exclude_match is not None
    assert keywords_any_match is not None
    assert include_match.group(1).strip() == "remux"
    assert exclude_match.group(1).strip() == "cam"
    assert keywords_any_match.group(1).strip() == ""


def test_search_page_from_rule_skips_release_year_when_not_enabled(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Ghosts Rule",
        content_name="Ghosts",
        normalized_title="Ghosts",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        include_release_year=False,
        release_year="2025",
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.query == "Ghosts"
        assert payload.release_year is None
        return JackettSearchRun(query_variants=["Ghosts"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "Derived from rule: Ghosts Rule" in response.text


def test_search_page_falls_back_to_title_when_rule_derivation_validation_fails(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Rule Fallback",
        content_name="Rule Fallback",
        normalized_title="Rule Fallback",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        additional_includes="2026",
        quality_include_tokens=["mp3"],
        quality_exclude_tokens=["flac"],
        feed_urls=["http://feed.example/fallback"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_build(rule):
        return (
            JackettSearchRequest(
                query="fallback",
                keywords_not=[str(index) for index in range(49)],
            ),
            True,
        )

    def fake_reduced_build(rule):
        return (
            JackettSearchRequest(
                query="Rule Fallback",
                keywords_all=["2026"],
                keywords_any_groups=[["mp3"]],
                keywords_not=["flac"],
            ),
            True,
        )

    def fake_search(self, payload):
        assert payload.query == "Rule Fallback"
        assert payload.keywords_all == ["2026"]
        assert payload.keywords_any == ["mp3"]
        assert payload.keywords_not == ["flac"]
        return JackettSearchRun(
            query_variants=["Rule Fallback 2026 mp3"],
            results=[],
        )

    monkeypatch.setattr("app.routes.pages.build_search_request_from_rule", fake_build)
    monkeypatch.setattr("app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "Search kept a reduced subset of inherited keywords." in response.text
    assert "Requests used" in response.text
    assert "Rule Fallback" in response.text


def test_search_page_handles_unexpected_rule_derivation_error_without_500(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Rule Crash Guard",
        content_name="Rule Crash Guard",
        normalized_title="Rule Crash Guard",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/crash-guard"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_build(rule):
        raise RuntimeError("boom")

    def fake_reduced_build(rule):
        return (
            JackettSearchRequest(
                query="Rule Crash Guard",
                keywords_all=["2026"],
            ),
            True,
        )

    def fake_search(self, payload):
        assert payload.query == "Rule Crash Guard"
        assert payload.keywords_all == ["2026"]
        return JackettSearchRun(
            query_variants=["Rule Crash Guard 2026"],
            results=[],
        )

    monkeypatch.setattr("app.routes.pages.build_search_request_from_rule", fake_build)
    monkeypatch.setattr("app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "The saved rule needed a compatibility fallback." in response.text
    assert "Rule Crash Guard 2026" in response.text


def test_search_page_uses_clamped_title_only_fallback_when_reduction_still_fails(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    long_title = "Rule Search Fallback Title " * 20
    rule = Rule(
        rule_name=long_title,
        content_name=long_title,
        normalized_title=long_title,
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/long-fallback"],
    )
    db_session.add(rule)
    db_session.commit()

    seen_queries: list[str] = []

    def fake_build(rule):
        return (
            JackettSearchRequest(
                query="fallback",
                keywords_not=[str(index) for index in range(49)],
            ),
            True,
        )

    def fake_reduced_build(rule):
        return (
            JackettSearchRequest(
                query=long_title,
                keywords_not=[str(index) for index in range(49)],
            ),
            True,
        )

    def fake_search(self, payload):
        seen_queries.append(payload.query)
        return JackettSearchRun(
            query_variants=[payload.query],
            results=[],
        )

    monkeypatch.setattr("app.routes.pages.build_search_request_from_rule", fake_build)
    monkeypatch.setattr("app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build)
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "Search fell back to the saved title only." in response.text
    assert "could not be reduced into a safe structured search" not in response.text
    assert seen_queries == [clamp_search_query_text(long_title)]
    assert len(seen_queries[0]) <= 255


def test_search_page_handles_unexpected_setup_error_without_500(app_client, monkeypatch) -> None:
    def fake_get_or_create(session):
        raise RuntimeError("settings boom")

    monkeypatch.setattr("app.routes.pages.SettingsService.get_or_create", fake_get_or_create)

    response = app_client.get("/search")

    assert response.status_code == 200
    assert "Search setup failed unexpectedly (RuntimeError): settings boom" in response.text


def test_rule_pages_expose_run_search_actions(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Search Actions",
        content_name="Rule Search Actions",
        normalized_title="Rule Search Actions",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/actions"],
    )
    db_session.add(rule)
    db_session.commit()

    index_response = app_client.get("/")
    edit_response = app_client.get(f"/rules/{rule.id}")

    assert index_response.status_code == 200
    assert f'/rules/{rule.id}/search' in index_response.text
    assert ">Run Search</a>" in index_response.text
    assert edit_response.status_code == 200
    assert f'/rules/{rule.id}/search' in edit_response.text
    assert ">Run Search Here</a>" in edit_response.text
    assert ">Advanced Search Workspace</a>" in edit_response.text


def test_edit_rule_page_can_render_inline_search_results(app_client, db_session, monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Shrinking Inline Search",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/inline"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        return JackettSearchRun(
            request_variants=['t=search q="Shrinking"'],
            results=[
                JackettSearchResult(
                    title="Shrinking S01E01",
                    link="https://example.com/shrinking.torrent",
                    indexer="example-indexer",
                    category_ids=["5000"],
                    category_labels=["TV"],
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(f"/rules/{rule.id}", params={"run_search": "1"})

    assert response.status_code == 200
    assert 'id="inline-search-results"' in response.text
    assert "Results on this page" in response.text
    assert "Shrinking S01E01" in response.text
    assert "Queue via Rule" in response.text
    assert 'data-search-table-wrap="primary"' in response.text
    assert 'data-search-sort-field="1"' in response.text
    assert 'data-search-view-mode' in response.text


def test_edit_rule_inline_search_scopes_single_jackett_feed_indexer(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Single Feed Scope",
        content_name="Single Feed Scope",
        normalized_title="Single Feed Scope",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/?apikey=abc&t=tvsearch&cat=5000"
        ],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.indexer == "rutracker"
        assert payload.filter_indexers == ["rutracker"]
        return JackettSearchRun(
            request_variants=['t=tvsearch indexer="rutracker" q="Single Feed Scope"'],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(f"/rules/{rule.id}", params={"run_search": "1"})

    assert response.status_code == 200
    assert "Search scoped to affected feed indexer: rutracker." in response.text


def test_edit_rule_inline_search_uses_feed_url_override_scope(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Override Feed Scope",
        content_name="Override Feed Scope",
        normalized_title="Override Feed Scope",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://jackett:9117/api/v2.0/indexers/thepiratebay/results/torznab/api?apikey=abc&t=tvsearch&cat=5000",
            "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api?apikey=abc&t=tvsearch&cat=5000",
        ],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.indexer == "rutracker"
        assert payload.filter_indexers == ["rutracker"]
        return JackettSearchRun(
            request_variants=['t=tvsearch indexer="rutracker" q="Override Feed Scope"'],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(
        f"/rules/{rule.id}",
        params=[
            ("run_search", "1"),
            ("feed_scope_override", "1"),
            (
                "feed_urls",
                "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api?apikey=abc&t=tvsearch&cat=5000",
            ),
        ],
    )

    assert response.status_code == 200
    assert "Inline search used current affected-feed selection from the form (not yet saved)." in response.text
    assert "Search scoped to affected feed indexer: rutracker." in response.text


def test_edit_rule_inline_search_scopes_multiple_jackett_feed_indexers(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Multi Feed Scope",
        content_name="Multi Feed Scope",
        normalized_title="Multi Feed Scope",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[
            "http://jackett:9117/api/v2.0/indexers/alpha/results/torznab/api?apikey=abc&t=tvsearch&cat=5000",
            "http://jackett:9117/api/v2.0/indexers/beta/results/torznab/api?apikey=abc&t=tvsearch&cat=5000",
        ],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.indexer == "all"
        assert payload.filter_indexers == ["alpha", "beta"]
        return JackettSearchRun(
            request_variants=['t=tvsearch indexer="all" q="Multi Feed Scope"'],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(f"/rules/{rule.id}", params={"run_search": "1"})

    assert response.status_code == 200
    assert "Search scoped to affected feed indexers: alpha, beta." in response.text


def test_edit_rule_inline_search_warns_when_feed_scope_not_derivable(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Unparseable Feed Scope",
        content_name="Unparseable Feed Scope",
        normalized_title="Unparseable Feed Scope",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/not-jackett"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.indexer == "all"
        assert payload.filter_indexers == []
        return JackettSearchRun(
            request_variants=['t=tvsearch indexer="all" q="Unparseable Feed Scope"'],
            results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(f"/rules/{rule.id}", params={"run_search": "1"})

    assert response.status_code == 200
    assert "Affected feeds could not be mapped to Jackett indexers; using default indexer scope." in response.text


def test_jackett_search_api_returns_results(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        assert payload.indexer == "all"
        return JackettSearchRun(
            query_variants=["The Expanse"],
            results=[
                JackettSearchResult(
                    title="The Expanse S01",
                    link="magnet:?xt=urn:btih:DEF456",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.post(
        "/api/search/jackett",
        json={"query": "The Expanse", "media_type": "series"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_kind"] == "jackett_active_search"
    assert payload["results"][0]["title"] == "The Expanse S01"


def test_queue_search_result_api_requires_configured_qb(app_client) -> None:
    response = app_client.post(
        "/api/search/queue",
        json={"link": "https://example.com/result.torrent"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "qBittorrent connection is not configured."


def test_queue_search_result_api_uses_rule_defaults(app_client, db_session, monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        default_add_paused=True,
    )
    db_session.add(settings)
    rule = Rule(
        rule_name="Queue Rule Defaults",
        content_name="Queue Rule Defaults",
        normalized_title="Queue Rule Defaults",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/queue-rule"],
        assigned_category="Series/Shrinking [imdbid-tt15153834]",
        save_path="/data/shrinking",
        add_paused=False,
    )
    db_session.add(rule)
    db_session.commit()

    captured: dict[str, object] = {}

    def fake_add_torrent_url(
        self,
        *,
        link: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        captured.update(
            {
                "link": link,
                "category": category,
                "save_path": save_path,
                "paused": paused,
                "sequential_download": sequential_download,
                "first_last_piece_prio": first_last_piece_prio,
            }
        )

    monkeypatch.setattr("app.routes.api.QbittorrentClient.add_torrent_url", fake_add_torrent_url)

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "https://example.com/shrinking.torrent",
            "rule_id": rule.id,
            "sequential_download": True,
            "first_last_piece_prio": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["category"] == "Series/Shrinking [imdbid-tt15153834]"
    assert payload["save_path"] == "/data/shrinking"
    assert payload["add_paused"] is False
    assert payload["sequential_download"] is True
    assert payload["first_last_piece_prio"] is True
    assert captured == {
        "link": "https://example.com/shrinking.torrent",
        "category": "Series/Shrinking [imdbid-tt15153834]",
        "save_path": "/data/shrinking",
        "paused": False,
        "sequential_download": True,
        "first_last_piece_prio": True,
    }


def test_queue_search_result_api_uses_settings_default_pause_when_no_rule(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        default_add_paused=False,
    )
    db_session.add(settings)
    db_session.commit()

    captured: dict[str, object] = {}

    def fake_add_torrent_url(
        self,
        *,
        link: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        captured.update(
            {
                "link": link,
                "category": category,
                "save_path": save_path,
                "paused": paused,
                "sequential_download": sequential_download,
                "first_last_piece_prio": first_last_piece_prio,
            }
        )

    monkeypatch.setattr("app.routes.api.QbittorrentClient.add_torrent_url", fake_add_torrent_url)

    response = app_client.post(
        "/api/search/queue",
        json={"link": "https://example.com/no-rule.torrent"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == ""
    assert payload["save_path"] == ""
    assert payload["add_paused"] is False
    assert captured["paused"] is False


def test_save_search_preferences_api_persists_defaults(app_client, db_session) -> None:
    response = app_client.post(
        "/api/search/preferences",
        json={
            "view_mode": "cards",
            "sort_criteria": [
                {"field": "seeders", "direction": "desc"},
                {"field": "title", "direction": "asc"},
            ],
            "default_sequential_download": True,
            "default_first_last_piece_prio": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["view_mode"] == "cards"
    assert response.json()["sort_criteria"] == [
        {"field": "seeders", "direction": "desc"},
        {"field": "title", "direction": "asc"},
    ]
    assert response.json()["default_sequential_download"] is True
    assert response.json()["default_first_last_piece_prio"] is True
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.search_result_view_mode == "cards"
    assert settings.search_sort_criteria == [
        {"field": "seeders", "direction": "desc"},
        {"field": "title", "direction": "asc"},
    ]
    assert settings.default_sequential_download is True
    assert settings.default_first_last_piece_prio is True


def test_taxonomy_page_renders_editor(app_client) -> None:
    response = app_client.get("/taxonomy")

    assert response.status_code == 200
    assert "Inspect and edit the quality taxonomy" in response.text
    assert 'name="taxonomy_json"' in response.text


def test_apply_taxonomy_updates_source_and_records_audit(app_client, tmp_path, monkeypatch) -> None:
    payload, taxonomy_path, audit_path = _use_temp_taxonomy(tmp_path, monkeypatch)
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least HD Revised"

    response = app_client.post(
        "/api/taxonomy/apply",
        data={
            "taxonomy_json": json.dumps(payload),
            "taxonomy_change_note": "rename bundle label",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert json.loads(taxonomy_path.read_text(encoding="utf-8"))["bundles"][0]["label"] == "At Least HD Revised"
    assert "rename bundle label" in audit_path.read_text(encoding="utf-8")


def test_apply_taxonomy_allows_label_rename_when_invalid_tokens_already_exist(
    app_client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    payload, taxonomy_path, audit_path = _use_temp_taxonomy(tmp_path, monkeypatch)
    rule = Rule(
        rule_name="Rule Legacy Token",
        content_name="Rule Legacy Token",
        normalized_title="Rule Legacy Token",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        quality_include_tokens=["legacy_missing"],
        quality_exclude_tokens=[],
    )
    db_session.add(rule)
    db_session.commit()

    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"

    response = app_client.post(
        "/api/taxonomy/apply",
        data={
            "taxonomy_json": json.dumps(payload),
            "taxonomy_change_note": "rename bundle label with legacy token present",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert json.loads(taxonomy_path.read_text(encoding="utf-8"))["bundles"][0]["label"] == "At Least Full HD"
    assert "rename bundle label with legacy token present" in audit_path.read_text(encoding="utf-8")


def test_apply_taxonomy_rejects_orphaning_rule_tokens(app_client, db_session, tmp_path, monkeypatch) -> None:
    payload, taxonomy_path, audit_path = _use_temp_taxonomy(tmp_path, monkeypatch)
    rule = Rule(
        rule_name="Rule Beta",
        content_name="Rule Beta",
        normalized_title="Rule Beta",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        quality_include_tokens=["hevc"],
        quality_exclude_tokens=[],
    )
    db_session.add(rule)
    db_session.commit()

    options = payload["options"]
    aliases = payload["aliases"]
    assert isinstance(options, list)
    assert isinstance(aliases, list)
    payload["options"] = [item for item in options if item["value"] != "hevc"]
    payload["aliases"] = [item for item in aliases if item["canonical"] != "hevc"]

    response = app_client.post(
        "/api/taxonomy/apply",
        data={
            "taxonomy_json": json.dumps(payload),
            "taxonomy_change_note": "remove hevc",
        },
    )

    assert response.status_code == 400
    assert "Cannot apply a taxonomy update that would orphan persisted tokens." in response.text
    assert any(item["value"] == "hevc" for item in json.loads(taxonomy_path.read_text(encoding="utf-8"))["options"])
    assert not audit_path.exists()


def test_new_rule_uses_taxonomy_bundle_labels_for_builtin_profiles(app_client, tmp_path, monkeypatch) -> None:
    payload, taxonomy_path, _ = _use_temp_taxonomy(tmp_path, monkeypatch)
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    quality_filters._clear_quality_taxonomy_cache()

    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert ">At Least Full HD</option>" in response.text


def test_settings_uses_taxonomy_bundle_labels_for_builtin_profiles(app_client, tmp_path, monkeypatch) -> None:
    payload, taxonomy_path, _ = _use_temp_taxonomy(tmp_path, monkeypatch)
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    quality_filters._clear_quality_taxonomy_cache()

    response = app_client.get("/settings")

    assert response.status_code == 200
    assert "<legend>At Least Full HD include</legend>" in response.text


def test_new_rule_uses_ultra_hd_hdr_defaults(app_client) -> None:
    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'name="quality_profile" value="2160p_hdr"' in response.text
    assert 'option value="builtin-ultra-hd-hdr" selected' in response.text
    assert 'option value="builtin-music-lossless"' not in response.text
    assert 'id="metadata-lookup-provider"' in response.text
    assert ">OMDb (Video)</option>" in response.text
    assert 'data-quality-token="ultra_hd"' in response.text
    assert 'data-quality-token="hdr"' in response.text


def test_metadata_lookup_accepts_legacy_imdb_payload(app_client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_lookup(self, provider, lookup_value, media_type):
        captured["provider"] = str(provider)
        captured["lookup_value"] = lookup_value
        captured["media_type"] = media_type.value
        return MetadataResult(
            title="3 Body Problem",
            provider=MetadataLookupProvider.OMDB,
            imdb_id="tt13016388",
            source_id="tt13016388",
            media_type=MediaType.SERIES,
            year="2024",
        )

    monkeypatch.setattr(MetadataClient, "lookup", fake_lookup)

    response = app_client.post(
        "/api/metadata/lookup",
        json={"imdb_id": "tt13016388"},
    )

    assert response.status_code == 200
    assert captured == {
        "provider": "MetadataLookupProvider.OMDB",
        "lookup_value": "tt13016388",
        "media_type": "series",
    }
    assert response.json()["imdb_id"] == "tt13016388"


def test_metadata_lookup_accepts_provider_and_title_payload(app_client, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_lookup(self, provider, lookup_value, media_type):
        captured["provider"] = str(provider)
        captured["lookup_value"] = lookup_value
        captured["media_type"] = media_type.value
        return MetadataResult(
            title="Kind of Blue",
            provider=MetadataLookupProvider.MUSICBRAINZ,
            source_id="f5093c06-23e3-404f-aeaa-40f72885ee3a",
            media_type=MediaType.MUSIC,
            year="1959",
        )

    monkeypatch.setattr(MetadataClient, "lookup", fake_lookup)

    response = app_client.post(
        "/api/metadata/lookup",
        json={
            "provider": "musicbrainz",
            "lookup_value": "Kind of Blue",
            "media_type": "music",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "provider": "MetadataLookupProvider.MUSICBRAINZ",
        "lookup_value": "Kind of Blue",
        "media_type": "music",
    }
    assert response.json()["provider"] == "musicbrainz"


def test_create_rule_persists_locally_even_without_qb_config(app_client, db_session) -> None:
    response = app_client.post(
        "/api/rules",
        data={
            "rule_name": "Rule Alpha",
            "content_name": "Rule Alpha",
            "normalized_title": "Rule Alpha",
            "imdb_id": "tt1234567",
            "media_type": "series",
            "quality_profile": "plain",
            "release_year": "2024",
            "include_release_year": "on",
            "additional_includes": "remux",
            "quality_include_tokens": ["2160p", "4k"],
            "quality_exclude_tokens": ["1080p", "720p"],
            "start_season": "3",
            "start_episode": "7",
            "enabled": "on",
            "add_paused": "on",
            "feed_urls": ["http://feed.example/alpha"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    rule = db_session.scalar(select(Rule).where(Rule.rule_name == "Rule Alpha"))
    assert rule is not None
    assert rule.release_year == "2024"
    assert rule.include_release_year is True
    assert rule.additional_includes == "remux"
    assert rule.quality_include_tokens == ["2160p", "4k"]
    assert rule.quality_exclude_tokens == ["1080p", "720p"]
    assert rule.start_season == 3
    assert rule.start_episode == 7
    assert rule.last_sync_status == SyncStatus.ERROR


def test_create_rule_rejects_incomplete_episode_progress_floor(app_client) -> None:
    response = app_client.post(
        "/api/rules",
        data={
            "rule_name": "Rule Floor Validation",
            "content_name": "Rule Floor Validation",
            "normalized_title": "Rule Floor Validation",
            "media_type": "series",
            "quality_profile": "plain",
            "start_season": "3",
            "feed_urls": ["http://feed.example/alpha"],
        },
    )

    assert response.status_code == 400
    assert "Set both Start Season and Start Episode, or leave both empty." in response.text


def test_import_preview_renders_summary_table(app_client) -> None:
    fixture_path = Path("tests/fixtures/qb_rules_export.json")

    with fixture_path.open("rb") as handle:
        response = app_client.post(
            "/api/import/qb-json",
            data={"mode": "skip", "preview_only": "1"},
            files={"rules_file": (fixture_path.name, handle, "application/json")},
        )

    assert response.status_code == 200
    assert "Preview" in response.text
    assert "3 Body Problem" in response.text


def test_save_settings_persists_profile_management_tokens(app_client, db_session) -> None:
    response = app_client.post(
        "/api/settings",
        data={
            "jackett_api_url": "http://jackett:9117",
            "jackett_qb_url": "http://docker-host:9117",
            "jackett_api_key": "secret-key",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
            "profile_1080p_include_tokens": ["full_hd", "1080p"],
            "profile_1080p_exclude_tokens": ["360p"],
            "profile_2160p_hdr_include_tokens": ["ultra_hd", "2160p"],
            "profile_2160p_hdr_exclude_tokens": ["bdremux", "ts"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.jackett_api_url == "http://jackett:9117"
    assert settings.jackett_qb_url == "http://docker-host:9117"
    assert settings.jackett_api_key_encrypted is not None
    assert settings.default_quality_profile.value == "2160p_hdr"
    assert settings.default_sequential_download is True
    assert settings.default_first_last_piece_prio is True
    assert settings.quality_profile_rules["1080p"]["include_tokens"] == ["full_hd", "1080p"]
    assert settings.quality_profile_rules["1080p"]["exclude_tokens"] == ["360p"]
    assert settings.quality_profile_rules["2160p_hdr"]["include_tokens"] == ["ultra_hd", "2160p"]
    assert settings.quality_profile_rules["2160p_hdr"]["exclude_tokens"] == ["bdremux", "ts"]


def test_save_filter_profile_creates_custom_profile(app_client, db_session) -> None:
    response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "create",
            "profile_name": "HEVC Web Only",
            "media_type": "series",
            "include_tokens": ["hevc", "web_dl"],
            "exclude_tokens": ["bluray", "bdremux"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_key"] == "hevc-web-only"
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.saved_quality_profiles["hevc-web-only"]["label"] == "HEVC Web Only"
    assert settings.saved_quality_profiles["hevc-web-only"]["include_tokens"] == ["hevc", "web_dl"]
    assert settings.saved_quality_profiles["hevc-web-only"]["exclude_tokens"] == ["bluray", "bdremux"]
    assert settings.saved_quality_profiles["hevc-web-only"]["media_types"] == ["series"]

    overwrite_response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "overwrite",
            "target_key": "hevc-web-only",
            "media_type": "movie",
            "include_tokens": ["hevc"],
            "exclude_tokens": ["bluray"],
        },
    )

    assert overwrite_response.status_code == 200
    db_session.refresh(settings)
    assert settings.saved_quality_profiles["hevc-web-only"]["include_tokens"] == ["hevc"]
    assert settings.saved_quality_profiles["hevc-web-only"]["exclude_tokens"] == ["bluray"]
    assert settings.saved_quality_profiles["hevc-web-only"]["media_types"] == ["movie"]


def test_overwrite_filter_profile_updates_builtin_at_least_hd(app_client, db_session) -> None:
    response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "overwrite",
            "target_key": "builtin-at-least-hd",
            "media_type": "series",
            "include_tokens": ["full_hd", "1080p", "2160p", "4k"],
            "exclude_tokens": ["480p", "360p", "sd"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_key"] == "builtin-at-least-hd"
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.quality_profile_rules["1080p"]["include_tokens"] == ["full_hd", "1080p", "2160p", "4k"]
    assert settings.quality_profile_rules["1080p"]["exclude_tokens"] == ["480p", "360p", "sd"]


def test_overwrite_filter_profile_updates_builtin_at_least_uhd(app_client, db_session) -> None:
    response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "overwrite",
            "target_key": "builtin-at-least-uhd",
            "media_type": "movie",
            "include_tokens": ["ultra_hd", "uhd", "2160p", "4k"],
            "exclude_tokens": ["1080p", "720p", "480p", "360p", "sd", "bdremux"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_key"] == "builtin-at-least-uhd"
    assert [profile["key"] for profile in payload["profiles"]].count("builtin-at-least-uhd") == 1
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.saved_quality_profiles["builtin-at-least-uhd"]["include_tokens"] == [
        "ultra_hd",
        "uhd",
        "2160p",
        "4k",
    ]
    assert settings.saved_quality_profiles["builtin-at-least-uhd"]["exclude_tokens"] == [
        "1080p",
        "720p",
        "480p",
        "360p",
        "sd",
        "bdremux",
    ]
    assert settings.saved_quality_profiles["builtin-at-least-uhd"]["media_types"] == ["series", "movie"]


def test_new_rule_prefills_remembered_default_feeds(app_client, db_session) -> None:
    settings = AppSettings(id="default")
    settings.default_feed_urls = ["http://feed.example/remembered"]
    db_session.add(settings)
    db_session.commit()

    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'type="checkbox" name="feed_urls" value="http://feed.example/remembered" checked' in response.text
    assert 'name="remember_feed_defaults" value="on" checked' in response.text


def test_create_rule_can_remember_selected_feeds_as_defaults(app_client, db_session) -> None:
    response = app_client.post(
        "/api/rules",
        data={
            "rule_name": "Rule With Feed Defaults",
            "content_name": "Rule With Feed Defaults",
            "normalized_title": "Rule With Feed Defaults",
            "imdb_id": "tt7654321",
            "media_type": "series",
            "quality_profile": "plain",
            "enabled": "on",
            "add_paused": "on",
            "feed_urls": ["http://feed.example/alpha", "http://feed.example/bravo"],
            "remember_feed_defaults": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.default_feed_urls == ["http://feed.example/alpha", "http://feed.example/bravo"]


def test_edit_rule_defaults_to_remembering_selected_feeds(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Remember Toggle",
        content_name="Rule Remember Toggle",
        normalized_title="Rule Remember Toggle",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/original"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(f"/rules/{rule.id}")

    assert response.status_code == 200
    assert 'name="remember_feed_defaults" value="on" checked' in response.text


def test_update_rule_can_remember_selected_feeds_as_defaults(app_client, db_session) -> None:
    settings = AppSettings(id="default")
    settings.default_feed_urls = ["http://feed.example/original-default"]
    db_session.add(settings)

    rule = Rule(
        rule_name="Rule Update Feed Defaults",
        content_name="Rule Update Feed Defaults",
        normalized_title="Rule Update Feed Defaults",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/original"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.post(
        f"/api/rules/{rule.id}",
        data={
            "rule_name": "Rule Update Feed Defaults",
            "content_name": "Rule Update Feed Defaults",
            "normalized_title": "Rule Update Feed Defaults",
            "imdb_id": "tt8765432",
            "media_type": "series",
            "quality_profile": "plain",
            "enabled": "on",
            "add_paused": "on",
            "feed_urls": ["http://feed.example/alpha", "http://feed.example/bravo"],
            "remember_feed_defaults": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    refreshed_settings = db_session.get(AppSettings, "default")
    assert refreshed_settings is not None
    assert refreshed_settings.default_feed_urls == ["http://feed.example/alpha", "http://feed.example/bravo"]


def test_rule_form_includes_bulk_feed_selection_controls(app_client) -> None:
    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'id="feed-select-all"' in response.text
    assert 'id="feed-clear-all"' in response.text
    assert 'id="feed-options"' in response.text
    assert 'id="feed-select"' not in response.text


def test_edit_rule_renders_saved_feeds_as_checked_checkboxes(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Saved Feed",
        content_name="Rule Saved Feed",
        normalized_title="Rule Saved Feed",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/saved"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(f"/rules/{rule.id}")

    assert response.status_code == 200
    assert 'type="checkbox" name="feed_urls" value="http://feed.example/saved" checked' in response.text
