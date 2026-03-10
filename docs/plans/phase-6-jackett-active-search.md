# Phase 6: Jackett-Backed Active Search

## Status

- Implementation is in progress in the repo as an initial slice.
- This phase is still scoped for the next release after phase 5 validation closes.
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
- The full repo pytest suite now also passes in the project `.venv`; remaining validation is manual browser coverage.
- 2026-03-09 reruns confirm targeted (`63 passed`) and full-suite (`117 passed`) pytest coverage still pass in the Windows `.venv`, and full-suite pytest also passes in Linux `.venv-linux`.
- `scripts/test.sh` now defaults to `--capture=sys` when no capture mode is provided and auto-detects `.venv-linux/bin/python`, so Linux/WSL wrapper runs no longer require manual `-s` or explicit activation in the common path.
- Branch-level static quality gates now pass in Linux `.venv-linux` (`ruff check .`, `mypy app`, and full pytest via `./scripts/check.sh`), so remaining release risk is primarily manual QA coverage.
- DB-driven phase-6 release QA matrix execution on 2026-03-09 is now complete with `15/15` passing scenarios and no `critical/high` findings; evidence is captured in `logs/qa/phase6-matrix-20260309T220744Z.{json,md}` and `docs/plans/phase-6-release-qa-plan.md`.
- v0.1.0 release docs were prepared on 2026-03-10 (`CHANGELOG.md`, `ROADMAP.md`) and release gates were re-run successfully; phase-6 remains a v0.2.0 target slice.
- Local annotated git tag `v0.1.0` was created on 2026-03-10 from the release-prep `main` commit; phase-6 remains queued for the v0.2.0 cycle.
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
- `scripts/run_dev.sh` now auto-detects repo-local interpreters and launches via `python -m uvicorn`, removing the prior hard dependency on a globally installed `uvicorn` binary in WSL/Linux shells.
- Linux/WSL screenshot runs currently require host browser libraries (`python -m playwright install-deps chromium` with sudo); when missing, the script now exits with an explicit remediation message instead of a traceback.
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
- Manually verify `/search` for:
  - a plain title-only fetch with local keyword refinement
  - grouped any-of keyword refinement using `|` separators (for example `uhd, 4k | hdr, hdr10`) so each group is enforced independently
  - local refinement for release year, size, indexer, and category filters without extra network calls
  - release-year filtering where Torznab omits `year` attrs but the title includes a year token (for example `(2026)`)
  - short excluded-token behavior (`sd`, `ts`) to confirm token-only blocking and no substring-driven false positives
  - short included-token behavior (`hdr`) to confirm token-only matching and no metadata-substring false positives (for example `HDRezka`)
  - season/episode shorthand behavior (`s3`, `e7`, `s3e1`) to confirm matches against zero-padded title tokens (`s03`, `e07`, `s03e01`)
  - query/title alignment behavior so unrelated fallback titles do not remain in filtered results when title query terms are missing
  - card/table view toggle and 3-level hierarchical sort behavior without extra network calls
  - filter-impact diagnostics (`remain if alone`, `filtered out`, and blocker highlighting for empty results)
  - `logs/search-debug.log` output for Jackett search debug summaries and drop-reason diagnostics while iterating on filters
  - an indexer-limited search
  - the search-to-rule handoff into `/rules/new`
- Manually verify `/rules/{rule_id}/search` for saved movie or series rules with metadata-filled `IMDb ID` / `Release year` fields and confirm Jackett still returns results with the narrower request.
- Manually verify `/rules/{rule_id}/search` for a movie or series rule with `IMDb ID` populated and confirm the page shows split `IMDb-first` and `Title fallback` sections where fallback fetch still runs even when IMDb-first has hits.
- Manually verify `/rules/{rule_id}/search` for imported or legacy rules with unusually long saved titles and confirm the clamped title-only fallback still runs when structured reduction cannot.
- Manually verify graceful errors for missing Jackett config, HTTP failures, and empty result sets.

## Dependencies

- Jackett must be reachable from the local app host and expose Torznab endpoints for the configured indexers.
- Phase 5 validation should close first so the existing rule-form contract is stable before the new search surface is added.
- Linux/WSL validation environments need `python3-venv` and `python3-pip` available so native `python3 -m pytest` runs can be provisioned.

## Roll-forward notes

- If direct "send to qBittorrent" actions are needed later, add them as explicit user-triggered actions on top of the normalized result model.
- If non-Jackett providers are added later, keep the app-level structured search contract provider-agnostic.
- If persistent Jackett-backed rule sources are added later, store them as a distinct source type instead of treating them as plain RSS feed URLs in the app UI.
