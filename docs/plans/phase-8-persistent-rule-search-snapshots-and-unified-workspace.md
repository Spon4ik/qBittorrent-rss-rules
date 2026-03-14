# Phase 8: Persistent Rule Search Snapshots and Unified Workspace

## Status

- Planning baseline created on 2026-03-14 from the next-version roadmap request.
- Phase 7 remains fully implemented and release-validated; new scope starts as phase 8.
- This phase is the active track for `v0.4.0` because it combines new persistence behavior with a substantial UX redesign.
- Scope wording adjusted on 2026-03-14: unified-table rendering now explicitly replaces standalone filter-impact diagnostics, and sorting requirements now explicitly describe interactive table-header behavior.
- Implementation has started on 2026-03-14 with snapshot persistence foundations and replay/refresh route wiring.
- Initial execution slice `P8-01`..`P8-03` is completed with route regression coverage and targeted/full `tests/test_routes.py` validation.
- `P8-04` is completed on 2026-03-14: `/search` and rule-inline rendering now use one unified result table/list keyed by query source, with standalone filter-impact panels removed and legacy snapshots auto-upgraded on replay.
- `P8-05` is completed on 2026-03-14: the edit-rule page now renders a sticky criteria rail plus adjacent results workspace on desktop, and collapses cleanly to a single-column flow on smaller viewports.
- `P8-06`..`P8-09` are completed on 2026-03-14: active-filter chips, header-driven sorting, compact queue controls, centralized snapshot-backed inline replay/refresh behavior, and deterministic browser closeout automation now align with unified-table contracts.
- Jackett query-shape hardening update completed on 2026-03-14: scoped indexer runs now omit default media-root `cat` narrowing when indexer category support is unknown, preventing hardcoded `cat=2000` assumptions in feed-scoped movie/series flows while retaining aggregate narrowing behavior.
- Rule-page regex/local-filter consistency update completed on 2026-03-14: episode-progress matching now accepts whole-season pack forms, inline rule pages auto-load saved snapshots by default, local clear-filters resets regex + episode-floor controls, and inline queue panel copy no longer duplicates potentially stale filtered/fetched counters.
- Unified local-filter/source-breakdown consistency update completed on 2026-03-14: local filtering no longer re-applies remote title/IMDb fetch scope by default, clearing local filters restores full fetched visibility, and per-source filtered counts now recompute from visible unified rows via `query_source_key` row metadata.
- DB-debugged local-filter indexer-scope decoupling completed on 2026-03-14: local filters no longer inherit feed-derived indexer constraints after `Clear local filters`, and inline rule results now reliably expand back to the full persisted fetched set unless explicit local filters are set.
- Inline affected-feed/table-only workspace refinement completed on 2026-03-14: affected-feed selections now scope inline unified results immediately by indexer, inline category/indexer local filters are restored in the result panel, and result controls are compacted to table-only with save-sort-default action.

## Goal

Deliver a rule-centric search workflow where each rule keeps a persisted, reusable search-result snapshot for local refinement, and users can refresh provider data only when they explicitly choose to.

## Requested roadmap scope (2026-03-14)

1. Persist search results per rule (not only in-memory page cache) so filtering logic can be tuned without re-querying Jackett each run.
2. Add explicit on-demand refresh for rule snapshots.
3. Redesign the rule page so filtering controls and results stay close together with minimal scrolling.
4. Remove the standalone `Filter impact` panel as part of unified-table rendering, so true empty IMDb-first states (`0 filtered / 0 fetched`) no longer expose misleading diagnostics.
5. Compact the `Queue to qBittorrent` area.
6. Redesign result interaction as an interactive table display where sorting is done from column titles (clear asc/desc indicators and compact multi-sort behavior).
7. Unify IMDb-first and title-fallback results into one table with a query-source key column.
8. Define a professional compact criteria model for both rule and result filtering surfaces.

## UX direction (recommended)

### Desktop IA

- Use a split workspace:
  - left sticky refinement rail (`Search criteria`, `Local filters`, `Queue defaults`) with internal scroll,
  - right main results region with sticky summary toolbar and unified table.
- Keep the page shell scrollable, but keep the left rail and result toolbar sticky so controls remain accessible.
- Keep advanced controls collapsed by default and expose active filter chips above the table for quick removal.

### Mobile IA

