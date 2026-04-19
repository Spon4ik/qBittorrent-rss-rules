from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.config import obfuscate_secret, reveal_secret
from app.main import DESKTOP_BACKEND_CAPABILITIES, DESKTOP_BACKEND_CONTRACT
from app.models import (
    AppSettings,
    IndexerCategoryCatalog,
    MediaType,
    QualityProfile,
    Rule,
    RuleSearchSnapshot,
    SyncStatus,
)
from app.routes.pages import _auto_imdb_first_payload
from app.schemas import (
    JackettSearchRequest,
    JackettSearchResult,
    JackettSearchRun,
    MetadataLookupProvider,
    MetadataResult,
)
from app.services import quality_filters
from app.services.hover_debug import clear_hover_events
from app.services.jackett import JackettClient, clamp_search_query_text
from app.services.metadata import MetadataClient
from app.services.selective_queue import ParsedTorrentInfo
from tests.jellyfin_test_utils import (
    add_jellyfin_episode,
    add_jellyfin_series,
    add_jellyfin_user,
    add_jellyfin_userdata,
    create_jellyfin_test_db,
)
from tests.stremio_test_utils import create_stremio_local_storage, stremio_library_item


def _use_temp_taxonomy(tmp_path: Path, monkeypatch):
    payload = json.loads(quality_filters.QUALITY_TAXONOMY_PATH.read_text(encoding="utf-8"))
    taxonomy_path = tmp_path / "quality_taxonomy.json"
    audit_path = tmp_path / "taxonomy_audit.jsonl"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_PATH", taxonomy_path)
    monkeypatch.setattr(quality_filters, "QUALITY_TAXONOMY_AUDIT_PATH", audit_path)
    quality_filters._clear_quality_taxonomy_cache()
    return payload, taxonomy_path, audit_path


def _install_stremio_api(
    monkeypatch,
    *,
    items: list[dict[str, object]],
    meta_items: list[list[object]] | None = None,
) -> None:
    resolved_meta = meta_items or [[item["_id"], index + 1] for index, item in enumerate(items)]

    def fake_post_api(self, endpoint, payload):
        if endpoint == "datastoreGet":
            return items
        if endpoint == "datastoreMeta":
            return resolved_meta
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr("app.services.stremio.StremioService._post_api", fake_post_api)


@pytest.fixture(autouse=True)
def clear_quality_taxonomy_cache() -> None:
    quality_filters._clear_quality_taxonomy_cache()
    yield
    quality_filters._clear_quality_taxonomy_cache()


def test_health_endpoint(app_client) -> None:
    response = app_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_version"] == "1.0.0"
    assert payload["desktop_backend_contract"] == DESKTOP_BACKEND_CONTRACT
    assert "hover_debug_telemetry" in payload["capabilities"]
    assert "search_hidden_result_diagnostics" in payload["capabilities"]
    assert list(payload["capabilities"]) == list(DESKTOP_BACKEND_CAPABILITIES)
    assert payload["static_asset_version"]


