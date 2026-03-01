from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.models import AppSettings, Rule, SyncStatus


def test_health_endpoint(app_client) -> None:
    response = app_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_new_rule_uses_ultra_hd_hdr_defaults(app_client) -> None:
    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'name="quality_profile" value="2160p_hdr"' in response.text
    assert 'option value="builtin-ultra-hd-hdr" selected' in response.text
    assert 'name="quality_include_tokens" value="ultra_hd" checked' in response.text
    assert 'name="quality_include_tokens" value="hdr" checked' in response.text


def test_create_rule_persists_locally_even_without_qb_config(app_client, db_session) -> None:
    response = app_client.post(
        "/api/rules",
        data=[
            ("rule_name", "Rule Alpha"),
            ("content_name", "Rule Alpha"),
            ("normalized_title", "Rule Alpha"),
            ("imdb_id", "tt1234567"),
            ("media_type", "series"),
            ("quality_profile", "plain"),
            ("release_year", "2024"),
            ("include_release_year", "on"),
            ("additional_includes", "remux"),
            ("quality_include_tokens", "2160p"),
            ("quality_include_tokens", "4k"),
            ("quality_exclude_tokens", "1080p"),
            ("quality_exclude_tokens", "720p"),
            ("enabled", "on"),
            ("add_paused", "on"),
            ("feed_urls", "http://feed.example/alpha"),
        ],
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
        data=[
            ("metadata_provider", "disabled"),
            ("series_category_template", "Series/{title} [imdbid-{imdb_id}]"),
            ("movie_category_template", "Movies/{title} [imdbid-{imdb_id}]"),
            ("save_path_template", ""),
            ("default_enabled", "on"),
            ("default_add_paused", "on"),
            ("default_quality_profile", "2160p_hdr"),
            ("profile_1080p_include_tokens", "full_hd"),
            ("profile_1080p_include_tokens", "1080p"),
            ("profile_1080p_exclude_tokens", "360p"),
            ("profile_2160p_hdr_include_tokens", "ultra_hd"),
            ("profile_2160p_hdr_include_tokens", "2160p"),
            ("profile_2160p_hdr_exclude_tokens", "bdremux"),
            ("profile_2160p_hdr_exclude_tokens", "ts"),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    settings = db_session.get(AppSettings, "default")
    assert settings is not None
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

    overwrite_response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "overwrite",
            "target_key": "hevc-web-only",
            "include_tokens": ["hevc"],
            "exclude_tokens": ["bluray"],
        },
    )

    assert overwrite_response.status_code == 200
    db_session.refresh(settings)
    assert settings.saved_quality_profiles["hevc-web-only"]["include_tokens"] == ["hevc"]
    assert settings.saved_quality_profiles["hevc-web-only"]["exclude_tokens"] == ["bluray"]


def test_overwrite_filter_profile_updates_builtin_at_least_hd(app_client, db_session) -> None:
    response = app_client.post(
        "/api/filter-profiles",
        json={
            "mode": "overwrite",
            "target_key": "builtin-at-least-hd",
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
