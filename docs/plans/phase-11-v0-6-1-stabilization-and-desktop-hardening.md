# Phase 11: v0.6.1 Stabilization and Desktop Hardening

## Status

- Plan baseline created on 2026-03-24 from post-`v0.6.0` follow-up planning.
- Phase 11 was the active implementation track for `v0.6.1` and is now implemented/release-validated.
- Scope is intentionally stabilization-first: no new feature-scope expansion unless a hardening slice exposes a required compatibility fix.
- Phase 10 remains the shipped baseline; this phase owns the first post-release desktop/runtime hardening pass.
- `P11-01` and `P11-02` were completed on 2026-03-24:
  - the desktop app now enforces a single local desktop instance via a named mutex and best-effort foregrounds the existing window before a duplicate instance exits;
  - `scripts/run_dev.bat desktop` now skips rebuilds when the desktop is already running, and `full` now hands off directly to the desktop-managed startup path instead of prelaunching a separate API process.
- `P11-03` and `P11-04` were completed on 2026-03-24:
  - the base unfiltered `/` rules-page load now queues poster completion onto a detached worker with its own DB session and in-flight guard instead of doing OMDb lookups on the request thread;
  - targeted route regressions now prove that release-state rendering still works and that the rules page response renders before poster lookup completion is released.
- `P11-06` was completed on 2026-03-24:
  - a fresh live hover-evidence run was captured against `http://127.0.0.1:8000` plus a relaunched local WinUI shell, producing new browser and desktop manifests/screenshots under `logs/live-hover/live-hover-20260324T074139Z/`;
  - both capture paths recorded four lower-row samples, and the desktop/browser telemetry shows the expected side-adjacent placement with above/below vertical flips near the bottom rows instead of detached upper-list reuse.
- `P11-05` was completed on 2026-03-24:
  - the desktop shell now recognizes a packaged app root with `app\` plus a bundled `python\` runtime, prefers bundled `python.exe` for auto-start, and disables dev-only `--reload` when launching from the packaged runtime;
  - `scripts\package_desktop_bundle.ps1` plus `scripts\run_dev.bat desktop-package` now produce a portable Windows bundle under `dist\qB RSS Rules Desktop-win-x64\`, and the bundle includes `QbRssRulesDesktop.exe`, `Install qB RSS Rules Desktop.cmd`, `scripts\install_desktop_bundle.ps1`, a private Python runtime, and the app source/static/templates needed for local backend auto-start;
  - install/update flow is validated via a temp install root at `dist\install-smoke\`, and re-running the installer preserves existing `data\` content.
- Scope was adjusted on 2026-03-24 after user clarification that this product is a local end-user utility and no second Windows machine is currently available:
  - easy end-user installation and an explicit easy-to-find executable now take precedence over cross-machine dev-environment proof for `v0.6.1`;
  - the phase now treats Windows packaging/install ergonomics as the remaining release-shaping work, while multi-machine validation moves to follow-up risk/backlog tracking.
- Scope was adjusted again on 2026-03-24 after the user requested local Jellyfin recovery plus watched-progress-driven rule floors:
  - live Jellyfin operator repair is now part of this phase because the local library had stale missing-path rows and failed cleanup churn that blocked reliable progress reads;
  - a read-only Jellyfin integration that updates this app's local `start_season` / `start_episode` values is now in scope for `v0.6.1`, while writing back to Jellyfin remains explicitly out of scope.
- Scope was adjusted again on 2026-03-25 after the user clarified two runtime expectations:
  - the Jellyfin sync control must be explicit and easy to find in the UI, not only available as a low-visibility bottom-of-form submit action in Settings;
  - when Jellyfin is configured, the app should sync on app open/startup and keep listening for Jellyfin DB changes while the app is already running, rather than depending entirely on manual operator clicks.
- Scope was adjusted again on 2026-03-25 after the user tightened the Jellyfin rule contract:
  - for series, whenever Jellyfin inventory can be matched, the saved rule itself must carry the effective season+episode minimum search floor instead of depending on silent exclusion-only behavior later in result filtering;
  - for movies, a Jellyfin library match should disable the saved rule by default unless the per-rule "keep searching for better quality" override is enabled.
- Live Jellyfin DB recovery work was completed on 2026-03-24 against `C:\ProgramData\Jellyfin\Server\data\jellyfin.db`:
  - created a timestamped backup under `C:\ProgramData\Jellyfin\Server\data\SQLiteBackups\codex-20260324T213411\` before any mutation;
  - repaired duplicate `UserData` business-key collisions that were causing Jellyfin cleanup failures (`duplicate_groups_before=2`, `duplicate_groups_after=0`, `repaired_groups=2`);
  - removed `19` stale missing-path `BaseItems` rows after validating cascade safety (`missing_rows_before=19`, `missing_rows_after=0`);
  - relaunched Jellyfin directly against `C:\ProgramData\Jellyfin\Server\` and verified that the real library scan re-imported the current series directories (`db_series_rows 12`, `missing_in_db 0`, health `200` on `http://127.0.0.1:8096/health`).
