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

## Token-efficient debugging

- Prefer deterministic evidence over model interpretation: assertions, exit codes, JUnit, API/DB/DOM/state checks, and small diagnostic scripts.
- Run the narrowest relevant test first; broaden only after the targeted check passes or cannot explain the failure.
- Prefer `scripts\test.bat` (Windows) or `scripts/test.sh` (Linux/WSL). They keep full pytest output in `logs/tests/` and print a compact summary. Use `QB_TEST_VERBOSE=1` only when full output is necessary.
- Do not read full logs to determine PASS/FAIL. If the summary is insufficient, inspect only the relevant failure, stack frames, or filtered log region; deduplicate repeated errors.
- Pass conclusions plus minimal supporting evidence between agents, not the same raw logs or repository dumps repeatedly.
- Prefer DOM/API/state assertions over screenshots for behavior. Use vision only for genuinely visual defects.

## Model routing and task ownership

Subagents consume extra tokens. Prefer one task owner over a fixed multi-agent pipeline, and do not delegate when the current parent already has the right capability and can finish the task without duplicated context.

- **Known task type beats classification.** An application maintenance request with `mode=incident` or `route=incident_lead` is already classified: delegate it once to `incident_lead` and pass the structured payload unchanged.
- **Human-reported wrong or unexpected existing behavior:** the normal owner is Terra/medium. A Terra/medium-or-stronger parent should own the investigation directly; a cheaper parent should delegate once to `investigator`.
- **Clear, sufficiently specified feature/change:** the normal owner is Terra/medium. A suitable parent should implement directly; otherwise delegate once to `builder`.
- **Open-ended product/UX/feature-concept/architecture work:** the normal owner is GPT-5.6/high. If the parent is below that capability, pass the user's original request verbatim to `architect`; the architect designs and a Terra owner normally implements afterward.
- **Exceptional unresolved debugging:** use `deep_debugger` only when the current owner can state a concrete unresolved question, competing hypotheses, non-local causality, or contradictory evidence. One failed attempt is not sufficient reason to escalate.
- Do not route routine compact test output through another model merely to classify PASS/FAIL or an obvious local failure; the parent or current owner can consume the deterministic summary directly.
- Do not paraphrase the user's original request into a speculative diagnosis before handing work to a more capable agent. Send the original request plus only established constraints/evidence.
- No fixed `triage -> explore -> fix -> debug` ladder. Agents own tasks end to end where safe; use at most two concurrent subagents and parallelize only genuinely independent work.
- Handoffs should be compact decision packets using the applicable fields: `status` (`solved`, `design_complete`, `needs_architect`, `needs_deep_debugger`, `blocked`), `confidence`, established evidence, decision/root cause, change surface, validation, unresolved question, and escalation reason.
- Project custom agents must not recursively delegate. The parent performs any justified next dispatch after reading the compact packet.

Practical parent defaults: application-generated incident automation may use Luna/low because classification is explicit; normal human coding/behavior sessions should normally start Terra/medium; long interactive product or architecture discussions should normally start GPT-5.6/high.

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

## Backend completion gate and Docker runtime

After a coherent backend code change is ready for final validation, do not run the local checks and Docker refresh as separate remembered steps. Use the repository's deterministic backend finalizer.

From PowerShell, Codex, or another PowerShell-based non-interactive shell, run exactly:

```powershell
& ".\Finalize Backend.cmd" --no-pause
```

PowerShell requires the call operator (`&`) when invoking a quoted executable/script path that contains spaces. Do not use the unquoted form `./Finalize Backend.cmd ...` or `.\Finalize Backend.cmd ...`.

A backend-affecting task is not complete unless this command exits with code 0. The finalizer provides the mechanical chain:

1. runs `scripts\check.bat` (`ruff` -> `mypy` -> pytest);
2. stops immediately if any deterministic check fails, without rebuilding Docker;
3. only after all checks pass, invokes `Update Docker.cmd --no-pause` internally;
4. the Docker updater rebuilds/restarts `qb-rss-rules`, waits for `/health`, and returns non-zero if build, startup, configuration, or health validation fails.

During iterative debugging, continue to run the narrowest targeted tests needed; do **not** run the finalizer after every intermediate edit. Run it once the backend change appears complete and is ready for final validation.

`Update Docker.cmd` remains the canonical on-demand Docker-only command. A human may double-click it after syncing Git on the Docker host. From PowerShell/Codex, invoke it as `& ".\Update Docker.cmd" --no-pause` when reproducing or validating Docker-specific runtime behavior before the final gate. Do not use the Docker-only updater as a substitute for the finalizer when closing a backend code task.

The Docker updater:

- uses `C:\Users\nucc\docker-config\docker-compose.yml` and rebuilds/restarts only `qb-rss-rules`;
- uses the shared Compose `.env` file when present;
- uses the known-good Docker Desktop CLI path rather than relying on `PATH`;
- starts Docker Desktop automatically when the engine is not ready;
- verifies that the Compose build context points at the checkout from which the updater is running, preventing an accidental rebuild of another clone;
- captures verbose Docker output in `logs\docker\update-docker-last.log` instead of flooding the model context;
- waits for `http://127.0.0.1:8000/health` and returns non-zero on build, startup, configuration, or health failure;
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
