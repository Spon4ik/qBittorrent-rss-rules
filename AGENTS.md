# Repository Instructions

## Session Startup

At the start of each meaningful work session:

1. Read `docs/plans/current-status.md`.
2. Read the active phase plan under `docs/plans/` before making changes that affect planned implementation scope, architecture, or incomplete phase work.
3. Read `ROADMAP.md` only when phase scope, sequencing, or long-term direction may be affected.

## WinUI desktop and release versions

The WinUI shell (`QbRssRulesDesktop`) embeds `RequiredDesktopBackendAppVersion` and compares it to `/health`’s `app_version`. If those diverge from `pyproject.toml` / `app/main.py`, the desktop shows an incompatible-backend error even when Python code is current.

- When bumping the app version, keep **one** semver across `pyproject.toml`, `app/main.py`, `QbRssRulesDesktop/Views/MainPage.xaml.cs` (`RequiredDesktopBackendAppVersion`), `tests/test_routes.py` (health assert), and `tests/test_stremio_addon.py` (manifest `+stremio.1` assert). Prefer `python scripts/release_prep.py <patch|minor|major> --apply` from the repo root so those files move together.
- After changing the desktop constants or pulling a branch that did, **rebuild** the desktop (`scripts\run_dev.bat desktop-build` or `desktop`) so the EXE you launch matches the repo; stale local builds keep old expectations.
- When changing `DESKTOP_BACKEND_CONTRACT` or `DESKTOP_BACKEND_CAPABILITIES` in `app/main.py`, mirror the same contract date and capability list in `MainPage.xaml.cs`.

## Core Behavior

- Prefer correct design over fast implementation.
- Do not assume the user's requested implementation is automatically the best approach.
- If a request appears brittle, overly manual, lossy, inefficient, or contrary to platform capabilities or best practices, pause before coding and briefly propose a better approach.
- Think 1–2 steps ahead about maintainability, correctness, API capabilities, and edge cases.
- For non-trivial features or architecture changes, do light targeted research in the codebase and relevant docs/API surface before implementation.
- Prefer the simplest robust design that makes good use of the system’s actual capabilities and avoids unnecessary complexity, duplication, or workaround logic.

## Change Scope

- Default to the smallest safe change that solves the requested problem.
- Inspect and edit only the smallest set of files needed to complete the task safely.
- Prefer minimal diffs and avoid unrelated refactors.
- Do not broaden scope unless required for correctness, safety, or explicit user request.
- Identify the likely edit surface before making broader changes.

## Deterministic debugging and UI QA

- Prefer deterministic evidence over model interpretation: assertions, exit codes, JUnit, API/DB/DOM/state checks, and small diagnostic scripts.
- Run the narrowest relevant test first; broaden only after the targeted check passes or cannot explain the failure.
- Prefer `scripts\test.bat` on Windows or `scripts/test.sh` on Linux/WSL. They keep full pytest output in `logs/tests/` and print a compact summary. Use `QB_TEST_VERBOSE=1` only when full output is necessary.
- For iterative browser/UI work, use `scripts\browser_qa.bat --check <ID>` on Windows or `scripts/browser_qa.sh --check <ID>` on Linux/WSL. Use `--suite ui` for the maintained deterministic UI-invariants audit before spending model context on screenshots or one-off visual inspection.
- The UI suite uses DOM geometry/state for representative responsive overflow, action-group safety, rule-header stability, Result-toolbar behavior, and bounded generic disclosure/menu interactions. Consume the JSON report and `UI-*-metrics.json` first. Screenshots are failure evidence only and should not be opened unless deterministic metrics are insufficient.
- Focused browser QA starts an isolated temporary app process from the checkout. A focused/UI-suite PASS proves checkout behavior only; it is **not** evidence that the Docker runtime the user is viewing was rebuilt or updated.
- Use `scripts\runtime_state.bat` on Windows or `scripts/runtime_state.sh` on Linux/WSL to report checkout version/HEAD, worktree and tracked-upstream persistence state, and deployed `/health` version. `--require-runtime-current` is the deterministic deployment-freshness gate; `--require-upstream-synced` is available when pushed persistence is required.
- Run `scripts\browser_qa.bat --full` or `scripts/browser_qa.sh --full` at most once for browser-wide closeout when that coverage is warranted. Read `codex-summary.json` / `codex-summary.md` before raw legacy reports, logs, or screenshots.
- Do not read full logs to determine PASS/FAIL. If a compact summary is insufficient, inspect only the relevant failure, stack frames, or filtered log region; deduplicate repeated errors.
- Prefer DOM/API/state assertions over screenshots for behavior. Use vision only for genuinely visual defects that deterministic checks cannot establish reliably.