- `P11-08` was completed on 2026-03-24:
  - app settings now support a Jellyfin DB path plus optional Jellyfin username, with environment overrides available for both and route-level test/sync actions on `/settings`;
  - the new read-only Jellyfin service matches saved series rules by IMDb first and normalized title fallback, resolves watched state per Jellyfin user, and intentionally treats alias-key `UserData` rows as valid progress sources so post-cleanup Jellyfin history still advances rule floors correctly;
  - bulk sync now uses a two-part contract:
    - the sync records both watched progress and existing library inventory, and existing ahead-of-progress floors are still not rolled back;
    - existing unseen library episodes are recorded separately in `Rule.jellyfin_existing_episode_numbers`, excluded by default from generated patterns, and can be re-included per rule with the `Keep searching existing unseen episodes` toggle when upgrade hunting is desired;
  - `Save + Sync Jellyfin` is available as an explicit operator action, and when qBittorrent is configured that same action immediately pushes changed rules through `SyncService` so local Jellyfin-derived rule changes do not sit unsynced in the app DB;
  - live app DB sync against `data\qb_rules.db` updated `6` saved rules on the first run (`Fauda`, `Ghosts: Fantomes en Heritage`, `Rick and Morty`, `Ted`, `The Hack`, `Yaffa`) after backing up the app DB to `data\backups\qb_rules-before-jellyfin-sync-20260324T215755.db`; the second verification run reported those same `6` rules as unchanged and `55` rules skipped because they had no Jellyfin series match.
- `P11-08` follow-up work was completed on 2026-03-25:
  - `/settings` now exposes a dedicated Jellyfin sync panel directly beside the Jellyfin DB/user fields, with visible `Test Jellyfin` and `Save + Sync Jellyfin Now` actions, an auto-sync toggle, interval control, and persisted last-run status/message;
  - the app now starts a Jellyfin auto-sync service on startup, forces an initial sync on open/startup, and then re-runs only when the configured Jellyfin DB file timestamp changes while the app remains open;
  - Jellyfin sync now records existing library episodes even when the matched series has no watched `UserData` rows yet, so default rule generation still suppresses already-present unseen episodes like `Shrinking S03E07` instead of re-searching them;
  - targeted regressions now cover visible settings controls plus the watcher startup/change-detection contract.
- `P11-09` was completed on 2026-03-25:
  - synchronized the release touchpoints to `0.6.1` (`pyproject.toml`, `app/main.py`, `CHANGELOG.md`, `tests/test_routes.py`) and closed phase 11 as the shipped stabilization slice;
  - fixed the remaining zero-based season/episode range leak across saved-rule generation parity, server-side local filtering, and browser-side local filtering so titles like `...S3E00-07...Полный S3` no longer slip through while `...S03E00-08...` still does;
  - added direct regressions for the leak in `tests/test_rule_builder.py`, `tests/test_rule_fetch_ops.py`, and a Node-backed browser-pattern test in `tests/test_routes.py`, plus live verification against the stored `The Good Ship Murder` rule row in `data\qb_rules.db`;
  - release validation passed on the final `v0.6.1` worktree via `cmd.exe /c scripts\check.bat` (`215 passed`, `57 warnings`), `cmd.exe /c scripts\closeout_qa.bat` (artifacts under `logs/qa/phase-closeout-20260325T004632Z/`), and `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`).

