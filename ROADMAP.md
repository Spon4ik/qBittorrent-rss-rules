# Roadmap

## Current release target: Post-v0.9.0 planning

### In progress

- Phase 23 is now closed and release-validated in `v0.9.0` as the Stremio cross-addon aggregation slice, including persisted provider manifests, live Torrentio-compatible provider ingestion inside the local addon, exact-first desktop/result-contract precursors, and real desktop smoke proof for merged provider ordering.
- Phase 24 remains closed and release-validated in `v0.8.3` as the hotfix for long-running Stremio series lookups that were over-constrained by the original series year, along with early phase 23 qB-side precursors for visibility and search precision.
- Phase 22 is now closed and release-validated in `v0.8.2` as the Stremio patch slice covering full qB RSS variant retention, global quality-first ordering, and exact-variant local playback marking after the `v0.8.1` release still suppressed rows too aggressively.
- Phase 21 is now closed and release-validated in `v0.8.1` as the Stremio playback follow-up slice covering qB RSS stream ordering and qB-backed local playback acceleration so predownloaded torrents materially improve Stremio playback.
- Phase 20 is now closed and release-validated in `v0.8.0` as the Stremio library sync and native addon parity slice, including real desktop proof that qB RSS rows render in Stremio for known items such as `The Beauty`.
- Phase 19 is now closed and release-validated as the filter-profile live-apply, request-time asset versioning, and managed-engine lifecycle hardening patch slice.
- Phase 18 is now closed and release-validated as the rule-form filter-profile live-update patch slice.
- Phase 17 remains closed and release-validated as the shared watch-state arbitration foundation slice, with Stremio sync intentionally deferred to a later phase.
- Decide whether the next Stremio-focused phase should prioritize richer catalog providers, watched-progress arbitration, or native addon metadata/configuration expansion.
- Keep the explicit music/audiobook structured Jackett search follow-up as the next cleanup/backlog slice after the main phase-23 aggregation decision, so direct capable indexers and native `music` / `book` params can replace more manual regex-heavy narrowing.
- Keep deterministic browser QA, static checks, full pytest, WinUI desktop builds, and the Stremio addon smoke pair as release gates for the next feature phase.

### Current phase track

- Phase 24: Stremio long-running series year hotfix (implemented and release-validated in `v0.8.3`; `docs/plans/phase-24-stremio-long-running-series-year-hotfix.md`)
- Phase 23: global cross-addon stream ordering (implemented and release-validated in `v0.9.0`; `docs/plans/phase-23-global-cross-addon-stream-ordering.md`)
- Phase 22: Stremio variant parity and local playback marking (implemented and release-validated in `v0.8.2`; `docs/plans/phase-22-stremio-variant-parity-and-local-marking.md`)
- Phase 21: Stremio stream ordering and qB-backed local playback acceleration (implemented and release-validated in `v0.8.1`; `docs/plans/phase-21-stremio-stream-ordering-and-local-playback.md`)
- Phase 20: Stremio library sync and native addon parity (implemented and release-validated in `v0.8.0`; `docs/plans/phase-20-stremio-library-rule-sync.md`)
- Phase 19: filter-profile live-apply, request-time asset versioning, desktop freshness polling, and managed engine lifecycle hardening (implemented and release-validated in `v0.7.6`; `docs/plans/phase-19-filter-profile-live-apply-and-managed-engine-lifecycle-hardening.md`)
- Phase 18: rule-form filter-profile live recompute and patch release (implemented and release-validated in `v0.7.5`; `docs/plans/phase-18-rule-form-filter-profile-live-recompute-and-patch-release.md`)
- Phase 17: shared watch-state arbitration foundation (implemented and release-validated in `v0.7.4`; `docs/plans/phase-17-shared-watch-state-arbitration-foundation.md`)
- Phase 16: desktop build portability and NuGet source cleanup (implemented and release-validated; `docs/plans/phase-16-desktop-build-portability-and-nuget-source-cleanup.md`)
- Phase 15: repo-local backend startup portability maintenance (implemented and manually validated; `docs/plans/phase-15-repo-local-backend-startup-portability.md`)
- Phase 14: `v0.7.2` template warning cleanup and release push (implemented and release-validated; `docs/plans/phase-14-v0-7-2-template-warning-cleanup-and-release-push.md`)
- Phase 13: `v0.7.1` desktop freshness and engine shutdown controls (implemented and release-validated; `docs/plans/phase-13-v0-7-1-desktop-freshness-and-engine-shutdown.md`)
- Phase 12: `v0.7.0` catalog-aware Jellyfin floors and missing-only queue selection (implemented and release-validated; `docs/plans/phase-12-v0-7-0-catalog-aware-jellyfin-and-missing-only-queue.md`)
- Phase 11: `v0.6.1` stabilization and desktop hardening (implemented and release-validated; `docs/plans/phase-11-v0-6-1-stabilization-and-desktop-hardening.md`)
- Phase 10: WinUI desktop bootstrap baseline + next-version planning (implemented and release-validated in `v0.6.0`)
- Phase 9: rules main-page release-aware operations + Jackett fetch orchestration (implemented and release-validated in v0.5.0)
- Phase 8: persistent rule-search snapshots and unified results workspace UX (implemented and release-validated in v0.4.0)
- Phase 7: cached-refinement responsiveness and category-catalog integrity (implemented and release-validated in v0.3.0)
- Phase 6: Jackett-backed active search workspace (implemented and release-validated in v0.2.0; follow-up polish completed, deeper persistence still deferred)
- Phase 4: feed selection UX improvements (implemented, automated closeout validated)
- Phase 5: media-aware rule form and multi-provider metadata lookup (implemented, automated closeout validated)