## Ambiguity and Planning

- If the request is materially ambiguous, underspecified, or has multiple valid implementations, do not start coding immediately.
- First ask brief clarifying question(s) or state explicit working assumptions.
- For complex work, produce a short plan before editing.
- If the likely intent is obvious and low-risk, proceed with the smallest reasonable interpretation and make the assumption explicit.

## Phase Discipline

- Confirm whether an active implementation phase already exists before making changes.
- Implement against the active phase plan instead of improvising scope.
- If implementation must diverge from the current phase plan, update the relevant plan document before or with the code change.
- Keep roadmap, plan, and status docs aligned with the actual codebase state.

## Quality Bar

- Do not stop at the first partial fix; continue until the reported problem is actually fixed or a concrete blocker is documented.
- Be proactive about logical bugs, weak assumptions, and non-optimal designs discovered while working when they are clearly in scope.
- Make hidden constraints and tradeoffs explicit.

## Autonomous execution and validation

- When a task requires tests, fresh shells, clean Python processes, Docker rebuilds, health probes, or local service checks, do them autonomously instead of asking the user to intervene.
- If a command/test run hangs or leaves stale helper processes, recover autonomously with the smallest safe cleanup needed, then rerun the validation in a fresh process.
- Do not hand work back to the user for routine environment recovery, reruns, dependency checks, or non-destructive diagnostics.
- Pause for user confirmation only when the next step risks destructive data loss, credential exposure, broad behavior changes outside the active phase, or other dangerous intent/behavior.
- Continue phase work sequentially until the active phase is actually validated and documented; only then proceed to the next planned phase.
- After closing each phase, inspect whether the work exposed previously unknown facts that should change later scope, sequencing, tests, or release criteria. If so, update the roadmap/status docs first, then keep following the adjusted plan without waiting for routine user intervention.
- Keep packaging, commit, push, PR, and release handoff work moving after validation passes; do not leave completed phase work local unless a concrete blocker is documented.

## Session Closeout

Before ending a meaningful work session:

1. Update `docs/plans/current-status.md`.
2. Update the active phase plan with completion state, follow-up work, or changed assumptions.
3. Update `ROADMAP.md` only when phase scope, ordering, or long-term direction changes.
4. Run `scripts\runtime_state.bat` (or `scripts/runtime_state.sh`) when the task changes deployable application code or deployment/persistence status is relevant.
5. Report these states separately when applicable:
   - **Implementation:** PASS / FAIL / BLOCKED.
   - **Focused validation:** PASS / FAIL / NOT RUN, with the relevant deterministic checks.
   - **GitHub persistence:** PUSHED/SYNCED with branch+commit, LOCAL ONLY/UNPUSHED, or NOT APPLICABLE.
   - **Docker deployment:** CURRENT with running version, STALE with running-vs-checkout versions, NOT ATTEMPTED, FAILED, or NOT APPLICABLE.
   - **Release/tag:** PUBLISHED, NOT PUBLISHED, NOT REQUESTED, or BLOCKED.

If the finalizer stops before Docker rebuild, say explicitly that deployment was **not attempted** and that the currently running UI/runtime may still be the previous version. Do not ask the user to visually validate a fix in that runtime until deployment state is CURRENT.

## Backend completion gate and Docker runtime

After a coherent backend code change is ready for final validation, use the repository's deterministic finalizer rather than remembering local checks and Docker refresh as separate steps:

```powershell
.\Finalize-Backend.cmd --no-pause
```

