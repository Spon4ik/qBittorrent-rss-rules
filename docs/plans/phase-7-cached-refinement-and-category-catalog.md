# Phase 7: Cached Refinement Responsiveness and Category Catalog Integrity

## Status

- Planning baseline created on 2026-03-12.
- This phase is intentionally separated from phase 6 to avoid widening the v0.2.0 release slice after closeout.
- Implementation is active: `P7-01`..`P7-04` are complete; `P7-05` and `P7-06` are in progress.
- Follow-up UX integration slice `P7-08` is in progress: saved-rule `Run Search` now renders inline results on `/rules/{id}` with queue-to-qB actions, but browser closeout evidence and full QA-gate reruns are pending.
- Extension slice execution is active: `P7-09` is completed in code/tests; `P7-10`/`P7-11`/`P7-12` implementation is landed and awaiting deterministic browser QA evidence; `P7-13` closeout remains pending.
- Follow-up request handling is active: feed-scope parser hardening for Torznab URL variants and episode-progress floor filtering fields are implemented with targeted regressions (`P7-14`).
- Added persistent category-catalog foundations in this branch (`IndexerCategoryCatalog` model + Alembic migration + catalog service write/read helpers + `/search` persistence wiring).
- `/search` category options now refresh from cached results scoped by current non-category filters, with per-option count badges, explicit inactive-state labeling for stale selections, and a dynamic status note that explains category-only narrowing vs stale selections.

## Goal

Deliver a `/search` refinement experience where cached-result filtering is immediately responsive across all local controls and `Result categories` always represent valid, explainable categories derived from the current result set.

## Requested scope extension (2026-03-12 handoff)

Implement rule-page inline-search parity for the following requested outcomes:

1. Search must respect rule `Affected feeds` selection.
2. `Generated pattern preview` changes must immediately refine cached inline results.
3. Queue actions must respect `Queue options -> Add paused`.
4. Inline rule-page results must use tabular default rendering with the same sort behavior as `/search`.
5. Rule form should support an episode-progress floor (`Start season` + `Start episode`) that keeps only results at/after that point, including range variants like `S03E01-07`.

This extension remains in phase 7 because it is a cached-refinement UX contract hardening slice and does not add new persistence models.

## Why this phase exists

- Local refinement should feel instant once a Jackett result pool is cached; users should not need a new remote search to see filter effects.
- Current category filter UX can present inconsistent/unclear options (for example, a category label appears but selecting it yields zero results).
- Category provenance must be explicit and auditable: category IDs from results should map through a normalized indexer-category catalog before being exposed as filter options.

## In scope

- Ensure every local refinement control applies immediately to cached results without new Jackett requests.
- Harden client-side refinement plumbing so `Generated pattern preview`, quality sliders, category/indexer selections, and free-text fields all share one deterministic local-filter pipeline.
- Introduce a persistent normalized category catalog store keyed by `(indexer, category_id)` with a human label and update metadata.
- Build category option generation from cached result rows joined with the normalized catalog, so only categories present in cached results are selectable.
- Improve `Result categories` visual design and interaction density for desktop/mobile.
- Add diagnostics to explain category availability and prevent “ghost category” confusion.
- Ensure rule-page inline search uses feed-aware scoping derived from the rule's selected `feed_urls`.
- Bring rule-page inline result rendering/interaction to `/search` parity for table-first view + shared multi-level sorting.
- Ensure rule-page inline cached filtering reacts to generated regex/pattern changes without remote Jackett calls.
- Keep queue-option semantics explicit and deterministic for `add_paused`.
- Keep the saved-rule search trigger on the rule edit page and render search results inline below the rule form, with advanced `/search` workspace kept as an explicit optional path.
- Add queue actions on rendered search results so users can enqueue directly into qBittorrent with rule defaults plus optional queue behavior toggles.

## Out of scope

- Background scheduled category sync jobs.
- Replacing Jackett as the provider or changing the IMDb-first/title-fallback search model.
- Adding persistent Jackett-backed rule sources (separate product decision).
- Reworking qBittorrent RSS rule schema.

## Design decisions

