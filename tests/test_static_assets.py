from __future__ import annotations

import os
from pathlib import Path

from app.services.static_assets import compute_static_asset_version

APP_CSS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "app.css"
BASE_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "base.html"
RULE_FORM_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "rule_form.html"
SEARCH_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app" / "templates" / "search.html"
APP_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"
RUNTIME_HEALTH_JS_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "runtime_health.js"
CLOSEOUT_BROWSER_QA_PATH = Path(__file__).resolve().parents[1] / "scripts" / "closeout_browser_qa.py"


def test_compute_static_asset_version_tracks_app_asset_mtime(tmp_path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    css_path = static_dir / "app.css"
    js_path = static_dir / "app.js"
    runtime_health_path = static_dir / "runtime_health.js"
    css_path.write_text("body { color: #111; }\n", encoding="utf-8")
    js_path.write_text("console.log('initial');\n", encoding="utf-8")
    runtime_health_path.write_text("console.log('runtime');\n", encoding="utf-8")

    initial_version = compute_static_asset_version(static_dir)
    assert initial_version

    bumped_mtime_ns = runtime_health_path.stat().st_mtime_ns + 1_000_000_000
    os.utime(
        runtime_health_path,
        ns=(runtime_health_path.stat().st_atime_ns, bumped_mtime_ns),
    )

    updated_version = compute_static_asset_version(static_dir)

    assert updated_version != initial_version


def test_browser_closeout_targets_current_defaults_page_contract() -> None:
    harness = CLOSEOUT_BROWSER_QA_PATH.read_text(encoding="utf-8")

    assert 'f"{app_base_url}/settings/defaults"' in harness
    assert 'button:has-text("Save defaults and quality profiles")' in harness
    assert "getComputedStyle(document.querySelector('.result-card'))" in harness


def test_queue_ui_exposes_only_rule_and_one_time_pause_overrides() -> None:
    settings_template = (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "settings.html"
    ).read_text(encoding="utf-8")
    rule_template = RULE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    search_template = SEARCH_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'name="default_add_paused"' not in settings_template
    assert "Add paused by default for this rule" in rule_template
    assert "Queue paused" in rule_template
    assert "Queue paused" in search_template
    assert 'data-result-queue-option="paused"' in rule_template
    assert 'data-result-queue-option="paused"' in search_template


def test_result_toolbar_uses_shared_non_reflowing_menu_contract() -> None:
    rule_template = RULE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    search_template = SEARCH_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = APP_CSS_PATH.read_text(encoding="utf-8")
    js = APP_JS_PATH.read_text(encoding="utf-8")
    harness = CLOSEOUT_BROWSER_QA_PATH.read_text(encoding="utf-8")

    assert rule_template.count("data-result-toolbar-menu") == 3
    assert search_template.count("data-result-toolbar-menu") == 1
    assert "queue-paused-field" in rule_template
    assert "queue-paused-field" in search_template
    assert ".result-toolbar-row .queue-paused-field" in css
    assert "function initResultToolbarMenus" in js
    assert "event.key !== \"Escape\"" in js
    assert "closeMenusExcept(menu)" in js
    assert "P44-03" in harness
    assert "itemsOverlap" in harness
    assert "Opening queue options reflowed surrounding layout" in harness


def test_background_work_ui_has_maintenance_and_message_lifecycle_controls() -> None:
    base_template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    acceleration_template = (BASE_TEMPLATE_PATH.parent / "acceleration.html").read_text(encoding="utf-8")
    rule_template = RULE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    js = APP_JS_PATH.read_text(encoding="utf-8")

    assert "data-acceleration-problem-link" in base_template
    assert "data-acceleration-jobs" in acceleration_template
    assert "Ask Codex" in js
    assert "/ask-codex" in js
    assert "Remove acceleration" in js
    assert "Dismiss" in js
    assert '<details class="rule-search-notices"' in rule_template


def test_app_css_declares_responsive_shell_contract() -> None:
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    for token in (
        "--shell-gutter",
        "--shell-max",
        "--shell-wide-max",
        "--content-padding",
        "--content-padding-wide",
        "--density-gap",
        "--density-gap-tight",
    ):
        assert token in css

    assert "width: calc(100% - (2 * var(--shell-gutter)))" in css
    assert "max-width: var(--shell-max)" in css
    assert "max-width: var(--shell-wide-max)" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (min-width: 901px) and (max-width: 1400px)" in css

    for utility in (
        ".layout-stack",
        ".layout-stack--tight",
        ".layout-cluster",
        ".layout-density-compact",
    ):
        assert utility in css


def test_global_operation_progress_shell_assets_are_present() -> None:
    template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    index_template = (BASE_TEMPLATE_PATH.parent / "index.html").read_text(encoding="utf-8")
    rule_form_template = RULE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = APP_CSS_PATH.read_text(encoding="utf-8")
    js = APP_JS_PATH.read_text(encoding="utf-8")

    assert 'data-operation-progress-shell' in template
    assert 'data-operation-progress-bar' in template
    assert 'data-operation-progress-summary>Checking progress...' in template
    shell_open_tag = template.partition('data-operation-progress-shell')[0].rsplit("<section", 1)[-1]
    assert " hidden" not in shell_open_tag
    assert ".operation-progress-shell" in css
    assert "function initOperationProgress" in js
    assert 'fetch("/api/operations/status"' in js
    assert 'data-acceleration-problem-link' in template
    assert "/api/acceleration/jobs/" in js
    assert "The torrent and downloaded files will be kept" in js
    assert 'titleElement.textContent = "Background work"' in js
    assert '"No active progress"' in js
    assert '"operation-progress-starting"' in js
    assert 'data-operation-start-label' in index_template
    assert 'data-operation-start-label' in rule_form_template


def test_acceleration_console_and_variant_actions_are_present() -> None:
    template = (BASE_TEMPLATE_PATH.parent / "acceleration.html").read_text(encoding="utf-8")
    js = APP_JS_PATH.read_text(encoding="utf-8")
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    assert 'data-acceleration-console' in template
    assert 'data-acceleration-status-filter' in template
    assert 'data-acceleration-jobs' in template
    assert "function initAccelerationConsole" in js
    assert "function initVariantAcceleration" in js
    assert "Ask Codex" in js
    assert ".acceleration-console-toolbar" in css


def test_app_shell_declares_compact_operational_console_contract() -> None:
    template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    assert 'class="site-header-brand"' in template
    assert 'class="site-header-meta"' in template
    assert 'class="site-nav site-nav--primary"' in template
    assert 'aria-label="Primary navigation"' in template

    for token in (
        "--app-bg",
        "--surface",
        "--surface-raised",
        "--chrome",
        "--accent",
        "--radius",
    ):
        assert token in css

    assert ".site-header-brand" in css
    assert ".site-header-meta" in css
    assert ".site-nav--primary" in css
    assert "font-family: var(--font-ui)" in css
    assert "max-height: none" in css


def test_console_surfaces_share_stronger_component_contract() -> None:
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    for selector in (
        ".rules-command-center",
        ".rules-data-grid tbody tr",
        ".rules-title-cell::before",
        "input[type=\"file\"]::file-selector-button",
        ".taxonomy-metric-list",
        ".rule-card--console",
    ):
        assert selector in css

    assert "grid-template-columns: 0.35rem minmax(0, 1fr)" in css
    assert "border-left: 3px solid var(--accent)" in css


def test_rule_edit_page_uses_full_width_console_results_contract() -> None:
    template = RULE_FORM_TEMPLATE_PATH.read_text(encoding="utf-8")
    search_template = SEARCH_TEMPLATE_PATH.read_text(encoding="utf-8")
    css = APP_CSS_PATH.read_text(encoding="utf-8")

    for section_class in (
        "rule-criteria-section--identity",
        "rule-criteria-section--quality",
        "rule-criteria-section--scope",
        "rule-criteria-section--advanced",
    ):
        assert section_class in template

    assert ".rule-workspace-results" in css
    assert "grid-template-columns: minmax(21rem, 27rem) minmax(0, 1fr)" in css
    assert ".rule-workspace-rail" in css
    assert "position: sticky" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "data-rule-edit-profile-summary" in template
    assert "data-rule-edit-command-bar" in template
    assert "data-rule-settings-panel" in template
    assert "data-rule-settings-drawer" not in template
    assert "episode-floor-field" in template
    assert "data-quality-mode-description" not in template
    assert "data-quality-managed-help" in template
    assert "data-quality-manual-help" in template
    assert 'id="metadata-lookup-value"' in template
    assert 'id="metadata-lookup"' in template
    app_js = APP_JS_PATH.read_text(encoding="utf-8")
    assert "if (contentField) {\n      contentField.value = payload.title" in app_js
    assert "if (contentField && !contentField.value.trim())" not in app_js
    assert "data-feed-summary" in template
    assert "Quality pre-defined profile" in template
    assert "rule-search-notices" in template
    assert 'data-search-display-status="combined"' in template
    assert 'data-search-display-status="combined"' in search_template
    assert ".rule-edit-profile-strip" in css
    assert ".rule-edit-command-bar" in css
    assert ".rule-settings-panel" in css
    assert ".rule-settings-drawer" not in css
    assert ".rule-form--compact > .quality-mode-panel {\n  grid-column: 1 / -1;" in css
    assert ".rule-form--compact > .rule-criteria-section--identity {\n  grid-column: 1 / -1;" in css
    assert ".feed-dropdown" in css
    assert ".search-multiselect:not([open]) .search-multiselect-panel" in css
    assert "#inline-search-results .result-view-active-filters" in css
    assert "#inline-search-results .search-table-wrap" in css
    assert "#inline-search-results > .search-table-wrap" in css
    assert "max-height: min(56vh, 38rem)" in css
    assert "display: flex;\n    flex-direction: column;" in css
    assert "#inline-search-results > .rule-search-notices" in css
    assert "max-height: 10rem" in css
    assert '<details class="rule-search-notices"' in template
    assert "flex: 1 1 0" in css
    assert "flex-basis: 10rem" in css
    assert "min-height: 10rem" in css
    assert "grid-template-rows: auto auto auto auto auto auto minmax(0, 1fr)" not in css
    assert "min-width: 0" in css
    assert ".search-action-icon" in css
    assert "#inline-search-results .search-table td::before" in css
    js = APP_JS_PATH.read_text(encoding="utf-8")
    assert 'td[data-label="Title"] .helper-text' in js
    assert "categoryMediaFailure" in js
    assert "STANDARD_NON_VIDEO_CATEGORY_ROOTS" in js
    assert "displayStatusElement" in js
    assert "const displayedEntryCount" in js
    assert "state.tableWrap.hidden = !tableMode || displayedEntryCount === 0;" in js


def test_runtime_health_reconciler_is_versioned_and_loaded() -> None:
    template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")
    runtime_js = RUNTIME_HEALTH_JS_PATH.read_text(encoding="utf-8")

    assert "runtime_health.js" in template
    assert "/api/diagnostics/runtime" in runtime_js
    assert "recovered_historical" in runtime_js
    assert "historical error" in runtime_js
