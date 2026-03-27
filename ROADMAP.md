# Roadmap

## Current release target: v0.7.7 patch hardening

### In progress

- Phase 19 is now closed and release-validated as the filter-profile live-apply, request-time asset versioning, and managed-engine lifecycle hardening patch slice.
- Phase 18 is now closed and release-validated as the rule-form filter-profile live-update patch slice.
- Phase 17 remains closed and release-validated as the shared watch-state arbitration foundation slice, with Stremio sync intentionally deferred to a later phase.
- Next planning focus is to open the Stremio source-adapter phase, then return to richer catalog providers, broader watch-history persistence, and large-file/module split work.
- Keep deterministic browser QA, static checks, full pytest, and WinUI desktop builds as release gates for the next feature phase.

### Current phase track

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

- Decide whether the next Jellyfin/catalog step should expand beyond OMDb-backed season boundaries into richer provider support or more explicit release-calendar reasoning.
- Decide whether deleted-history persistence should stay rule-local or graduate to a broader watch-history/scrobble-compatible cache.
- Reduce context and maintenance cost by splitting the largest rule/search/Jellyfin files along real domain boundaries.
- Keep deterministic browser QA and route/service regressions as release gates for every workflow change.

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
