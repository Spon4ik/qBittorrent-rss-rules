from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AppSettings, MediaType, QualityProfile, Rule, SyncStatus
from app.services import quality_filters


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


def test_new_rule_prefills_remembered_default_feeds(app_client, db_session) -> None:
    settings = AppSettings(id="default")
    settings.default_feed_urls = ["http://feed.example/remembered"]
    db_session.add(settings)
    db_session.commit()

    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'option value="http://feed.example/remembered" selected' in response.text


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


def test_rule_form_includes_bulk_feed_selection_controls(app_client) -> None:
    response = app_client.get("/rules/new")

    assert response.status_code == 200
    assert 'id="feed-select-all"' in response.text
    assert 'id="feed-clear-all"' in response.text
