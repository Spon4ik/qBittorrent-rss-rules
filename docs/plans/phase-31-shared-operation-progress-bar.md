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