1. Local-first responsiveness contract
   - After a search response is cached in page state, all refinement edits must recompute locally.
   - No local-filter control may trigger additional Jackett network calls.
   - UI should show that refinement is local (no spinner that implies network activity).

2. Category catalog source of truth
   - Add a DB table: `indexer_category_catalog`.
   - Canonical columns: `indexer`, `category_id`, `category_name`, `source`, `updated_at`.
   - Primary key: `(indexer, category_id)`.
   - `source` values: `result_attr`, `indexer_caps`, `manual_fallback`.

3. Category option derivation rule
   - `Result categories` options must be derived only from categories that actually appear in the cached result pool.
   - Display labels come from catalog join by `(indexer, category_id)`.
   - If no catalog label exists, render deterministic fallback label `Category #<id>`.
   - Distinct option list is scoped to current cached results, not global catalog inventory.

4. Explainability rule
   - For each rendered category option, keep a visible count badge.
   - Category option selection that yields zero results must surface explicit blocker diagnostics (which other filters eliminated matches).
   - Never show orphan labels disconnected from current cached rows.

5. Feed-aware rule-search contract
   - Rule-page inline search must derive Jackett indexer scope from selected `feed_urls` when those URLs are Jackett Torznab endpoints.
   - For one derived indexer: run remote request with that indexer slug.
   - For multiple derived indexers: keep remote `indexer=all` fetch but enforce local `filter_indexers` to derived set so rendered results only reflect affected feeds.
   - For non-Jackett/unparseable feed URLs: keep current fallback behavior and show a warning that feed scoping could not be derived.

6. Inline parity contract
   - Rule-page inline results must expose the same cached data contract used by `/search` (`raw_results` + visibility flags + sortable metrics).
   - Table view must be default and use the same 3-level sort criteria logic as `/search`.
   - Queue actions must always send an explicit `add_paused` boolean from current queue-option checkbox state.

7. Pattern-driven cached refinement contract
   - Rule-page generated pattern preview changes must trigger local-only result recompute.
   - Filtering logic should compile and apply the same generated regex semantics used for rule generation (include/exclude/mustContain/mustNotContain), not an independent ad hoc matcher.
   - No Jackett request is allowed for these local refinements once inline cache is present.

## Professional skill delegation

| Workstream | Primary skill | Supporting skills | Deliverable |
| --- | --- | --- | --- |
| UX interaction model for local refinement + category controls | `ui-ux-designer` | `project-design-documentation-engineer` | Wire/state spec for responsive controls, improved category selector visuals, and empty/blocker states |
| Torznab category metadata normalization and fallback behavior | `jackett-api-expert` | `programming-sprint-manager` | Service-layer mapping rules, capability-derived enrichment, and deterministic merge behavior |
| Incremental engineering execution slices | `programming-sprint-manager` | `project-management` | Slice board, sequencing, and status updates with explicit done criteria |
| Risk-based verification and regression gates | `qa-engineer` | `project-management` | Test plan, scenario matrix, severity-ranked findings, release recommendation |
| Planning/status/roadmap synchronization | `project-management` | `project-design-documentation-engineer` | Updated phase plan, current-status handoff, roadmap/version intent alignment |

## Proposed implementation

1. Persistence and models
   - Files: `app/models.py`, `app/db.py`, `alembic/versions/*`, `app/schemas.py`.
   - Add `IndexerCategoryCatalog` model/table and migration support.
   - Keep existing search result schema backward compatible while adding category-catalog metadata fields needed by UI.

2. Category normalization service
   - Files: `app/services/jackett.py`, optional new module `app/services/category_catalog.py`.
   - Upsert catalog entries from:
     - normalized result attributes (`category_ids`, discovered labels),
     - indexer capability payloads (`t=indexers`) when available.
   - Add deterministic resolution helper:
     - input: result `(indexer, category_id[])`
     - output: resolved labels + unresolved IDs.

3. Search route integration
   - Files: `app/routes/pages.py`, `app/routes/api.py`.
   - During search result normalization:
     - persist/refresh catalog mappings,
     - attach category option payload scoped to cached results.
   - Ensure local refinement endpoints/flows do not require new Jackett fetch for category list updates tied to local controls.