def test_debug_hover_telemetry_api_records_filters_and_clears_events(app_client) -> None:
    clear_hover_events()

    first_response = app_client.post(
        "/api/debug/hover-telemetry",
        json={
            "session_id": "session-a",
            "reason": "mouseenter",
            "row_name": "Rule A",
            "poster_rect": {"top": 120, "bottom": 300},
        },
    )
    second_response = app_client.post(
        "/api/debug/hover-telemetry",
        json={
            "session_id": "session-b",
            "reason": "mouseenter",
            "row_name": "Rule B",
            "poster_rect": {"top": 240, "bottom": 420},
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    filtered = app_client.get(
        "/api/debug/hover-telemetry", params={"session_id": "session-b", "limit": 10}
    )

    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert filtered_payload["count"] == 1
    assert filtered_payload["events"][0]["session_id"] == "session-b"
    assert filtered_payload["events"][0]["row_name"] == "Rule B"

    cleared = app_client.get(
        "/api/debug/hover-telemetry", params={"session_id": "session-b", "clear": 1}
    )

    assert cleared.status_code == 200
    cleared_payload = cleared.json()
    assert cleared_payload["cleared_count"] == 1
    assert cleared_payload["count"] == 0

    remaining = app_client.get("/api/debug/hover-telemetry", params={"limit": 10})

    assert remaining.status_code == 200
    remaining_payload = remaining.json()
    assert remaining_payload["count"] == 1
    assert remaining_payload["events"][0]["session_id"] == "session-a"


def test_rules_page_header_includes_create_rule_button(app_client) -> None:
    response = app_client.get("/")

    assert response.status_code == 200
    assert ">Create Rule</a>" in response.text


def test_rules_page_renders_release_status_from_snapshots(app_client, db_session) -> None:
    rule_with_matches = Rule(
        rule_name="Rule With Matches",
        content_name="Rule With Matches",
        normalized_title="Rule With Matches",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/matches/results/torznab/api"],
    )
    rule_without_matches = Rule(
        rule_name="Rule Without Matches",
        content_name="Rule Without Matches",
        normalized_title="Rule Without Matches",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=2,
        start_episode=1,
        feed_urls=["https://jackett.test/api/v2.0/indexers/no-matches/results/torznab/api"],
    )
    rule_without_snapshot = Rule(
        rule_name="Rule Without Snapshot",
        content_name="Rule Without Snapshot",
        normalized_title="Rule Without Snapshot",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/no-snapshot/results/torznab/api"],
    )
    db_session.add_all([rule_with_matches, rule_without_matches, rule_without_snapshot])
    db_session.flush()
    db_session.add_all(
        [
            RuleSearchSnapshot(
                rule_id=rule_with_matches.id,
                payload={"query": "Rule With Matches"},
                inline_search={
                    "raw_results": [],
                    "results": [],
                    "raw_fallback_results": [],
                    "fallback_results": [],
                    "unified_raw_results": [
                        {
                            "title": "Rule With Matches S01E01",
                            "link": "https://example.com/rule-with-matches.torrent",
                            "indexer": "matches",
                            "visible": True,
                        }
                    ],
                },
            ),
            RuleSearchSnapshot(
                rule_id=rule_without_matches.id,
                payload={"query": "Rule Without Matches"},
                inline_search={
                    "raw_results": [],
                    "results": [],
                    "raw_fallback_results": [],
                    "fallback_results": [],
                    "unified_raw_results": [
                        {
                            "title": "Rule Without Matches S01E01",
                            "link": "https://example.com/rule-without-matches.torrent",
                            "indexer": "no-matches",
                            "visible": False,
                        }
                    ],
                },
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/")

    assert response.status_code == 200
    assert "data-rules-page" in response.text
    assert "Matches found" in response.text
    assert "No matches" in response.text
    assert "No snapshot" in response.text
    assert "1 / 1" in response.text
    assert "0 / 1" in response.text


def test_rules_page_renders_exact_status_from_snapshots(app_client, db_session) -> None:
    exact_rule = Rule(
        rule_name="Exact Rule",
        content_name="Exact Rule",
        normalized_title="Exact Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/exact/results/torznab/api"],
    )
    fallback_only_rule = Rule(
        rule_name="Fallback Only Rule",
        content_name="Fallback Only Rule",
        normalized_title="Fallback Only Rule",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/fallback/results/torznab/api"],
    )
    no_exact_rule = Rule(
        rule_name="No Exact Rule",
        content_name="No Exact Rule",
        normalized_title="No Exact Rule",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/no-exact/results/torznab/api"],
    )
    unknown_rule = Rule(
        rule_name="Unknown Exact Rule",
        content_name="Unknown Exact Rule",
        normalized_title="Unknown Exact Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/unknown/results/torznab/api"],
    )
    db_session.add_all([exact_rule, fallback_only_rule, no_exact_rule, unknown_rule])
    db_session.flush()
    db_session.add_all(
        [
            RuleSearchSnapshot(
                rule_id=exact_rule.id,
                payload={"query": "Exact Rule", "imdb_id_only": True},
                inline_search={},
                release_filtered_count=4,
                release_fetched_count=9,
                exact_filtered_count=3,
                exact_fetched_count=5,
            ),
            RuleSearchSnapshot(
                rule_id=fallback_only_rule.id,
                payload={"query": "Fallback Only Rule", "imdb_id_only": True},
                inline_search={},
                release_filtered_count=2,
                release_fetched_count=8,
                exact_filtered_count=0,
                exact_fetched_count=4,
            ),
            RuleSearchSnapshot(
                rule_id=no_exact_rule.id,
                payload={"query": "No Exact Rule", "imdb_id_only": True},
                inline_search={},
                release_filtered_count=0,
                release_fetched_count=6,
                exact_filtered_count=0,
                exact_fetched_count=2,
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/")

    assert response.status_code == 200
    assert "Exact found" in response.text
    assert "Fallback only" in response.text
    assert "No exact" in response.text
    assert "3 / 5" in response.text
    assert "0 / 4" in response.text
    assert "0 / 2" in response.text


def test_rules_page_filters_by_exact_state(app_client, db_session) -> None:
    exact_rule = Rule(
        rule_name="Exact Filter Rule",
        content_name="Exact Filter Rule",
        normalized_title="Exact Filter Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/exact-filter/results/torznab/api"],
    )
    fallback_rule = Rule(
        rule_name="Fallback Filter Rule",
        content_name="Fallback Filter Rule",
        normalized_title="Fallback Filter Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/fallback-filter/results/torznab/api"],
    )
    db_session.add_all([exact_rule, fallback_rule])
    db_session.flush()
    db_session.add_all(
        [
            RuleSearchSnapshot(
                rule_id=exact_rule.id,
                payload={"query": "Exact Filter Rule", "imdb_id_only": True},
                inline_search={},
                release_filtered_count=1,
                release_fetched_count=3,
                exact_filtered_count=1,
                exact_fetched_count=2,
            ),
            RuleSearchSnapshot(
                rule_id=fallback_rule.id,
                payload={"query": "Fallback Filter Rule", "imdb_id_only": True},
                inline_search={},
                release_filtered_count=1,
                release_fetched_count=5,
                exact_filtered_count=0,
                exact_fetched_count=2,
            ),
        ]
    )
    db_session.commit()

    response = app_client.get("/?exact=exact")

    assert response.status_code == 200
    assert "Exact Filter Rule" in response.text
    assert "Fallback Filter Rule" not in response.text
    assert 'name="exact"' in response.text
    assert 'value="exact" selected' in response.text


def test_rules_page_does_not_trigger_automatic_poster_backfill(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        omdb_api_key_encrypted=obfuscate_secret("omdb-key"),
    )
    rule = Rule(
        rule_name="Posterless Rule",
        content_name="Posterless Rule",
        normalized_title="Posterless Rule",
        imdb_id="tt13016388",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/posterless"],
        poster_url=None,
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    seen_imdb_ids: list[str] = []
    def fake_lookup_by_imdb_id(self, imdb_id):
        seen_imdb_ids.append(imdb_id)
        return MetadataResult(
            title="Posterless Rule",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2024",
            poster_url="https://images.example/posterless-rule.jpg",
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)

    response = app_client.get("/")

    assert response.status_code == 200
    assert seen_imdb_ids == []
    db_session.expire_all()
    updated_rule = db_session.get(Rule, rule.id)
    assert updated_rule is not None
    assert updated_rule.poster_url is None


def test_save_rules_page_preferences_api_persists_defaults(app_client, db_session) -> None:
    response = app_client.post(
        "/api/rules/page-preferences",
        json={
            "view_mode": "cards",
            "sort_field": "release_state",
            "sort_direction": "asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["view_mode"] == "cards"
    assert payload["sort_field"] == "release_state"
    assert payload["sort_direction"] == "asc"
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.rules_page_view_mode == "cards"
    assert settings.rules_page_sort_field == "release_state"
    assert settings.rules_page_sort_direction == "asc"


def test_run_rules_fetch_api_runs_selected_rules_and_saves_snapshot(
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
    selected_rule = Rule(
        rule_name="Selected Rule",
        content_name="Selected Rule",
        normalized_title="Selected Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/selected-rule"],
    )
    other_rule = Rule(
        rule_name="Other Rule",
        content_name="Other Rule",
        normalized_title="Other Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/other-rule"],
    )
    db_session.add_all([selected_rule, other_rule])
    db_session.commit()

    seen_queries: list[str] = []

    def fake_search(self, payload):
        seen_queries.append(payload.query)
        return JackettSearchRun(
            query_variants=[payload.query],
            raw_results=[
                JackettSearchResult(
                    title=f"{payload.query} S01E01",
                    link=f"https://example.com/{payload.query}.torrent",
                )
            ],
            results=[
                JackettSearchResult(
                    title=f"{payload.query} S01E01",
                    link=f"https://example.com/{payload.query}.torrent",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.post(
        "/api/rules/fetch",
        json={
            "run_all": False,
            "rule_ids": [selected_rule.id],
            "include_disabled": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["attempted"] == 1
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0
    assert seen_queries == ["Selected Rule"]
    assert db_session.get(RuleSearchSnapshot, selected_rule.id) is not None
    assert db_session.get(RuleSearchSnapshot, other_rule.id) is None


def test_run_rules_fetch_api_returns_error_without_jackett_config(
    app_client,
    db_session,
) -> None:
    rule = Rule(
        rule_name="Rule Missing Jackett",
        content_name="Rule Missing Jackett",
        normalized_title="Rule Missing Jackett",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/missing-jackett"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.post(
        "/api/rules/fetch",
        json={
            "run_all": False,
            "rule_ids": [rule.id],
            "include_disabled": False,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert "Jackett app search is not configured" in payload["message"]


def test_rules_fetch_schedule_api_save_and_run_now(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett:9117",
        jackett_api_key_encrypted=obfuscate_secret("api-key"),
        rules_fetch_schedule_enabled=False,
    )
    rule = Rule(
        rule_name="Scheduled Rule",
        content_name="Scheduled Rule",
        normalized_title="Scheduled Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/scheduled-rule"],
    )
    db_session.add(settings)
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=[payload.query],
            raw_results=[
                JackettSearchResult(
                    title=f"{payload.query} S01E01",
                    link="https://example.com/scheduled-rule.torrent",
                )
            ],
            results=[
                JackettSearchResult(
                    title=f"{payload.query} S01E01",
                    link="https://example.com/scheduled-rule.torrent",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    schedule_save = app_client.post(
        "/api/rules/fetch-schedule",
        json={
            "enabled": True,
            "interval_minutes": 5,
            "scope": "enabled",
        },
    )
    assert schedule_save.status_code == 200
    schedule_payload = schedule_save.json()["schedule"]
    assert schedule_payload["enabled"] is True
    assert schedule_payload["interval_minutes"] == 5
    assert schedule_payload["scope"] == "enabled"

    run_now = app_client.post("/api/rules/fetch-schedule/run-now")
    assert run_now.status_code == 200
    run_payload = run_now.json()
    assert run_payload["attempted"] == 1
    assert run_payload["succeeded"] == 1
    assert run_payload["failed"] == 0
    db_session.expire_all()
    refreshed_settings = db_session.get(AppSettings, "default")
    assert refreshed_settings is not None
    assert refreshed_settings.rules_fetch_schedule_last_run_at is not None
    assert refreshed_settings.rules_fetch_schedule_next_run_at is not None


def test_inline_local_generated_pattern_uses_raw_title_surface() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert (
        'regexSurface: String(card.dataset.title || card.dataset.textSurface || "").trim(),'
        in app_js_source
    )
    assert "const getLocalPatternForFilters = () => {" in app_js_source
    assert (
        "if (!manualMustContainValue && (normalizedStartSeason === null || normalizedStartEpisode === null)) {"
        in app_js_source
    )
    assert (
        "generatedPatternRegex: compileGeneratedPatternRegex(getLocalPatternForFilters()),"
        in app_js_source
    )
    assert 'cleaned.includes("title fallback")' in app_js_source


def test_inline_local_generated_pattern_supports_jellyfin_existing_episode_exclusions() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert 'const episodeRangeAny = "0*\\\\d{1,2}";' in app_js_source
    assert (
        "function buildLowerEpisodeExclusionRegexFragment(startSeasonValue, startEpisodeValue) {"
        in app_js_source
    )
    assert (
        "function buildExistingEpisodeExclusionRegexFragment(existingEpisodeKeys) {"
        in app_js_source
    )
    assert "function anchorGeneratedPatternAtStart(pattern) {" in app_js_source
    assert (
        "const lowerEpisodeExclusion = buildLowerEpisodeExclusionRegexFragment(startSeason, startEpisode);"
        in app_js_source
    )
    assert 'form.dataset.jellyfinExistingEpisodeNumbers || "[]"' in app_js_source
    assert "return anchorGeneratedPatternAtStart(deriveGeneratedPattern({" in app_js_source
    assert "jellyfinSearchExistingUnseen: getJellyfinSearchExistingUnseen()," in app_js_source
    assert "jellyfinExistingEpisodeNumbers: getJellyfinExistingEpisodeNumbers()," in app_js_source


def test_inline_local_generated_pattern_rejects_zero_based_ranges_with_empty_title() -> None:
    node_executable = shutil.which("node")
    if not node_executable:
        pytest.skip("node is required for inline JS pattern validation")

    repo_root = Path(__file__).resolve().parents[1]
    app_js_path = repo_root / "app" / "static" / "app.js"
    leaked_title = "Убийство на борту (The Good Ship Murder)S3E00-07 (HD 1080p WEBRip) Полный S3"
    allowed_title = "The Good Ship Murder S03E08 1080p"
    node_script = f"""
const fs = require("fs");
const vm = require("vm");

global.document = {{
  addEventListener() {{}},
  querySelector() {{ return null; }},
  querySelectorAll() {{ return []; }},
}};
global.window = {{
  addEventListener() {{}},
  removeEventListener() {{}},
  setTimeout() {{}},
  clearTimeout() {{}},
  requestAnimationFrame() {{ return 0; }},
  cancelAnimationFrame() {{}},
  location: {{ href: "http://127.0.0.1:8000/" }},
}};
global.Event = class Event {{}};
global.CustomEvent = class CustomEvent {{}};
global.FormData = class FormData {{}};
global.URLSearchParams = URLSearchParams;
global.fetch = async () => {{ throw new Error("not used"); }};

const source = fs.readFileSync({json.dumps(str(app_js_path))}, "utf8");
vm.runInThisContext(source, {{ filename: "app/static/app.js" }});

const generated = deriveGeneratedPattern({{
  title: "",
  useRegex: true,
  startSeason: 3,
  startEpisode: 8,
  jellyfinSearchExistingUnseen: false,
  jellyfinExistingEpisodeNumbers: ["S03E01", "S03E02", "S03E03", "S03E04", "S03E05", "S03E06", "S03E07"],
}});
const local = anchorGeneratedPatternAtStart(generated);
let sourcePattern = local;
let flags = "u";
if (sourcePattern.startsWith("(?i)")) {{
  sourcePattern = sourcePattern.slice(4);
  flags = "iu";
}}
const regex = new RegExp(sourcePattern, flags);
console.log(JSON.stringify({{
  local,
  leakedMatches: regex.test({json.dumps(leaked_title)}),
  allowedMatches: regex.test({json.dumps(allowed_title)}),
}}));
"""
    completed = subprocess.run(
        [node_executable, "-e", node_script],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    payload = json.loads(completed.stdout.strip())

    assert payload["local"].startswith("(?i)^")
    assert payload["leakedMatches"] is False
    assert payload["allowedMatches"] is True


def test_inline_clear_local_filters_resets_regex_and_episode_floor_inputs() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert 'mustContainOverrideInput.value = "";' in app_js_source
    assert 'startSeasonInput.value = "";' in app_js_source
    assert 'startEpisodeInput.value = "";' in app_js_source
    assert 'kind: "manual_must_contain"' in app_js_source
    assert 'kind: "episode_progress_floor"' in app_js_source


def test_inline_rule_filter_profile_selection_updates_immediately() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert "const handleFilterProfileSelection = () => {" in app_js_source
    assert (
        'filterProfileSelect?.addEventListener("input", handleFilterProfileSelection);'
        in app_js_source
    )
    assert (
        'filterProfileSelect?.addEventListener("change", handleFilterProfileSelection);'
        in app_js_source
    )
    assert "if (element === filterProfileSelect) {" in app_js_source
    assert "refreshDerivedFields();" in app_js_source


def test_inline_feed_scope_indexer_matching_uses_key_variants() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert "function buildIndexerKeyVariants(value) {" in app_js_source
    assert "const getSelectedFeedIndexerSlugs = () => {" in app_js_source
    assert (
        "const feedScopeBlocksAll = hasFeedSelectionConstraint() && feedScopedIndexers.length === 0;"
        in app_js_source
    )
    assert "indexerVariantKeys: mergeUniqueIndexerVariantKeys(selectedIndexers)," in app_js_source
    assert (
        "feedScopedIndexerVariantKeys: mergeUniqueIndexerVariantKeys(feedScopedIndexers),"
        in app_js_source
    )
    assert 'indexerKeys: buildIndexerKeyVariants(card.dataset.indexer || ""),' in app_js_source
    assert "entry.indexerKeys.some((item) => allowedIndexerKeys.has(item))" in app_js_source
    assert "entry.indexerKeys.some((item) => allowedFeedKeys.has(item))" in app_js_source


def test_rules_page_filter_state_persists_locally_in_app_js() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert 'const FILTER_STORAGE_KEY = "qb-rules-page-filters:v1";' in app_js_source
    assert (
        'const FILTER_FIELD_NAMES = ["search", "media", "sync", "enabled", "release", "exact"];'
        in app_js_source
    )
    assert "window.localStorage.setItem(" in app_js_source
    assert 'window.sessionStorage.setItem(FILTER_RESTORE_FLAG_KEY, "1");' in app_js_source
    assert "filterForm.requestSubmit();" in app_js_source


def test_inline_local_filters_enforce_query_and_imdb_parity() -> None:
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert "const matchesQueryText = (titleSurface, queryValue) => {" in app_js_source
    assert 'const payloadImdbId = normalizeSearchImdbId(filters.imdbId || "");' in app_js_source
    assert 'const resultImdbId = normalizeSearchImdbId(entry.imdbId || "");' in app_js_source
    assert (
        "const imdbExactMatch = Boolean(payloadImdbId && resultImdbId && payloadImdbId === resultImdbId);"
        in app_js_source
    )
    assert (
        "if (!isPrecisePrimaryRow && !imdbExactMatch && !matchesQueryText(entry.titleSurface, filters.query)) {"
        in app_js_source
    )


def test_inline_local_filters_keep_precise_primary_rows_separate_from_fallback_regex_logic() -> (
    None
):
    app_js_path = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
    app_js_source = app_js_path.read_text(encoding="utf-8")

    assert "const matchesPreciseTitleIdentity = (title, queryValue) => {" in app_js_source
    assert "payloadImdbId && effectiveQuerySourceKeys(entry, filters).includes(\"primary\")" in app_js_source
    assert "const effectiveQuerySourceKeys = (entry, filters) => {" in app_js_source
    assert "if (!payloadImdbId || imdbExactMatch || matchesPreciseTitleIdentity(entry.title, filters.query)) {" in app_js_source
    assert (
        "if (!isPrecisePrimaryRow && filters.generatedPatternRegex && !filters.generatedPatternRegex.test(entry.regexSurface)) {"
        in app_js_source
    )


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
            (
                "feed_urls",
                "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api?apikey=abc",
            ),
            (
                "feed_urls",
                "http://jackett:9117/api/v2.0/indexers/kinozal/results/torznab/api?apikey=abc",
            ),
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


def test_run_rule_search_route_preserves_refresh_snapshot_flag(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Rule Search Redirect Refresh",
        content_name="Rule Search Redirect Refresh",
        normalized_title="Rule Search Redirect Refresh",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/redirect-refresh"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(
        f"/rules/{rule.id}/search",
        params={"refresh_snapshot": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/rules/{rule.id}?run_search=1&refresh_snapshot=1#inline-search-results"
    )


def test_search_page_renders_jackett_as_separate_source(app_client) -> None:
    response = app_client.get("/search")

    assert response.status_code == 200
    assert "Active Jackett search" in response.text
    assert "Not mixed with RSS feeds" in response.text
    assert "Queue Stremio Variant" not in response.text


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
    assert 'data-search-card="combined"' in response.text
    assert 'data-search-row="combined"' in response.text
    assert "data-search-view-mode" not in response.text
    assert 'data-search-table-sort-field="title"' in response.text
    assert "data-filter-impact-list=" not in response.text
    assert 'data-search-filtered-count="combined"' in response.text
    assert 'data-search-fetched-count="combined"' in response.text
    assert "data-search-category-scope-status" in response.text
    assert "data-result-links=" in response.text
    assert "data-result-info-hash=" in response.text


def test_search_page_keeps_exact_rows_ahead_of_fallback_rows(app_client, monkeypatch) -> None:
    def fake_search(self, payload):
        return JackettSearchRun(
            query_variants=["Dune Part Two"],
            raw_results=[
                JackettSearchResult(
                    merge_key="hash:exact111",
                    title="Dune Part Two Exact 2160p",
                    link="magnet:?xt=urn:btih:EXACT111",
                    info_hash="exact111",
                    indexer="rutracker",
                )
            ],
            results=[
                JackettSearchResult(
                    merge_key="hash:exact111",
                    title="Dune Part Two Exact 2160p",
                    link="magnet:?xt=urn:btih:EXACT111",
                    info_hash="exact111",
                    indexer="rutracker",
                )
            ],
            raw_fallback_results=[
                JackettSearchResult(
                    merge_key="hash:fallback222",
                    title="Dune Part Two Fallback 1080p",
                    link="magnet:?xt=urn:btih:FALLBACK222",
                    info_hash="fallback222",
                    indexer="kinozal",
                )
            ],
            fallback_results=[
                JackettSearchResult(
                    merge_key="hash:fallback222",
                    title="Dune Part Two Fallback 1080p",
                    link="magnet:?xt=urn:btih:FALLBACK222",
                    info_hash="fallback222",
                    indexer="kinozal",
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "Dune Part Two",
            "media_type": "movie",
            "imdb_id": "tt15239678",
        },
    )

    assert response.status_code == 200
    table_body = response.text.split('<tbody data-search-table-body="combined">', 1)[1].split(
        "</tbody>",
        1,
    )[0]
    assert table_body.index("Dune Part Two Exact 2160p") < table_body.index(
        "Dune Part Two Fallback 1080p"
    )


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
    monkeypatch.setattr(
        JackettClient, "configured_indexer_category_labels", fake_configured_indexer_labels
    )

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
    monkeypatch.setattr(
        JackettClient, "configured_indexer_category_labels", fake_configured_indexer_labels
    )

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


def test_search_page_auto_enforces_imdb_and_renders_unified_results_table(
    app_client, monkeypatch
) -> None:
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
            fallback_request_variants=['t=tvsearch q="Ghosts full hd" cat=5000'],
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
    assert "Unified query results" in response.text
    assert "Precise results" in response.text
    assert "Title fallback" in response.text
    assert "IMDb-enforced Jackett lookup" in response.text
    assert "t=tvsearch imdbid=tt11379026 cat=5000" in response.text
    assert "Ghosts full hd" in response.text
    assert "Ghosts S03E01 1080p" in response.text


def test_search_page_renders_single_result_view_panel_for_unified_results(
    app_client, monkeypatch
) -> None:
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
    assert response.text.count("data-search-controls") == 1
    assert response.text.count("data-search-save-defaults") == 1
    assert response.text.count("data-search-show-hidden-toggle") == 1
    assert 'data-search-scope-summary="combined"' in response.text
    assert 'data-search-hidden-summary="combined"' in response.text
    assert "data-search-visibility-status" in response.text
    assert "<th>Visibility</th>" in response.text


def test_search_page_unified_results_do_not_render_filter_impact_panels(
    app_client, monkeypatch
) -> None:
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
    assert 'data-filter-impact-list="primary"' not in response.text
    assert 'data-filter-impact-list="fallback"' not in response.text
    assert "Unified query results" in response.text


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


def test_search_page_hides_availability_columns_when_metrics_absent(
    app_client, monkeypatch
) -> None:
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


def test_search_page_expands_quality_token_terms_for_search_payload(
    app_client, monkeypatch
) -> None:
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


def test_search_page_groups_quality_include_tokens_by_quality_group(
    app_client, monkeypatch
) -> None:
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


def test_search_page_from_rule_uses_structured_terms_not_raw_regex(
    app_client, db_session, monkeypatch
) -> None:
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


def test_search_page_from_rule_carries_series_episode_floor_into_imdb_search(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        imdb_id="tt15677150",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=7,
        feed_urls=["http://feed.example/shrinking"],
    )
    db_session.add(rule)
    db_session.commit()

    def fake_search(self, payload):
        assert payload.query == "Shrinking"
        assert payload.imdb_id == "tt15677150"
        assert payload.imdb_id_only is True
        assert payload.season_number == 3
        assert payload.episode_number == 7
        assert payload.primary_keywords_any_groups == []
        return JackettSearchRun(query_variants=["Shrinking"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "series floor S03E07" in response.text
    assert "IMDb-enforced Jackett lookup" in response.text


def test_search_page_auto_derives_series_episode_floor_from_query_for_imdb_search(
    app_client,
    monkeypatch,
) -> None:
    def fake_search(self, payload):
        assert payload.query == "The Rookie S08E13"
        assert payload.imdb_id == "tt7587890"
        assert payload.imdb_id_only is True
        assert payload.season_number == 8
        assert payload.episode_number == 13
        assert payload.release_year is None
        return JackettSearchRun(query_variants=["The Rookie S08E13"], results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get(
        "/search",
        params={
            "query": "The Rookie S08E13",
            "media_type": "series",
            "imdb_id": "tt7587890",
            "release_year": "2026",
            "include_release_year": "1",
        },
    )

    assert response.status_code == 200
    assert "series floor S08E13" in response.text
    assert "IMDb-enforced Jackett lookup" in response.text
    assert 'name="release_year" value=""' in response.text


def test_search_page_uses_standard_search_for_imdb_episode_queries(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("jackett-key"),
    )
    db_session.add(settings)
    db_session.commit()

    captured_payloads: list[JackettSearchRequest] = []

    def fake_search(self, payload):
        captured_payloads.append(payload)
        return JackettSearchRun(
            query_variants=[payload.query],
            request_variants=[f't=search q="{payload.query}"'],
            raw_results=[
                JackettSearchResult(
                    merge_key="desktop-fallback-pack",
                    title="Jury Duty Company Retreat fallback pack",
                    link="magnet:?xt=urn:btih:AAA111",
                    indexer="FallbackIndexer",
                )
            ],
            results=[
                JackettSearchResult(
                    merge_key="desktop-fallback-pack",
                    title="Jury Duty Company Retreat fallback pack",
                    link="magnet:?xt=urn:btih:AAA111",
                    indexer="FallbackIndexer",
                )
            ],
            raw_fallback_results=[],
            fallback_results=[],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    response = app_client.get(
        "/search",
        params={
            "query": "Jury Duty Presents: Company Retreat S01E01",
            "media_type": "series",
            "imdb_id": "tt22074164",
        },
    )

    assert response.status_code == 200
    assert captured_payloads
    assert captured_payloads[0].imdb_id == "tt22074164"
    assert captured_payloads[0].imdb_id_only is True
    assert captured_payloads[0].season_number == 1
    assert captured_payloads[0].episode_number == 1
    assert captured_payloads[0].query == "Jury Duty Presents: Company Retreat S01E01"
    assert "Jury Duty Company Retreat fallback pack" in response.text


@pytest.mark.parametrize(
    ("query", "expected_season", "expected_episode"),
    [
        ("The Rookie S08E13", 8, 13),
        ("Death in Paradise 14x01", 14, 1),
    ],
)
def test_auto_imdb_first_payload_derives_episode_floor_from_query(
    query: str,
    expected_season: int,
    expected_episode: int,
) -> None:
    payload = JackettSearchRequest(
        query=query,
        media_type=MediaType.SERIES,
        imdb_id="tt1234567",
    )

    transformed = _auto_imdb_first_payload(payload)

    assert transformed.imdb_id_only is True
    assert transformed.season_number == expected_season
    assert transformed.episode_number == expected_episode
    assert transformed.query == query


def test_auto_imdb_first_payload_clears_release_year_for_episode_query() -> None:
    payload = JackettSearchRequest(
        query="The Rookie S08E13",
        media_type=MediaType.SERIES,
        imdb_id="tt7587890",
        release_year="2026",
    )

    transformed = _auto_imdb_first_payload(payload)

    assert transformed.imdb_id_only is True
    assert transformed.season_number == 8
    assert transformed.episode_number == 13
    assert transformed.release_year is None


def test_auto_imdb_first_payload_clears_release_year_for_explicit_series_episode_floor() -> None:
    payload = JackettSearchRequest(
        query="Jury Duty Presents: Company Retreat",
        media_type=MediaType.SERIES,
        imdb_id="tt22074164",
        season_number=1,
        episode_number=3,
        release_year="2024",
    )

    transformed = _auto_imdb_first_payload(payload)

    assert transformed.imdb_id_only is True
    assert transformed.season_number == 1
    assert transformed.episode_number == 3
    assert transformed.release_year is None


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
    monkeypatch.setattr(
        "app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build
    )
    monkeypatch.setattr(JackettClient, "search", fake_search)

    response = app_client.get("/search", params={"rule_id": rule.id})

    assert response.status_code == 200
    assert "Search kept a reduced subset of inherited keywords." in response.text
    assert "Source requests" in response.text
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
    monkeypatch.setattr(
        "app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build
    )
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
    monkeypatch.setattr(
        "app.routes.pages.build_reduced_search_request_from_rule", fake_reduced_build
    )
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
    assert f"/rules/{rule.id}/search" in index_response.text
    assert ">Run Search</a>" in index_response.text
    assert edit_response.status_code == 200
    assert f"/rules/{rule.id}/search" in edit_response.text
    assert ">Run Search Here</a>" in edit_response.text
    assert ">Refresh Search Snapshot</a>" in edit_response.text
    assert ">Advanced Search Workspace</a>" in edit_response.text


def test_edit_rule_page_can_render_inline_search_results(
    app_client, db_session, monkeypatch
) -> None:
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
    assert "rule-workspace" in response.text
    assert "rule-workspace-rail" in response.text
    assert "rule-workspace-results" in response.text
    assert "rule-form--compact" in response.text
    assert "data-initial-feed-urls=" in response.text
    assert "Shrinking S01E01" in response.text
    assert "Queue via Rule" in response.text
    assert "Advanced queue options" in response.text
    assert 'data-search-table-wrap="combined"' in response.text
    assert 'data-search-table-sort-field="title"' in response.text
    assert "data-search-view-mode" not in response.text
    assert "data-search-show-hidden-toggle" in response.text
    assert 'data-search-multiselect="indexers"' in response.text
    assert 'data-search-multiselect="categories"' in response.text
    assert 'data-search-source-summary="primary"' in response.text
    assert "data-search-source-filtered-count" in response.text
    assert 'data-search-scope-summary="combined"' in response.text
    assert 'data-search-hidden-summary="combined"' in response.text
    assert "data-search-visibility-status" in response.text
    assert "<th>Visibility</th>" in response.text
    assert 'data-query-source-key="primary"' in response.text
    assert "data-filter-impact-list=" not in response.text
    snapshot = db_session.get(RuleSearchSnapshot, rule.id)
    assert snapshot is not None
    assert snapshot.inline_search["raw_results"][0]["title"] == "Shrinking S01E01"


def test_edit_rule_page_preserves_zero_episode_floor_in_form(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Season Finale Floor Rule",
        content_name="Season Finale Floor Rule",
        normalized_title="Season Finale Floor Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=2,
        start_episode=0,
        feed_urls=["http://feed.example/season-finale-floor"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(f"/rules/{rule.id}")

    assert response.status_code == 200
    assert 'name="start_season" value="2"' in response.text
    assert 'name="start_episode" value="0"' in response.text
    assert "use `0` to catch `E00` specials when the next season begins." in response.text


def test_edit_rule_inline_search_replays_saved_snapshot_without_jackett_call(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Replay Snapshot Rule",
        content_name="Replay Snapshot Rule",
        normalized_title="Replay Snapshot Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/replay-snapshot"],
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        RuleSearchSnapshot(
            rule_id=rule.id,
            payload={"query": "Replay Snapshot Rule", "media_type": "series"},
            inline_search={
                "query": "Replay Snapshot Rule",
                "primary_label": "Rule search results",
                "request_variants": ['t=search q="Replay Snapshot Rule"'],
                "raw_results": [
                    {
                        "title": "Replay Snapshot S01E01",
                        "link": "https://example.com/replay-snapshot.torrent",
                        "indexer": "snapshot-indexer",
                        "visible": True,
                    }
                ],
                "results": [
                    {
                        "title": "Replay Snapshot S01E01",
                        "link": "https://example.com/replay-snapshot.torrent",
                    }
                ],
                "fallback_label": "",
                "fallback_request_variants": [],
                "raw_fallback_results": [],
                "fallback_results": [],
                "warning_messages": [],
                "ignored_full_regex": False,
                "show_peers_column": False,
                "show_leechers_column": False,
                "show_grabs_column": False,
            },
        )
    )
    db_session.commit()

    def fail_search(self, payload):
        raise AssertionError("Jackett search should not run when replaying a saved snapshot.")

    monkeypatch.setattr(JackettClient, "search", fail_search)

    response = app_client.get(f"/rules/{rule.id}", params={"run_search": "1"})

    assert response.status_code == 200
    assert "Replay Snapshot S01E01" in response.text
    assert "Showing saved search snapshot from" in response.text


def test_edit_rule_page_loads_saved_snapshot_by_default_and_can_clear_results(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Auto Replay Snapshot Rule",
        content_name="Auto Replay Snapshot Rule",
        normalized_title="Auto Replay Snapshot Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/auto-replay-snapshot"],
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        RuleSearchSnapshot(
            rule_id=rule.id,
            payload={"query": "Auto Replay Snapshot Rule", "media_type": "series"},
            inline_search={
                "query": "Auto Replay Snapshot Rule",
                "primary_label": "Rule search results",
                "request_variants": ['t=search q="Auto Replay Snapshot Rule"'],
                "raw_results": [
                    {
                        "title": "Auto Replay Snapshot S01E02",
                        "link": "https://example.com/auto-replay-snapshot.torrent",
                        "indexer": "snapshot-indexer",
                        "visible": True,
                    }
                ],
                "results": [
                    {
                        "title": "Auto Replay Snapshot S01E02",
                        "link": "https://example.com/auto-replay-snapshot.torrent",
                    }
                ],
                "fallback_label": "",
                "fallback_request_variants": [],
                "raw_fallback_results": [],
                "fallback_results": [],
                "warning_messages": [],
                "ignored_full_regex": False,
                "show_peers_column": False,
                "show_leechers_column": False,
                "show_grabs_column": False,
            },
        )
    )
    db_session.commit()

    def fail_search(self, payload):
        raise AssertionError("Jackett search should not run when auto-replaying a saved snapshot.")

    monkeypatch.setattr(JackettClient, "search", fail_search)

    default_response = app_client.get(f"/rules/{rule.id}")

    assert default_response.status_code == 200
    assert "Auto Replay Snapshot S01E02" in default_response.text
    assert "Showing saved search snapshot from" in default_response.text
    assert f'href="/rules/{rule.id}?clear_results=1"' in default_response.text

    cleared_response = app_client.get(f"/rules/{rule.id}", params={"clear_results": "1"})

    assert cleared_response.status_code == 200
    assert "Auto Replay Snapshot S01E02" not in cleared_response.text


def test_edit_rule_inline_search_ignores_feed_override_when_selection_matches_rule(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    feed_url = "http://jackett:9117/api/v2.0/indexers/rutracker/results/torznab/api?apikey=abc&t=tvsearch&cat=5000"
    rule = Rule(
        rule_name="Replay Snapshot With Matching Override",
        content_name="Replay Snapshot With Matching Override",
        normalized_title="Replay Snapshot With Matching Override",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=[feed_url],
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        RuleSearchSnapshot(
            rule_id=rule.id,
            payload={"query": "Replay Snapshot With Matching Override", "media_type": "series"},
            inline_search={
                "query": "Replay Snapshot With Matching Override",
                "primary_label": "Rule search results",
                "request_variants": ['t=search q="Replay Snapshot With Matching Override"'],
                "raw_results": [
                    {
                        "title": "Replay Override Snapshot S01E01",
                        "link": "https://example.com/replay-override.torrent",
                        "indexer": "snapshot-indexer",
                        "visible": True,
                    }
                ],
                "results": [
                    {
                        "title": "Replay Override Snapshot S01E01",
                        "link": "https://example.com/replay-override.torrent",
                    }
                ],
                "fallback_label": "",
                "fallback_request_variants": [],
                "raw_fallback_results": [],
                "fallback_results": [],
                "warning_messages": [],
                "ignored_full_regex": False,
                "show_peers_column": False,
                "show_leechers_column": False,
                "show_grabs_column": False,
            },
        )
    )
    db_session.commit()

    def fail_search(self, payload):
        raise AssertionError(
            "Jackett search should not run when feed override matches saved rule feeds."
        )

    monkeypatch.setattr(JackettClient, "search", fail_search)

    response = app_client.get(
        f"/rules/{rule.id}",
        params=[
            ("run_search", "1"),
            ("feed_scope_override", "1"),
            ("feed_urls", feed_url),
        ],
    )

    assert response.status_code == 200
    assert "Replay Override Snapshot S01E01" in response.text
    assert "Showing saved search snapshot from" in response.text


def test_edit_rule_inline_search_refreshes_and_persists_snapshot(
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
        rule_name="Refresh Snapshot Rule",
        content_name="Refresh Snapshot Rule",
        normalized_title="Refresh Snapshot Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/refresh-snapshot"],
    )
    db_session.add(rule)
    db_session.flush()
    db_session.add(
        RuleSearchSnapshot(
            rule_id=rule.id,
            payload={"query": "Refresh Snapshot Rule", "media_type": "series"},
            inline_search={
                "query": "Refresh Snapshot Rule",
                "primary_label": "Rule search results",
                "request_variants": ['t=search q="Refresh Snapshot Rule"'],
                "raw_results": [
                    {
                        "title": "Old Snapshot Result",
                        "link": "https://example.com/old-snapshot.torrent",
                        "visible": True,
                    }
                ],
                "results": [
                    {
                        "title": "Old Snapshot Result",
                        "link": "https://example.com/old-snapshot.torrent",
                    }
                ],
                "fallback_label": "",
                "fallback_request_variants": [],
                "raw_fallback_results": [],
                "fallback_results": [],
                "warning_messages": [],
                "ignored_full_regex": False,
                "show_peers_column": False,
                "show_leechers_column": False,
                "show_grabs_column": False,
            },
        )
    )
    db_session.commit()

    captured: dict[str, int] = {"count": 0}

    def fake_search(self, payload):
        captured["count"] += 1
        return JackettSearchRun(
            request_variants=['t=search q="Refresh Snapshot Rule"'],
            results=[
                JackettSearchResult(
                    title="New Snapshot Result",
                    link="https://example.com/new-snapshot.torrent",
                    indexer="snapshot-indexer",
                    category_ids=["5000"],
                    category_labels=["TV"],
                )
            ],
        )

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    response = app_client.get(
        f"/rules/{rule.id}",
        params={"run_search": "1", "refresh_snapshot": "1"},
    )

    assert response.status_code == 200
    assert captured["count"] == 1
    assert "New Snapshot Result" in response.text
    assert "Search snapshot refreshed from Jackett and saved for future runs." in response.text

    db_session.expire_all()
    snapshot = db_session.get(RuleSearchSnapshot, rule.id)
    assert snapshot is not None
    assert snapshot.inline_search["raw_results"][0]["title"] == "New Snapshot Result"


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
    assert (
        "Inline search used current affected-feed selection from the form (not yet saved)."
        in response.text
    )
    assert "Search scoped to affected feed indexer: rutracker." in response.text
    snapshot = db_session.get(RuleSearchSnapshot, rule.id)
    assert snapshot is not None
    assert snapshot.payload.get("filter_indexers") == ["rutracker"]


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
    assert (
        "Affected feeds could not be mapped to Jackett indexers; using default indexer scope."
        in response.text
    )


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


def test_queue_search_result_api_uploads_http_torrent_file_to_qb_instead_of_remote_url_fetch(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        jackett_api_url="http://localhost:9117",
        jackett_qb_url="http://docker-host:9117",
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    torrent_bytes = b"d4:infod4:name8:test.mkv6:lengthi1eee"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (torrent_bytes, "jackett-result.torrent"),
    )

    def fake_add_torrent_file(
        self,
        *,
        torrent_bytes: bytes,
        filename: str,
        category: str = "",
        save_path: str = "",
        paused: bool = True,
        sequential_download: bool = False,
        first_last_piece_prio: bool = False,
    ) -> None:
        captured.update(
            {
                "torrent_bytes": torrent_bytes,
                "filename": filename,
                "category": category,
                "save_path": save_path,
                "paused": paused,
                "sequential_download": sequential_download,
                "first_last_piece_prio": first_last_piece_prio,
            }
        )

    def fail_add_torrent_url(self, **kwargs) -> None:
        raise AssertionError(f"Unexpected add_torrent_url call: {kwargs!r}")

    monkeypatch.setattr("app.routes.api.QbittorrentClient.add_torrent_file", fake_add_torrent_file)
    monkeypatch.setattr("app.routes.api.QbittorrentClient.add_torrent_url", fail_add_torrent_url)

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "http://localhost:9117/dl/bitru/?jackett_apikey=secret&path=abc",
            "sequential_download": True,
            "first_last_piece_prio": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["queued_via_torrent_file"] is True
    assert captured == {
        "torrent_bytes": torrent_bytes,
        "filename": "jackett-result.torrent",
        "category": "",
        "save_path": "",
        "paused": True,
        "sequential_download": True,
        "first_last_piece_prio": True,
    }


def test_queue_search_result_api_rejects_broken_local_jackett_url_instead_of_remote_fetching(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://docker-host:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        jackett_api_url="http://localhost:9117",
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (_ for _ in ()).throw(httpx.HTTPError("boom")),
    )

    def fail_add_torrent_url(self, **kwargs) -> None:
        raise AssertionError(f"Unexpected add_torrent_url call: {kwargs!r}")

    monkeypatch.setattr("app.routes.api.QbittorrentClient.add_torrent_url", fail_add_torrent_url)

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        },
    )

    assert response.status_code == 400
    assert (
        response.json()["error"]
        == "Could not fetch a valid torrent file from the local Jackett-style URL, so the app did not hand it off to qBittorrent for remote fetching."
    )


def test_queue_search_result_api_rewrites_jackett_qb_url_for_app_fetch(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        jackett_api_url="http://localhost:9117",
        jackett_qb_url="http://docker-host:9117",
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    torrent_bytes = b"d4:infod4:name8:Example12:piece lengthi1e6:pieces20:01234567890123456789ee"
    seen_links: list[str] = []

    def fake_download(link):
        seen_links.append(link)
        return torrent_bytes, "jackett-result.torrent"

    monkeypatch.setattr("app.services.selective_queue._download_torrent_bytes", fake_download)
    monkeypatch.setattr(
        "app.services.selective_queue.parse_torrent_info",
        lambda torrent_bytes, *, source_name="queued-result.torrent": ParsedTorrentInfo(
            info_hash="0123456789abcdef0123456789abcdef01234567",
            filename=source_name,
            files=[],
            tracker_urls=[],
        ),
    )
    monkeypatch.setattr(
        "app.routes.api.QbittorrentClient.add_torrent_file",
        lambda self, **kwargs: None,
    )

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "http://docker-host:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        },
    )

    assert response.status_code == 200
    assert response.json()["queued_via_torrent_file"] is True
    assert seen_links == ["http://localhost:9117/dl/kinozal/?jackett_apikey=secret&path=abc"]


def test_queue_search_result_api_queues_redirected_local_jackett_magnet(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        jackett_api_url="http://localhost:9117",
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    queued_links: list[str] = []

    monkeypatch.setattr(
        "app.services.selective_queue._resolve_local_jackett_redirect_magnet_link",
        lambda link: (
            "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
            "&tr=https://tracker.example/announce"
        ),
    )
    monkeypatch.setattr(
        "app.routes.api.QbittorrentClient.add_torrent_url",
        lambda self, **kwargs: queued_links.append(str(kwargs["link"])),
    )

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["queued_via_torrent_file"] is False
    assert queued_links == [
        "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
        "&tr=https://tracker.example/announce"
    ]


def test_queue_search_result_api_allows_local_remote_fetch_when_qb_is_loopback(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        jackett_api_url="http://localhost:9117",
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    queued_links: list[str] = []

    monkeypatch.setattr(
        "app.services.selective_queue._download_torrent_bytes",
        lambda link: (_ for _ in ()).throw(httpx.ReadTimeout("slow jackett")),
    )
    monkeypatch.setattr(
        "app.routes.api.QbittorrentClient.add_torrent_url",
        lambda self, **kwargs: queued_links.append(str(kwargs["link"])),
    )

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["queued_via_torrent_file"] is False
    assert queued_links == [
        "http://127.0.0.1:9117/dl/kinozal/?jackett_apikey=secret&path=abc"
    ]


def test_queue_search_result_api_reports_missing_only_selection_details(
    app_client, db_session, monkeypatch
) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        default_add_paused=True,
    )
    rule = Rule(
        rule_name="Queue Missing Only Rule",
        content_name="Queue Missing Only Rule",
        normalized_title="Queue Missing Only Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        feed_urls=["http://feed.example/queue-missing-only"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    monkeypatch.setattr(
        "app.routes.api.queue_result_with_optional_file_selection",
        lambda **kwargs: SimpleNamespace(
            message="Queued only missing/unseen episode files (2 selected, 1 skipped).",
            selected_file_count=2,
            skipped_file_count=1,
            deferred_file_selection=False,
            queued_via_torrent_file=True,
        ),
    )

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "https://example.com/shrinking-s03.torrent",
            "rule_id": rule.id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Queued only missing/unseen episode files (2 selected, 1 skipped)."
    assert payload["selected_file_count"] == 2
    assert payload["skipped_file_count"] == 1
    assert payload["queued_via_torrent_file"] is True
    assert payload["deferred_file_selection"] is False


def test_queue_search_result_api_uses_grouped_queue_flow(app_client, db_session, monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        qb_base_url="http://localhost:8080",
        qb_username="admin",
        qb_password_encrypted=obfuscate_secret("secret"),
        default_add_paused=True,
    )
    db_session.add(settings)
    db_session.commit()

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.routes.api.queue_grouped_search_results",
        lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(
            message="Processed grouped queue.",
            selected_file_count=0,
            skipped_file_count=0,
            deferred_file_selection=False,
            queued_via_torrent_file=False,
        ),
    )

    response = app_client.post(
        "/api/search/queue",
        json={
            "link": "magnet:?xt=urn:btih:ABC123",
            "links": [
                "magnet:?xt=urn:btih:ABC123",
                "https://example.com/variant.torrent",
            ],
            "info_hash": "abc123",
            "tracker_urls": ["https://tracker.one/announce"],
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Processed grouped queue."
    assert captured["links"] == [
        "magnet:?xt=urn:btih:ABC123",
        "https://example.com/variant.torrent",
    ]
    assert captured["info_hash"] == "abc123"
    assert captured["tracker_urls"] == ["https://tracker.one/announce"]


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
    assert (
        json.loads(taxonomy_path.read_text(encoding="utf-8"))["bundles"][0]["label"]
        == "At Least HD Revised"
    )
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
    assert (
        json.loads(taxonomy_path.read_text(encoding="utf-8"))["bundles"][0]["label"]
        == "At Least Full HD"
    )
    assert "rename bundle label with legacy token present" in audit_path.read_text(encoding="utf-8")


def test_apply_taxonomy_rejects_orphaning_rule_tokens(
    app_client, db_session, tmp_path, monkeypatch
) -> None:
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
    assert any(
        item["value"] == "hevc"
        for item in json.loads(taxonomy_path.read_text(encoding="utf-8"))["options"]
    )
    assert not audit_path.exists()


def test_new_rule_uses_taxonomy_bundle_labels_for_builtin_profiles(
    app_client, tmp_path, monkeypatch
) -> None:
    payload, taxonomy_path, _ = _use_temp_taxonomy(tmp_path, monkeypatch)
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    quality_filters._clear_quality_taxonomy_cache()

    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert ">At Least Full HD</option>" in response.text


def test_settings_uses_taxonomy_bundle_labels_for_builtin_profiles(
    app_client, tmp_path, monkeypatch
) -> None:
    payload, taxonomy_path, _ = _use_temp_taxonomy(tmp_path, monkeypatch)
    bundles = payload["bundles"]
    assert isinstance(bundles, list)
    bundles[0]["label"] = "At Least Full HD"
    taxonomy_path.write_text(json.dumps(payload), encoding="utf-8")
    quality_filters._clear_quality_taxonomy_cache()

    response = app_client.get("/settings")

    assert response.status_code == 200
    assert "<legend>At Least Full HD include</legend>" in response.text


def test_settings_page_renders_jellyfin_controls(app_client) -> None:
    response = app_client.get("/settings")

    assert response.status_code == 200
    assert 'name="jellyfin_db_path"' in response.text
    assert 'name="jellyfin_user_name"' in response.text
    assert 'name="jellyfin_auto_sync_enabled"' in response.text
    assert 'name="jellyfin_auto_sync_interval_seconds"' in response.text
    assert 'formaction="/api/settings/test-jellyfin"' in response.text
    assert 'formaction="/api/settings/sync-jellyfin"' in response.text
    assert "Automatic Jellyfin sync runs when the app starts" in response.text
    assert "Save + Sync Jellyfin Now" in response.text
    assert "Auto-sync status:" in response.text


def test_settings_page_renders_stremio_controls(app_client) -> None:
    response = app_client.get("/settings")

    assert response.status_code == 200
    assert 'name="stremio_local_storage_path"' in response.text
    assert 'name="stremio_auto_sync_enabled"' in response.text
    assert 'name="stremio_auto_sync_interval_seconds"' in response.text
    assert 'formaction="/api/settings/test-stremio"' in response.text
    assert 'formaction="/api/settings/sync-stremio"' in response.text
    assert "Automatic Stremio sync runs when the app starts" in response.text
    assert "Save + Sync Stremio Now" in response.text
    assert "Use this exact URL in Stremio" not in response.text
    assert "Add-on Repository URL box" not in response.text
    assert "Auto-sync status:" in response.text


def test_edit_movie_rule_page_renders_jellyfin_movie_sync_copy(app_client, db_session) -> None:
    rule = Rule(
        rule_name="Movie Jellyfin Rule",
        content_name="The Rip",
        normalized_title="The Rip",
        imdb_id="tt32642706",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        enabled=False,
        movie_completion_auto_disabled=True,
        movie_completion_sources=["jellyfin", "stremio"],
        feed_urls=["http://feed.example/the-rip"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.get(f"/rules/{rule.id}")

    assert response.status_code == 200
    assert "Keep searching this movie for better quality" in response.text
    assert (
        "centralized watch-state sync disables this rule after the movie is marked completed in any connected platform"
        in response.text
    )
    assert (
        "disabled automatically because completed watch state was reported by Jellyfin, Stremio"
        in response.text
    )


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
            "jellyfin_db_path": r"C:\ProgramData\Jellyfin\Server\data\jellyfin.db",
            "jellyfin_user_name": "Spon4ik",
            "stremio_local_storage_path": r"C:\Users\test\AppData\Local\Programs\Stremio\leveldb",
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
    assert settings.jellyfin_db_path == r"C:\ProgramData\Jellyfin\Server\data\jellyfin.db"
    assert settings.jellyfin_user_name == "Spon4ik"
    assert (
        settings.stremio_local_storage_path
        == r"C:\Users\test\AppData\Local\Programs\Stremio\leveldb"
    )
    assert settings.default_quality_profile.value == "2160p_hdr"
    assert settings.default_sequential_download is True
    assert settings.default_first_last_piece_prio is True
    assert settings.quality_profile_rules["1080p"]["include_tokens"] == ["full_hd", "1080p"]
    assert settings.quality_profile_rules["1080p"]["exclude_tokens"] == ["360p"]
    assert settings.quality_profile_rules["2160p_hdr"]["include_tokens"] == ["ultra_hd", "2160p"]
    assert settings.quality_profile_rules["2160p_hdr"]["exclude_tokens"] == ["bdremux", "ts"]


def test_save_settings_normalizes_omdb_full_url_to_api_key(app_client, db_session) -> None:
    response = app_client.post(
        "/api/settings",
        data={
            "omdb_api_key": "https://www.omdbapi.com/?apikey=191938ea",
            "metadata_provider": "omdb",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert reveal_secret(settings.omdb_api_key_encrypted) == "191938ea"


def test_save_settings_treats_literal_none_stremio_path_as_empty(app_client, db_session) -> None:
    response = app_client.post(
        "/api/settings",
        data={
            "stremio_local_storage_path": "None",
            "stremio_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
    assert settings.stremio_local_storage_path is None


def test_test_metadata_settings_accepts_full_omdb_url_value(app_client, monkeypatch) -> None:
    seen_imdb_ids: list[str] = []

    def fake_lookup_by_imdb_id(self, imdb_id):
        seen_imdb_ids.append(imdb_id)
        assert self.api_key == "191938ea"
        return MetadataResult(
            title="Game of Thrones",
            provider=MetadataLookupProvider.OMDB,
            imdb_id=imdb_id,
            source_id=imdb_id,
            media_type=MediaType.SERIES,
            year="2011",
        )

    monkeypatch.setattr(MetadataClient, "lookup_by_imdb_id", fake_lookup_by_imdb_id)

    response = app_client.post(
        "/api/settings/test-metadata",
        data={
            "omdb_api_key": "https://www.omdbapi.com/?apikey=191938ea",
            "metadata_provider": "omdb",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "Metadata lookup test succeeded." in response.text
    assert seen_imdb_ids == ["tt0944947"]


def test_test_jellyfin_settings_reports_success(app_client, tmp_path) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id="USER-1", username="Spon4ik")

    response = app_client.post(
        "/api/settings/test-jellyfin",
        data={
            "jellyfin_db_path": str(db_path),
            "jellyfin_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "Jellyfin read-only connection test succeeded." in response.text
    assert "Spon4ik" in response.text
    assert "Users found: Spon4ik." in response.text


def test_test_stremio_settings_reports_success(app_client, monkeypatch, tmp_path) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    response = app_client.post(
        "/api/settings/test-stremio",
        data={
            "stremio_local_storage_path": str(storage_path),
            "stremio_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "Stremio connection test succeeded." in response.text
    assert "Auth source: local storage." in response.text
    assert "Active movie/series library items: 1 of 1." in response.text


def test_test_stremio_settings_compat_path_reports_success(
    app_client, monkeypatch, tmp_path
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    response = app_client.post(
        "/settings/test-stremio",
        data={
            "stremio_local_storage_path": str(storage_path),
            "stremio_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "Stremio connection test succeeded." in response.text


def test_sync_jellyfin_settings_updates_matching_rules(app_client, db_session, tmp_path) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id="USER-1", username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-1",
        title="Shrinking",
        clean_name="Shrinking",
        production_year=2023,
    )
    add_jellyfin_episode(
        db_path,
        episode_id="EP-1",
        series_id="SERIES-1",
        title="Coin Flip",
        season_number=1,
        episode_number=1,
        tvdb_id="1001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="EP-2",
        series_id="SERIES-1",
        title="Fortress of Solitude",
        season_number=1,
        episode_number=2,
        tvdb_id="1002",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="EP-1",
        user_id="USER-1",
        custom_data_key="ep-1",
        play_count=1,
    )
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/shrinking"],
    )
    db_session.add(rule)
    db_session.commit()

    response = app_client.post(
        "/api/settings/sync-jellyfin",
        data={
            "jellyfin_db_path": str(db_path),
            "jellyfin_user_name": "Spon4ik",
            "jellyfin_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "Jellyfin sync completed for" in response.text
    assert "Spon4ik" in response.text
    assert "1 updated, 0 unchanged, 0 skipped, 0 errors" in response.text
    db_session.refresh(rule)
    assert (rule.start_season, rule.start_episode) == (1, 3)


def test_sync_jellyfin_settings_pushes_changed_rules_to_qb_when_configured(
    app_client,
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    db_path = create_jellyfin_test_db(tmp_path / "jellyfin.db")
    add_jellyfin_user(db_path, user_id="USER-1", username="Spon4ik")
    add_jellyfin_series(
        db_path,
        series_id="SERIES-QB-1",
        title="Shrinking",
        clean_name="Shrinking",
        production_year=2023,
    )
    add_jellyfin_episode(
        db_path,
        episode_id="QB-EP-1",
        series_id="SERIES-QB-1",
        title="Coin Flip",
        season_number=1,
        episode_number=1,
        tvdb_id="2001",
    )
    add_jellyfin_episode(
        db_path,
        episode_id="QB-EP-2",
        series_id="SERIES-QB-1",
        title="Fortress of Solitude",
        season_number=1,
        episode_number=2,
        tvdb_id="2002",
    )
    add_jellyfin_userdata(
        db_path,
        item_id="QB-EP-1",
        user_id="USER-1",
        custom_data_key="qb-ep-1",
        play_count=1,
    )
    rule = Rule(
        rule_name="Shrinking Rule",
        content_name="Shrinking",
        normalized_title="Shrinking",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["http://feed.example/shrinking"],
    )
    db_session.add(rule)
    db_session.commit()

    pushed_rule_ids: list[str] = []

    def fake_sync_rule(self, rule_id):
        pushed_rule_ids.append(rule_id)
        return SimpleNamespace(success=True, message="Rule synced to qBittorrent.")

    monkeypatch.setattr("app.routes.api.SyncService.sync_rule", fake_sync_rule)

    response = app_client.post(
        "/api/settings/sync-jellyfin",
        data={
            "qb_base_url": "http://127.0.0.1:8080",
            "qb_username": "admin",
            "qb_password": "secret",
            "jellyfin_db_path": str(db_path),
            "jellyfin_user_name": "Spon4ik",
            "jellyfin_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    assert response.status_code == 200
    assert "1 pushed to qB" in response.text
    assert pushed_rule_ids == [rule.id]


def test_sync_stremio_settings_creates_rules_for_library_titles(
    app_client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    response = app_client.post(
        "/api/settings/sync-stremio",
        data={
            "stremio_local_storage_path": str(storage_path),
            "stremio_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    created_rule = db_session.scalar(
        select(Rule).where(Rule.stremio_library_item_id == "tt13016388")
    )
    assert response.status_code == 200
    assert created_rule is not None
    assert "Stremio sync completed for 1 active title(s)" in response.text
    assert "1 created" in response.text


def test_sync_stremio_settings_pushes_changed_rules_to_qb_when_configured(
    app_client,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    storage_path = create_stremio_local_storage(tmp_path)
    _install_stremio_api(
        monkeypatch,
        items=[stremio_library_item("tt13016388", "3 Body Problem", item_type="series")],
    )

    pushed_rule_ids: list[str] = []

    def fake_sync_rule(self, rule_id):
        pushed_rule_ids.append(rule_id)
        return SimpleNamespace(success=True, message="Rule synced to qBittorrent.")

    monkeypatch.setattr("app.services.stremio_sync_ops.SyncService.sync_rule", fake_sync_rule)

    response = app_client.post(
        "/api/settings/sync-stremio",
        data={
            "qb_base_url": "http://127.0.0.1:8080",
            "qb_username": "admin",
            "qb_password": "secret",
            "stremio_local_storage_path": str(storage_path),
            "stremio_auto_sync_enabled": "on",
            "metadata_provider": "disabled",
            "series_category_template": "Series/{title} [imdbid-{imdb_id}]",
            "movie_category_template": "Movies/{title} [imdbid-{imdb_id}]",
            "save_path_template": "",
            "default_enabled": "on",
            "default_add_paused": "on",
            "default_sequential_download": "on",
            "default_first_last_piece_prio": "on",
            "default_quality_profile": "2160p_hdr",
        },
    )

    created_rule = db_session.scalar(
        select(Rule).where(Rule.stremio_library_item_id == "tt13016388")
    )
    assert response.status_code == 200
    assert created_rule is not None
    assert "1 pushed to qB" in response.text
    assert pushed_rule_ids == [created_rule.id]


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
    assert settings.saved_quality_profiles["hevc-web-only"]["exclude_tokens"] == [
        "bluray",
        "bdremux",
    ]
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
    assert settings.quality_profile_rules["1080p"]["include_tokens"] == [
        "full_hd",
        "1080p",
        "2160p",
        "4k",
    ]
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
    assert settings.saved_quality_profiles["builtin-at-least-uhd"]["media_types"] == [
        "series",
        "movie",
    ]


def test_new_rule_prefills_remembered_default_feeds(app_client, db_session) -> None:
    settings = AppSettings(id="default")
    settings.default_feed_urls = ["http://feed.example/remembered"]
    db_session.add(settings)
    db_session.commit()

    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert (
        'type="checkbox" name="feed_urls" value="http://feed.example/remembered" checked'
        in response.text
    )
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
    assert refreshed_settings.default_feed_urls == [
        "http://feed.example/alpha",
        "http://feed.example/bravo",
    ]


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
    assert (
        'type="checkbox" name="feed_urls" value="http://feed.example/saved" checked'
        in response.text
    )
