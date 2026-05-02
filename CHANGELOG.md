# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and the project follows Semantic Versioning.

## [Unreleased]

- No entries yet.

## [1.1.2] - 2026-05-02

- Fixed built-in video filter profiles so `At Least Full HD`, `At Least Ultra HD`, and `Ultra HD HDR` derive their include/exclude resolution tokens from the live runtime taxonomy rank instead of frozen preset lists.
- Existing uncustomized profile settings and profile-owned rule token snapshots now refresh when taxonomy resolution values such as `240p`, `400p`, or future higher resolutions are added, so saved rules keep their selected profile identity and active local filters stay current after Docker/app restart.
- Added focused regressions for runtime taxonomy rank inheritance, stored default-profile migration, matching-profile detection, and the rule/search quality-profile consumers.

## [1.1.1] - 2026-04-29

- Fixed Stremio local-storage auth discovery so the app extracts the real auth key, retries older discovered local sessions when the newest key is stale, and no longer stops at `Stremio API datastoreGet failed: Session does not exist` when a valid signed-in session is still present.
- Hardened quality tag filtering so quality/source tokens match release-token boundaries instead of ordinary title substrings, while keeping `HDCAM`, `CAMRip`, `HDTS`, and similar release tags detectable.
- Added focused Stremio auth fallback, Python quality-filter, and browser-side quality-filter regressions for the escaped failures.
## [1.1.0] - 2026-04-20

- Added a rule-level language selector that resolves matching Jackett-backed qB RSS feeds under the hood, so qBittorrent RSS auto-downloader scope can now follow the chosen language without manually picking indexers first.
- Updated the rule form UX to expose live language options discovered from configured Jackett indexers, explain the language-managed feed behavior clearly, and disable manual feed editing while language mode is active.
- Revalidated the feature with focused route/builder pytest coverage, Ruff on the touched Python surfaces, live local Jackett/qB inspection proving the current `he`/`ru` feed groups, and Playwright captures of the real `/rules/new` form before and after selecting `ru`.
- Fixed a stale-Jackett-link retry bug in `/api/search/queue` that surfaced during the broader route regression sweep for this release.
## [1.0.0] - 2026-04-19

- Removed the native Stremio add-on host, provider-ingestion surface, local-playback route, and Stremio queue bridge from qBittorrent RSS Rules now that addon ownership moved to `jackett-stremio-fork`.
- Kept Stremio library and watch-progress synchronization in place, including live settings test/sync flows and the background Stremio auto-sync scheduler.
- Removed addon-only settings, search UI controls, smoke scripts, and release-version touchpoints, while keeping the old addon-era DB columns as deferred compatibility cleanup instead of bundling a schema migration into the split.
- Revalidated the breaking-change release with focused pytest/ruff coverage, live HTTP checks proving `/stremio/manifest.json` now returns `404`, real Stremio test/sync requests against the local desktop data, and a rebuilt desktop shell against backend version `1.0.0`.

## [0.9.2] - 2026-04-17

- Cleaned local machine-generated repo noise by removing stray `*-DESKTOP-*` Python backup copies that were no longer part of the tracked application.
- Ignored the accidental repo-root `app.db` artifact so the app’s real SQLite datastore remains the intended `data/qb_rules.db` without extra release noise.
- Revalidated the cleanup with focused pytest coverage across release/versioning, routes, Stremio addon, queueing, and settings flows, plus Ruff across `app`, `tests`, and `scripts`.
## [0.9.1] - 2026-04-17

- Added release-prep automation so patch/minor/major version bumps can synchronize repo touchpoints and scaffold changelog entries from one script-driven path.
- Added an exact-variant Stremio-to-qB queue bridge so a chosen Stremio stream can be turned into a magnet, queued in qBittorrent, and optionally prioritized to the exact `fileIdx` once metadata is available.
- Hardened OMDb handling by normalizing pasted OMDb URLs down to raw API keys, auto-healing previously saved URL-shaped secrets, and preventing background Stremio/Jellyfin sync plus passive rules-page loads from silently consuming OMDb quota.
- Improved qB/Stremio queueing and search parity by keeping grouped same-hash metadata, merging newly discovered trackers into existing qB torrents, and preserving the merged `v0.9.0` follow-up work in a clean post-release patch.
## [0.9.0] - 2026-04-11

- Completed the phase-23 cross-addon Stremio aggregation release so the local addon can merge qB RSS rows with Torrentio-compatible provider manifests into one globally ranked stream response instead of relying on Stremio's per-addon grouping.
- Persisted provider manifest configuration in app settings, fixed manifest parsing for real provider URLs that contain commas in their option payloads, and URL-encoded episode item IDs so Torrentio-compatible episode requests resolve correctly.
- Switched external provider fetches to a browser-like request profile that survives the current Torrentio edge protection, which restored live provider ingestion in the local addon and the real Stremio desktop smoke flow.
- Improved qB-authored episode metadata so resolved season-pack rows show the selected file size first, keep pack size as secondary context, and expose `behaviorHints.videoSize` alongside filename and `fileIdx`, matching Torrentio-style file-specific detail more closely.
- Revalidated the release with focused pytest/ruff/mypy checks, `scripts\\check.bat` (`337 passed`), `scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260410T222004Z\\`), `scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), fresh HTTP addon smoke on `http://127.0.0.1:8001`, and a real Stremio desktop smoke under `logs\\qa\\stremio-desktop-smoke-20260410T221925Z\\`.