Phase 24 detail pointer:
- Dated checklist, regression evidence, and scope for the active `v0.8.3` long-running series hotfix live in `docs/plans/phase-24-stremio-long-running-series-year-hotfix.md`.

Phase 23 detail pointer:
- Dated checklist, release validation evidence, and follow-up notes for the delivered `v0.9.0` cross-addon ordering slice live in `docs/plans/phase-23-global-cross-addon-stream-ordering.md`.

Phase 22 detail pointer:
- Dated checklist, variant-retention decisions, and validation evidence for the completed `v0.8.2` Stremio patch slice live in `docs/plans/phase-22-stremio-variant-parity-and-local-marking.md`.

Phase 21 detail pointer:
- Dated checklist, ranking/local-playback decisions, and validation evidence for the current Stremio follow-up slice live in `docs/plans/phase-21-stremio-stream-ordering-and-local-playback.md`.

Phase 20 detail pointer:
- Dated checklist, discovery decisions, Stremio-managed rule contract, native addon decisions, and validation evidence are tracked in `docs/plans/phase-20-stremio-library-rule-sync.md`.

Phase 15 detail pointer:
- Dated checklist, repo-local `.venv` portability decisions, and manual backend health validation are tracked in `docs/plans/phase-15-repo-local-backend-startup-portability.md`.

Phase 16 detail pointer:
- Dated checklist, machine-specific NuGet source cleanup, desktop build portability validation, and `v0.7.3` release publication notes are tracked in `docs/plans/phase-16-desktop-build-portability-and-nuget-source-cleanup.md`.

Phase 17 detail pointer:
- Dated checklist, shared watch-state arbitration decisions, Jellyfin parity validation, and the later Stremio split are tracked in `docs/plans/phase-17-shared-watch-state-arbitration-foundation.md`.

Phase 18 detail pointer:
- Dated checklist, filter-profile live-update bug fix decisions, browser regression coverage, and patch-release publication notes are tracked in `docs/plans/phase-18-rule-form-filter-profile-live-recompute-and-patch-release.md`.

Phase 14 detail pointer:
- Dated checklist, warning-cleanup validation evidence, and release publication notes are tracked in `docs/plans/phase-14-v0-7-2-template-warning-cleanup-and-release-push.md`.

Phase 13 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for WinUI desktop freshness watching, fail-closed backend refresh/reconnect behavior, and in-app managed-backend shutdown/exit controls are tracked in `docs/plans/phase-13-v0-7-1-desktop-freshness-and-engine-shutdown.md`.

Phase 12 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for OMDb-backed season-finale detection, remembered Jellyfin episode history after local file cleanup, episode-`0` floor support, and qB missing/unseen file selection are tracked in `docs/plans/phase-12-v0-7-0-catalog-aware-jellyfin-and-missing-only-queue.md`.

Phase 11 detail pointer:
- Dated checklist, Jellyfin sync contract decisions, zero-based range leak closeout, and final `v0.6.1` release validation are tracked in `docs/plans/phase-11-v0-6-1-stabilization-and-desktop-hardening.md`.

