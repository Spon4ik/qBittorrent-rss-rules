from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cross_surface_contracts as contracts  # noqa: E402
import cross_surface_guard as guard  # noqa: E402


@pytest.mark.parametrize(
    ("endpoint", "family"),
    [
        ("/api/sync/all", "sync"),
        ("/api/rules/abc/sync?return_to=rule", "sync"),
        ("/api/rules/fetch", "fetch-snapshot"),
        ("/api/rules/fetch-schedule/run-now", "fetch-snapshot"),
        ("/api/rules", "create-rule"),
        ("/api/rules/abc", "save-rule"),
        ("/api/search/queue", "queue"),
        ("/api/feeds/refresh", "refresh-feeds"),
        ("/api/acceleration/jobs/abc/retry", "retry-acceleration"),
        ("/api/acceleration/jobs/abc/cleanup", "remove-acceleration"),
        ("/api/settings/sync-jellyfin", "save-sync"),
        ("/api/settings/sync-stremio", "save-sync"),
        ("/api/settings/sync-watch-progress", "sync"),
        ("/api/settings/test-jellyfin", "provider-command"),
        ("/api/settings/real-debrid/connect", "provider-command"),
        ("/api/taxonomy/options/add", "taxonomy-add"),
        ("/api/taxonomy/options/move", "taxonomy-move"),
        ("/api/taxonomy/options/remove", "taxonomy-remove"),
        ("/api/taxonomy/validate", "taxonomy-validate"),
        ("/api/taxonomy/apply", "taxonomy-apply"),
    ],
)
def test_common_endpoints_map_to_action_families(endpoint: str, family: str) -> None:
    assert contracts.classify_endpoint(endpoint) == family


def test_dynamic_endpoint_normalization_removes_concrete_identity() -> None:
    assert contracts.normalize_endpoint("/api/rules/{{ rule.id }}/sync") == "/api/rules/{id}/sync"
    assert (
        contracts.normalize_endpoint("/api/acceleration/jobs/${encodeURIComponent(job.id)}/retry")
        == "/api/acceleration/jobs/{id}/retry"
    )


def test_same_endpoint_can_refine_to_distinct_semantic_actions() -> None:
    base = contracts.classify_endpoint("/api/import/qb-json")
    assert base == "import-apply"
    assert contracts.refine_family(base, "Preview Import") == "import-preview"
    assert contracts.refine_family(base, "Apply Import") == "import-apply"


def test_internal_telemetry_is_not_a_user_command_family() -> None:
    assert contracts.is_internal_endpoint("/api/debug/hover-telemetry") is True
    assert contracts.classify_endpoint("/api/debug/hover-telemetry") is None


def test_shared_action_families_have_stable_canonical_verbs() -> None:
    assert contracts.canonical_label_matches("sync", "Sync rule") is True
    assert contracts.canonical_label_matches("sync", "Refresh rule") is False
    assert contracts.canonical_label_matches("save-sync", "Save + Sync Jellyfin") is True
    assert contracts.canonical_label_matches("delete-rule", "Delete") is True
    assert contracts.canonical_label_matches("fetch-snapshot", "Fetch all snapshots") is True
    assert contracts.canonical_label_matches("fetch-snapshot", "Run now") is False
    assert contracts.canonical_label_matches("taxonomy-move", "Move 1080p up") is True


def test_unknown_post_command_is_actionable_guard_failure() -> None:
    surface = guard.CommandSurface(
        source="app/static/app.js",
        line=42,
        transport="fetch-post",
        endpoint="/api/new-unclassified-command",
        family=None,
    )

    findings = guard.evaluate_surfaces([surface])

    assert len(findings) == 1
    assert findings[0].kind == "unclassified-command"


def test_inconsistent_repeated_command_label_is_actionable_guard_failure() -> None:
    surface = guard.CommandSurface(
        source="app/templates/example.html",
        line=9,
        transport="form-post",
        endpoint="/api/sync/all",
        family="sync",
        label="Refresh all",
    )

    findings = guard.evaluate_surfaces([surface])

    assert len(findings) == 1
    assert findings[0].kind == "inconsistent-command-label"


def test_destructive_form_requires_common_tone_and_confirmation() -> None:
    unsafe = guard.CommandSurface(
        source="app/templates/example.html",
        line=12,
        transport="form-post",
        endpoint="/api/rules/{id}/delete",
        family="delete-rule",
        label="Delete",
    )

    findings = guard.evaluate_surfaces([unsafe])

    assert {item.kind for item in findings} == {
        "destructive-command-tone",
        "destructive-command-confirmation",
    }


def test_command_registry_distinguishes_destructive_and_long_running_actions() -> None:
    assert contracts.contract_for_family("delete-rule").destructive is True
    assert contracts.contract_for_family("taxonomy-remove").destructive is True
    assert contracts.contract_for_family("remove-acceleration").destructive is True
    assert contracts.contract_for_family("sync").long_running is True
    assert contracts.contract_for_family("save-sync").long_running is True
    assert contracts.contract_for_family("fetch-snapshot").long_running is True
    assert contracts.contract_for_family("dismiss-acceleration").destructive is False


def test_template_scanner_honors_submit_formaction_overrides() -> None:
    surfaces = guard._scan_template(guard.PROJECT_DIR / "app" / "templates" / "settings_provider.html")
    families = {surface.family for surface in surfaces}

    assert "save-settings" in families
    assert "provider-command" in families
    assert "save-sync" in families
    assert "sync" in families


def test_template_scanner_inventory_keeps_taxonomy_actions_distinct() -> None:
    surfaces = guard._scan_template(guard.PROJECT_DIR / "app" / "templates" / "taxonomy.html")
    families = {surface.family for surface in surfaces}

    assert {
        "taxonomy-add",
        "taxonomy-move",
        "taxonomy-remove",
        "taxonomy-validate",
        "taxonomy-apply",
    }.issubset(families)


def test_template_scanner_finds_form_owned_submit_button_outside_form() -> None:
    surfaces = guard._scan_template(guard.PROJECT_DIR / "app" / "templates" / "rule_form.html")
    labels = {surface.label for surface in surfaces if surface.family == "save-rule"}

    assert "Save Changes" in labels
