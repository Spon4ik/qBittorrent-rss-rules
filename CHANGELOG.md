# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and the project follows Semantic Versioning.

## [Unreleased]

- No entries yet.

## [0.7.5] - 2026-03-27

- Fixed the rule-form filter-profile selector so choosing a profile now updates the derived minimum-quality state, token controls, and generated pattern preview immediately instead of waiting for another field change.
- Added regression coverage for the immediate-update path in the pytest source checks and the live browser closeout QA flow.
- Revalidated the patch with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and `scripts\\run_dev.bat desktop-build`, then published `main` and the `v0.7.5` tag to `origin`.

## [0.7.4] - 2026-03-27

- Extracted a shared watch-state arbitration module so episode-key normalization, merging, and floor selection can be reused outside the Jellyfin adapter.
- Routed Jellyfin sync through the shared watch-state layer without changing the existing floor behavior or rule-history persistence contract.
- Kept Stremio watched-history sync as a separate follow-up phase so the new shared module stays source-agnostic instead of mixing two integration surfaces into one release.
- Added direct regression coverage for the shared watch-state helpers plus Jellyfin parity, validated the release candidate with `scripts\\check.bat`, `scripts\\run_dev.bat desktop-build`, and `scripts\\closeout_qa.bat`, and published the `v0.7.4` release after the final checks passed.

## [0.7.3] - 2026-03-27