- Convert the left rail into a slide-over filter drawer with a persistent `Filters` button and active-filter counter.
- Keep queue + sort actions in a compact sticky bar above results.
- Preserve one-tap reset actions for filters and sorting.

### Why this over a fully non-scrollable left frame

- A fully fixed non-scrollable frame breaks on smaller viewport heights and hides controls.
- A sticky rail with internal scroll preserves constant access without sacrificing long-form criteria usability.
- The same interaction model degrades cleanly to mobile drawer behavior.

## In scope

- Add persisted per-rule search snapshot storage with metadata (`fetched_at`, source params, warning summaries).
- Add `Refresh snapshot` behavior that re-runs Jackett search for a rule and replaces the stored snapshot atomically.
- Load rule-page results from persisted snapshot by default when present.
- Merge IMDb-first and title-fallback rows into one normalized result table with query-source key labels.
- Remove the standalone filter-impact panel and keep only concise zero-state/result-context messaging in the unified table workflow.
- Redesign rule-page layout for compact criteria/filter/result proximity and reduced scroll.
- Replace sort-direction dropdown-heavy UX with interactive table-header sorting controls.
- Compact queue controls into a denser action bar while retaining advanced options and defaults.

## Out of scope

- Background/automatic refresh schedulers for rule snapshots.
- Replacing Jackett with another search provider.
- qBittorrent rule-schema rework unrelated to queue action UX compaction.
- Multi-user or remote-hosted collaboration behavior.

## Design decisions

1. Snapshot persistence contract
   - Persist one current snapshot per rule for immediate local refinement replay.
   - Refresh replaces the prior snapshot atomically.
   - Optional historical snapshot retention is deferred.

2. Refresh contract
   - `Run Search` on rule page uses stored snapshot if present and valid.
   - `Refresh snapshot` performs a provider call and rewrites snapshot.
   - UI exposes `Snapshot age` and `Last refreshed` timestamps.

3. Unified results contract
   - Render one table for all results.
   - Add `query_source` key per row (`IMDb-first` or `Title fallback`).
   - Keep dedup logic deterministic before rendering.

4. Unified-table diagnostics contract
   - Do not render a standalone filter-impact panel in rule/search results.
   - Show concise empty-state or active-filter summary messaging near the unified table header only.
   - Keep zero-result states actionable without per-filter diagnostic clutter.

5. Sorting interaction model
   - Sorting is controlled directly from interactive table column headers with visible direction glyphs.
   - Support compact one-click/tap direction toggle and optional multi-level sorting via modifier click.
   - Remove standalone direction dropdown from the primary workflow.

6. Queue control compaction
   - Keep primary action as one compact `Queue selected` / `Queue row` control.
   - Move advanced queue toggles (`paused`, `sequential`, `first/last`) into a concise expandable area.
   - Preserve persisted queue defaults behavior from phase 7.

7. Criteria compactness model
   - Promote chips/toggles for common filters; relegate low-frequency fields to collapsible advanced sections.
   - Keep active filter state visible near results to reduce context switching.

## Professional skill delegation

| Workstream | Primary skill | Supporting skills | Deliverable |
| --- | --- | --- | --- |
| Rule/results IA and compact interaction design | `ui-ux-designer` | `project-design-documentation-engineer` | Buildable wire/spec for sticky rail + unified table + compact queue/sort controls |
| Snapshot persistence model and refresh semantics | `jackett-api-expert` | `programming-sprint-manager` | Deterministic storage and refresh behavior for rule search snapshots |
| Execution sequencing and scope control | `programming-sprint-manager` | `project-management` | Slice board with resumable acceptance criteria |
| Regression and closeout strategy | `qa-engineer` | `project-management` | Risk-ranked test matrix and deterministic browser checks |
| Roadmap/status synchronization | `project-management` | `project-design-documentation-engineer` | Updated roadmap + phase + current-status alignment |

## Proposed implementation

1. Persistence model and migration
   - Files: `app/models.py`, `app/db.py`, `app/schemas.py`, `alembic/versions/*`.
   - Add rule-snapshot entities for normalized rows + metadata needed for replay and diagnostics.

2. Snapshot service layer
   - Files: `app/services/jackett.py`, new `app/services/rule_search_snapshots.py`.
   - Add helpers for save/load/replace snapshot and structured refresh metadata.

