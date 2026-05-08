from __future__ import annotations

import re
import threading
import time
from datetime import timedelta

from app.config import obfuscate_secret
from app.models import AppSettings, MediaType, QualityProfile, Rule, RuleSearchSnapshot, utcnow
from app.schemas import JackettSearchRun
from app.services import rule_fetch_ops
from app.services.jackett import JackettClient
from app.services.rule_fetch_ops import (
    _rule_local_filtered_count_from_rows,
    _rule_local_generated_pattern,
    refresh_snapshot_release_cache,
    release_state_from_snapshot,
)


def test_release_state_from_snapshot_reuses_cached_local_count_after_non_filter_rule_update(
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Rule Cached Count",
        content_name="Rule Cached Count",
        normalized_title="Rule Cached Count",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=2,
        start_episode=1,
        feed_urls=["https://jackett.test/api/v2.0/indexers/cached/results/torznab/api"],
    )
    db_session.add(rule)
    db_session.flush()

    snapshot = RuleSearchSnapshot(
        rule_id=rule.id,
        inline_search={
            "combined_filtered_count": 1,
            "combined_fetched_count": 1,
            "unified_raw_results": [
                {
                    "title": "Rule Cached Count S01E01 1080p",
                    "text_surface": "rule cached count s01e01 1080p",
                    "indexer": "cached",
                    "year": "2026",
                }
            ],
        },
        fetched_at=utcnow(),
    )
    db_session.add(snapshot)
    db_session.commit()

    assert refresh_snapshot_release_cache(snapshot, rule=rule) is True
    db_session.commit()

    initial_release = release_state_from_snapshot(snapshot, rule=rule)
    assert initial_release["combined_filtered_count"] == 0
    assert initial_release["state"] == "no_matches"

    rule.poster_url = "https://example.com/poster.jpg"
    db_session.add(rule)
    db_session.commit()

    def fail_slow_path(*args, **kwargs):
        raise AssertionError("expected cached release count to be reused")

    monkeypatch.setattr(rule_fetch_ops, "_rule_local_filtered_count_from_rows", fail_slow_path)

    cached_release = release_state_from_snapshot(snapshot, rule=rule)
    assert cached_release["combined_filtered_count"] == 0
    assert cached_release["combined_fetched_count"] == 1


def test_rule_fetch_prefers_explicit_search_indexers_over_feed_urls(
    db_session,
    monkeypatch,
) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("apikey"),
    )
    rule = Rule(
        rule_name="Fetch Explicit Scope",
        content_name="Fetch Explicit Scope",
        normalized_title="Fetch Explicit Scope",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        feed_urls=["https://jackett.test/api/v2.0/indexers/rutracker/results/torznab/api"],
        search_indexers=["kinozal"],
    )
    db_session.add_all([settings, rule])
    db_session.commit()

    def fake_search(self, payload):
        assert payload.indexer == "kinozal"
        assert payload.filter_indexers == ["kinozal"]
        return JackettSearchRun(results=[])

    monkeypatch.setattr(JackettClient, "search", fake_search)
    monkeypatch.setattr(JackettClient, "enrich_result_category_labels", lambda self, results: None)
    monkeypatch.setattr(JackettClient, "configured_indexer_category_labels", lambda self: {})

    result = rule_fetch_ops.execute_rule_fetch(db_session, rule=rule)

    assert result["success"] is True
    assert "Scoped to saved Jackett search indexer: kinozal." in result["notices"]


