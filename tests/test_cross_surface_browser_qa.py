from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cross_surface_browser_qa as browser_qa  # noqa: E402


def test_same_origin_page_discovery_rejects_api_static_and_external_links() -> None:
    base = "http://127.0.0.1:8123"

    assert browser_qa._same_origin_path(base, "/settings/jackett") == "/settings/jackett"
    assert browser_qa._same_origin_path(base, "http://127.0.0.1:8123/taxonomy") == "/taxonomy"
    assert browser_qa._same_origin_path(base, "/api/rules/fetch") is None
    assert browser_qa._same_origin_path(base, "/static/app.css") is None
    assert browser_qa._same_origin_path(base, "https://example.com/settings") is None


def test_browser_validator_rejects_inconsistent_fetch_snapshot_label() -> None:
    commands = [
        {
            "transport": "async-control",
            "endpoint": "",
            "family": "fetch-snapshot",
            "label": "Run now",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "status-surface",
        }
    ]

    failures = browser_qa._validate_commands(commands, page_label="rules")

    assert any("canonical verb" in failure for failure in failures)


def test_browser_validator_accepts_scoped_fetch_with_feedback() -> None:
    commands = [
        {
            "transport": "async-control",
            "endpoint": "",
            "family": "fetch-snapshot",
            "label": "Fetch selected",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "status-surface",
        }
    ]

    assert browser_qa._validate_commands(commands, page_label="rules") == []


def test_browser_validator_requires_destructive_tone_and_form_confirmation() -> None:
    commands = [
        {
            "transport": "form-post",
            "endpoint": "/api/rules/abc/delete",
            "family": None,
            "label": "Delete",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "navigation",
        }
    ]

    failures = browser_qa._validate_commands(commands, page_label="rules")

    assert any("danger-styled" in failure for failure in failures)
    assert any("confirmation" in failure for failure in failures)


def test_browser_validator_refines_import_preview_and_apply_from_same_endpoint() -> None:
    preview = [
        {
            "transport": "form-post",
            "endpoint": "/api/import/qb-json",
            "family": None,
            "label": "Preview Import",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "navigation",
        }
    ]
    apply = [
        {
            "transport": "form-post",
            "endpoint": "/api/import/qb-json",
            "family": None,
            "label": "Apply Import",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "navigation",
        }
    ]

    assert browser_qa._validate_commands(preview, page_label="import") == []
    assert preview[0]["family"] == "import-preview"
    assert browser_qa._validate_commands(apply, page_label="import") == []
    assert apply[0]["family"] == "import-apply"


def test_browser_validator_allows_distinct_provider_verbs_with_one_semantic_family() -> None:
    commands = [
        {
            "transport": "form-post",
            "endpoint": "/api/settings/test-jellyfin",
            "family": None,
            "label": "Test Jellyfin",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "navigation",
        },
        {
            "transport": "form-post",
            "endpoint": "/api/settings/real-debrid/connect",
            "family": None,
            "label": "Connect Real-Debrid",
            "disabled": False,
            "danger": False,
            "confirmation": False,
            "feedback": "navigation",
        },
    ]

    assert browser_qa._validate_commands(commands, page_label="settings") == []
