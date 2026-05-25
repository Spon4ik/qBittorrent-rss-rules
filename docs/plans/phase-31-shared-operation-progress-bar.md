# Phase 31 - Shared Operation Progress Bar

## Summary

Add a compact global progress surface for long-running backend work. The first slice reports in-process qB rule sync, Stremio sync, Jellyfin sync, and Jackett rule fetch progress without changing the underlying sync semantics.

## Scope

- Add a process-local operation registry with active/recent operation snapshots.
- Expose `GET /api/operations/status` for the browser to poll.
- Instrument existing qB sync queue, Jackett fetch batches, Jellyfin sync, and Stremio sync.
- Render a visible global progress bar in the base layout and update it from `app.js`, including an idle state on normal page loads.
- Keep bidirectional Jellyfin/Stremio watch-progress write-back as a future phase.

## Acceptance Criteria

- Multiple simultaneous operations can be represented independently.
- The aggregate progress bar reflects all known active/recent work.
- Completed operations remain visible briefly, then expire from the registry.
- The main page renders the progress surface visibly even when there is no active/recent backend work, so the feature is not backend-only.
- Existing per-page status messages and persisted settings last-run state remain unchanged.

## Validation Checklist

- [x] Focused operation/status tests pass.
- [x] `node --check app/static/app.js` passes.
- [x] `cmd.exe /c scripts\check.bat` passes.
- [x] Shared Docker backend rebuild passes.
- [x] Docker `/health` returns `status=ok`.
- [x] Browser smoke confirms the main page visibly renders the progress surface.

## Status

- Status: implemented and locally/Docker validated on 2026-05-25; patched the closeout visibility gap so the main-page progress surface is present even when idle.
- Implemented: process-local operation registry, `/api/operations/status`, qB sync queue progress, Jackett fetch batch progress, Jellyfin/Stremio sync progress summaries, and the global base-layout polling UI.
- Validation evidence: focused operation/status/static/routes tests passed; `node --check app/static/app.js` passed; `cmd.exe /c scripts\check.bat` passed with `405 passed` and `280 warnings`; shared Docker Compose rebuild passed; Docker `/health` returned `status=ok`, `app_version=1.1.6`; browser smoke against `http://127.0.0.1:8000/` confirmed the global progress shell/bar/list are visible on the main page with idle copy, with screenshot evidence at `logs/qa/phase-31-progress-visible/main-page-progress.png`.
- Follow-up fix on 2026-05-25: main-page row sync and Sync All now enqueue qB sync work instead of running the old blocking inline routes or redirecting into individual rule pages; the qB progress operation is refreshed when the dispatcher fills a worker slot so active-worker counts do not get stuck at the post-completion `2 active` snapshot while the third slot is refilled. Validation evidence: focused route/sync-queue/rule-fetch regressions passed, `cmd.exe /c scripts\check.bat` passed with `409 passed` and `284 warnings`, shared Docker Compose rebuild passed, Docker `/health` returned `status=ok`, and browser smoke confirmed Sync All changes the visible progress surface to `Background work running` with `Syncing qBittorrent rules`.
- Adaptive qB sync follow-up on 2026-05-25: queued qB rule sync now uses a bounded adaptive worker limit instead of a fixed three-worker cap. The dispatcher starts at three concurrent rule syncs, reports the active limit in the global progress message, ramps up by one after healthy completion streaks, caps at 24 concurrent workers, and halves the learned limit on timeout/transport/back-pressure-like failures. Validation evidence: adaptive sync-queue regressions passed, route sync-all regressions passed, Ruff passed for touched files, and `cmd.exe /c scripts\check.bat` passed with `412 passed` and `284 warnings`.
- Parallel-throughput follow-up on 2026-05-25: queued qB workers no longer repeat Jackett feed discovery and qB RSS feed reconciliation for every single rule. The queue now performs feed refresh/reconciliation once before dispatching the batch, then each worker calls `sync_rule(..., reconcile_feeds=False)` so parallel slots spend their time on actual rule pushes. If batch preparation fails, workers fall back to per-rule reconciliation for correctness. Validation evidence: sync-queue regressions passed and `cmd.exe /c scripts\check.bat` passed with `414 passed` and `284 warnings`.
- qB drift-diagnostics follow-up on 2026-05-25: successful `sync_rule` repair now clears the active remote-drift banner/timestamp after qB is rewritten from local rule semantics while keeping the last observed stale remote payload for diagnostics evidence. This prevents rules such as `Rick and Morty` from continuing to show "next sync rewrites qB" after a successful sync already repaired qB. Validation evidence: focused sync/version tests passed, Ruff passed for touched sync files, `cmd.exe /c scripts\check.bat` passed with `415 passed` and `284 warnings`, desktop build passed with `0 Warning(s)` and `0 Error(s)`, shared Docker Compose rebuild passed, Docker `/health` returned `app_version=1.1.7`, live Docker sync for `Rick and Morty` cleared `drift_message`, and live qB readback matched the app-managed payload. Release state: commit `b3ffdb49` is pushed to `main`, tag `v1.1.7` is pushed, and GitHub Release `https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.1.7` is published.
- Single-rule edit-page action follow-up on 2026-05-25: the edit page now has one snapshot-aware button instead of separate `Run Search Here` and `Refresh Search Snapshot` actions. Rules without a saved snapshot route to the normal first-run snapshot flow; rules with a saved snapshot route with `refresh_snapshot=1`. The edit-page `Sync This Rule` form now queues only that rule and redirects back to the same rule page, while main-page row sync keeps returning to the rules workbench. Validation evidence: focused route regressions for snapshot action state, edit-page sync redirect, main-page row sync, and inline snapshot refresh passed; Ruff passed for touched Python files; `node --check app/static/app.js` passed; `cmd.exe /c scripts\check.bat` passed with `417 passed` and `288 warnings`; shared Docker Compose rebuild passed; Docker `/health` returned `status=ok` / `app_version=1.1.7` via `curl.exe` after PowerShell `Invoke-WebRequest` raised a local `NullReferenceException`.
- Search-result Magnet follow-up on 2026-05-25: known-infohash Jackett results now carry a merged magnet link built from the shared infohash, best display title, and all grouped tracker hints already present in magnet/Torznab result metadata. Search and rule result cards/tables render a magnet-icon action beside `Queue`; it copies the merged magnet when clipboard access is available and otherwise opens the magnet, without fetching torrent files for enrichment. The follow-up was extended for `v1.1.8` so no-hash rows can bridge into a matching known-hash sibling when title family, size bucket, year, and quality tags line up; browser validation for Rick and Morty rule `895b840e-5d41-49ba-9eff-79313cfa18bb` confirmed the original 78 GB pack groups as four variants, exposes an SVG magnet action, and the rule edit page has no document-level horizontal overflow at 1600px. Validation evidence: grouped same-hash and hash-bridge Jackett regressions passed, focused grouped queue/search tests passed, Ruff passed for touched Python files, `node --check app/static/app.js` passed, `cmd.exe /c scripts\check.bat` passed with `418 passed` and `288 warnings`, desktop build passed with `0 Warning(s)` / `0 Error(s)`, shared Docker Compose rebuild passed, and Docker `/health` returned `status=ok` / `app_version=1.1.8`.