def test_rules_page_skips_poster_backfill_on_filtered_requests(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    rule = Rule(
        rule_name="Filtered Rule",
        content_name="Filtered Rule",
        normalized_title="Filtered Rule",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    db_session.add(rule)
    db_session.commit()

    called = False

    def fake_backfill(session, *, rules, settings) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("app.routes.pages._backfill_missing_rule_posters", fake_backfill)

    response = app_client.get("/?search=filtered")

    assert response.status_code == 200
    assert called is False


def test_rules_fetch_batch_fetches_missing_then_oldest_snapshots(
    db_session,
    monkeypatch,
) -> None:
    now = utcnow()
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("apikey"),
        rules_fetch_parallelism=1,
    )
    newest_rule = Rule(
        rule_name="Alpha Newest Snapshot",
        content_name="Alpha Newest Snapshot",
        normalized_title="Alpha Newest Snapshot",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    oldest_rule = Rule(
        rule_name="Middle Oldest Snapshot",
        content_name="Middle Oldest Snapshot",
        normalized_title="Middle Oldest Snapshot",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    missing_rule = Rule(
        rule_name="Zulu Missing Snapshot",
        content_name="Zulu Missing Snapshot",
        normalized_title="Zulu Missing Snapshot",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
    )
    db_session.add_all([settings, newest_rule, oldest_rule, missing_rule])
    db_session.flush()
    db_session.add_all(
        [
            RuleSearchSnapshot(
                rule_id=newest_rule.id,
                inline_search={},
                fetched_at=now - timedelta(minutes=5),
            ),
            RuleSearchSnapshot(
                rule_id=oldest_rule.id,
                inline_search={},
                fetched_at=now - timedelta(days=2),
            ),
        ]
    )
    db_session.commit()

    fetched_rule_names: list[str] = []

    def fake_execute_rule_fetch(session, *, rule, feed_urls_override=None):
        fetched_rule_names.append(rule.rule_name)
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": True,
            "state": "no_matches",
            "rank": 3,
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": [],
            "error": "",
        }

    monkeypatch.setattr(rule_fetch_ops, "execute_rule_fetch", fake_execute_rule_fetch)

    result = rule_fetch_ops.run_rules_fetch_batch(db_session, run_all=True)

    assert result["status"] == "ok"
    assert fetched_rule_names == [
        "Zulu Missing Snapshot",
        "Middle Oldest Snapshot",
        "Alpha Newest Snapshot",
    ]


def test_rules_fetch_batch_limits_parallel_workers(db_session, monkeypatch) -> None:
    settings = AppSettings(
        id="default",
        jackett_api_url="http://jackett.test",
        jackett_api_key_encrypted=obfuscate_secret("apikey"),
        rules_fetch_parallelism=2,
    )
    rules = [
        Rule(
            rule_name=f"Parallel Rule {index}",
            content_name=f"Parallel Rule {index}",
            normalized_title=f"Parallel Rule {index}",
            media_type=MediaType.SERIES,
            quality_profile=QualityProfile.PLAIN,
        )
        for index in range(5)
    ]
    db_session.add(settings)
    db_session.add_all(rules)
    db_session.commit()

    active_workers = 0
    max_active_workers = 0
    lock = threading.Lock()

    def fake_execute_rule_fetch(session, *, rule, feed_urls_override=None):
        nonlocal active_workers, max_active_workers
        with lock:
            active_workers += 1
            max_active_workers = max(max_active_workers, active_workers)
        time.sleep(0.05)
        with lock:
            active_workers -= 1
        return {
            "rule_id": rule.id,
            "rule_name": rule.rule_name,
            "success": True,
            "state": "no_matches",
            "rank": 3,
            "filtered_count": 0,
            "fetched_count": 0,
            "warnings": [],
            "notices": [],
            "error": "",
        }

    monkeypatch.setattr(rule_fetch_ops, "execute_rule_fetch", fake_execute_rule_fetch)

    result = rule_fetch_ops.run_rules_fetch_batch(db_session, run_all=True)

    assert result["attempted"] == 5
    assert result["succeeded"] == 5
    assert max_active_workers == 2


def test_rule_local_filter_excludes_zero_based_ranges_below_episode_floor() -> None:
    rule = Rule(
        rule_name="The Good Ship Murder",
        content_name="The Good Ship Murder",
        normalized_title="The Good Ship Murder",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=3,
        start_episode=8,
        jellyfin_existing_episode_numbers=[
            "S03E01",
            "S03E02",
            "S03E03",
            "S03E04",
            "S03E05",
            "S03E06",
            "S03E07",
        ],
    )

    pattern = _rule_local_generated_pattern(rule)
    compiled = re.compile(pattern[4:], re.IGNORECASE | re.UNICODE)
    leaked_title = "Убийство на борту (The Good Ship Murder)S3E00-07 (HD 1080p WEBRip) Полный S3"
    allowed_title = "The Good Ship Murder S03E08 1080p"

    assert compiled.search(leaked_title) is None
    assert compiled.search(allowed_title) is not None
    assert (
        _rule_local_filtered_count_from_rows(
            rule,
            [
                {
                    "title": leaked_title,
                    "text_surface": leaked_title.lower(),
                },
                {
                    "title": allowed_title,
                    "text_surface": allowed_title.lower(),
                },
            ],
        )
        == 1
    )


def test_rule_local_filter_keeps_same_season_complete_pack_when_keep_searching_enabled() -> None:
    rule = Rule(
        rule_name="The Miniature Wife",
        content_name="The Miniature Wife",
        normalized_title="The Miniature Wife",
        media_type=MediaType.SERIES,
        quality_profile=QualityProfile.PLAIN,
        start_season=1,
        start_episode=11,
        jellyfin_search_existing_unseen=True,
        jellyfin_existing_episode_numbers=[
            "S01E03",
            "S01E04",
            "S01E05",
            "S01E06",
            "S01E07",
            "S01E08",
            "S01E09",
            "S01E10",
        ],
    )

    complete_pack_title = (
        "Миниатюрная жена (The Miniature Wife)S1E01-10 (HD 1080p WEBRip) Полный S1"
    )
    assert (
        _rule_local_filtered_count_from_rows(
            rule,
            [
                {
                    "title": complete_pack_title,
                    "text_surface": complete_pack_title.lower(),
                }
            ],
        )
        == 1
    )


def test_refresh_snapshot_release_cache_records_hidden_reason_counts(db_session) -> None:
    rule = Rule(
        rule_name="Reason Count Rule",
        content_name="Reason Count Rule",
        normalized_title="Reason Count Rule",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.PLAIN,
        additional_includes="wanted",
        must_not_contain="bad",
        include_release_year=True,
        release_year="2026",
    )
    db_session.add(rule)
    db_session.flush()

    snapshot = RuleSearchSnapshot(
        rule_id=rule.id,
        inline_search={
            "combined_filtered_count": 4,
            "combined_fetched_count": 4,
            "unified_raw_results": [
                {
                    "title": "Reason Count Rule wanted 2026",
                    "text_surface": "reason count rule wanted 2026",
                    "year": "2026",
                },
                {
                    "title": "Reason Count Rule 2026",
                    "text_surface": "reason count rule 2026",
                    "year": "2026",
                },
                {
                    "title": "Reason Count Rule wanted bad 2026",
                    "text_surface": "reason count rule wanted bad 2026",
                    "year": "2026",
                },
                {
                    "title": "Reason Count Rule wanted 2025",
                    "text_surface": "reason count rule wanted 2025",
                    "year": "2025",
                },
            ],
        },
        fetched_at=utcnow(),
    )
    db_session.add(snapshot)
    db_session.commit()

    assert refresh_snapshot_release_cache(snapshot, rule=rule) is True
    db_session.commit()

    assert snapshot.release_filtered_count == 1
    assert snapshot.release_fetched_count == 4
    assert snapshot.inline_search["rule_local_hidden_reasons"] == {
        "Missing include keyword: wanted.": 1,
        "Matched excluded keyword: bad.": 1,
        "Release year does not match 2026.": 1,
    }


def test_refresh_snapshot_release_cache_requires_rule_title_identity(db_session) -> None:
    rule = Rule(
        rule_name="Rule Identity Count",
        content_name="Rule Identity Count",
        normalized_title="Rule Identity Count",
        media_type=MediaType.MOVIE,
        quality_profile=QualityProfile.CUSTOM,
        quality_include_tokens=[],
        quality_exclude_tokens=["1080p"],
        feed_urls=[
            "https://jackett.test/api/v2.0/indexers/rutracker/results/torznab/api"
        ],
    )
    db_session.add(rule)
    db_session.flush()

    snapshot = RuleSearchSnapshot(
        rule_id=rule.id,
        inline_search={
            "combined_filtered_count": 2,
            "combined_fetched_count": 2,
            "unified_raw_results": [
                {
                    "title": "Broad Variant 2160p",
                    "text_surface": "broad variant 2160p",
                    "indexer": "RuTracker.org",
                    "query_source_key": "fallback",
                    "visible": False,
                },
                {
                    "title": "Rule Identity Count 2160p",
                    "text_surface": "rule identity count 2160p",
                    "indexer": "RuTracker.org",
                    "query_source_key": "fallback",
                    "visible": False,
                },
            ],
        },
        fetched_at=utcnow(),
    )
    db_session.add(snapshot)
    db_session.commit()

    assert refresh_snapshot_release_cache(snapshot, rule=rule) is True
    db_session.commit()

    assert snapshot.release_filtered_count == 1
    assert snapshot.release_fetched_count == 2
    assert snapshot.inline_search["rule_local_hidden_reasons"] == {
        'Title does not match query "Rule Identity Count".': 1
    }
