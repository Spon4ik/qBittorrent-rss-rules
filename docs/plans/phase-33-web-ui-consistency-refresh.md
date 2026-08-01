# Phase 33 - Web UI Consistency Refresh

## Summary

Refresh the FastAPI/Jinja web UI into a compact operational console without changing backend behavior. The slice reduces the oversized header/navigation footprint, tightens the global operation progress strip, standardizes typography around UI sans-serif styling, and compresses rules/search/settings/new-rule control surfaces so the first viewport reaches useful work sooner.

## Scope

- Replace the hero-like base header with a compact app bar that keeps product name, version, short context text, and primary navigation visible without dominating mobile or desktop.
- Restyle shared CSS tokens around a neutral workspace, deep teal chrome, rust primary actions, compact radii, denser controls, and consistent sans-serif headings.
- Tighten the rules workbench filters, toolbar, scheduled-fetch strip, global operation progress strip, search criteria sections, import/taxonomy surfaces, rule form controls, and rule edit inline-results table enough to prevent obvious text overlap and reduce unnecessary vertical scroll.
- Preserve routes, form names, data attributes, API behavior, database schema, and Phase 32 sync behavior.

## Acceptance Criteria

- `/`, `/search`, `/settings`, `/rules/new`, `/import`, `/taxonomy`, and representative `/rules/{id}` edit pages render without document-level horizontal overflow at desktop and mobile widths.
- The mobile header/nav no longer consumes nearly the full first viewport before useful page content appears.
- The global operation progress shell remains visible and readable in idle/running/completed states.
- Existing static asset, route, and JavaScript checks continue to pass.

## Validation Checklist

- [x] `node --check app/static/app.js` passes.
- [x] `python -m pytest tests/test_static_assets.py tests/test_routes.py::test_health_endpoint tests/test_routes.py::test_rule_pages_expose_run_search_actions tests/test_routes.py::test_edit_rule_page_can_render_inline_search_results tests/test_routes.py::test_edit_rule_page_preserves_zero_episode_floor_in_form tests/test_routes.py::test_rule_form_includes_bulk_feed_selection_controls -q --basetemp=.pytest-tmp` passes.
- [x] Browser screenshot capture covers `/`, `/search`, `/settings`, `/rules/new`, `/import`, and `/taxonomy` at desktop and mobile widths.
- [x] Layout metrics confirm `scrollWidth <= clientWidth` for the target routes at desktop and mobile widths.
- [x] Full `cmd.exe /c scripts\check.bat` passes.
- [x] Shared Docker Compose rebuild succeeds and Docker `/health` returns `status=ok`.

## Status

- Status: implemented and locally/Docker validated on 2026-06-01, including stronger follow-up passes after visual QA found that some pages still read too much like the old UI and the rule edit page still used a narrow old-style results table.
- Implemented: compact base app bar markup, shared neutral/teal/rust design tokens, denser controls, tightened progress/search/settings/new-rule/import styling, visibly restyled rules command center and table rows, taxonomy console metric cards, mobile-safe quality matrix containment, compact scrollable operation history, full-width rule edit inline-results layout, visible edit-page quality profile strip, stable no-scroll edit result-table columns, compact icon row actions, mobile card-style edit rows, and static contract coverage.
- Follow-up implemented for `v1.2.1`: edit pages now expose a sticky compact command bar with save/search/sync/delete/back actions; long season/feed helper copy moved into accessible help bubbles; affected feeds render as a compact dropdown while preserving `feed_urls` checkboxes; inline result controls and queue options sit above the table; the result table gives title the primary dynamic column, narrows secondary columns/actions, and confines large result sets to table scrolling instead of page-wide overflow.
- Follow-up implemented for `v1.2.2`: `/rules` now renders the same compact rules workbench as `/`, matching the user-facing URL used in feedback.
- Follow-up implemented for `v1.2.3`: edit-page rule settings are collapsed behind a compact drawer by default so the first viewport stays focused on sticky actions, inline result controls, and the result table; expanding the drawer exposes the unchanged saved form fields.
- Follow-up implemented for `v1.2.4`: edit-page rule settings moved into a sticky desktop rail beside results instead of below them, and watch-state floor derivation now advances from watched `S05E09` to `S05E10` instead of using metadata's latest-released episode as proof that the season is complete and jumping to `S06E00`; prior next-season-zero over-advances can be corrected on sync.
- Follow-up implemented for `v1.2.5`: browser-side result filtering now mirrors server-side media/category incompatibility checks so Books/software/tutorial rows containing words such as `Hacks` stay hidden for series rules while valid TV rows remain visible.
- Follow-up implemented for `v1.2.6` through `v1.2.15`: after production QA showed the `v1.2.9` compacting pass made the page cramped and clipped, qB diagnostics moved into a compact disclosure, long rule checkbox explanations moved into accessible help text, Unified Query Results scope/source detail moved into compact disclosures, and active-filter chips gained bounded internal scrolling so controls remain readable without giant text blocks.
- Follow-up implemented on 2026-06-02: edit-page Rule settings now opens by default in the side rail, the start season/start episode floor controls are combined into one compact row, metadata lookup and quality-authority explanations are exposed through hover/focus help instead of visible helper paragraphs, and desktop inline results reserve the remaining workspace height for table-local scrolling rather than document scrolling.
- Feedback correction implemented on 2026-06-02: the edit-page Rule settings rail is now a non-collapsible settings panel, metadata/quality explanations live on the actual related inputs/buttons/labels rather than separate help icons, and desktop edit pages are viewport-contained so the result table is the only long-result scroll surface. The desktop Unified Query Results summary is hidden in the compact edit workspace to return usable height to the table.
- Internal-overlap correction implemented on 2026-06-02 after QA feedback: the previous rendered gate measured only high-level Rule settings vs results-panel rectangles, so it missed child overflow from the 4-column `Quality authority` panel into the adjacent 8-column `Criteria / Core Identity` section inside the narrow settings rail. The compact rule form now stacks both sections full-width (`grid-column: 1 / -1`), and targeted rendered metrics verify `parentOverlap=false` plus no Quality authority descendants intersect the Core Identity rectangle.
- Regression correction implemented for `v1.2.18` on 2026-07-14: verbose inline search warnings are grouped into one bounded notice region, hidden fetched-row display is explicitly summarized beside its toggle, and empty/table states are mutually exclusive. The desktop result workspace now uses a resilient flex column with internal scrolling and a guaranteed 10rem table viewport, preventing tables from collapsing to a one-pixel strip after warning-heavy searches. Live Docker browser validation against the reported Fauda rule confirmed that enabling hidden rows hides the empty panel and displays all 63 fetched rows in a usable table.
- Validation evidence: `node --check app/static/app.js` passed; focused route/static checks passed; full `cmd.exe /c scripts\check.bat` passed (`450 passed`, `292 warnings`); desktop build passed (`0 Warning(s)`, `0 Error(s)`); shared Docker Compose rebuild passed; Docker `/health` returned `status=ok` / `app_version=1.2.15`; Docker-served browser screenshots and scroll-segment captures wrote `logs/ui-feedback/compact-rules-v1215-qa-20260602`; layout metrics showed no desktop document scroll on the representative edit page at 1600px and 2048px, `scrollWidth == clientWidth`, no clipped Unified Query Results summary, no long checkbox prose in the visible rail, compact qB diagnostics, relevant `Hacks S5E01-10` TV rows visible, and unrelated hidden rows still hidden with local filter reasons.