## Goal

Deliver a narrow `v0.6.1` release that makes the WinUI companion-process baseline safer to run day-to-day, removes the last major rules-page latency hotspot, produces an end-user-friendly Windows bundle with a clear launcher and simple install path, and adds a read-only Jellyfin watched-progress sync for saved series rules.

## Requested scope (2026-03-24)

1. Define and implement single-instance behavior for the WinUI desktop shell and its managed backend.
2. Re-run live WebView hover capture against the released desktop shell and keep evidence in the repo artifact flow.
3. Remove poster completion work from the baseline unfiltered `/` request path so rules-page loads are not held up by metadata backfill.
4. Produce an end-user-friendly Windows install bundle with a clear launcher/executable and a simple local install flow.
5. Repair the local Jellyfin library/DB state so missing-path churn stops blocking accurate watched-progress reads.
6. Connect this project to a Jellyfin database in read-only mode and update matched saved rules from watched season/episode progress.
7. Close out `v0.6.1` only after these hardening gates pass.

## In scope

- Desktop single-instance policy and managed-backend ownership semantics.
- `QbRssRulesDesktop` and `scripts/run_dev.bat` changes required to prevent duplicate managed desktop/backend sprawl.
- Rules-page poster backfill/request-path hardening on `/`.
- Windows packaging/install flow for the local desktop app, including a clear launcher and bundled backend runtime story.
- Live hover evidence capture against the released desktop shell.
- Conservative local Jellyfin DB/operator repair needed to restore the current library state before read-only integration is added.
- Read-only Jellyfin settings, series matching, watched-progress derivation, and bulk update of this app's saved series rules.
- Automatic Jellyfin sync-at-startup and low-cost background change detection while the app remains open.
- Route/unit/browser/desktop validation updates plus release-doc synchronization for `v0.6.1`.

## Out of scope

- New end-user feature flows such as rule clone/duplicate or bulk rule creation.
- Native desktop UX beyond the current WebView-hosted app.
- Writing to Jellyfin tables or relying on Jellyfin server-side mutation APIs for rule sync.
- Large refactors unrelated to desktop launch semantics or poster-path latency.

## Key decisions

### Decision: `v0.6.1` is a stabilization release
- Date: 2026-03-24
- Context: The repo just shipped `v0.6.0` with a new desktop baseline and the biggest remaining risks are operational, not feature-gap driven.
- Options considered: ship another feature-heavy minor slice; use `v0.6.1` as a hardening pass; defer hardening and expand phase scope immediately.
- Chosen option: use `v0.6.1` for a narrow stabilization pass.
- Reasoning: The desktop lifecycle baseline, cross-machine behavior, and residual rules-page latency need tighter proof before feature expansion adds more moving parts.
- Consequences: Feature backlog items such as rule clone/duplicate and bulk creation remain after `v0.6.x` unless they become necessary to support the hardening scope.

### Decision: enforce one managed desktop instance per user profile
- Date: 2026-03-24
- Context: Repeated `desktop-run` and `full` executions can still create duplicate desktop windows and managed backend ownership confusion.
- Options considered: allow multiple instances; prompt every relaunch; enforce one managed instance with best-effort handoff/reuse.
- Chosen option: enforce one managed desktop instance per user profile, with best-effort foreground/reuse behavior and a hard requirement against duplicate managed backend ownership.
- Reasoning: This gives the safest operational behavior for a localhost companion-process app without requiring a broader native desktop redesign.
- Consequences: The phase must define an explicit launch contract and may need small Windows/WinUI interop work to foreground or hand off to an existing instance.