3. Route/API integration
   - Files: `app/routes/pages.py`, `app/routes/api.py`.
   - Add rule-page load path that prefers persisted snapshots.
   - Add explicit snapshot refresh endpoint/action.

4. Unified table model
   - Files: `app/routes/pages.py`, `app/templates/rule_form.html`, `app/templates/search.html`.
   - Merge primary/fallback rendering into one table with query-source badges.
   - Keep summary cards showing per-source fetched/filtered counts and replace standalone filter-impact with concise zero-state/context messaging.

5. Rule-page UX redesign and compact controls
   - Files: `app/templates/rule_form.html`, `app/static/app.css`, `app/static/app.js`.
   - Introduce sticky left refinement rail + sticky result toolbar.
   - Compact search criteria, queue controls, and local filter controls.

6. Sort/queue interaction redesign
   - Files: `app/static/app.js`, `app/templates/rule_form.html`, `app/templates/search.html`.
   - Implement interactive table-header sorting and compact queue action panels.

7. Test and QA coverage
   - Files: `tests/test_routes.py`, `tests/test_jackett.py`, `tests/test_qbittorrent_client.py`, `scripts/closeout_browser_qa.py`.
   - Add regressions for snapshot persistence, refresh behavior, unified table semantics, removal of standalone filter-impact, and compact interaction flows.

8. Documentation sync
   - Files: `README.md`, `docs/api.md`, `docs/architecture.md`, `ROADMAP.md`, `docs/plans/current-status.md`.
   - Document snapshot lifecycle, refresh UX, and unified result rendering contract.

## Acceptance criteria

- Running search for a rule produces a persisted snapshot that remains available across page reloads/restarts.
- Users can refresh a rule snapshot on demand and see updated `Last refreshed` metadata.
- Rule page keeps criteria and results visible together without long top-to-bottom navigation.
- The unified table flow does not render a standalone `Filter impact` panel; `0 fetched / 0 filtered` states show only concise empty-state context.
- Queue controls are visibly denser while preserving all queue behaviors.
- Sorting is driven from interactive table headers with compact direction indicators and clear asc/desc behavior.
- IMDb-first and title-fallback rows render in a single table with a query-source key.
- Mobile and desktop layouts remain usable with minimal scroll overhead.

