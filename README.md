# qBittorrent RSS Rule Manager

qBittorrent RSS Rule Manager is a localhost-only FastAPI application for creating, importing, editing, and syncing qBittorrent RSS auto-download rules without relying on qBittorrent's manual JSON import flow after the initial bootstrap.

## Why it exists

qBittorrent's built-in RSS rule editor is functional but awkward for large libraries and repeated workflows. This app turns rule management into a structured, documented workflow:

- create rules from `content name`, `IMDb ID`, and quality preferences
- optionally require release year and extra include keywords in generated regex
- derive categories from templates
- fetch selectable RSS feeds from qBittorrent
- import an existing exported rules JSON once
- save changes locally and sync them to qBittorrent immediately

## Core features

- Local SQLite source of truth for app-managed rules
- qBittorrent WebUI API sync (`rss/setRule`, `rss/removeRule`, `torrents/createCategory`)
- Separate Jackett-backed active search workspace for on-demand searching, including one-click rule-derived searches that reuse saved structured terms without sending raw regex text to Jackett
- Media-aware metadata lookup via OMDb, MusicBrainz, OpenLibrary, and Google Books, with manual fallback
- Rule generation from preset-managed include/exclude quality selections, optional year matching, and extra include keywords
- Split video and audio quality filters with reusable saved profiles and media-aware built-in presets
- Bootstrap import for existing qBittorrent RSS rules export JSON
- Sync event tracking and error reporting
- Roadmap, ADRs, and release process docs included in the repo

## Local setup

1. Create a virtual environment.
2. Install the project and dev dependencies.
3. Copy `.env.example` to `.env` and adjust connection settings.
4. Run the development server.