### Decision: `full` becomes a compatibility alias for desktop-managed startup
- Date: 2026-03-24
- Context: The WinUI shell already owns backend auto-start; keeping `full` as a separate hidden-API launcher creates duplicate-start risk and conflicts with the single-instance contract.
- Options considered: preserve legacy `full` semantics; remove `full`; keep `full` as a compatibility alias that hands off to `desktop`.
- Chosen option: keep `full` as a compatibility alias for `desktop`.
- Reasoning: This preserves the familiar command name while ensuring backend startup ownership stays inside the single desktop instance.
- Consequences: Repeated `full` invocations now reuse the running desktop instead of trying to build through a locked EXE or launch a second hidden API process.

### Decision: poster completion must not block the base rules page
- Date: 2026-03-24
- Context: Phase-10 performance work reduced the cost of filtered rules-page requests, but the plain unfiltered `/` path can still spend noticeable time on poster backfill.
- Options considered: keep bounded in-request retries; disable poster backfill entirely; move poster completion off the main request path.
- Chosen option: move poster completion off the main unfiltered request path while preserving eventual poster availability.
- Reasoning: Users should get a fast rules index render even when metadata is incomplete; poster completion is secondary enrichment, not a blocking requirement.
- Consequences: The phase must define how deferred poster completion is triggered, observed, and regression-tested.

### Decision: prioritize end-user Windows packaging over second-machine dev validation for `v0.6.1`
- Date: 2026-03-24
- Context: The user clarified that the product is meant to run locally for a single end user and that a second Windows environment is not available right now.
- Options considered: hold `v0.6.1` on second-machine validation; ship without either packaging or second-machine proof; pivot the remaining release work to an end-user-friendly Windows bundle/install flow.
- Chosen option: pivot the remaining release work to packaging/install ergonomics.
- Reasoning: For a local desktop utility, the highest user-facing risk is currently installation friction and launcher discoverability, not proving the dev workflow on another machine the team does not have today.
- Consequences: Cross-machine validation becomes follow-up backlog/risk tracking instead of the blocking `v0.6.1` gate; the phase now needs a portable Windows bundle, bundled backend runtime strategy, and explicit installer/shortcut flow.

### Decision: repair the live Jellyfin DB conservatively before using it as a sync source
- Date: 2026-03-24
- Context: The local Jellyfin library was not reflecting current files, removed files were still present, and logs showed repeated cleanup failures caused by duplicate `UserData` uniqueness collisions.
- Options considered: ignore the live breakage and implement against a stale DB; wipe and rebuild the library blindly; back up the DB, repair the concrete constraint issue, remove stale missing-path rows, and then re-scan.
- Chosen option: back up first, then apply the narrowest DB repair needed to restore reliable library and watched-progress reads.
- Reasoning: The read-only integration is only useful if the underlying Jellyfin library state is trustworthy; the observed failures were localized and evidence-backed rather than a full corruption scenario.
- Consequences: Phase evidence must include the exact backup location, repair outputs, and post-scan verification numbers so the operator action remains resumable and auditable.

### Decision: Jellyfin integration stays read-only and only updates this app's local rules
- Date: 2026-03-24
- Context: The user wants Jellyfin watched progress to influence this app's `start_season` / `start_episode` floors, but Jellyfin is the source of truth for watch history.
- Options considered: write progress back into Jellyfin; use server APIs with mutation risk; read Jellyfin DB only and update local rules only.
- Chosen option: read Jellyfin DB in read-only mode and update only this app's local rule rows.
- Reasoning: This is the lowest-risk contract and keeps Jellyfin ownership boundaries clear.
- Consequences: The implementation must use SQLite read-only access, expose the DB path as configuration, and report match/sync outcomes without mutating Jellyfin data.