4. Frontend refinement responsiveness hardening
   - Files: `app/templates/search.html`, `app/static/app.js`, `app/static/app.css`.
   - Consolidate local-filter recomputation triggers so all relevant controls refresh:
     - `Generated pattern preview`
     - quality token sliders
     - `additional_includes` / `must_not_contain`
     - indexer/category selections
     - year/size/availability toggles
   - Replace/refresh `Result categories` UI with cleaner multi-select + count badges + clearer labels.

5. Diagnostics and debuggability
   - Files: `app/static/app.js`, `app/templates/search.html`, `logs/search-debug.log` emitter paths.
   - Add category-specific filter-impact diagnostics:
     - selected categories,
     - matched row counts before/after each active filter family,
     - reason when selected category appears but ends at zero after other filters.

6. Test coverage
   - Files: `tests/test_jackett.py`, `tests/test_routes.py`, optional `tests/test_category_catalog.py`.
   - Add coverage for:
     - category catalog upsert and join behavior,
     - category option derivation from cached results only,
     - immediate local refinement updates without remote calls,
     - mixed-indexer category ID collisions mapped correctly by indexer key,
     - ghost-category regression scenario (`Cartoons`-style mismatch case).

7. Documentation
   - Files: `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/plans/current-status.md`, `ROADMAP.md`.
   - Document category-catalog semantics and local refinement responsiveness contract.

## Acceptance criteria

- Local refinement controls on `/search` update filtered counts and result rendering immediately against cached data.
- No extra Jackett network request occurs when changing local-only filters.
- `Result categories` options are derived only from categories present in cached results.
- Category labels are resolved by `(indexer, category_id)` catalog mapping with deterministic fallback for unknowns.
- Selecting a category that appears in options is explainable via diagnostics when final result is zero (for example, blocked by other active filters).
- UI for category filtering is visually clearer and remains usable on desktop and mobile.

