from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
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


def test_run_rule_search_route_redirects_to_search(app_client, db_session) -> None:
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
    assert response.headers["location"] == f"/search?rule_id={rule.id}"


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
        feed_urls=["http://feed.example/music"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.query == "Andrew Michael Blues Band"
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
    assert ">Run Search</a>" in edit_response.text


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


def test_save_search_preferences_api_persists_defaults(app_client, db_session) -> None:
    response = app_client.post(
        "/api/search/preferences",
        json={
            "view_mode": "cards",
            "sort_criteria": [
                {"field": "seeders", "direction": "desc"},
                {"field": "title", "direction": "asc"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["view_mode"] == "cards"
    assert response.json()["sort_criteria"] == [
        {"field": "seeders", "direction": "desc"},
        {"field": "title", "direction": "asc"},
    ]
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.search_result_view_mode == "cards"
    assert settings.search_sort_criteria == [
        {"field": "seeders", "direction": "desc"},
        {"field": "title", "direction": "asc"},
    ]


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
    assert 'name="quality_include_tokens" value="ultra_hd" checked' in response.text
    assert 'name="quality_include_tokens" value="hdr" checked' in response.text


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
    assert rule.last_sync_status == SyncStatus.ERROR


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