### Decision: Jellyfin sync derives the floor from watched progress, while existing unseen library episodes are tracked separately
- Date: 2026-03-24
- Context: Follow-up clarification established that the rule should search from the episode after the watched one, but also distinguish already-present unseen library files from genuinely missing future episodes.
- Options considered: treat any existing library episode as equivalent to watched progress; keep only a watched-derived floor and ignore library inventory; derive the floor from watched progress and store existing unseen episodes as a separate exclusion list with a per-rule override.
- Chosen option: derive the floor strictly from watched progress, store existing unseen episode keys separately, and exclude them by default while preserving a per-rule override for upgrade hunting.
- Reasoning: This preserves the user's requested semantic distinction between watched and merely downloaded files while keeping the default rule set conservative.
- Consequences: Rule/UI/pattern code must expose the override clearly, and sync must update exclusion inventory even for rules already ahead of progress.

### Decision: by default, Jellyfin sync should advance the saved rule floor past the latest existing library episode, not only rely on hidden exclusion filtering
- Date: 2026-03-25
- Context: Live verification showed that keeping `start_season` / `start_episode` pinned to watched progress while silently filtering already-present unseen episodes is operationally misleading: the saved rule still appears to search episode 7 even though the generated pattern blocks it, and users expect the rule state itself to advance to the next missing episode.
- Options considered: keep watched-derived floors plus hidden filtering only; advance the saved floor to one past the latest existing library episode by default; add a second persisted floor concept and keep both watched and effective search floors.
- Chosen option: keep recording watched progress and existing-library inventory, but advance the saved rule floor to one past the latest existing library episode by default, while preserving the existing per-rule override for users who explicitly want to keep searching unseen library episodes for upgrades.
- Reasoning: The saved rule should reflect the actual default search target, not a lower watched-progress floor that is later corrected by filtering. This directly addresses the observed `Shrinking` and `Ted` confusion.
- Consequences: Jellyfin sync tests and live verification now need to assert stored-floor advancement beyond the latest local library episode, not only exclusion-list behavior; the future “true next episode” behavior across season boundaries/specials remains a follow-up concern because the current implementation still increments numerically from known library episodes.

### Decision: when Jellyfin is configured, sync should run automatically on app startup and on DB changes
- Date: 2026-03-25
- Context: The user explicitly wants the app to listen to the Jellyfin DB while the rules app is already running and to sync especially on open.
- Options considered: keep manual-only sync; add only a more visible manual button; add a background watcher that performs an initial sync on startup and then reacts to DB mtime changes.
- Chosen option: keep manual sync available, but add a background automatic sync path with an initial startup run plus low-cost DB change detection while the app remains running.
- Reasoning: For a localhost companion app that is already running a background scheduler, automatic Jellyfin sync is operationally consistent and removes a manual step the user does not want.
- Consequences: The phase now needs persisted Jellyfin auto-sync settings/state, a background watcher lifecycle tied to app startup/shutdown, and clear UI status so automatic behavior is visible rather than hidden.

### Decision: watched progress is per Jellyfin user, with auto-selection only when the DB has exactly one user
- Date: 2026-03-24
- Context: Jellyfin stores episode progress per `UserId`, while this app currently has no user model of its own.
- Options considered: aggregate progress across all Jellyfin users; require an explicit user for every install; auto-select when exactly one Jellyfin user exists and otherwise require a username.
- Chosen option: auto-select the user when the Jellyfin DB has exactly one user; otherwise require an explicit username in settings.
- Reasoning: Aggregating across multiple users could silently over-advance rule floors; the auto-select path preserves local single-user ergonomics without taking that risk.
- Consequences: Settings now need an optional Jellyfin username field, connection tests should report discovered users, and multi-user DBs must fail closed until the user picks a Jellyfin username.

## Acceptance criteria