Phase 10 detail pointer:
- Dated checklist, release validation, and post-release follow-up decisions for WinUI desktop phase-10 work (`QbRssRulesDesktop` scaffold, dev-loop hardening, WebView-shell baseline, and retained companion-process direction) are tracked in `docs/plans/phase-10-winui-desktop-bootstrap.md`.

Phase 9 detail pointer:
- Detailed checklist and dated execution tracker for the table-first rules page UX, poster hover/cards behavior, on-demand/scheduled Jackett rule fetch orchestration, and rule sorting by post-filter release availability is tracked in `docs/plans/phase-9-rules-main-page-release-ops.md`.

Phase 8 detail pointer:
- Detailed checklist and dated execution tracker for persistent per-rule snapshots, unified IMDb-first/title-fallback results, and compact rule-page UX is tracked in `docs/plans/phase-8-persistent-rule-search-snapshots-and-unified-workspace.md` under `Dated execution checklist (2026-03-14 baseline)`.

Phase 7 detail pointer:
- Detailed checklist and dated execution tracker for immediate cached filtering responsiveness and normalized category mapping is tracked in `docs/plans/phase-7-cached-refinement-and-category-catalog.md` under `Dated execution checklist (2026-03-12 baseline)`.

Phase 6 detail pointer:
- Detailed checklist and dated execution tracker for the latest search/rules UX hardening request is tracked in `docs/plans/phase-6-jackett-active-search.md` under `Request Checklist` and `Dated execution checklist (2026-03-10 baseline)`.

### Post-release focus

- Decide whether the next catalog/addon step should expand beyond OMDb-backed title search into richer provider support or more explicit release-calendar reasoning.
- Decide whether the next Stremio follow-up should tackle watched-progress arbitration, richer addon metadata, or provider-side configuration/options.
- Replace the fixed quality-tag bank with a compact Settings UI that lets users add, remove, and reorganize quality tokens and aliases without editing raw taxonomy JSON.
- Decide whether deleted-history persistence should stay rule-local or graduate to a broader watch-history/scrobble-compatible cache.
- Reduce context and maintenance cost by splitting the largest rule/search/Jellyfin files along real domain boundaries.
- Keep deterministic browser QA and route/service regressions as release gates for every workflow change.

## Release-validated: v0.9.0 (2026-04-11)

- Shipped the phase-23 Stremio aggregation release so the local addon can merge qB RSS rows with Torrentio-compatible provider manifests into one globally ranked stream response instead of relying on Stremio's per-addon grouping.
- Persisted provider manifest configuration in `/settings`, fixed comma-safe parsing for real provider URLs, URL-encoded episode item ids for provider stream URLs, and switched external provider fetches to a browser-like request profile that survives the current Torrentio edge protection.
- Improved qB-authored episode rows so resolved season-pack results show the selected file size first, keep pack size as secondary context, and emit `behaviorHints.videoSize` alongside filename and `fileIdx`.
- Revalidated the release with `scripts\\check.bat` (`337 passed`), `scripts\\closeout_qa.bat` (artifacts under `logs\\qa\\phase-closeout-20260410T222806Z\\`), `scripts\\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), fresh HTTP addon smoke on `http://127.0.0.1:8002`, and real desktop smoke artifacts under `logs\\qa\\stremio-desktop-smoke-20260410T223201Z\\`.

## Release-validated: v0.8.3 (2026-04-02)

- Shipped the phase-24 hotfix so long-running series like `Death in Paradise` no longer hide episode streams due to outdated start-year constraints in Stremio lookup queries.
- Shipped early phase-23 precursors: improved Stremio addon variant visibility (quality markers, size, attribution) and added episode-floor precision to the main app Jackett IMDb-first series fallback path.
- Revalidated the patch with focused pytest/typing/lint checks, realtime direct route probes, and desktop smoke reruns for the corrected `Death in Paradise` and `The Beauty` request payloads.

## Release-validated: v0.8.4 (2026-04-02)

- Shipped a maintenance hotfix so season-finale series rules that advance to next-season `E00` no longer lose `start_episode=0` when opened and re-saved from the edit form.
- Added focused route regression coverage and deterministic browser closeout coverage for the `E00` edit-form flow so the stored episode floor remains visible and stable across UI round trips.

## Release-validated: v0.8.5 (2026-04-03)

