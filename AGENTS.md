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

## Session Closeout

Before ending a meaningful work session:

1. Update `docs/plans/current-status.md`.
2. Update the active phase plan with completion state, follow-up work, or changed assumptions.
3. Update `ROADMAP.md` only when phase scope, ordering, or long-term direction changes.

## Docker backend runtime

After any code edit, make sure the Docker qBittorrent RSS Rules backend is rebuilt, up to date, and running from the shared Docker Compose file:

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build -d qb-rss-rules
```

Then verify the running container serves the current backend:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

- The shared Compose file path is `C:\Users\nucc\docker-config\docker-compose.yml`; do not create or rely on a repo-local `docker-compose.yml` for this project.
- Use the full Docker executable path above on this machine because `C:\Windows\System32\docker` may appear earlier in `PATH` and is not the working Docker CLI.
- If Docker is unavailable or the refresh/health check fails, document the blocker in the session closeout and in `docs/plans/current-status.md`.

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