`Finalize-Backend.cmd` is a shell-safe wrapper around the human-friendly `Finalize Backend.cmd`.

A backend-affecting task is not deployment-complete unless this command exits with code 0. The finalizer:

1. runs `scripts\check.bat` (`ruff` -> `mypy` -> pytest);
2. if deterministic checks fail, stops immediately, labels Docker deployment **NOT ATTEMPTED**, and prints checkout/upstream/runtime state;
3. only after all checks pass, invokes the Docker updater;
4. the updater rebuilds/restarts `qb-rss-rules` and waits for `/health`;
5. final runtime-state validation returns non-zero unless `/health.app_version` matches the checkout `pyproject.toml` version.

During iterative debugging, run the narrowest targeted tests needed; do **not** run the finalizer after every intermediate edit.

`Update-Docker.cmd` is the canonical shell/automation Docker-only command. `Update Docker.cmd` remains available for human double-click use. From Codex or PowerShell, use `.\Update-Docker.cmd --no-pause` only when reproducing or validating Docker-specific runtime behavior before the final gate; do not use it as a substitute for the finalizer when closing a backend code task. The Docker-only wrapper also requires the runtime version check before reporting success.

The Docker updater:

- uses `C:\Users\nucc\docker-config\docker-compose.yml` and rebuilds/restarts only `qb-rss-rules`;
- uses the shared Compose `.env` file when present;
- uses the known-good Docker Desktop CLI path rather than relying on `PATH`;
- starts Docker Desktop automatically when the engine is not ready;
- verifies that the Compose build context points at the checkout from which the updater is running;
- captures verbose Docker output in `logs\docker\update-docker-last.log` instead of flooding model context;
- waits for `http://127.0.0.1:8000/health` and returns non-zero on build, startup, configuration, health, or deployed-version freshness failure;
- prints only a concise success result, or a bounded failure tail plus the full log path.

- The shared Compose file path is `C:\Users\nucc\docker-config\docker-compose.yml`; do not create or rely on a repo-local `docker-compose.yml` for this project.
- If the updater reports that the Compose build context does not match the current checkout, update the shared Compose file intentionally before retrying; do not bypass the safety check.
- If Docker is unavailable or the finalizer/updater/health check fails, document the blocker in the session closeout and in `docs/plans/current-status.md`.

## Database location

The app's SQLite database must stay with the project runtime data, not with the shell's current working directory.

- Relative SQLite URLs such as `sqlite:///./data/qb_rules.db` must resolve from the app/repo root (`app.config.ROOT_DIR`), not from `Path.cwd()`.
- The shared Docker service must bind-mount the repo `data` directory to `/app/data`; do not use an anonymous or named Docker volume for `qb_rules.db`, because that creates an empty database after moving the project folder.
- After moving the repo again, update `C:\Users\nucc\docker-config\docker-compose.yml` so the `qb-rss-rules` service bind mount points at the new repo `data` path, then rebuild/start Docker and verify `/health` plus the rule count.

## Host path handling in Docker

Saved Windows file paths must keep working when the backend runs in Docker.

- Windows absolute paths such as `C:\Users\...\Stremio\...\leveldb` and `C:\ProgramData\Jellyfin\Server\data\jellyfin.db` are translated through `QB_RULES_WINDOWS_HOST_MOUNT_ROOT` (default `/host`) by `app.config.resolve_runtime_path`.
- Keep the shared Docker service mounts aligned with that translation:
  - `C:\Users` -> `/host/C/Users`
  - `C:\ProgramData` -> `/host/C/ProgramData`
- When adding any backend code that reads a local file path from settings or env, use `resolve_runtime_path(...)` instead of `Path(...)` / `Path.cwd()` so repo moves and Docker migration do not create `/app/C:\...` style paths.
- After path-related changes, verify Stremio and Jellyfin from inside Docker, not only with unit tests.

## Resumability

- Record what is already implemented.
- Record what is currently in progress.
- Record the next concrete steps.
- Keep phase plans decision-complete enough that another engineer or agent can resume work immediately.
- Treat `docs/plans/current-status.md` as the live short-form handoff and `docs/plans/` as the implementation-level source of truth.