- Shipped a phase-23 maintenance follow-up so the `bluray` quality token no longer over-matches `BDRip/BRRip`, which was hiding otherwise valid exact 4K HDR results in the main qB RSS search path.
- Hardened the deterministic browser-closeout and smoke layers so the rules-page exact-filter memory check no longer depends on a flaky same-page submit transition, direct `scripts\stremio_addon_smoke.py` execution delegates to the module path, and cold live HTTP addon requests no longer fall back to a misleading local-only row for `The Beauty` episode 1.
- Added targeted taxonomy and Jackett regressions plus a deterministic browser-closeout check that proves exact movie rules keep `BDRip` rows visible when only `bluray` and `bdremux` are excluded.
- Revalidated the patch with `scripts\check.bat`, `scripts\closeout_browser_qa.py`, `scripts\run_dev.bat desktop-build`, and sequential Stremio addon service/http smoke runs.

## Release-validated: v0.8.2 (2026-03-28)

- Shipped the phase-22 Stremio variant-parity follow-up so qB RSS now keeps the broader viable variant set instead of collapsing back to a tiny local-first subset.
- qB RSS stream rows now sort by quality first and seeds second while exact locally available variants are upgraded in-place to fast local-playback rows instead of hiding the broader fallback set.
- Revalidated the patch with `scripts\check.bat` (`270 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T163220Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), addon service/http smokes, and real desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T162948Z/` and `logs/qa/stremio-desktop-smoke-20260328T163111Z/`.

## Release-validated: v0.8.1 (2026-03-28)

- Shipped the phase-21 Stremio playback follow-up so qB RSS addon rows now rank best-playable-first, keeping the strongest available qB variant ahead of weaker fallbacks in the addon payload and the real desktop client.
- Added qB-backed direct local playback for completed media files via `/stremio/local-playback/{token}`, including qB torrent/file inspection helpers, deterministic local-file resolution, and inventory fallback so already-downloaded content can play directly from disk instead of buffering like an ordinary remote torrent.
- Revalidated the patch with `scripts\check.bat` (`269 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T154314Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), `.\.venv\Scripts\python.exe scripts\stremio_addon_smoke.py --mode service --min-streams 2 --require-4k --json`, `.\.venv\Scripts\python.exe scripts\stremio_addon_smoke.py --mode http --min-streams 2 --require-4k --base-url http://127.0.0.1:8013 --json`, and real desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T154722Z/` and `logs/qa/stremio-desktop-smoke-20260328T154802Z/`.
- Verified the local playback transport directly with a ranged probe against the generated `/stremio/local-playback/...` URL, receiving `206 Partial Content`, `1,048,576` bytes, and about `9.7 ms` response time from the local backend.

## Release-validated: v0.8.0 (2026-03-28)

- Shipped the phase-20 Stremio slice with local desktop auth discovery, authoritative library sync, Stremio-managed rule creation/linkage, background auto-sync, and centralized completed-movie auto-disable shared across providers.
- Added a native qB RSS Stremio addon served from the local backend, including manifest delivery, movie/series search catalogs, and IMDb-backed stream lookups powered by the app's own metadata and Jackett search stack.
- Fixed the final desktop-only addon acceptance issue by simplifying qB RSS stream payloads to the Stremio-compatible contract proven by the real desktop smoke harness, so qB RSS rows now render in the Stremio desktop client for episodes such as `tt33517752:1:1` and `tt33517752:1:4`.
- Hardened the live addon path by avoiding long-lived caching of empty stream responses, so transient Jackett misses no longer leave the running backend looking broken until a manual restart.
- Revalidated the slice with `scripts\check.bat` (`262 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260328T140235Z/`), `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`), addon HTTP/service smokes, and real Stremio desktop smoke artifacts under `logs/qa/stremio-desktop-smoke-20260328T140625Z/` and `logs/qa/stremio-desktop-smoke-20260328T140706Z/`.

## Recently released: v0.7.4 (2026-03-27)

- Shipped the phase-17 shared watch-state arbitration foundation slice so episode-key normalization, merging, sorting, and floor selection now live in a reusable shared module.
- Jellyfin sync now routes through the shared arbitration layer without changing existing floor or history behavior, while Stremio sync remains a later follow-up phase.
- Revalidated the patch with `scripts\check.bat` (`229 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`15/15` browser checks passed), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.4` tag to `origin`.

## Recently released: v0.7.6 (2026-03-27)

- Shipped the phase-19 patch so rule-form filter-profile changes apply immediately, repo-local frontend edits refresh with a request-time asset version token, and managed backend shutdown/restart controls actually stop the process tree when confirmed.
- Added regression coverage for the live profile-selection path, the request-time asset-version refresh, and the release closeout QA flow.
- Revalidated the patch with `scripts\check.bat` (`231 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`all browser closeout checks passed`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.6` tag to `origin`.

## Recently released: v0.7.5 (2026-03-27)

- Shipped the phase-18 rule-form patch so choosing a filter profile now immediately applies the selected minimum-quality state and regenerates the derived pattern preview without waiting for another field edit.
- Added a dedicated regression check for the immediate profile-application path in both the pytest source assertions and the live browser closeout QA flow.
- Revalidated the patch with `scripts\check.bat` (`230 passed`, `1 skipped`), `scripts\closeout_qa.bat` (`all browser closeout checks passed`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)` after clearing a stale locked desktop process).
- Published `main` and the `v0.7.5` tag to `origin`.

## Recently released: v0.7.3 (2026-03-27)

- Shipped the phase-16 build-portability slice so the repo no longer depends on the missing Visual Studio offline NuGet source path and the WinUI build can restore cleanly from a fresh machine.
- Removed the hardcoded `C:\Program Files (x86)\Microsoft SDKs\NuGetPackages\` source from `NuGet.config`, leaving `nuget.org` as the sole configured restore source for the project.
- Hardened `scripts\run_dev.bat` so copied repo-local `.venv` launchers fail fast with concrete recreate commands instead of a stale `No Python at ...` error.
- Revalidated the patch with `scripts\check.bat` (`226 passed`, `1 skipped`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260327T093517Z/`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.3` tag to `origin`.

## Previously released: v0.7.2 (2026-03-25)

- Shipped the phase-14 patch so the remaining Starlette `TemplateResponse` request-second call sites are now updated to the request-first signature and no longer emit the repeated deprecation warnings during route/rendering tests.
- Synchronized the patch release touchpoints to `0.7.2` across the FastAPI app, the WinUI desktop backend-version guard, and the `/health` route regression contract.
- Revalidated the patch with `scripts\check.bat` (`227 passed`), `scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T133040Z/`), and `scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`).
- Published `main` and the `v0.7.2` tag to `origin`.

## Previously released: v0.7.1 (2026-03-25)

- Shipped the phase-13 desktop patch so the WinUI shell now watches local app changes in repo/dev-checkout mode, reloads the WebView when current scripts/templates change, and fails closed into the offline state during required refreshes that cannot reach a compatible backend.
- Tightened desktop backend compatibility checks so the `0.7.1` desktop shell rejects stale `0.7.0` backends even when they still expose the older desktop contract, and instead starts a managed fallback backend on a fresh loopback port when needed.
- Added explicit `Shut Down Engine` and `Exit Desktop` controls so stopping the desktop-managed Python backend no longer requires Task Manager.
- Revalidated the patch with `scripts\check.bat`, `scripts\closeout_qa.bat`, `scripts\run_dev.bat desktop-build`, and live WinUI launch verification against a managed `0.7.1` backend at `http://127.0.0.1:8001/`.

## Previously released: v0.7.0 (2026-03-25)

- Shipped the phase-12 catalog-aware Jellyfin/qB slice with OMDb-backed season-boundary checks, remembered skip history for deleted local episodes, and automatic missing/unseen qB file selection for saved series rules.
- Jellyfin sync now detects real season finales, advances to `S(next)E00`, and avoids false same-season floors such as `S01E11` when the current season is already complete in the external catalog.
- Saved rules now retain remembered Jellyfin known/watched episode history so deleting watched or already-known local files does not re-open them for later searches, while keeping Jellyfin read-only and avoiding a separate scrobbling subsystem.
- `Add to queue` now narrows multi-file series torrents to only missing/unseen episode files when torrent metadata is safe enough to parse, with explicit fallback or deferred messaging when it is not.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.6.1 (2026-03-25)

- Shipped the phase-11 stabilization slice with single-instance WinUI desktop enforcement, deferred poster backfill on the base rules page, fresh live WebView hover evidence, and a portable Windows bundle/install flow.
- Added read-only Jellyfin startup/background sync, explicit Settings sync controls, persisted next-missing series floors, and default movie auto-disable when a matching local Jellyfin item already exists.
- Fixed generated-pattern parity for season/episode minima so zero-based range titles such as `S3E00-07` are rejected consistently in saved rules, server-side local filtering, and browser-side local filtering while still allowing ranges that include the requested next episode.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.6.0 (2026-03-23)

- Shipped the phase-10 WinUI `QbRssRulesDesktop` WebView shell with repo-local build/run flow, shortcut refresh, and hidden companion-backend startup.
- Added stale-backend contract validation plus managed fallback-port startup so the desktop no longer reuses incompatible local servers already listening on `:8000`.
- Added desktop freshness protections (`--reload`, launch cache-buster query, orphaned managed-backend cleanup) and `/health` compatibility metadata.
- Added hidden fetched-row diagnostics and visibility reasons across `/search` and inline rule results.
- Hardened rules main-page performance with persisted release-cache columns, filtered snapshot loading, and bounded poster backfill retries.
- Revalidated the release with `scripts\check.bat`, `scripts\closeout_qa.bat`, and `scripts\run_dev.bat desktop-build`.

## Earlier release: v0.5.0 (2026-03-15)

- Shipped the phase-9 rules main-page workspace redesign with table-first defaults, cards fallback mode, and row-hover poster previews.
- Added poster metadata plumbing to persisted rules and metadata lookup flows, with graceful no-poster fallbacks in table/cards surfaces.
- Added on-demand Jackett fetch orchestration from the rules page (`Fetch Selected` and `Fetch All`) with centralized snapshot persistence for each run.
- Added schedule controls and runtime execution for recurring rule fetches, including persisted cadence/scope/last-run status in app settings.
- Added release-availability sorting and status chips derived from centralized `RuleSearchSnapshot` data (`Matches found`/`No matches`/`No snapshot`).
- Extended deterministic browser closeout automation with a phase-9 rules-workspace check (`P9-01`) plus compatibility updates for the table-only result controls.

## Earlier release: v0.4.0 (2026-03-15)

- Phase-8 persistent per-rule snapshot workflow shipped, including centralized replay/refresh behavior for inline rule results.
- Unified IMDb-first/title-fallback rendering shipped as a single source-keyed table with compact empty-state diagnostics and no standalone filter-impact panel.
- Rule-page workspace modernization shipped (sticky split rail/results layout, header-driven sorting, compact queue controls, and active local-filter chips).
- Inline affected-feed scope now applies both to rule RSS listener configuration and immediate indexer visibility in cached unified results.

## Earlier release: v0.3.0 (2026-03-13)

- Phase-7 cached-refinement/category-catalog slice shipped, including persisted indexer category mapping and scoped category option diagnostics.
- Saved-rule `Run Search` now renders inline rule-page results with feed-aware scope handling, queue actions, and table-first sort/view parity.
- Rule model and generated-pattern behavior now include episode-progress floor fields plus stricter grouped quality include semantics.
- Deterministic browser closeout automation now covers phase-7 inline local recompute, queue paused semantics, table/sort parity, and stale-category scope warnings.

## Earlier release: v0.2.0 (2026-03-11)

- Phase-6 Jackett active search shipped with IMDb-first and title-fallback split workflows
- `/search` UX density pass shipped (wider layout, compact criteria/filter-impact composition, refined result-view controls)
- Deterministic browser closeout automation + optional live-provider smoke evidence adopted for release gating
- WSL qBittorrent localhost rewrite shipped for mixed Windows/WSL topology

## Initial release: v0.1.0 (2026-03-10)

- Local FastAPI app with SQLite storage
- qBittorrent API sync for rule create/update/delete
- Import from exported qBittorrent rules JSON
- Taxonomy-driven quality filtering and media-aware rule form
- Baseline docs, ADRs, and automated test suite

## Planned after v0.7.0

- Bulk rule creation from list or CSV
- Rule clone/duplicate flows
- Improved feed grouping UX
- Dry-run sync preview
- Manual drift resolution UX
- Rule export back to normalized JSON
- Basic DB backup and restore
- Better category template editor
- Richer Jellyfin sync controls (per-rule preview/selection beyond the initial bulk sync path)

## Future / North Star

- Rule templates and preset libraries
- Sample feed simulation before save
- Desktop packaging for Windows
- Optional LAN-safe auth
- Background health checks
- Snapshot rollback
- Expanded browser automation coverage (live-provider smoke + CI gating)
- Release automation and compatibility matrix

## Explicit non-goals for v0.1.0

- Multi-user access
- Cloud deployment
- Remote hosting defaults
- Background workers
- Advanced auth and RBAC
- Raw qBittorrent JSON editing UI

## Deferred items

- Strong secret storage: deferred until a concrete platform-specific strategy is selected
- Automatic drift healing: deferred to avoid surprising overwrites in early releases
