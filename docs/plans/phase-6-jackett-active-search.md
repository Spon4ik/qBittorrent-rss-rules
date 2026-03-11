# Phase 6: Jackett-Backed Active Search

## Status

- Implementation is complete in the repo for the v0.2.0 release slice.
- Phase 5 closeout automation is green and phase 6 initial goals are release-validated; follow-up decisions move to v0.2.x.
- The current branch now includes separate Jackett app/qB connection settings, a `/search` page, one-click rule-level search launch links, and search-to-rule handoff without mixing Jackett search into RSS feed selection.
- Rule-derived searches now clamp overlong saved titles before validation and can still auto-run a title-only fallback when reduced keyword derivation remains invalid.
- Rule-derived searches now also reuse saved IMDb IDs, release years, and media-type category narrowing when those fields are available, so Jackett can receive richer Torznab parameters than `q` alone.
- IMDb-based Jackett narrowing now sends the full `tt1234567` identifier format that Jackett expects, avoiding `400 Bad Request` responses from the richer Torznab mode.
- Richer Torznab requests now retry `400 Bad Request` responses in stages, preserving `imdbid` where possible before falling back to broad text search only as a last resort.
- The `/search` UI now auto-enforces an IMDb-first path for movie/series lookups whenever an IMDb ID is present, using strict `imdbid` requests only for primary IMDb-first fetches; if the aggregate `all` indexer rejects the request, the app retries only direct indexers that advertise `imdbid` input support, and broader title text matching remains isolated in the separate `Title fallback` section.
- Jackett Torznab XML error bodies such as `<error code="203" ...>` are now treated as failed requests, so unsupported TV `imdbid` searches trigger the intended retries instead of silently appearing as empty result sets.
- If the configured TV indexers do not advertise input-side `imdbid` support at all, the app now keeps the failed IMDb-first attempts in the primary section and renders a separate broader title-fallback section below instead of pretending the fallback itself was an IMDb-constrained search.
- Jackett timeout failures now include the concrete request label in the surfaced error, so the UI identifies which Torznab query variant timed out.
- Timed-out Jackett variants now degrade at the variant level: the client can retry that same variant's fallback params (for example, dropping `year`) and, if other expanded variants still succeed, return partial results with an inline warning instead of failing the entire search run.
- The search strategy now uses a high-recall hybrid flow: IMDb-first remote fetch when available, plus an always-run broad title fallback fetch, then local refinement over cached result pools.
- Torznab results now capture richer normalized metadata (category IDs, year, peers/leechers, grabs, volume factors) plus raw Torznab attrs for local filtering and future UI slices.
- `/search` now keeps split `IMDb-first` and `Title fallback` sections while exposing fetched-vs-filtered counts and client-side local filter updates without extra Jackett calls.
- `/search` now also supports a card/table result view toggle, 3-level hierarchical local sorting (for example published -> seeders -> title), and per-section filter-impact diagnostics that show per-value keep/drop counts plus blocker highlighting when filters produce an empty list.
- `/search` now defaults to table view and can persist default view mode + 3-level sort preferences via `AppSettings` and `/api/search/preferences`, with save actions exposed directly in the result-view options panel.
- `/search` now renders synchronized result-view options panels above both `IMDb-first` and `Title fallback` sections so users can adjust display/sorting from either section without scrolling.
- `/search` now aligns local keyword UX with the rule form via quality include/exclude checkbox groups and an explicit `Filter by release year` checkbox.
- `/search` now strictly honors the `Filter by release year` toggle for both manual and rule-derived runs: unchecked form submissions no longer carry `release_year`, and checkbox state binding now targets the checkbox field instead of the hidden fallback input.
- `/search` filter-impact diagnostics now render explicit sentence separators and clearer "sole blocker vs other active blockers" wording, preventing merged text like `20260` / `2160p1` in copied plain-text output.
- When `IMDb-first` fetched count is `0`, the primary summary now suppresses filter-impact diagnostics and keeps only query/request context for the empty primary section.
- Jackett result parsing now derives `year` from the title when Torznab omits year attrs, keeping release-year filtering and Year column rendering consistent for common title formats like `(2026)`.
- Jackett result parsing now also reads indexer labels from non-`attr` Torznab tags such as `<jackettindexer>`/`<indexer>`, and search tables now show `Unknown` instead of `Jackett` when indexer labels are absent.
- `/search` any-of keyword input now supports grouped syntax via `|` separators (for example `uhd, 4k | hdr, hdr10`), and client-side local filtering + filter-impact rows now preserve group semantics.
- Excluded-keyword matching now treats very short terms (`sd`, `ts`) as whole tokens instead of broad substrings, reducing false positives from hidden Torznab metadata values like `sdr` and URL fragments.
- Local Jackett refinement now requires title-query alignment (so unrelated fallback titles are removed), and very short included terms such as `hdr` now use token-aware matching to prevent substring false positives from metadata values like `HDRezka`.
- Local title/query refinement now supports non-Latin scripts (for example Cyrillic), so multilingual libraries do not bypass query matching.
- IMDb-first local refinement now keeps localized-title results when the Torznab result IMDb ID exactly matches the requested IMDb ID.
- Rule-derived search term extraction now treats legacy sentinel text values such as `None` / `null` as empty optional override fields.
- Local keyword matching now recognizes season/episode shorthand variants (`s3`, `e7`, `s3e1`) against zero-padded title tokens (`s03`, `e07`, `s03e01`) so required-keyword filtering stays intuitive.
- Jackett search runs now append structured debug events to `logs/search-debug.log` (search payload filters, fetched-vs-filtered counts) and emit debug-level drop-reason aggregates for local-filter tuning.
- Added `docs/plans/phase-6-release-qa-plan.md` with a DB-backed release matrix that exercises phase-6 search behavior against representative saved rules from `data/qb_rules.db`.
- The project `.venv` now passes targeted phase-6 pytest coverage for `tests/test_jackett.py` and `tests/test_routes.py`.
- The full repo pytest suite now also passes in the project `.venv`.
- 2026-03-09 reruns confirm targeted (`63 passed`) and full-suite (`117 passed`) pytest coverage still pass in the Windows `.venv`, and full-suite pytest also passes in Linux `.venv-linux`.
- `scripts/test.sh` now defaults to `--capture=sys` when no capture mode is provided and auto-detects `.venv-linux/bin/python`, so Linux/WSL wrapper runs no longer require manual `-s` or explicit activation in the common path.
- Branch-level static quality gates now pass in Linux `.venv-linux` (`ruff check .`, `mypy app`, and full pytest via `./scripts/check.sh`).
- DB-driven phase-6 release QA matrix execution on 2026-03-09 is now complete with `15/15` passing scenarios and no `critical/high` findings; evidence is captured in `logs/qa/phase6-matrix-20260309T220744Z.{json,md}` and `docs/plans/phase-6-release-qa-plan.md`.
- v0.1.0 release docs were prepared on 2026-03-10 (`CHANGELOG.md`, `ROADMAP.md`) and release gates were re-run successfully.
- Local annotated git tag `v0.1.0` was created on 2026-03-10 from the release-prep `main` commit.
- Targeted IMDb-first regression coverage now passes for `tests/test_jackett.py` after the strict `imdbid`-only request update.
- Linux route-test reruns are now stable through the supported wrapper path (`./scripts/test.sh tests/test_routes.py`: `44 passed` on 2026-03-10), clearing the previous `.venv-linux` route-test blocker for this slice.
- A repo-local `project-management` skill now exists under `.codex/skills/project-management` so in-progress phase validation sessions can follow a consistent status/plan closeout workflow.
- A repo-local `qa-engineer` skill now exists under `.codex/skills/qa-engineer` so validation sessions can follow a consistent risk-map, evidence capture, and severity-first reporting workflow.
- A repo-local `jackett-api-expert` skill now exists under `.codex/skills/jackett-api-expert` to guide Torznab capability-aware query design, fallback sequencing, and failure triage.
- A repo-local `ui-ux-designer` skill now exists under `.codex/skills/ui-ux-designer` to structure feature UX workflow, accessibility checks, and implementation-ready handoff specs during manual validation/polish passes.
- A repo-local `project-design-documentation-engineer` skill now exists under `.codex/skills/project-design-documentation-engineer` to standardize project and design documentation updates (plans, specs, ADRs, QA docs) during phase execution and validation.
- A repo-local `versioning-manager` skill now exists under `.codex/skills/versioning-manager` to standardize SemVer bump decisions and cross-file version synchronization during release prep.
- A repo-local `programming-sprint-manager` skill now exists under `.codex/skills/programming-sprint-manager` to split mixed bug/feature/improvement execution into small validated slices with consistent sprint tracking and closeout notes.
- The dated execution checklist for the latest UX/request slice (`P6-01` through `P6-09`) is completed as of 2026-03-10 with evidence links in the checklist table.
- `/search` now uses a denser phase-6 polish layout: explicit `Search criteria` and `Local refinement` panels, paired include/exclude checkbox rows per quality group, and a collapsible keyword-checkbox section.
- `/search` summary/filter-impact rendering now uses compact grid composition with multi-column, scrollable impact rows so large filter sets consume less vertical space.
- `/search` source-context summary now renders as 3 aligned cards (`App source`, `Rule-source path`, `Model split`), and filter-impact sections are now individually collapsible.
- Result-view controls now render as grouped cards (`view mode` + three sort-level blocks) with clearer visual hierarchy while keeping the existing synchronized control behavior.
- Added automated UX screenshot tooling (`scripts/capture_search_ui.py`, `scripts/capture_ui.sh`, `scripts/capture_ui.bat`) and README usage docs so iterative `/search` visual review runs can be repeated quickly.
- Screenshot capture defaults now target stable non-query `/search` states; live Jackett-query captures are opt-in via `--include-live-search` to avoid routine timeout failures during UX iteration.
- Screenshot capture now skips auto-starting uvicorn when a local server is already reachable, preventing duplicate server churn during multi-shell iteration loops.
- Added deterministic browser closeout QA automation for phases 4/5/6 (`scripts/closeout_browser_qa.py` plus `scripts/closeout_qa.sh` / `scripts/closeout_qa.bat`) with isolated mock qBittorrent/Jackett services and pass/fail artifact reports.
- Browser closeout automation run on 2026-03-11 passed `9/9` checks with evidence at `logs/qa/phase-closeout-20260311T113931Z/closeout-report.md`.
- Optional live-provider smoke gate run on 2026-03-11 passed `4/4` checks without `QB_RULES_QB_BASE_URL` override, confirming WSL localhost rewrite behavior against real Jackett/qB/OMDb endpoints; evidence: `logs/qa/live-provider-smoke-20260311T163136Z/result.md`.
- `scripts/run_dev.sh` now auto-detects repo-local interpreters and launches via `python -m uvicorn`, removing the prior hard dependency on a globally installed `uvicorn` binary in WSL/Linux shells.
- Linux/WSL screenshot runs currently require host browser libraries (`python -m playwright install-deps chromium` with sudo); when missing, the script now exits with an explicit remediation message instead of a traceback.
- Local annotated git tag `v0.2.0` was created on 2026-03-11 from commit `da37dc8` after release gates and live-provider smoke evidence passed.
- v0.2.1 follow-up slice for unified keyword-token controls across rules/search, search local-refinement responsiveness fixes, and cross-indexer category-label consolidation for local filtering is now implemented in this branch with targeted + full gate coverage passing.
- `/search` quality-token selection now enforces include-first normalization in both local JS refinement and server payload construction, so contradictory include/exclude states cannot keep a token shown as `In` while still applying it as an exclusion.
- `/search` local refinement quality-tag filtering now reuses rule-style quality regex patterns (same token pattern source used by rule pattern generation) when matching cached results, with fallback to term expansion only if a token regex cannot compile.
- `/search` local refinement now replaces free-text `Result indexers` and `Result categories` inputs with assisted multi-select checkbox dropdowns populated from distinct values in fetched cached results.
- Search page result rendering now proactively enriches category labels from configured per-indexer category dictionaries (`t=indexers`) even when the active payload did not request label-based category filtering, so category dropdowns can prefer semantic names over raw IDs.
- Deterministic browser closeout automation now includes an explicit phase-6 check for quality-tag slider responsiveness plus indexer/category multiselect local filtering without extra Jackett requests.
- `/search` local refinement now includes a rule-style `Generated pattern preview` backed by the same centralized client-side regex builder used on `/rules/*`; quality sliders, grouped any-of terms, `Extra include keywords`, and `mustNotContain` all synchronize into one preview string.
- `/search` local free-text refinement now uses the same field contract as `/rules/*` (`additional_includes`, `must_not_contain`) with backward-compatible parsing of legacy query params (`keywords_all`, `keywords_not`).
- Grouped any-of include parsing (`|`) is now handled inside the shared `deriveGeneratedPattern` builder instead of search-only pre-fragmenting, and rule-derived `/search` prefill now keeps literal rule free-text values instead of expanded token-derived terms.
- `/search` runs opened from saved rules now keep the local `Additional any-of keyword groups` field blank by default, so inherited structured search terms do not leave stale text in local refinement inputs.
- Rule-page `Generated pattern preview` now re-applies `mustNotContain` values, and free-text `|` alternatives now render as OR groups (for example `bbb|ccc` => `(?:bbb|ccc)`) instead of concatenated token chains.
- Backend rule generation and rule-derived Jackett request extraction now match the free-text `|` OR semantics by mapping multi-option include entries into grouped lookaheads / optional-keyword groups.
- The goal is to add an on-demand search workflow beside RSS rule authoring, not to replace RSS automation.

