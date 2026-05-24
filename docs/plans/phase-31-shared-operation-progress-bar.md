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
