# Architecture

## System overview

qBittorrent RSS Rule Manager is a localhost-only FastAPI application that stores app-managed rule definitions in SQLite and synchronizes them to qBittorrent through the WebUI API.

The app is designed around one rule authority:

- local DB is the editing source of truth
- qBittorrent is the execution target
- exported qBittorrent JSON is only a bootstrap/import format

## Major components

- `app/routes/pages.py`: HTML pages for rules, settings, and import
- `app/routes/api.py`: form actions and JSON endpoints
- `app/models.py`: SQLAlchemy models and core enums
- `app/services/settings_service.py`: saved settings and env override resolution
- `app/services/rule_builder.py`: category, path, and pattern generation
- `app/services/qbittorrent.py`: qBittorrent WebUI API client
- `app/services/metadata.py`: OMDb lookup by IMDb ID
- `app/services/importer.py`: import exported qBittorrent rules JSON
- `app/services/sync.py`: save-to-remote orchestration and sync event logging

## Data flow

### Create or update rule

1. User submits the rule form.
2. The API route validates the input with Pydantic.
3. The validated payload is mapped into the `rules` table.
4. Derived category and save path are filled if the user left them blank.
5. The local record is committed.
6. The sync service logs in to qBittorrent, ensures the category exists, and upserts the rule.
7. The rule is marked `ok` or `error`, and a `sync_events` row is recorded.

### Import existing JSON

1. User uploads an exported qBittorrent rules JSON file.
2. The importer parses the top-level object keyed by rule name.
3. Supported fields are mapped into local rules.
4. Runtime-only fields are ignored.
5. A preview can be rendered before import.
6. On apply, the importer records an `import_batches` row and writes the imported rules locally.

### Metadata lookup

1. User clicks the metadata lookup button.
2. The browser posts the IMDb ID to `/api/metadata/lookup`.
3. The server resolves the metadata provider configuration.
4. The metadata client calls OMDb and returns normalized title and media type.
5. The browser updates title/media/category preview fields in place.

## Sync flow

- Login: `POST /api/v2/auth/login`
- Feed discovery: `GET /api/v2/rss/items?include_feed_data=true`
- Category creation: `POST /api/v2/torrents/createCategory`
- Rule create/update: `POST /api/v2/rss/setRule`
- Rule delete: `POST /api/v2/rss/removeRule`

The app saves locally first. If qBittorrent sync fails, the user does not lose the local change.

## Failure modes

- qBittorrent unreachable: local save succeeds, sync is marked `error`
- qBittorrent auth failure: local save succeeds, sync is marked `error`
- OMDb unavailable: metadata lookup fails; user can still fill the form manually
- Invalid import file: import page returns a validation error and writes nothing
- Rule name collision: create or rename is rejected by the DB unique constraint unless import conflict mode allows a rename

## Security posture

- The app binds to `127.0.0.1` by default.
- v0.1.0 has no separate application login.
- Environment variables override saved secrets and are the preferred secret source.
- Saved secrets are only lightly obfuscated for convenience, not strongly encrypted.
- The app is intentionally scoped to a trusted local machine in v0.1.0.