## Request Checklist (2026-03-10 refresh)

This section maps the requested UX/search improvements to implementation status so roadmap-level intent is easy to audit.

1. Search page UI parity with rule-style keyword include/exclude + release-year toggle.
   - Status: implemented.
2. Rules/search pages use wider responsive layout to reduce vertical scrolling.
   - Status: implemented.
3. Default search result view is `table` and users can save default view + sort preferences.
   - Status: implemented.
4. Result view options panel UX redesign.
   - Status: implemented.
5. Duplicate result view options panel above both `IMDb-first` and `Title fallback`.
   - Status: implemented.
6. When `IMDb-first` fetched is `0`, show query/request context only and hide filter-impact panel.
   - Status: implemented.
7. Strict IMDb-first request behavior (`imdbid` input only for primary lookup); title text stays in explicit fallback flow.
   - Status: implemented.
8. Improve result metadata relevance (`indexer`, peers/leechers/grabs semantics, unknown handling).
   - Status: implemented.
9. Persist these decisions in project docs with resumable execution notes.
   - Status: implemented; tracked in this phase plan plus `docs/plans/current-status.md`.
10. Additional expert recommendations across UX/backend/QA/ops.
   - Status: documented as follow-up opportunities; implementation pending prioritization.
11. Rework dense `/search` layout usage (`criteria`, checkbox rows, filter-impact density) to reduce wasted space on wide screens.
   - Status: implemented.
