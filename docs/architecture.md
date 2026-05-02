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
- `app/services/quality_filters.py`: quality taxonomy loading, validation, and token normalization
- `app/services/rule_builder.py`: category, path, and pattern generation
- `app/services/qbittorrent.py`: qBittorrent WebUI API client
- `app/services/metadata.py`: normalized metadata lookup dispatch for OMDb, MusicBrainz, OpenLibrary, and Google Books
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
2. The browser posts the selected provider, a title or provider-specific ID, and the current media type to `/api/metadata/lookup`.
3. The server resolves the metadata provider configuration.
4. The metadata client dispatches to the relevant upstream provider and returns a normalized title, media type, and optional external IDs.
5. The browser updates title/media/category preview fields in place and fills `IMDb ID` only when the chosen provider returns one.

### Quality token normalization

1. The server loads runtime `data/quality_taxonomy.json`, seeding it from `app/data/quality_taxonomy.json` when missing, and validates schema version `1`, `2`, or `3` at startup-time use.
2. Leaf option IDs remain the canonical storage format for rules and saved filter profiles.
3. `app/services/quality_filters.py` keeps optional `media_types` metadata for UI scoping, but still expands bundles and aliases into leaf option IDs before persistence or regex generation.
4. Saved filter profiles may carry optional `media_types` for rule-form visibility; stored rule tokens remain flat leaf IDs.
5. Built-in video filter profiles derive their resolution include/exclude thresholds from the live `resolution` rank, so adding a lower value such as `240p` automatically extends preset exclusions and adding a higher value automatically extends preset inclusions.
6. `SettingsService.get_or_create()` refreshes stored default profile rules only when they still match known default snapshots; customized profile rules remain as authored.
7. Rules that carry a built-in `quality_profile` plus an older explicit token snapshot are treated as profile-owned when the only missing tokens are taxonomy-added resolution values, preserving profile identity without overriding genuinely manual token edits.



### Feed selection defaults

1. `AppSettings.default_feed_urls` stores remembered feed URLs for future new rules.
2. `GET /rules/new` renders the feed selector as checkbox inputs and prefills matching entries from `default_feed_urls`.
3. The rule form renders a default-checked `remember_feed_defaults` toggle on both create and edit.
4. On `POST /api/rules` or `POST /api/rules/{rule_id}`, keeping that toggle enabled atomically persists the submitted `feed_urls` as the next default set.
5. Existing rules always keep their own stored `feed_urls`; defaults only prefill create mode, and client-side feed refresh keeps currently selected saved feeds visible if qBittorrent does not return them.

### Taxonomy management

1. The `/taxonomy` page reads the live JSON source of truth and renders a local editor.
2. `POST /api/taxonomy/validate` parses a draft, runs the same schema validation as the live loader, and previews added or removed leaf tokens.
3. The draft preview checks saved filter profiles plus all stored rules to detect any removed live tokens that would newly orphan persisted selections.
4. `POST /api/taxonomy/apply` writes the formatted JSON back to runtime `data/quality_taxonomy.json`, clears the loader cache, and appends a local audit entry in `data/taxonomy_audit.jsonl`.
5. Unsafe drafts are rejected before the live taxonomy file is changed, while already-invalid legacy tokens are still surfaced for cleanup without blocking non-destructive label edits.

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
- Metadata provider unavailable: lookup fails; user can still fill the form manually
- Invalid import file: import page returns a validation error and writes nothing
- Rule name collision: create or rename is rejected by the DB unique constraint unless import conflict mode allows a rename

## Security posture

- The app binds to `127.0.0.1` by default.
- v0.4.0 has no separate application login.
- Environment variables override saved secrets and are the preferred secret source.
- Saved secrets are only lightly obfuscated for convenience, not strongly encrypted.
- The app is intentionally scoped to a trusted local machine in v0.4.0.