- Repeated WinUI desktop launches do not create duplicate managed backend processes; relaunch behavior is explicit and deterministic.
- A fresh live hover capture run against the released desktop shell is recorded and confirms the poster overlay remains correctly attached in real WebView behavior.
- The baseline unfiltered rules page no longer performs poster backfill work on the critical request path.
- A Windows bundle can be produced locally with a clear launcher/executable, bundled backend runtime support, and an install flow that does not require the user to know the repo layout or install Python manually.
- The local Jellyfin DB/library state is repaired enough that stale missing-path rows are gone and current series directories are re-imported.
- Settings can connect to a Jellyfin SQLite DB in read-only mode, resolve a usable Jellyfin user context, and report configuration errors clearly.
- Matched saved series rules can be bulk-updated from Jellyfin watched progress plus existing library inventory so `start_season` / `start_episode` move to the default next-missing episode floor reflected by the stored rule itself.
- When Jellyfin auto-sync is enabled, the app performs an initial sync on startup and reruns when the Jellyfin DB file changes while the app remains open, and `/settings` makes both automatic and manual Jellyfin sync actions obvious.
- `ruff`, `mypy`, `pytest`, deterministic browser closeout, and WinUI desktop build all pass before release closeout.

## Dated execution checklist (2026-03-24 baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P11-01 | Lock the `v0.6.1` single-instance launch contract. | Codex | 2026-03-24 | completed | Phase plan and implementation notes define how repeated launches interact with an existing desktop instance and managed backend owner. | This phase plan; decision log entries above; `docs/plans/current-status.md`; `README.md`; and launcher-contract implementation notes in `QbRssRulesDesktop/App.xaml.cs` / `scripts/run_dev.bat`. |
| P11-02 | Implement single-instance desktop + managed-backend enforcement. | Codex | 2026-03-25 | completed | Relaunches no longer create duplicate managed backends and the resulting desktop behavior is deterministic. | `QbRssRulesDesktop/App.xaml.cs` (named mutex + best-effort foreground handoff), `scripts/run_dev.bat` (`desktop` reuse path and `full` alias semantics), `README.md`, `cmd.exe /v:on /c "scripts\\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`), and a clean relaunch verification with `BeforeCount=1`, `AfterCount=1` while `cmd.exe /c scripts\\run_dev.bat full` reported reuse instead of rebuild. |
| P11-03 | Remove poster completion from the base rules-page request path. | Codex | 2026-03-25 | completed | Unfiltered `/` renders without waiting on poster backfill work; poster completion is deferred or otherwise decoupled from the critical request path. | `app/routes/pages.py` now queues candidate rule IDs onto a detached poster-backfill worker that uses its own session, retry cooldowns, and in-flight dedupe instead of doing metadata lookup in the route handler. |
| P11-04 | Revalidate rules-page latency and release-state behavior after poster changes. | Codex | 2026-03-25 | completed | Performance and release-status rendering remain correct after poster-path hardening. | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "rules_page_renders_release_status_from_snapshots or rules_page_defers_missing_poster_backfill_from_response_render"` (`2 passed`, `76 deselected`); `.\\.venv\\Scripts\\python.exe -m ruff check app\\routes\\pages.py tests\\test_routes.py` (`All checks passed`). The deferred-poster regression explicitly holds poster lookup until after `/` returns, proving the render path is no longer blocked by metadata fetch latency. |
| P11-05 | Build and validate an end-user Windows bundle/install flow. | Codex | 2026-03-26 | completed | A portable Windows bundle can be produced with a clear launcher/executable, bundled backend runtime support, and a simple local install path that preserves user data across updates. | `cmd.exe /v:on /c "scripts\\run_dev.bat desktop-package & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`); portable bundle smoke at `dist\\qB RSS Rules Desktop-win-x64\\QbRssRulesDesktop.exe` reached `http://127.0.0.1:8037/health`; installed-copy smoke at `dist\\install-smoke\\QbRssRulesDesktop.exe` reached `http://127.0.0.1:8041/health`; installer re-run preserved `dist\\install-smoke\\data\\preserve.txt`; supporting files: `QbRssRulesDesktop/Views/MainPage.xaml.cs`, `app/config.py`, `scripts/package_desktop_bundle.ps1`, `scripts/install_desktop_bundle.ps1`, `scripts/install_desktop_bundle.cmd`, `scripts/run_dev.bat`, `README.md`. |
| P11-06 | Re-run live WebView hover capture against the released desktop shell. | Codex | 2026-03-26 | completed | A fresh desktop hover-evidence run confirms poster overlay positioning remains correct in real WebView behavior. | `.\\.venv\\Scripts\\python.exe scripts\\capture_live_hover_overlay.py --desktop-relaunch` saved artifacts under `logs/live-hover/live-hover-20260324T074139Z/`; `summary.json`, `browser/manifest.json`, and `desktop/manifest.json` each recorded four lower-row samples, with desktop telemetry showing correct side-adjacent placement and above/below flips instead of detached upper-list reuse. |
| P11-07 | Repair the live Jellyfin DB/library state conservatively. | Codex | 2026-03-24 | completed | Jellyfin no longer retains stale missing-path items, the cleanup constraint collision is repaired, and a real scan re-imports the current library paths. | Backup at `C:\ProgramData\Jellyfin\Server\data\SQLiteBackups\codex-20260324T213411\`; duplicate repair output `duplicate_groups_before=2`, `duplicate_groups_after=0`, `repaired_groups=2`; stale-row cleanup `missing_rows_before=19`, `missing_rows_after=0`; relaunched Jellyfin on `http://127.0.0.1:8096/health` with post-scan verification `db_series_rows 12` and `missing_in_db 0`. |
| P11-08 | Add read-only Jellyfin watched-progress sync for saved series/movie rules. | Codex | 2026-03-25 | completed | Settings expose Jellyfin DB path plus optional username, visible manual sync controls, automatic startup/background sync, and bulk Jellyfin-driven rule updates that keep the saved rule itself aligned with the default search target: matched series store the effective next-missing season+episode floor, while matched movies auto-disable by default unless the per-rule better-quality override is enabled. | Added movie-aware Jellyfin sync plus explicit `Rule.jellyfin_auto_disabled` state in `app/models.py`, `app/db.py`, `app/services/jellyfin.py`, `app/services/jellyfin_sync_ops.py`, `app/routes/pages.py`, `app/routes/api.py`, and `app/templates/rule_form.html`; expanded test helpers and regressions in `tests/jellyfin_test_utils.py`, `tests/test_jellyfin.py`, and `tests/test_routes.py`. Validation on 2026-03-25: `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_jellyfin.py -q` (`9 passed`), `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_routes.py -k "settings_page_renders_jellyfin_controls or edit_movie_rule_page_renders_jellyfin_movie_sync_copy or edit_rule_page_can_render_inline_search_results" -q` (`3 passed`), `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_jellyfin.py tests\\test_routes.py -k "jellyfin or movie_sync_copy or settings_page_renders_jellyfin_controls" -q` (`15 passed`), `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_jellyfin_auto_sync.py -q` (`1 passed`), `.\\.venv\\Scripts\\python.exe -m ruff check app\\services\\jellyfin.py app\\services\\jellyfin_sync_ops.py app\\services\\jellyfin_auto_sync.py app\\models.py app\\db.py app\\routes\\pages.py app\\routes\\api.py tests\\jellyfin_test_utils.py tests\\test_jellyfin.py tests\\test_jellyfin_auto_sync.py tests\\test_routes.py` (`All checks passed`), `.\\.venv\\Scripts\\python.exe -m mypy app\\services\\jellyfin.py app\\services\\jellyfin_sync_ops.py app\\routes\\api.py` (`Success: no issues found in 3 source files`). Live verification against `data\\qb_rules.db` after backup `data\\backups\\qb_rules-before-jellyfin-contract-20260325T001121Z.db` confirmed `Shrinking` remains at `S03E09`, `Ted` remains at `S01E08`, matched movies `The Rip` / `Michael McIntyre: Showman` are disabled in the local rule DB, and `Red Alert` is still skipped because the real Jellyfin DB currently has no matching root item by title or IMDb ID (`tt34888633`). |
| P11-09 | Close out docs and release validation for `v0.6.1`. | Codex | 2026-03-26 | completed | Version touchpoints, release docs, and validation gates are synchronized for the stabilization release. | `pyproject.toml`, `app/main.py`, `CHANGELOG.md`, `ROADMAP.md`, `docs/plans/current-status.md`, `cmd.exe /c scripts\check.bat` (`215 passed`, `57 warnings`), `cmd.exe /c scripts\closeout_qa.bat`, `cmd.exe /v:on /c "scripts\run_dev.bat desktop-build & echo EXITCODE:!ERRORLEVEL!"` (`EXITCODE:0`), and live verification against `data\qb_rules.db` rule `3506a56d-f2e3-47da-8fe6-352911fdbf45`. |

