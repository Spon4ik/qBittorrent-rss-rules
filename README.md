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
- Real-Debrid Device OAuth, personal torrent-cloud/download-history search, and qBittorrent HTTP web-seed acceleration
- MyJDownloader fallback for Real-Debrid files when a hash-only torrent never obtains metadata in qBittorrent
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

## Docker backend quick start

The FastAPI backend can run in Docker while the WinUI desktop shell, qBittorrent, Jackett, Jellyfin, and Stremio remain outside the container.

```bash
docker compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build qb-rss-rules
```

Then open:

```text
http://127.0.0.1:8000
```

The shared Compose setup in `C:\Users\nucc\docker-config\docker-compose.yml` bind-mounts this repo's `data` directory into `/app/data` and publishes the backend on `${QB_RULES_PORT:-8000}`. This keeps Docker and local/dev launches pointed at the same `data/qb_rules.db`.

### Real-Debrid and MyJDownloader setup

1. Open `/settings`, connect Real-Debrid, and authorize the displayed Device OAuth code. Acceleration enables only for a Premium account.
2. Keep the web-seed base URL reachable from qBittorrent. For the current Windows-host qBittorrent and Docker backend, `http://127.0.0.1:8000` is correct; use an appropriate host/container address for other network layouts.
3. Optionally enter MyJDownloader credentials, test the connection, select a device, then save settings. It is used only for standalone Real-Debrid history items or after the configurable metadata timeout.
4. New manual and RSS downloads receive the `qb-rss-rules` tag automatically. Use **Adopt Existing Torrents** to opt incomplete torrents in enabled rule categories into acceleration; untagged torrents are never adopted automatically.

Real-Debrid is not a public indexer: searches cover only the authenticated account's torrent cloud and download history. qBittorrent remains the primary downloader whenever v1/hybrid torrent metadata exists. Private or credential-bearing metainfo is never uploaded; the app sends only a tracker-free hash magnet. The local secret key is stored as ignored runtime data at `data/.secret-key`; back it up with the database or provide a stable `QB_RULES_SECRET_KEY`.

If you move the project folder again, update that bind mount in `C:\Users\nucc\docker-config\docker-compose.yml` to the new repo `data` path, then rebuild the `qb-rss-rules` service. The app itself resolves relative SQLite URLs from its own app root, so local runs do not depend on the shell's current working directory.

When qBittorrent or Jackett run on the host machine, container-side `localhost` points at the container, not the host. Use `host.docker.internal` URLs in `.env` or shell environment before starting compose:

```bash
QB_RULES_QB_BASE_URL=http://host.docker.internal:8080
QB_RULES_JACKETT_API_URL=http://host.docker.internal:9117
docker compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build qb-rss-rules
```

In the current shared Compose stack, Jackett publishes port `9117` on the host while using Docker bridge networking, so the backend defaults both app-side and qB-facing Jackett URLs through `host.docker.internal`.

Windows host file paths saved in settings are also container-aware. The shared Compose service mounts `C:\Users` at `/host/C/Users` and `C:\ProgramData` at `/host/C/ProgramData`, and the backend translates paths such as `C:\Users\nucc\...` or `C:\ProgramData\Jellyfin\...` through `QB_RULES_WINDOWS_HOST_MOUNT_ROOT=/host`. This keeps Stremio local storage sync and Jellyfin DB sync working after moving the project into Docker.

Docker validation checklist for this machine:

1. Rebuild and start the shared backend service:

   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build -d qb-rss-rules
   ```

2. Verify backend health:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8000/health
   ```