12. Add an automated visual-feedback capture loop for repeatable UI/UX review.
   - Status: implemented with explicit Linux/WSL host dependency notes.
13. Rebuild keyword-token controls so each token appears once with explicit enabled + include/exclude mode controls (rules + search UI parity).
   - Status: implemented.
14. Ensure `/search` keyword-token controls directly and responsively affect local cached refinement without manual text-field edits.
   - Status: implemented.
15. Consolidate local category filtering across indexers by supporting semantic category-label matching in addition to raw numeric IDs.
   - Status: implemented.
16. Replace the token mode selector with a true single-control 3-state slider (`Off` / `In` / `Out`) beside each tag, and keep token grids dense on desktop.
   - Status: implemented.
17. Normalize conflicting quality-token include/exclude states so include wins consistently in `/search` local filtering and request payload building.
   - Status: implemented.
18. Reuse rule-style quality regex patterns for cached-result keyword-tag filtering so slider toggles do not depend only on expanded plain terms.
   - Status: implemented.
19. Replace free-text local `Result indexers` / `Result categories` filters with assisted multi-select dropdown checkboxes from distinct cached result values.
   - Status: implemented.
20. Refine deterministic phase-6 closeout QA to explicitly validate quality-tag slider responsiveness and local multiselect filtering behavior.
   - Status: implemented.