## Risks and follow-up

### Risk: shortcut creation was not smoke-tested against the real Desktop/Start Menu targets in this session
- Trigger: Installer validation used `-SkipShortcuts` for the temp install-root smoke so it would not overwrite the current machine's existing shortcuts during development.
- Impact: The file-copy/update path is validated, but the actual Desktop/Start Menu shortcut creation step still relies on straightforward COM shortcut logic rather than a live smoke in this session.
- Mitigation: Keep the shortcut logic minimal, reuse the existing shortcut-creation pattern already used by repo dev flows, and optionally run one final no-`-SkipShortcuts` install smoke before release if a clean validation machine/profile becomes available.
- Owner: Codex
- Review date: 2026-03-26
- Status: open

### Risk: single-instance foreground handoff may need Windows-specific interop
- Trigger: Best-effort reuse of an existing desktop instance cannot be handled cleanly with the current WinUI shell alone.
- Impact: Duplicate-instance prevention may slip or require a less-polished fallback experience.
- Mitigation: Keep the hard requirement focused on blocking duplicate managed backend ownership even if foreground handoff must initially degrade to a clear exit/message path.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

### Risk: deferred poster completion could create stale or confusing UI states
- Trigger: Poster enrichment is moved off the request path without a clear refresh/update contract.
- Impact: Users may see delayed poster appearance or inconsistent cache behavior.
- Mitigation: Keep poster fallback behavior graceful, record refresh semantics in the plan, and cover visible state transitions with targeted regressions.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