## Dated execution checklist (2026-03-12 baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P7-01 | Lock UX behavior contract for local refinement responsiveness and category control states. | Codex | 2026-03-13 | completed | Wire/state spec documents trigger-to-update mapping and UI states (`default/loading/empty/error/blocked`). | `docs/plans/phase-7-cached-refinement-and-category-catalog.md` (`Design decisions` section, 2026-03-12) |
| P7-02 | Introduce normalized category catalog persistence model and migration. | Codex | 2026-03-14 | completed | DB has `indexer_category_catalog` with unique `(indexer, category_id)` and service write/read paths tested. | `app/models.py`, `alembic/versions/0002_indexer_category_catalog.py`, `app/services/category_catalog.py`, `tests/test_category_catalog.py` |
| P7-03 | Implement catalog enrichment + join-based category resolution in search normalization. | Codex | 2026-03-15 | completed | Search normalization emits category labels via catalog join and deterministic unknown fallback. | `app/routes/pages.py` catalog sync/resolve wiring, `tests/test_routes.py::test_search_page_persists_indexer_category_catalog_entries`, `tests/test_category_catalog.py` |
| P7-04 | Rework `Result categories` UI for readability and explainability. | Codex | 2026-03-16 | completed | Multi-select UI with counts and clearer labels ships on `/search` desktop/mobile breakpoints. | `app/static/app.js` scoped options + count badges + scope-status diagnostics, `app/static/app.css` multiselect readability styles, `app/templates/search.html` helper text + status target |
| P7-05 | Guarantee immediate cached-result recomputation for all local filter controls. | Codex | 2026-03-16 | in_progress | Changing any local control updates rendered results without remote fetch. | `scripts/closeout_browser_qa.py` phase-6 local-filter checks remain network-free after category-scope UI changes (`P6-02`/`P6-03`/`P6-04` pass in `logs/qa/phase-closeout-20260312T004852Z/closeout-report.md`) |
| P7-06 | Add regression tests for ghost-category mismatch and mixed-indexer category collisions. | Codex | 2026-03-17 | in_progress | New regression tests fail on old behavior and pass on new implementation. | Added collision + ambiguous-label regressions in `tests/test_category_catalog.py` and route-level collision persistence in `tests/test_routes.py`; remaining ghost-category end-to-end case still pending |
| P7-07 | Run full quality gates and closeout docs sync. | Codex | 2026-03-17 | pending | `./scripts/check.sh` and `./scripts/closeout_qa.sh` pass (or documented known non-phase blocker); roadmap/status/phase docs synchronized. | test logs + updated docs |
| P7-08 | Keep saved-rule search inline on `/rules/{id}` and add queue-to-qB actions with rule defaults. | Codex | 2026-03-18 | in_progress | `Run Search` keeps the user on the rule page, inline results render primary/fallback sets, and queue actions post to `/api/search/queue` with visible success/failure status. | `app/routes/pages.py` inline-search path, `app/routes/api.py` queue endpoint, `app/static/app.js` queue action handler, `tests/test_routes.py` inline-search + queue API tests |
| P7-09 | Add feed-aware search scoping from rule `feed_urls` to inline-search payload construction. | Codex | 2026-03-18 | completed | Inline `Run Search Here` restricts results to rule-affected feed/indexer scope where derivable, with explicit fallback warning when not derivable. | `app/routes/pages.py` feed URL parser + scope wiring; `tests/test_routes.py::{test_edit_rule_inline_search_scopes_single_jackett_feed_indexer,test_edit_rule_inline_search_scopes_multiple_jackett_feed_indexers,test_edit_rule_inline_search_warns_when_feed_scope_not_derivable,test_search_page_from_rule_uses_structured_terms_not_raw_regex}` |
| P7-10 | Wire generated-pattern-driven local recompute for inline cached results. | Codex | 2026-03-19 | in_progress | Changing rule form fields that affect `Generated pattern preview` immediately updates inline filtered counts/results without Jackett requests. | `app/static/app.js` now compiles inline generated pattern from live rule-form state via `getGeneratedPatternForFilters`; deterministic browser no-network evidence still pending |
| P7-11 | Enforce queue `Add paused` semantics end-to-end on inline and `/search` results. | Codex | 2026-03-19 | in_progress | Queue action payload always carries explicit `add_paused` checkbox state and backend behavior reflects the chosen value. | Shared queue JS posts explicit `add_paused` + existing API coverage in `tests/test_routes.py::test_queue_search_result_api_*`; deterministic browser payload assertion still pending |
| P7-12 | Make inline results table-first with `/search` sorting parity. | Codex | 2026-03-20 | in_progress | Inline results default to table mode and apply the same multi-level sorting fields/directions as `/search`. | `app/templates/rule_form.html` now renders `/search`-parity `data-search-controls` + card/table containers; route render assertion added in `tests/test_routes.py::test_edit_rule_page_can_render_inline_search_results`; browser sorting evidence pending |
| P7-13 | QA closeout for extension slice (feed scope + inline recompute + queue + table/sort parity). | Codex | 2026-03-20 | pending | Targeted tests + deterministic closeout checks pass (or documented non-phase blocker) with dated artifacts. | Planned evidence in `logs/tests/` + `logs/qa/phase-closeout-*` |
| P7-14 | Fix feed-scope Torznab URL variant parsing and add episode-progress floor fields (`Start season`, `Start episode`) with regex parity in backend/frontend. | Codex | 2026-03-21 | completed | Excluded feed indexers no longer leak due URL-shape parsing misses; new floor fields persist and generate regex matching `SxxExx` and `SxxExx-yy` variants at/after the configured point. | `app/routes/pages.py` Torznab parser update; `app/models.py` + `app/schemas.py` + `app/routes/api.py` + `app/services/rule_builder.py` + `app/static/app.js` + `app/templates/rule_form.html`; tests in `tests/test_routes.py` and `tests/test_rule_builder.py` |
| P7-15 | Persist queue defaults for `Sequential download` + `First and last pieces first`, and enforce affected-feed filtering from current rule-form selection in inline results/search runs. | Codex | 2026-03-21 | completed | Queue option defaults are saved and reloaded for search/inline queue panels; inline `Run Search Here` and cached local filtering honor current checked `Affected feeds` (including unsaved form state). | `app/models.py` + `app/services/settings_service.py` + `app/routes/api.py` + `app/routes/pages.py` + `app/static/app.js` + templates + migration `0003`; route regressions in `tests/test_routes.py` |