21. Add a `/search` local-refinement generated-pattern preview that reuses the rule-page regex builder and reflects slider/include/exclude edits immediately.
   - Status: implemented.
22. Ensure `/search` free-text include/exclude semantics are literally aligned with `/rules/*` defaults and shared regex-generation behavior, while keeping legacy param compatibility.
   - Status: implemented.
23. Restore rule-page generated-preview parity for `mustNotContain` and ensure free-text `|` alternatives behave as OR groups across preview and backend rule derivation.
   - Status: implemented.

## Step-by-step implementation plan

### Dated execution checklist (2026-03-10 baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P6-01 | Lock behavior contracts for this request set. | Codex | 2026-03-10 | completed | Expectations are explicit in this phase plan and covered by route/service tests where feasible. | `docs/plans/phase-6-jackett-active-search.md`, `tests/test_jackett.py`, `tests/test_routes.py` |
| P6-02 | Validate strict IMDb-first path manually. | Codex | 2026-03-11 | completed | Primary request labels show only `imdbid` variants; no `q+imdbid` in IMDb-first requests. | `./scripts/test.sh tests/test_jackett.py`, `tests/test_jackett.py` IMDb-first assertions |
| P6-03 | Validate release-year toggle behavior manually. | Codex | 2026-03-11 | completed | Unchecked `Filter by release year` never applies year filtering for manual or rule-derived searches. | `tests/test_routes.py::test_search_page_skips_release_year_when_toggle_is_unchecked`, `tests/test_routes.py::test_search_page_from_rule_skips_release_year_when_not_enabled`, `tests/test_jackett.py::test_build_search_request_from_rule_skips_release_year_when_not_enabled` |
| P6-04 | Validate dual-panel result options UX behavior. | Codex | 2026-03-11 | completed | Top panels for IMDb-first/fallback remain synchronized and save default view/sort reliably. | `tests/test_routes.py::test_search_page_renders_result_view_panels_for_primary_and_fallback`, `tests/test_routes.py::test_save_search_preferences_api_persists_defaults` |
| P6-05 | Validate result metadata semantics and column relevance. | Codex | 2026-03-11 | completed | Indexer labels appear when provided; unknown fallback is accurate; peers/leechers/grabs columns appear only when populated. | `tests/test_jackett.py::test_jackett_client_parses_indexer_tag_and_infers_peers`, `tests/test_routes.py::test_search_page_hides_availability_columns_when_metrics_absent` |
| P6-06 | Resolve Linux route-test environment blocker and rerun targeted route tests. | Codex | 2026-03-12 | completed | `tests/test_routes.py` targeted reruns complete in `.venv-linux` without `TestClient` hang. | `./scripts/test.sh tests/test_routes.py` (`44 passed`, 2026-03-10) |
| P6-07 | Final closeout for this request set. | Codex | 2026-03-12 | completed | `current-status`, phase plan status rows, and residual risks are synchronized and decision-complete. | `docs/plans/current-status.md`, this phase plan |
| P6-08 | Deliver compact `/search` layout polish for high-density desktop use. | Codex | 2026-03-10 | completed | Search criteria layout uses explicit panel grids, include/exclude checkbox rows are paired per group, and result-view/filter-impact composition is visibly denser. | `app/templates/search.html`, `app/static/app.css`, `app/static/app.js`, `./scripts/test.sh tests/test_routes.py` (`44 passed`, 2026-03-10) |
| P6-09 | Add automated `/search` visual feedback tooling for iterative UX polish. | Codex | 2026-03-10 | completed | Screenshot tooling exists with desktop/mobile capture support, wrappers, and documented setup/remediation steps. | `scripts/capture_search_ui.py`, `scripts/capture_ui.sh`, `scripts/capture_ui.bat`, `README.md` |
| P6-10 | Replace manual Phase 4/5/6 browser closeout with deterministic browser QA automation. | Codex | 2026-03-11 | completed | Browser closeout checks run against isolated mock qBittorrent/Jackett services and produce reproducible evidence artifacts for release decisions. | `scripts/closeout_browser_qa.py`, `scripts/closeout_qa.sh`, `scripts/closeout_qa.bat`, `logs/qa/phase-closeout-20260311T113931Z/closeout-report.md` |
| P6-11 | Run optional live-provider smoke gate against real external endpoints. | Codex | 2026-03-11 | completed | `/search`, metadata lookup, `/rules/new`, and qB feed refresh all return success with real configured providers and no qB URL override in WSL. | `logs/qa/live-provider-smoke-20260311T163136Z/result.{md,json}` |
| P6-12 | Replace duplicate include/exclude quality token columns with single-token controls (`Off` / `In` / `Out`) in `/rules/*` and `/search`. | Codex | 2026-03-11 | completed | Rule and search forms render one visible row per token with a compact 3-state toggle; server payload compatibility for include/exclude tokens is preserved. | `app/templates/_quality_token_controls.html`, `app/templates/rule_form.html`, `app/templates/search.html`, `app/static/app.js`, `app/static/app.css` |
| P6-13 | Fix `/search` local refinement so keyword-token UI changes immediately update cached-result filtering without manual keyword text edits. | Codex | 2026-03-11 | completed | Toggling keyword tokens updates local filtered counts and filter-impact output through client-side refinement only. | `app/static/app.js`, `app/routes/pages.py`, `tests/test_routes.py::test_search_page_expands_quality_token_terms_for_search_payload` |
| P6-14 | Add cross-indexer category consolidation for local filtering via category-label normalization (alongside category IDs). | Codex | 2026-03-12 | completed | Category filters accept IDs or semantic labels and match across indexers with differing numeric category IDs. | `app/services/jackett.py`, `app/schemas.py`, `app/templates/search.html`, `tests/test_jackett.py::test_jackett_client_can_filter_by_category_label_across_indexers` |
| P6-15 | Make UI screenshot capture defaults include both rule-form and search pages for every standard UX review run. | Codex | 2026-03-11 | completed | Default capture run outputs `/rules/new` + `/search` across desktop/mobile so request-to-render comparisons cover both surfaces. | `scripts/capture_search_ui.py`, `README.md`, `logs/ui-feedback/20260311T182046Z/manifest.json` |
| P6-16 | Replace native radio-based token mode selector with button-based segmented control after visual regression review. | Codex | 2026-03-11 | completed | Each token renders a compact horizontal segmented `Off / In / Out` switch without vertical radio fallback rendering. | `app/templates/_quality_token_controls.html`, `app/static/app.js`, `app/static/app.css`, `logs/ui-feedback/20260311T183148Z/manifest.json` |
| P6-17 | Replace segmented mode buttons with a single-track 3-state slider control beside each token and enforce denser desktop token rows. | Codex | 2026-03-11 | completed | Each visible token uses one slider track with a moving indicator (`Off`/`In`/`Out`) and multi-column desktop packing across `/rules/new` and `/search`. | `app/templates/_quality_token_controls.html`, `app/static/app.css`, `app/static/app.js`, `app/templates/base.html`, `app/main.py`, `logs/ui-feedback/20260311T193540Z/manifest.json` |
| P6-18 | Normalize conflicting `/search` quality-token include/exclude state so include wins in both local refinement and Jackett payload expansion. | Codex | 2026-03-11 | completed | Conflicting token input (`quality_include_tokens=sd`, `quality_exclude_tokens=sd`) keeps only include-side behavior in UI filtering and backend payload terms. | `app/static/app.js`, `app/routes/pages.py`, `tests/test_routes.py::test_search_page_prefers_include_token_when_quality_token_lists_conflict`, `./scripts/test.sh tests/test_routes.py -k "search_page"` (`19 passed`, 2026-03-11) |
| P6-19 | Rework `/search` local quality-token refinement to apply rule-style quality regex matching on cached result text. | Codex | 2026-03-11 | completed | Toggling quality sliders immediately changes cached filtered counts with regex-backed matching aligned to rule token patterns, including include-slider precedence over conflicting manual excluded keyword text. | `app/static/app.js`, `app/services/jackett.py::quality_pattern_map`, `app/templates/search.html`, `scripts/closeout_browser_qa.py::P6-04`, `logs/qa/phase-closeout-20260311T213939Z/closeout-report.md` |
| P6-20 | Replace local free-text result indexer/category filters with dropdown multi-select checkboxes from distinct cached values. | Codex | 2026-03-11 | completed | `/search` local refinement exposes assisted indexer/category multi-selects, persists selections in form-compatible hidden fields, and applies filters locally without new Jackett requests. | `app/templates/search.html`, `app/static/app.js`, `app/static/app.css`, `tests/test_routes.py::test_search_page_accepts_repeated_multiselect_filter_params`, `scripts/closeout_browser_qa.py::P6-04` |
| P6-21 | Ensure cached result category labels are enriched from per-indexer category dictionaries even outside label-filter requests. | Codex | 2026-03-11 | completed | Search-page result cards/tables carry semantic category names from configured indexer maps so category-assisted filtering can use labels instead of raw IDs where available. | `app/services/jackett.py::enrich_result_category_labels`, `app/routes/pages.py`, `tests/test_jackett.py::test_jackett_client_can_enrich_result_category_labels_without_label_filter` |
| P6-22 | Add `/search` generated-pattern preview parity with rule-page regex builder for local refinement controls. | Codex | 2026-03-11 | completed | `/search` shows `Generated pattern preview` and keeps it synchronized with sliders, grouped any-of terms, extra include terms, and `mustNotContain`; deterministic browser QA fails if preview no longer updates with toggle changes. | `app/static/app.js::deriveGeneratedPattern`, `app/templates/search.html`, `tests/test_routes.py::test_search_page_expands_quality_token_terms_for_search_payload`, `scripts/closeout_browser_qa.py::P6-04`, `logs/qa/phase-closeout-20260311T213939Z/closeout-report.md`, `logs/ui-feedback/20260311T214712Z/manifest.json` |
| P6-23 | Align `/search` free-text include/exclude fields with `/rules/*` contract and move grouped any-of parsing into the shared pattern generator. | Codex | 2026-03-12 | completed | `/search` free-text fields use `additional_includes`/`must_not_contain`, rule-derived prefill preserves literal rule free-text values, legacy query params still parse, and grouped any-of (`|`) include groups are generated by shared `deriveGeneratedPattern`. | `app/routes/pages.py`, `app/templates/search.html`, `app/static/app.js::deriveGeneratedPattern`, `tests/test_routes.py::test_search_page_accepts_legacy_free_text_filter_query_params`, `tests/test_routes.py::test_search_page_from_rule_prefills_local_free_text_from_literal_rule_fields`, `./scripts/test.sh tests/test_routes.py tests/test_jackett.py` (`79 passed`, 2026-03-11), `./scripts/closeout_qa.sh` (`P6-02/P6-04 pass`, `logs/qa/phase-closeout-20260311T223130Z/closeout-report.md`) |
| P6-24 | Fix regressions in rule/search generated-pattern parity: blank rule-derived search any-of textbox, rule `mustNotContain` preview inclusion, and free-text pipe OR handling. | Codex | 2026-03-12 | completed | `/search` rule launches no longer prefill `keywords_any`; rule/search previews now parse free-text `|` as OR alternatives; rule preview includes `mustNotContain`; backend rule builder + Jackett derivation honor the same include pipe-group semantics. | `app/routes/pages.py`, `app/static/app.js`, `app/services/rule_builder.py`, `app/services/jackett.py`, `tests/test_rule_builder.py`, `tests/test_jackett.py`, `tests/test_routes.py`, `scripts/closeout_browser_qa.py::P5-02`, `./scripts/test.sh tests/test_rule_builder.py tests/test_jackett.py tests/test_routes.py` (`96 passed`, 2026-03-11), `logs/qa/phase-closeout-20260311T231251Z/closeout-report.md` |

