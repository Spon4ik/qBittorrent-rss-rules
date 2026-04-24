from __future__ import annotations

import re

from app.models import MediaType, QualityProfile, Rule, RuleSearchSnapshot, utcnow
from app.services import rule_fetch_ops
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