Example:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
./scripts/run_dev.sh
```

Windows `cmd.exe` example:

```bat
cd /d "C:\Users\user\OneDrive\Document\qBittorrent rss rules"
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
scripts\run_dev.bat
```

The app binds to `127.0.0.1` by default and creates its SQLite DB under `./data`.

## WinUI desktop quick start (Windows)

1. From the repository root, run `scripts\run_dev.bat desktop` to restore/build the WinUI shell (use `desktop-build` + `desktop-run` if you want separate steps).
   If the desktop app is already open, `desktop` reuses the existing instance instead of forcing a rebuild into a locked EXE.
2. Each successful desktop build refreshes two clickable shortcuts that use the app icon: `qB RSS Rules Desktop.lnk` in the repo root and `qB RSS Rules Desktop.lnk` on your Windows Desktop.
3. If you ever need to recreate those shortcuts without rebuilding, run `scripts\run_dev.bat desktop-shortcuts`.
4. You can still launch the GUI directly via `QbRssRulesDesktop\bin\x64\Debug\net10.0-windows10.0.19041.0\win-x64\QbRssRulesDesktop.exe`.
5. When the desktop starts, it automatically launches the FastAPI backend in the background (hidden `pythonw` process). Closing the desktop shuts down the backend it started.
6. Manual fallback commands: `scripts\run_dev.bat api` (API only). `scripts\run_dev.bat full` is now a compatibility alias for `desktop`, because the desktop app handles backend auto-start itself.
7. To point the desktop at a different backend (including one running in Docker), set `QB_RSS_DESKTOP_URL` before launching the app.

### Desktop ↔ backend version expectations

The WinUI app ships with a **fixed expected** backend semver (`RequiredDesktopBackendAppVersion` in `QbRssRulesDesktop/Views/MainPage.xaml.cs`). It must equal the FastAPI `version` in `app/main.py` (and `pyproject.toml`); otherwise the shell treats the loopback server as incompatible and stays offline.

- After pulling or bumping the app version, run `python scripts/release_prep.py patch --apply` (or `minor` / `major`) from the repo root so the WinUI constant and pytest `/health` assert stay synchronized, then rebuild with `scripts\run_dev.bat desktop-build` (or `desktop`) so the EXE you run embeds the new value. An older `QbRssRulesDesktop.exe` will keep expecting the version it was built with.
- Contract bumps (`DESKTOP_BACKEND_CONTRACT` / capabilities in `app/main.py`) must be mirrored in `MainPage.xaml.cs` (`RequiredDesktopBackendContract` / `RequiredDesktopBackendCapabilities`).

## Windows bundle / install flow

1. Run `scripts\run_dev.bat desktop-package` to publish the desktop app and stage a portable Windows bundle under `dist\qB RSS Rules Desktop-win-x64\`.
2. The bundle includes:
   - `QbRssRulesDesktop.exe` at the bundle root as the direct launcher;
   - `Install qB RSS Rules Desktop.cmd` for end-user installation;
   - a private Python runtime under `python\`, so the installed app does not require a separate Python install.
3. End users can either:
   - run `QbRssRulesDesktop.exe` directly from the extracted bundle for a portable launch, or
   - double-click `Install qB RSS Rules Desktop.cmd`, which installs the app to `%LOCALAPPDATA%\Programs\qB RSS Rules Desktop` and creates Desktop + Start Menu shortcuts.
4. Re-running the installer from a newer bundle updates the app files while preserving the existing `data\` and `logs\` folders in the install location.
5. If you also want a zip artifact for distribution, run `powershell -File scripts\package_desktop_bundle.ps1 -CreateZip`.

## Environment variables

- `QB_RULES_APP_ENV`: app mode label
- `QB_RULES_HOST`: bind host
- `QB_RULES_PORT`: bind port
- `QB_RULES_DATABASE_URL`: SQLAlchemy database URL
- `QB_RULES_REQUEST_TIMEOUT`: external HTTP timeout in seconds
- `QB_RULES_QB_BASE_URL`: qBittorrent WebUI base URL
- `QB_RULES_QB_USERNAME`: qBittorrent username
- `QB_RULES_QB_PASSWORD`: qBittorrent password
- `QB_RULES_JACKETT_API_URL`: Jackett URL the app uses for active search (for Docker this is often a container hostname)
- `QB_RULES_JACKETT_QB_URL`: optional Jackett URL qBittorrent uses if it reaches Jackett differently than the app
- `QB_RULES_JACKETT_API_KEY`: Jackett API key used for active search
- `QB_RULES_OMDB_API_KEY`: OMDb API key used for video lookups

Environment values override saved app settings for secrets and connection details.

## Running

```bash
./scripts/run_dev.sh
```

On Windows `cmd.exe`:

```bat
scripts\run_dev.bat
```

Or directly:

```bash
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

## Tests and checks

```bash
./scripts/test.sh
```

On Windows `cmd.exe`:

```bat
scripts\test.bat
```

Each test run writes fresh artifacts to:

- `logs/tests/pytest-last.log`
- `logs/tests/pytest-last.xml`

The wrapper also accepts normal `pytest` arguments, for example `./scripts/test.sh tests/test_routes.py` or `scripts\test.bat tests\test_routes.py`.
On bash/WSL, `scripts/test.sh` prefers repo-local interpreters (`.venv/bin/python`, then `.venv-linux/bin/python`) and defaults to `--capture=sys` unless you pass an explicit capture flag.

For Linux/WSL-native `python3 -m pytest` setup and resume steps, see `docs/native-python-pytest.md`.

Full checks:

```bash
./scripts/check.sh
```

On Windows `cmd.exe`:

```bat
scripts\check.bat
```

The check script runs:

- `ruff check .`
- `mypy app`
- `pytest` through the logging wrapper, which refreshes `logs/tests/pytest-last.log` and `logs/tests/pytest-last.xml`

## Automated UI screenshots

Use the screenshot helper to generate repeatable desktop/mobile captures for `/search` UX review:

```bash
python -m pip install playwright
python -m playwright install chromium
./scripts/capture_ui.sh --start-server
```

If your shell does not expose `python` (common on WSL), use the repo interpreter path instead:

```bash
./.venv-linux/bin/python -m pip install playwright
./.venv-linux/bin/python -m playwright install chromium
./scripts/capture_ui.sh --start-server
```

If the app server is already running on `127.0.0.1:8000`, the shortest command is:

```bash
./scripts/capture_ui.sh
```