## Goal

Add a local active-search workspace that queries Jackett from the app, supports richer keyword logic than qBittorrent's plain-text plugin search box, and lets users hand off a search query into rule authoring.

## Why this phase exists

qBittorrent's built-in search UI is a flat text box. The current app already models optional include keywords and media-aware filters for RSS rules, so it can provide a better front end for Jackett by fetching a high-recall result pool once and refining it locally.

## In scope

- Add optional Jackett connection settings (base URL and API key) alongside the existing qBittorrent settings.
- Keep the source model explicit: RSS feeds remain persistent rule inputs, while Jackett active search remains a separate on-demand source type.
- Support separate Jackett URLs for app-side search calls versus future qBittorrent-consumed rule sources when Docker/network topology differs.
- Add a normalized Jackett search client that can query one or more indexers through the Torznab API.
- Add structured search inputs for title, media type, indexer scope, and optional keyword groups.
- Derive active searches from saved rules using structured title/include/exclude terms instead of passing saved regex text through Jackett's plain-text query field, including multiple preserved any-of groups from saved regex lookaheads when possible.
- If a saved regex expands past the structured search limits, fall back to a title-only search with a visible warning instead of failing the page render.
- Prefer a reduced inherited keyword set before dropping all the way to title-only fallback, so saved-rule searches stay closer to the original rule intent.
- Fetch a broad Jackett result pool per search run, then apply keyword and metadata filters locally (`release_year`, size range, indexer, category IDs) against cached results without new Jackett requests.
- Render an active-search page with result metadata, source indexer, size, age, and search actions.
- Provide both card and table result views and local multi-level (hierarchical) sorting over cached results.
- Surface filter-impact diagnostics so users can see how many results each active filter value removes or keeps and which value blocks an otherwise non-empty result set.
- Add a search-to-rule handoff so an active search can prefill the rule form with the same title and filter intent.