## Dated execution checklist (2026-03-14 baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P8-01 | Add rule snapshot persistence model + migration. | Codex | 2026-03-16 | completed | DB schema stores one refreshable snapshot per rule with metadata. | `app/models.py::RuleSearchSnapshot`, `alembic/versions/0004_rule_search_snapshots.py`, route persistence assertions in `tests/test_routes.py::test_edit_rule_page_can_render_inline_search_results` |
| P8-02 | Implement snapshot save/load/replace service helpers. | Codex | 2026-03-16 | completed | Service can atomically replace snapshots and return replay payloads for UI. | `app/services/rule_search_snapshots.py::{save_rule_search_snapshot,get_rule_search_snapshot,inline_search_from_snapshot,build_inline_search_payload}`, regressions in `tests/test_routes.py::test_edit_rule_inline_search_replays_saved_snapshot_without_jackett_call` and `tests/test_routes.py::test_edit_rule_inline_search_refreshes_and_persists_snapshot` |
| P8-03 | Add rule-page refresh and replay route/API wiring. | Codex | 2026-03-17 | completed | Rule page can load persisted snapshot and refresh on demand. | `app/routes/pages.py` (`run_search` snapshot replay + `refresh_snapshot=1` refresh path), `app/templates/rule_form.html` refresh action link, `tests/test_routes.py::test_run_rule_search_route_preserves_refresh_snapshot_flag` |
| P8-04 | Unify IMDb-first/title-fallback rows into one table with query key and remove standalone filter-impact panel. | Codex | 2026-03-18 | completed | One normalized table renders both sources with source key column and deterministic dedup, while zero-result states show concise context only. | `app/services/rule_search_snapshots.py` unified payload + snapshot-compat upgrade, `app/templates/search.html` + `app/templates/rule_form.html` unified `combined` sections, `app/static/app.js` dynamic section handling, `tests/test_routes.py` unified-table/filter-impact regressions, `./scripts/test.sh tests/test_routes.py` (`66 passed`) |
| P8-05 | Redesign rule page into sticky refinement rail + results workspace. | Codex | 2026-03-19 | completed | Desktop uses split sticky layout; mobile uses responsive single-column stack with preserved interactions. | `app/templates/rule_form.html` workspace shell (`rule-workspace` rail/results), `app/static/app.css` sticky rail + responsive fallback, `tests/test_routes.py::test_edit_rule_page_can_render_inline_search_results`, `./scripts/test.sh tests/test_routes.py` (`66 passed`) |
| P8-06 | Compact criteria controls and active-filter chips to minimize scrolling. | Codex | 2026-03-19 | completed | Common controls remain visible; advanced controls are collapsible without losing discoverability. | Compact collapsible criteria sections + active-filter chip rail + clear-local-filters actions in unified result-view panel (`app/templates/search.html`, `app/templates/rule_form.html`, `app/static/app.css`, `app/static/app.js`), plus route assertions (`tests/test_routes.py`). |
| P8-07 | Redesign sort + queue controls (interactive table-header sorting + compact queue toolbar). | Codex | 2026-03-20 | completed | Standalone direction dropdown removed from primary flow; interactive column sorting and queue panel density improvements preserve current behaviors. | Header-click sort controls with asc/desc glyphs and Shift+click multi-sort in both unified tables, compact queue disclosures on `/search` and inline rule view (`app/templates/search.html`, `app/templates/rule_form.html`, `app/static/app.js`, `app/static/app.css`), plus route/browser regressions. |
| P8-08 | Finalize unified-table empty-state diagnostics without standalone filter-impact panel. | Codex | 2026-03-20 | completed | `0 fetched / 0 filtered` states never render separate filter-impact blocks and still provide actionable context. | Removed remaining JS/CSS filter-impact rendering paths, preserved concise unified empty states, and kept route regressions asserting no `data-filter-impact-list` markup (`app/static/app.js`, `app/static/app.css`, `tests/test_routes.py`). |
| P8-09 | Extend deterministic browser closeout for new workspace contracts. | Codex | 2026-03-21 | completed | Closeout covers snapshot replay/refresh, unified table, interactive column sorting, compact queue, and empty-state diagnostics. | Updated `scripts/closeout_browser_qa.py` for unified `combined` sections + header sorting + chip/queue expectations, raised isolated app startup timeout for local import latency, and validated `./scripts/closeout_qa.sh` (`14/14` pass; `logs/qa/phase-closeout-20260314T141253Z/closeout-report.md`). |
| P8-10 | Closeout docs and release-target sync for v0.4.0. | Codex | 2026-03-21 | in_progress | `ROADMAP.md`, phase plan, and `current-status` are aligned with implementation state. | phase/status sync in progress; Jackett scoped-category hardening validated via `./scripts/test.sh tests/test_jackett.py` (`37 passed`), targeted route scope regressions (`6 passed`), and static checks (`ruff`/`mypy`) on `app/services/jackett.py`; regex/snapshot/filter consistency slice validated via `./scripts/test.sh tests/test_rule_builder.py` (`18 passed`), `./scripts/test.sh tests/test_routes.py` (`69 passed`), and browser closeout `logs/qa/phase-closeout-20260314T161529Z/closeout-report.md`; local-filter/source-breakdown consistency slice validated via targeted route regression run (`5 passed`), full `tests/test_routes.py` (`69 passed`), static checks (`ruff`/`mypy`), and browser closeout `logs/qa/phase-closeout-20260314T165253Z/closeout-report.md`; DB-debugged clear-filter regression fix validated via `./scripts/test.sh tests/test_routes.py -k "inline_feed_scope_indexer_matching_uses_key_variants or inline_local_generated_pattern_uses_raw_title_surface or edit_rule_page_can_render_inline_search_results"` (`3 passed`), full `./scripts/test.sh tests/test_routes.py` (`70 passed`), and Playwright repro at `/rules/a39a2ad3-de32-4a68-8d9b-284aa88f2b74` (`0/539` before clear -> `539/539` after clear); affected-feed/table-only refinement validated via full `./scripts/test.sh tests/test_routes.py` (`70 passed`) plus browser verification at `/rules/a39a2ad3-de32-4a68-8d9b-284aa88f2b74` (`313/539` baseline with selected feeds, `0/539` after feed clear-all, `7/539` after single-feed selection, category filter options restored, table-only controls confirmed). |