On Windows `cmd.exe`:

```bat
python -m pip install playwright
python -m playwright install chromium
scripts\capture_ui.bat --start-server
```

Artifacts are written under `logs/ui-feedback/<timestamp>/` with a `manifest.json` so follow-up polish passes can compare the exact captured screens.
The default run captures stable `/rules/new` and `/search` UI states without triggering live Jackett queries.
Use `--include-live-search` only when you explicitly want a live query screenshot.
On Linux/WSL hosts, if Chromium fails to launch, run `./.venv-linux/bin/python -m playwright install-deps chromium`.

## Automated browser closeout QA

Run deterministic browser closeout checks for Phase 4/5/6 with isolated mock qBittorrent + Jackett services:

```bash
./scripts/closeout_qa.sh
```

On Windows `cmd.exe`:

```bat
scripts\\closeout_qa.bat
```

Artifacts are written under `logs/qa/phase-closeout-<timestamp>/`:

- `closeout-report.md` (human-readable pass/fail summary)
- `closeout-report.json` (machine-readable details)
- `uvicorn.log` and failure screenshots (when applicable)

## qBittorrent sync

The app does not depend on qBittorrent's manual "Import RSS Rules" action. It uses the WebUI API directly:

- authenticate with `api/v2/auth/login`
- read feeds via `api/v2/rss/items`
- create categories via `api/v2/torrents/createCategory`
- create or update rules via `api/v2/rss/setRule`
- delete rules via `api/v2/rss/removeRule`

Rules are saved locally first, then synced immediately. If sync fails, the local rule remains saved and the failure is tracked.

## Importing existing rules

Use the Import page to upload an exported qBittorrent RSS rules JSON file. The importer:

- maps supported fields into the app schema
- preserves legacy `mustContain` values
- ignores runtime-only fields like `lastMatch`
- supports `skip`, `overwrite`, and `rename` conflict modes

## Known limitations

- The current release is designed for single-user localhost use.
- qBittorrent secrets can be saved locally only as lightweight obfuscation; environment variables are preferred.
- Drift detection is conservative and does not auto-resolve every remote edit case.
- Jackett active search is separate from RSS feed selection; this slice does not yet create persistent Jackett-backed rule sources automatically.
- Metadata lookups use first-match provider results; there is no interactive multi-result picker yet.
- Only OMDb uses a saved API key in this phase; the other providers use anonymous public endpoints.

## Project docs

- See [ROADMAP.md](ROADMAP.md) for current, next, and long-term direction.
- See [AGENTS.md](AGENTS.md) for repo-local resumable work instructions used at the start of each session.
- See [docs/plans/README.md](docs/plans/README.md) for active implementation plans and the current work-status ledger.
- See [docs/architecture.md](docs/architecture.md) for system details.
- See [docs/api.md](docs/api.md) for route and integration contracts.
- See [docs/testing.md](docs/testing.md) for test expectations.
- See [docs/releases.md](docs/releases.md) for release process.

## Troubleshooting

- If the feed list is empty, verify qBittorrent WebUI is enabled and the configured credentials are valid.
- If metadata lookup fails, confirm the OMDb API key for video lookups, then try manual entry.
- If Jackett search fails in Docker, verify the app-side Jackett URL is reachable from the app container and use a separate qB URL when qBittorrent is on a different network path.
- If the app starts but data is not saved, confirm `QB_RULES_DATABASE_URL` points to a writable path.
- On WSL/Linux, do not source Windows venv paths like `C:\\...\\.venv\\Scripts\\activate`; use a Linux venv path (`source .venv-linux/bin/activate`) and run `./scripts/run_dev.sh`.
- On WSL with qBittorrent running on Windows host, `localhost` may not resolve to the host service. The app now rewrites qB base URLs that use `localhost`/`127.0.0.1` to `host.docker.internal` automatically for WSL runtime resolution.
- If `./scripts/capture_ui.sh` reports missing Chromium libs on WSL/Linux, run `./.venv-linux/bin/python -m playwright install-deps chromium` (this command elevates with sudo when needed).