## Out of scope

- Background saved searches or alerts.
- Auto-downloading or silently sending results to qBittorrent without an explicit follow-up action.
- Replacing the existing RSS rule workflow.
- Non-Jackett search providers in the initial slice.

## Proposed implementation

1. `app/models.py`, `app/schemas.py`, `app/services/settings_service.py`, `app/templates/settings.html`
   - Add optional Jackett settings fields and validation.
2. `app/config.py`
   - Add environment overrides for Jackett base URL and API key, matching the existing local-first secret handling pattern.
3. `app/services/jackett.py`
   - Add a client for Jackett Torznab search requests.
   - Normalize XML results into app-level search result models.
   - Keep remote fetch params broad and apply keyword/metadata refinement locally on cached result pools.
   - Store raw and filtered result sets in one run model so the UI can refresh filters interactively without re-querying Jackett.
   - Keep this as an app-local client instead of importing qBittorrent's Jackett plugin directly, because the plugin depends on qB-specific helper modules, printer hooks, and config-file conventions.
4. `app/routes/pages.py`, `app/routes/api.py`, `app/templates/search.html`, `app/static/app.js`
   - Add a `/search` page and supporting API endpoint for structured active searches.
   - Add query-prefill and "use this in rule form" actions.
5. `tests/test_jackett.py`, `tests/test_routes.py`
   - Cover connection handling, query expansion, result merging, error cases, and page rendering.