## Slice implementation plan (P7-09..P7-13)

### P7-09 Feed-aware scoping

Progress (2026-03-12):
- Completed: rule/search route payloads now apply feed-derived indexer scoping with single/multi-indexer handling plus unparseable-feed warning notices.
- Completed: route regressions added for single, multi, and unparseable feed URL cases.

Files:
- `app/routes/pages.py`
- optional helper in `app/services/jackett.py` or new local helper in `pages.py`
- `tests/test_routes.py`

Implementation:
- Add deterministic parser for Jackett feed URLs that extracts indexer slug from `/api/v2.0/indexers/{slug}/results/torznab/api`.
- Derive `rule_feed_indexers` from `Rule.feed_urls` when running inline rule search.
- Apply behavior:
  - one indexer -> `payload.indexer = slug`
  - many indexers -> keep remote `indexer=all`, inject local `filter_indexers` with derived set
  - none derivable -> keep current behavior + inline warning
- Expose derived indexer context in inline-search summary for diagnostics.

Done criteria:
- Inline results never include non-derived indexers when derivation succeeds.
- Warning appears when feed URLs are not Jackett-derivable.

Tests:
- single feed URL -> only that indexer queried/rendered
- multi feed URLs -> `filter_indexers` enforced locally
- non-Jackett feed URL -> fallback warning path

### P7-10 Generated-pattern local recompute

Progress (2026-03-12):
- In progress: inline local filtering now derives generated-pattern regex from live rule-form state (`derivePattern`) during filter evaluation, avoiding preview-update timing lag.
- Remaining: deterministic browser evidence that rule-form edits update cached inline results immediately without remote Jackett calls.

Files:
- `app/templates/rule_form.html`
- `app/static/app.js`
- `tests/test_routes.py` (render contract), browser closeout checks

Implementation:
- Add inline result cache payload script for rule-page results similar to `search-run-cache`.
- Reuse/refactor search local-filter engine so rule-page mode can run the same cached filtering pipeline.
- Bind rule-form inputs affecting `deriveGeneratedPattern` to inline result recompute.
- Ensure no network request is triggered by local edits after cache is present.

Done criteria:
- Changing any pattern-driving input updates inline filtered counts/results instantly.
- No Jackett call on local edits.

Tests/QA:
- deterministic browser check: toggle quality token and free-text fields; verify counts change without network.
- route template assertions for inline cache payload presence.

### P7-11 Queue `Add paused` semantics

Progress (2026-03-12):
- In progress: shared queue JS always sends explicit `add_paused` boolean from current checkbox state; backend queue API tests for pause defaults remain passing.
- Remaining: deterministic browser assertion that toggling `Add paused` changes queue behavior/message in inline and `/search` flows.

Files:
- `app/static/app.js`
- `tests/test_routes.py`
- optional closeout check updates in `scripts/closeout_browser_qa.py`

Implementation:
- Keep explicit `add_paused` in queue payload from checkbox state for both `/search` and inline rule views.
- Add UI status text confirming resolved paused behavior returned by API.

Done criteria:
- Checked -> API receives `add_paused=true`.
- Unchecked -> API receives `add_paused=false`.
- Behavior is consistent for rule-bound and non-rule queue actions.

Tests:
- extend/keep API tests and add frontend integration assertions in browser QA.

### P7-12 Table-first + sort parity

Progress (2026-03-12):
- In progress: inline rule-page result sections now render `/search`-parity result-view controls + table/card data attributes with table default.
- Remaining: deterministic browser evidence for sort-order behavior across at least two sort-field combinations.

Files:
- `app/templates/rule_form.html`
- `app/static/app.js`
- optional shared template partial extraction from `search.html`
- `tests/test_routes.py` + browser closeout checks

Implementation:
- Render inline results with the same card/table containers and sortable data attributes as `/search`.
- Default inline view mode to `table`.
- Reuse shared sort criteria controls (`published_at`, `seeders`, `peers`, `leechers`, `grabs`, `size_bytes`, `year`, `indexer`, `title`) and same 3-level comparator.

Done criteria:
- Inline page opens with table visible by default.
- Sorting changes reorder both table and card views consistently.