### Risk: Jellyfin watch history can be stored under multiple key forms, not only the current item ID
- Trigger: Jellyfin stores some `UserData` rows on the active item ID and some on alias `CustomDataKey` values or the sentinel item ID after library cleanup.
- Impact: A naive `UserData.ItemId = BaseItems.Id` join would undercount watched episodes and generate incorrect rule floors.
- Mitigation: Build the watched-progress query against item ID plus alias-key matches (current item ID, lowercase item ID, provider IDs) and cover that behavior with targeted tests.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

### Risk: multi-user Jellyfin installs need an explicit watched-progress owner
- Trigger: This app has no user model today, while Jellyfin progress is per `UserId`.
- Impact: Auto-aggregating across users could over-advance rule floors for the wrong person.
- Mitigation: Auto-select only when the DB contains exactly one Jellyfin user; otherwise require an explicit Jellyfin username in settings and fail closed when it is missing or ambiguous.
- Owner: Codex
- Review date: 2026-03-25
- Status: open

## Next concrete steps

1. Start post-`v0.6.1` planning before more implementation work; the strongest next candidates are catalog-aware next-episode semantics across season/special boundaries and the cleanup/module-split pass for oversized files.
2. Optionally run one final shortcut-creation smoke without `-SkipShortcuts` on a clean validation profile if that environment becomes available.
3. Track second-machine desktop validation as follow-up backlog once a second Windows environment is available again.
4. If `Red Alert` should sync, repair the underlying Jellyfin identity metadata first because the current DB has no matching title/IMDb root item for that rule.