6. `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/plans/current-status.md`, `ROADMAP.md`
   - Document the new search workflow and operational constraints.

## Acceptance criteria

- A user can run an active search against Jackett from the app without leaving the local UI.
- A single structured search can fetch once and refine interactively with local keyword + metadata filters.
- Duplicate results across strict and fallback fetch paths are merged deterministically before rendering.
- Search failures return actionable configuration or provider errors.
- Setup, saved-rule, or search-time edge cases degrade into an editable search form with a visible error instead of a 500 page.
- Transient Jackett timeout failures are retried automatically before the UI treats the search as failed.
- A search can prefill the rule form so RSS automation and one-off search share the same filter intent.

## Validation checklist

- Run targeted service and route tests for Jackett client behavior and search page rendering.
- Current status: targeted Linux wrapper reruns pass in `.venv-linux` (`./scripts/test.sh tests/test_jackett.py`: `28 passed`; `./scripts/test.sh tests/test_routes.py`: `44 passed` on 2026-03-10).
- Run the full pytest suite through `scripts/test.sh` or `scripts/test.bat`. Current status: passing in repo `.venv` and `.venv-linux`.
- Run `scripts/check.sh` / `scripts/check.bat` before release sign-off. Current status: passing in Linux `.venv-linux`.
- For Linux/WSL shells, bootstrap a native test interpreter using `docs/native-python-pytest.md` so `python3 -m pytest` is runnable without the Windows `.venv`.
- Execute the DB-backed QA matrix in `docs/plans/phase-6-release-qa-plan.md` and record severity-ranked findings before phase-6 release sign-off.
- Current status: completed on 2026-03-09 with `15/15` pass and no `critical/high`; see `logs/qa/phase6-matrix-20260309T220744Z.md`.
- Run `./scripts/closeout_qa.sh` (or `scripts\\closeout_qa.bat`) to execute deterministic browser validation for:
  - grouped any-of keyword behavior and short-token exclusion semantics
  - release-year toggle local filtering with no extra network requests
  - dual result-view panel synchronization and preference save UX
  - filter-impact rendering/collapse behavior
  - search-to-rule handoff and `/rules/{rule_id}/search` derived-search flow
  - non-Latin query/title local matching
  - structured `logs/search-debug.log` event emission
