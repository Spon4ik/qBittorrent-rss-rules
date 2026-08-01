# Phase 29 - Rules Operations Workbench

## Summary

Phase 29 turns the rules page into a compact operations workbench. Rule edits save locally first and hand qB sync to a background queue, while rule snapshots, quality assignment, filters, release signal, and status chips are designed for scan-and-batch work on the main grid.

## Scope

- Save create/update rule changes locally first, then enqueue qB sync in an in-process background worker.
- Add visible transient sync states for queued/background work.
- Add batch quality-profile assignment from the rules page for `No preset`, `At Least Full HD`, and `Ultra HD HDR`.
- Preserve managed/manual quality authority by setting managed built-in profile identity without rewriting stored manual token snapshots.
- Add a rules-page quality filter for manual/custom, all managed, no preset, and built-in managed profiles.
- Add active filter chips and clear-filter behavior that also clears localStorage filter restoration.
- Replace separate exact/matches table columns with a backend-derived release signal and combined counts.
- Prioritize batch/scheduled snapshot fetches by no snapshot first, oldest snapshot next, then rule name.
- Add bounded parallel rule snapshot fetching with default parallelism `3`.
- Redesign `/` around a desktop data-grid workbench: compact filters, contextual selected-row batch bar, schedule strip, readable chips, compact row actions, and global version visibility.
- Add detailed version/backend contract display in Settings.

## Non-Goals

- Do not add saved custom-profile identity to the rule data model.
- Do not rewrite the frontend to React or another framework.
- Do not change qB RSS payload semantics beyond moving create/update sync to background work.
- Do not change Jackett indexer scope authority from the Phase 28 `search_indexers` contract.

## Test Plan

- Route/service coverage:
  - create/update save enqueues qB sync instead of calling qB inline;
  - queued sync success/failure updates visible rule status;
  - batch profile assignment preserves managed/manual token contracts;
  - quality filter finds manual/custom rules;
  - release signal ranks exact/fallback/no-snapshot cases;
  - fetch ordering starts with missing snapshots, then oldest snapshots;
  - parallel fetch obeys configured worker limits.
- UI/static/browser coverage:
  - clear filters resets URL/form/localStorage restore;
  - contextual batch bar appears only with selected rows;
  - row actions remain grouped and compact;
  - release/sync chips are readable and do not stretch like progress bars;
  - version is visible in the shell and Settings;
  - narrow/medium/wide screenshots show no page-level horizontal overflow.
- Validation gate:
  - focused pytest slices for routes, rule fetch ops, sync queue, static assets;
  - `node --check app/static/app.js`;
  - Ruff on touched Python;
  - `cmd.exe /c scripts\check.bat`;
  - browser visual closeout;
  - required Docker rebuild and `/health` check.

## Status

- Status: implemented and validated locally; ready for packaging / review handoff.
- Started: 2026-05-08.
- Release target: post-`v1.1.6` feature slice.

## Current Evidence

- Follow-up on 2026-06-04: the Release signal column now renders compact `e/v/r` counts (`exact visible / visible / results fetched`) and the Release signal dropdown filters by waterfall thresholds (`Any results`, `Visible results`, `Exact results`, `No snapshot`) instead of the older status-only values. Validation evidence: focused release-signal regressions failed red first and passed after implementation; `tests/test_routes.py` passed; `node --check app/static/app.js` passed; full `cmd.exe /c scripts\check.bat` passed (`473 passed`, `292 warnings`); shared Docker Compose rebuild passed; Docker `/health` returned `status=ok`, `app_version=1.2.17` via `curl.exe` after the known local PowerShell `Invoke-WebRequest` failure.
- Added `SyncStatus.pending` / `SyncStatus.syncing` and a small background sync queue used by rule create/update and batch quality assignment.
- Added `POST /api/rules/batch-quality-profile`.
- Added `AppSettings.rules_fetch_parallelism` with SQLite backfill and clamped default `3`.
- Added release signal derivation to `release_state_from_snapshot`.
- Added compact rule-level snapshot summary fields so the rules workbench can render release signal without reading bulky snapshot payload rows on every page load.
- Added missing/oldest-first snapshot fetch prioritization and bounded parallel batch execution.
- Rebuilt the rules page template/CSS/JS around the data-grid direction, including quality filters, active chips, clear filters, contextual batch bar, small status chips, icon-only compact row actions, and version display.
- Fixed rule edit page saved-snapshot replay and the denormalized rule-local release-count cache so fallback rows must still match the rule title/IMDb identity before they count as visible.
- Focused validation passed:
  - `cmd.exe /c scripts\test.bat tests\test_routes.py tests\test_rule_fetch_ops.py tests\test_sync_queue.py tests\test_static_assets.py -q`
  - `node --check app/static/app.js`
  - Ruff on touched Python files
  - `git diff --check`
- Full validation passed:
  - `cmd.exe /c scripts\check.bat` (`388 passed`, `274 warnings`)
  - shared Docker Compose rebuild passed
  - Docker `/health` returned `status=ok`, `app_version=1.1.6`
  - Docker `/` timing after snapshot-summary backfill: `0.085s`, `0.055s`, `0.083s`
  - live Docker browser repro for `Spider-Man: Brand New Day` / `tt22084616` now shows `0 filtered / 745 fetched`, `0` visible cards, `745` hidden fetched rows, `Title fallback: 0 filtered / 745 fetched`, and the main rules grid row shows `visible 0 / 745`.
  - runtime data recovery after the cache refresh: backed up the malformed `data/qb_rules.db`, rebuilt a clean recovered DB with `212` rules / `205` snapshots / `8656` sync events, reconstructed four affected rule rows from saved snapshots and sync history, verified `PRAGMA integrity_check=ok`, verified Docker can acquire a write lock, and restarted the shared Docker backend successfully.
- Browser visual evidence is under `logs/qa/phase-29-visual/`.

## Discovery Review

- Visual QA caught the sync chip stretching inside grid cells, recreating the false progress-bar look from the report. CSS now makes status chips width-to-content and keeps row actions in one compact group on desktop and inside the horizontally scrollable table on narrow screens.
- Follow-up visual feedback caught that text row actions still did not match the approved sketch direction. Row actions are now compact icon controls with tooltips/accessible labels, and screenshots were refreshed at wide, medium, narrow, and selected-row states.
- Performance profiling showed the slow Docker `/` path was not qB sync or Jinja rendering; SQLite was spending seconds fetching lightweight columns from the large snapshot table because rows sit beside bulky persisted payloads. Phase 29 now denormalizes release-signal summary counts onto `rules`, backfills existing data once, and updates summaries whenever rule snapshots refresh.
- The in-app browser tab at `http://localhost:61597/` was still showing the earlier design companion frame, so implementation visual QA used a fresh app backend on `http://127.0.0.1:8017/`.
- User repro on 2026-05-08 caught a deeper rule-identity bug in the denormalized release-count cache: the cache enforced quality/scope/year filters but did not require fallback rows to match the rule title or IMDb id, so unrelated broad `Spider-Man` rows were counted as visible. The corrected path keeps browser title narrowing in place and moves the same title/IMDb identity check into backend rule-local filtering, so grid counts and edit-page visible rows now agree at `0 / 745` for `Spider-Man: Brand New Day`.