- Hardened `scripts\\run_dev.bat` so a copied repo-local `.venv` with a stale interpreter path now fails fast with concrete recreate commands instead of the generic `No Python at ...` launcher error.
- Removed the machine-specific Visual Studio offline NuGet source from `NuGet.config`, so WinUI restore and build now work from a fresh machine without `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\`.
- Revalidated the portability patch with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and `scripts\\run_dev.bat desktop-build`.
- Published the `v0.7.3` maintenance release after cross-machine validation.

## [0.7.2] - 2026-03-25

- Removed the remaining Starlette template deprecation warnings by switching the affected route/template renderers to the request-first `TemplateResponse(...)` signature in both page and API render helpers.
- Synchronized the patch release touchpoints to `0.7.2`, including the FastAPI app version, the WinUI desktop backend-version guard, and the `/health` route regression assertion.
- Revalidated the patch with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and a clean `scripts\\run_dev.bat desktop-build` run (`0 Warning(s)`, `0 Error(s)`).
- Published the `v0.7.2` release after warning-free validation.

## [0.7.1] - 2026-03-25

- Released the phase-13 desktop patch so the WinUI shell no longer silently reuses stale backend/app versions and now fails closed into the offline state when a required refresh cannot reach a compatible backend.
- Added desktop-side local app change watching plus debounced WebView refresh handling for repo/dev-checkout runs, keeping desktop behavior aligned with current browser scripts/templates instead of requiring Task Manager resets.
- Tightened desktop `/health` compatibility checks to require the expected backend app version in addition to the desktop backend contract, so stale `0.7.0` backends are rejected automatically by the `0.7.1` desktop shell.
- Added explicit `Shut Down Engine` and `Exit Desktop` controls to the WinUI shell so the desktop-managed Python backend can be stopped from inside the app.
- Revalidated the patch with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and WinUI desktop build/launch verification.

## [0.7.0] - 2026-03-25

- Released the phase-12 catalog-aware Jellyfin/qB slice with backward-compatible rule storage updates, OMDb-backed season-boundary checks, and automatic missing-only queue selection for saved series rules.
- Added OMDb season episode lookup support so Jellyfin sync can detect real season finales, avoid fake same-season floors like `S01E11`, and advance to `S(next)E00` so specials remain searchable.
- Persisted remembered Jellyfin known/watched episode history on each rule so deleting watched or already-known local files no longer regresses skip behavior, without introducing a separate scrobbling subsystem.
- Extended stored floors, generated regex, and browser/local filtering parity to support episode `0` safely for season specials while preserving the prior zero-based range protections.
- Added qBittorrent torrent-file inspection and file-priority updates so `Add to queue` can automatically select only missing/unseen episode files when a multi-file series result exposes safe episode metadata, while still falling back clearly for ambiguous or metadata-light results.
- Revalidated the release with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and `scripts\\run_dev.bat desktop-build`.

## [0.6.1] - 2026-03-25

- Released the phase-11 stabilization slice with single-instance desktop enforcement, deferred poster backfill on the base rules page, fresh live WebView hover evidence, and an end-user Windows bundle/install flow.
- Added read-only Jellyfin startup/background sync, explicit Settings sync controls, persisted next-missing series floors, and movie auto-disable when a matching local Jellyfin item already exists by default.
- Fixed generated-pattern parity for season/episode floors so zero-based range titles like `S3E00-07` are rejected consistently in saved qB rules, server-side local filtering, and browser-side local filtering while still allowing ranges that include the requested next episode.
- Expanded regression coverage with direct builder, server local-filter, and Node-backed browser-pattern checks for the zero-based range leak and validated the release with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, and `scripts\\run_dev.bat desktop-build`.

## [0.6.0] - 2026-03-23

- Released the phase-10 WinUI desktop baseline with `QbRssRulesDesktop`, repo-local desktop build/run commands, shortcut refresh, and hidden companion-backend startup.
- Added desktop freshness protections so managed backend launches use `--reload`, WebView navigations carry a launch cache-buster, and orphaned managed backend processes are cleaned up on later launches.
- Added stale-backend compatibility enforcement through `/health` contract metadata plus fallback-port startup, preventing the desktop shell from reattaching to incompatible servers already listening on `:8000`.
- Added `Show hidden fetched rows` diagnostics and per-row visibility reasons for unified search results and inline rule results.
- Hardened rules main-page performance with persisted release-cache columns, targeted snapshot loading, and bounded poster backfill retries.
- Revalidated the release with full Python checks, deterministic browser closeout, and WinUI desktop build evidence for the retained desktop baseline.

## [0.5.0] - 2026-03-15

- Released phase-9 rules main-page operations workspace with table-first defaults, cards fallback mode, and row-hover poster previews.
- Added poster metadata plumbing end-to-end (`MetadataResult.poster_url`, persisted `Rule.poster_url`, and cards/table rendering fallbacks).
- Added on-demand rule fetch orchestration from `/` (`Fetch Selected` and `Fetch All`) backed by centralized per-rule snapshot persistence.
- Added recurring fetch scheduling controls and runtime execution (persisted cadence/scope/status, API endpoints, and background scheduler loop).
- Added release-availability status/sorting on the rules page using centralized snapshot counts (`Matches found` / `No matches` / `No snapshot`).
- Added deterministic browser closeout phase-9 coverage (`P9-01`) and updated closeout compatibility checks for table-only search controls and collapsible rule criteria.

## [0.4.0] - 2026-03-15

- Released the phase-8 persistent rule-search snapshot workflow: saved rules now replay centralized DB-backed unified results by default and support explicit snapshot refresh.
- Unified IMDb-first and title-fallback rows into one result table with source-key attribution, compact empty states, and no standalone filter-impact panel.
- Shipped rule-page workspace modernization with a sticky split layout, denser queue controls, active local-filter chips, and interactive header-driven sorting.
- Added inline affected-feed dual behavior: feed selection continues to define RSS listener scope and now also narrows inline result visibility immediately by indexer.
- Restored inline consolidated category filtering controls and compacted result controls to a table-only workflow with `Save sort as default`.

## [0.3.0] - 2026-03-13

- Released the phase-7 cached-refinement + category-catalog slice, including persisted indexer/category mapping and scoped category multiselect diagnostics on `/search`.
- Shipped rule-page inline search as the default saved-rule run flow with feed-aware scoping, queue-to-qB actions, and `/search`-parity table/sort controls.
- Added episode-progress floor filtering (`Start season` + `Start episode`) and grouped quality include semantics so multi-group selections (for example `4K` + `HDR`) apply deterministically across backend and local refinement.
- Hardened qB add-paused compatibility by posting both `paused` and `stopped` flags for queue add actions across WebUI API versions.
- Expanded deterministic browser closeout coverage with phase-7 inline checks (pattern local recompute, queue paused semantics, and table/sort parity) and stale-category scope-status regression assertions.

## [0.2.0] - 2026-03-11

- Released the phase-6 Jackett active-search workflow as the v0.2.0 feature slice, including IMDb-first plus title-fallback result sections and richer local refinement controls.
- Delivered the second-pass `/search` UX density improvements: wider layout, rule-style include/exclude checkboxes, compact filter-impact rendering, and synchronized dual result-view panels.
- Added deterministic browser closeout automation (`scripts/closeout_qa.sh` / `.bat`) and repeatable UI screenshot capture tooling (`scripts/capture_ui.sh` / `.bat`).
- Added WSL-aware qBittorrent host resolution so `localhost`/`127.0.0.1` qB base URLs are rewritten to `host.docker.internal` when running inside WSL.
- Captured release evidence across static/test gates, deterministic browser closeout, DB-backed matrix QA, and optional live-provider smoke checks.

## [0.1.0] - 2026-03-10

- Initial public release.
- Local FastAPI app with SQLite-backed rule storage, import flows, and qBittorrent WebUI sync.
- Taxonomy-driven quality filtering with media-aware rule authoring, reusable profiles, and metadata lookup integrations.
- Jackett-backed active search workspace with rule-derived queries, IMDb-first fallback behavior, and search-to-rule handoff.
- Regression-tested release path with `ruff`, `mypy`, full `pytest`, and DB-driven phase-6 search QA evidence.