## [0.8.5] - 2026-04-03

- Split the overloaded `bluray` quality token from `BDRip/BRRip` so `exclude bluray` no longer hides otherwise valid exact 4K HDR disc-rip results.
- Hardened the rules-page closeout matrix plus Stremio addon smoke tooling so exact-filter/browser validation and direct smoke-script execution stay deterministic across real release reruns.
- Increased the Stremio episode search collection budget so cold live HTTP addon requests no longer collapse to a misleading local-only row for `The Beauty` episode 1 while the in-process service still finds the full exact stream set.
- Added targeted quality-taxonomy and Jackett regressions plus a deterministic browser-closeout case for the `bluray` versus `BDRip` exact-match path.
- Revalidated the patch with `scripts\\check.bat`, `scripts\\closeout_browser_qa.py`, `scripts\\run_dev.bat desktop-build`, and sequential Stremio addon HTTP/service smoke runs.

## [0.8.4] - 2026-04-02

- Fixed the saved-rule edit form so season-finale floors that advance to next-season `E00` keep `start_episode=0` visible instead of collapsing to a blank field on edit.
- Prevented accidental loss of the precise episode floor on re-save, so the main qB RSS app no longer broadens those season-finale searches just because the edit form dropped the zero value.
- Added focused route regression coverage plus deterministic browser closeout coverage for the `E00` rule-floor edit flow.

## [0.8.3] - 2026-04-02

- Removed the hard series start-year constraint for Stremio episode lookups so long-running series such as `Death in Paradise` no longer filter out later-season Jackett results.
- Added episode-floor context (`season_number` / `episode_number`) to the main app Jackett IMDb-first series fallback path so saved-rule searches remain precise for ambiguous titles such as `Ghosts` before broadening the search.
- Added richer Stremio row detail (quality markers, size, indexer attribution) so qB-authored rows expose variant differences before full cross-addon aggregation lands.
- Revalidated the patch with focused pytest/typing/lint checks, realtime direct route probes, and desktop smoke reruns for the corrected `Death in Paradise` and `The Beauty` request payloads.

## [0.8.2] - 2026-03-28

- Kept the qB RSS Stremio addon variant set instead of collapsing it back to a tiny local-first subset, so known episode pages such as `The Beauty` can render the local `2160p` row alongside multiple `1080p` fallbacks from qB RSS.
- Sorted the visible qB RSS rows by quality first and seeds second while still upgrading exact locally available variants into fast direct local playback rows.
- Revalidated the patch with focused pytest/typing/lint checks, addon HTTP/service smokes, real Stremio desktop smoke runs for episodes `tt33517752:1:1` and `tt33517752:1:4`, and a fresh `v0.8.2` desktop/backend contract so stale `0.8.1` processes are no longer reused as the active app runtime.

## [0.8.1] - 2026-03-28

- Re-ranked qB RSS Stremio addon streams so the strongest viable variant is emitted first, keeping `2160p`/4K ahead of weaker fallbacks in the addon payload and real Stremio desktop views.
- Added qB-backed direct local playback for completed media files, including a local playback route and qB inventory fallback so already-downloaded content can play directly instead of behaving like an ordinary remote torrent.
- Kept ordinary torrent fallback behavior intact when no safe completed local file is available, while deduping local-vs-search results and preserving Stremio-compatible payloads.
- Revalidated the patch with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, `scripts\\run_dev.bat desktop-build`, addon HTTP/service smokes, real desktop smokes for episodes `tt33517752:1:1` and `tt33517752:1:4`, and a direct ranged local playback probe against the generated `/stremio/local-playback/...` URL.

## [0.8.0] - 2026-03-28

- Released the phase-20 Stremio integration slice with local desktop auth discovery, authoritative Stremio library sync, Stremio-managed rule creation/linkage, background auto-sync, and centralized completed-movie auto-disable across providers.
- Added a native qB RSS Stremio addon served directly from this app, including local manifest delivery, movie/series search catalogs, and IMDb-backed stream lookups that reuse the app's own metadata and Jackett search stack.
- Fixed the final desktop-only addon acceptance bug by simplifying qB RSS stream payloads to the Stremio-compatible contract proven by the real desktop smoke harness, so qB RSS rows now render in the Stremio desktop client for known item pages such as `The Beauty`.
- Hardened the addon against stale false negatives by avoiding long-lived caching of empty stream responses, so a transient Jackett miss no longer makes the live backend appear broken until a manual restart.
- Added automated Stremio addon QA with `scripts\\stremio_addon_smoke.py` plus real Windows desktop automation with `scripts\\stremio_desktop_smoke.py`, and revalidated the release with `scripts\\check.bat`, `scripts\\closeout_qa.bat`, `scripts\\run_dev.bat desktop-build`, HTTP/service addon smokes, and real desktop smokes for episodes `tt33517752:1:1` and `tt33517752:1:4`.

## [0.7.6] - 2026-03-27

- Fixed the rule-form filter-profile selector so choosing a profile now updates the derived minimum-quality state, token controls, and inline search results immediately instead of waiting for another field change.
- Switched frontend asset versioning to request time so refreshed pages pick up changed `app.css` and `app.js` without needing a backend restart.
- Hardened managed backend shutdown/restart handling so the desktop shell only clears ownership state after the process tree is confirmed stopped.
- Added focused regression coverage in the pytest suite, browser closeout QA, and desktop build smoke check, then published `main` and the `v0.7.6` tag to `origin`.

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