3. Verify qBittorrent connectivity from inside the running backend container:

   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec qb-rss-rules python -c "from app.db import get_session_factory; from app.services.settings_service import SettingsService; from app.services.qbittorrent import QbittorrentClient; s=get_session_factory()(); settings=SettingsService.get_or_create(s); c=SettingsService.resolve_qb_connection(settings); QbittorrentClient(c.base_url, c.username, c.password).test_connection(); print('qb_test=ok')"
   ```

4. Verify Jackett reachability from inside the running backend container:

   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' exec qb-rss-rules python -c "from app.db import get_session_factory; from app.services.settings_service import SettingsService; from app.services.jackett import JackettClient; s=get_session_factory()(); settings=SettingsService.get_or_create(s); j=SettingsService.resolve_jackett(settings); print('jackett_indexers=' + str(len(JackettClient(j.api_url or '', j.api_key or '', language_overrides=j.language_overrides).configured_indexer_options())))"
   ```

To build and run without compose:

```bash
docker build -t qbittorrent-rss-rule-manager:local .
docker run --rm -p 8000:8000 -v qb-rss-rules-data:/app/data qbittorrent-rss-rule-manager:local
```

If you want the WinUI desktop shell to use the Docker backend, start the container first and launch the shell with `QB_RSS_DESKTOP_URL=http://127.0.0.1:8000`.

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
- `QB_RULES_SECRET_KEY`: optional stable Fernet key used to encrypt saved integration secrets; otherwise `data/.secret-key` is generated
- `QB_RULES_QB_BASE_URL`: qBittorrent WebUI base URL
- `QB_RULES_QB_USERNAME`: qBittorrent username
- `QB_RULES_QB_PASSWORD`: qBittorrent password
- `QB_RULES_JACKETT_API_URL`: Jackett URL the app uses for active search (for Docker this is often a container hostname)
- `QB_RULES_JACKETT_QB_URL`: optional Jackett URL qBittorrent uses if it reaches Jackett differently than the app
- `QB_RULES_JACKETT_API_KEY`: Jackett API key used for active search
- `QB_RULES_JACKETT_LANGUAGE_OVERRIDES`: optional manual language assignments for Jackett indexers when Jackett metadata is missing or wrong. Use JSON such as `{"noname-clubl":["ru"],"thepiratebay":["en"]}` or assignment syntax such as `noname-clubl=ru;thepiratebay=en,multi`. The same mappings can also be edited from `/settings` under `Indexer language overrides`.
- `QB_RULES_OMDB_API_KEY`: OMDb API key used for video lookups
- `QB_RULES_WINDOWS_HOST_MOUNT_ROOT`: container mount root for translating Windows absolute paths, default `/host`

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
- If a configured Jackett indexer appears as unclassified or the wrong language, add it in `/settings` under `Indexer language overrides`, or set `QB_RULES_JACKETT_LANGUAGE_OVERRIDES` with the Jackett indexer id and one or more language codes, then restart/rebuild the backend.
- Taxonomy edits made from `/taxonomy` are stored in `data/quality_taxonomy.json`. The packaged `app/data/quality_taxonomy.json` is only the seed/default, so local taxonomy values and quality presets survive ordinary code edits and rebuilds unless the change intentionally targets taxonomy behavior.
- If Jackett search fails in Docker, verify the app-side Jackett URL is reachable from the app container and use a separate qB URL when qBittorrent is on a different network path.
- If the app starts but data is not saved, confirm `QB_RULES_DATABASE_URL` points to a writable path. Relative SQLite URLs such as `sqlite:///./data/qb_rules.db` are resolved from the app root, not the shell's current directory.
- On WSL/Linux, do not source Windows venv paths like `C:\\...\\.venv\\Scripts\\activate`; use a Linux venv path (`source .venv-linux/bin/activate`) and run `./scripts/run_dev.sh`.
- On WSL with qBittorrent running on Windows host, `localhost` may not resolve to the host service. The app now rewrites qB base URLs that use `localhost`/`127.0.0.1` to `host.docker.internal` automatically for WSL runtime resolution.
- If `./scripts/capture_ui.sh` reports missing Chromium libs on WSL/Linux, run `./.venv-linux/bin/python -m playwright install-deps chromium` (this command elevates with sudo when needed).