- Current status: automated closeout rerun on 2026-03-11 includes rule-preview parity assertions (`P5-02`) plus phase-6 grouped any-of and local-toggle checks (`P6-02`/`P6-04`); all phase-5/6 checks pass and one pre-existing phase-4 feed-checkbox expectation (`P4-01`) remains open (`logs/qa/phase-closeout-20260311T231251Z/closeout-report.md`).
- Keep DB-backed phase-6 release matrix (`docs/plans/phase-6-release-qa-plan.md`) for live-data regression confidence.
- Current status: optional live-provider smoke run completed on 2026-03-11 with `4/4` pass (`logs/qa/live-provider-smoke-20260311T163136Z/result.md`); rerun after endpoint topology or credential changes.

## Dependencies

- Jackett must be reachable from the local app host and expose Torznab endpoints for the configured indexers.
- Phase 5 closeout is now automated and passing, so the existing rule-form contract is considered stable for this phase.
- Linux/WSL validation environments need `python3-venv` and `python3-pip` available so native `python3 -m pytest` runs can be provisioned.

## Roll-forward notes

- If direct "send to qBittorrent" actions are needed later, add them as explicit user-triggered actions on top of the normalized result model.
- If non-Jackett providers are added later, keep the app-level structured search contract provider-agnostic.
- If persistent Jackett-backed rule sources are added later, store them as a distinct source type instead of treating them as plain RSS feed URLs in the app UI.