Tests/QA:
- template assertions for sort controls + table markup.
- browser QA sorting checks for at least 2 sort-field combinations.

### P7-13 Closeout

Validation command set:
- `./.venv-linux/bin/ruff check app/routes/pages.py app/static/app.js app/templates/rule_form.html tests/test_routes.py`
- `./scripts/test.sh tests/test_routes.py tests/test_category_catalog.py -k "inline_search or queue_search_result_api or run_rule_search_route_redirects_to_inline_rule_page or category_catalog"`
- `./scripts/closeout_qa.sh`

Artifact expectations:
- updated `logs/tests/pytest-last.{log,xml}`
- updated `logs/qa/phase-closeout-*/closeout-report.{md,json}`

Closeout docs:
- update `docs/plans/current-status.md` (implemented/in-progress/next)
- update this phase doc statuses/evidence for `P7-09..P7-13`

### P7-14 Feed parser hardening + episode-progress floor

Progress (2026-03-12):
- Completed: feed URL parsing now accepts both Jackett Torznab endpoint shapes (`.../torznab` and `.../torznab/api`) so affected-feed scope derivation is not dropped due path variant.
- Completed: rule form now includes `Start season` and `Start episode` fields (paired validation) that persist and contribute to generated regex.
- Completed: backend/frontend regex builders now include an episode-progress floor fragment matching season/episode floor variants (for example `S03E07`, `S3E7`, `S03E01-07`, `S03E1-7`, later seasons).

Validation evidence:
- `./.venv-linux/bin/ruff check app/routes/pages.py app/routes/api.py app/services/rule_builder.py app/schemas.py app/models.py app/db.py tests/test_rule_builder.py tests/test_routes.py` (`All checks passed`, 2026-03-12)
- `./scripts/test.sh tests/test_rule_builder.py tests/test_routes.py -k "start_season or floor or inline_search_scopes_single_jackett_feed_indexer or create_rule_persists_locally_even_without_qb_config or create_rule_rejects_incomplete_episode_progress_floor"` (`4 passed`, `72 deselected`, 2026-03-12)

### P7-15 Queue defaults persistence + affected-feed live scope

Progress (2026-03-12):
- Completed: `Sequential download` and `First and last pieces first` are now persisted as app defaults and pre-checked on search/inline queue panels from saved settings.
- Completed: saving search defaults now persists queue defaults alongside view/sort defaults.
- Completed: inline `Run Search Here` now carries current checked `Affected feeds` (unsaved form state) into run-time feed scoping; inline local cached filtering also constrains by current checked feeds.

Validation evidence:
- `./.venv-linux/bin/ruff check app/models.py app/db.py app/services/settings_service.py app/routes/api.py app/routes/pages.py app/schemas.py tests/test_routes.py alembic/versions/0001_initial_schema.py alembic/versions/0003_search_queue_defaults.py` (`All checks passed`, 2026-03-12)
- `./scripts/test.sh tests/test_routes.py -k "run_rule_search_route_redirects_to_inline_rule_page or run_rule_search_route_preserves_feed_url_overrides or edit_rule_inline_search_scopes_single_jackett_feed_indexer or edit_rule_inline_search_uses_feed_url_override_scope or save_search_preferences_api_persists_defaults or save_settings_persists_profile_management_tokens or queue_search_result_api_uses_rule_defaults or queue_search_result_api_uses_settings_default_pause_when_no_rule"` (`8 passed`, `53 deselected`, 2026-03-12)

## Validation checklist

- Run targeted tests first:
  - `./scripts/test.sh tests/test_jackett.py`
  - `./scripts/test.sh tests/test_routes.py -k "search_page or category"`
