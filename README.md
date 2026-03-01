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
- OMDb lookup by IMDb ID, with manual fallback
- Rule generation from preset-managed include/exclude quality selections, optional year matching, and extra include keywords
- Split resolution, video-definition, and source filters with reusable saved profiles
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

## Environment variables

- `QB_RULES_APP_ENV`: app mode label
- `QB_RULES_HOST`: bind host
- `QB_RULES_PORT`: bind port
- `QB_RULES_DATABASE_URL`: SQLAlchemy database URL
- `QB_RULES_REQUEST_TIMEOUT`: external HTTP timeout in seconds
- `QB_RULES_QB_BASE_URL`: qBittorrent WebUI base URL
- `QB_RULES_QB_USERNAME`: qBittorrent username
- `QB_RULES_QB_PASSWORD`: qBittorrent password
- `QB_RULES_OMDB_API_KEY`: OMDb API key

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
./scripts/check.sh
```

On Windows `cmd.exe`:

```bat
scripts\check.bat
```

The check script runs:

- `ruff check .`
- `mypy app`
- `pytest`

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

- v0.1.0 is designed for single-user localhost use.
- qBittorrent secrets can be saved locally only as lightweight obfuscation; environment variables are preferred.
- Drift detection is conservative and does not auto-resolve every remote edit case.
- OMDb is the only metadata provider in v0.1.0.

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
- If metadata lookup fails, confirm the OMDb API key or use manual entry.
- If the app starts but data is not saved, confirm `QB_RULES_DATABASE_URL` points to a writable path.