- Current status (2026-03-12):
  - `./scripts/test.sh tests/test_category_catalog.py tests/test_routes.py -k "category_catalog or search_page_persists_indexer_category_catalog_entries"` (`4 passed`, `49 deselected`)
  - `./scripts/test.sh tests/test_routes.py -k "search_page_prefills_new_rule_from_active_search or search_page_embeds_raw_cache_payload_for_local_refinement or search_page_accepts_repeated_multiselect_filter_params or search_page_persists_indexer_category_catalog_entries"` (`4 passed`, `46 deselected`)
  - `./scripts/test.sh tests/test_routes.py -k "search_page_embeds_raw_cache_payload_for_local_refinement or search_page_accepts_repeated_multiselect_filter_params or search_page_persists_indexer_category_catalog_entries or search_page_expands_quality_token_terms_for_search_payload"` (`4 passed`, `46 deselected`)
  - `./scripts/test.sh tests/test_category_catalog.py tests/test_jackett.py -k "can_filter_by_category_label_across_indexers or can_enrich_result_category_labels_without_label_filter or category_catalog"` (`5 passed`, `29 deselected`)
  - `./.venv-linux/bin/ruff check app/services/category_catalog.py app/routes/pages.py app/services/jackett.py tests/test_category_catalog.py tests/test_routes.py` (`All checks passed`)
  - `./.venv-linux/bin/mypy app/services/category_catalog.py app/routes/pages.py` (`Success: no issues found in 2 source files`)
  - `./scripts/test.sh tests/test_category_catalog.py tests/test_routes.py -k "category_catalog or persists_indexer_category_catalog_entries or resolves_colliding_category_ids_per_indexer or embeds_raw_cache_payload_for_local_refinement"` (`8 passed`, `48 deselected`)
  - `./.venv-linux/bin/ruff check tests/test_category_catalog.py tests/test_routes.py app/routes/pages.py app/services/category_catalog.py app/services/jackett.py` (`All checks passed`)
  - `./scripts/test.sh tests/test_routes.py -k "run_rule_search_route_redirects_to_inline_rule_page or rule_pages_expose_run_search_actions or inline_search_results or queue_search_result_api"` (`6 passed`, `49 deselected`)
  - `./scripts/test.sh tests/test_category_catalog.py tests/test_routes.py -k "category_catalog or run_rule_search_route_redirects_to_inline_rule_page or rule_pages_expose_run_search_actions or inline_search_results or queue_search_result_api"` (`12 passed`, `49 deselected`)
  - `./.venv-linux/bin/ruff check app/routes/pages.py app/services/category_catalog.py tests/test_routes.py` (`All checks passed`)
  - `./scripts/closeout_qa.sh` (`10/11` checks pass; phase-5/phase-6 checks all pass including updated category multiselect path, one pre-existing phase-4 `P4-01` failure remains, 2026-03-12, `logs/qa/phase-closeout-20260312T004852Z/closeout-report.md`)
- Run full quality gates:
  - `./scripts/check.sh`
- Run deterministic browser closeout:
  - `./scripts/closeout_qa.sh`
- Add/refresh UI captures for `/search`:
  - `./scripts/capture_ui.sh`
- Execute focused manual smoke scenario for the reported mismatch:
  - Search `shrinking` style title
  - Confirm displayed category options have non-zero source counts
  - Select one category and verify either matching results remain or blocker diagnostics clearly identify conflicting filters
- Execute focused manual smoke scenario for inline rule-page workflow:
  - Open `/rules/{id}` and click `Run Search Here`
  - Confirm page remains on `/rules/{id}?run_search=1#inline-search-results`
  - Queue a result with sequential/first-last options and confirm status feedback

## Risks and mitigations

- Risk: category mappings differ across indexers and drift over time.
  - Mitigation: indexer-scoped keying + timestamped catalog updates + unknown fallback labels.
- Risk: local-filter recompute path grows too complex and regresses responsiveness.
  - Mitigation: single recompute function, debounced UI events where needed, targeted regression coverage.
- Risk: UX density improvements reduce clarity.
  - Mitigation: run `ui-ux-designer` checklist + desktop/mobile screenshot review before merge.

## Dependencies

- Existing phase-6 local refinement model and cached-result payload contract.
- Stable Jackett capability/indexer metadata endpoint behavior (`t=indexers`) for enrichment when available.
- Local test environments with project dependencies installed (`.venv` or `.venv-linux`).

## Roll-forward notes

- If persistent search-source management is approved later, keep catalog storage reusable and independent from RSS feed source storage.
- If category-level personalization is added later (hiding unwanted categories), store user preferences separately from normalized catalog facts.
