# API

## HTML routes

- `GET /`: rule list
- `GET /rules/new`: new rule form
- `GET /rules/{rule_id}`: edit rule form
- `GET /settings`: settings page
- `GET /import`: import page
- `GET /health`: JSON health check

## Form and JSON action routes

- `POST /api/metadata/lookup`: lookup title and media type from an IMDb ID
- `POST /api/feeds/refresh`: fetch the current qBittorrent feed list
- `POST /api/filter-profiles`: save or overwrite a reusable saved filter profile
- `POST /api/import/qb-json`: preview or apply an import from an exported JSON file
- `POST /api/rules`: create a rule
- `POST /api/rules/{rule_id}`: update a rule
- `POST /api/rules/{rule_id}/sync`: sync one rule
- `POST /api/rules/{rule_id}/delete`: delete one rule
- `POST /api/sync/all`: sync all local rules
- `POST /api/settings`: save settings
- `POST /api/settings/test-qb`: test qBittorrent connectivity
- `POST /api/settings/test-metadata`: test metadata lookup configuration

The settings routes extend the original v1 route list because the settings page needs explicit save/test actions.

## Internal service contracts

### `QbittorrentClient`

- `login() -> None`
- `test_connection() -> None`
- `get_rules() -> dict[str, dict[str, object]]`
- `get_feeds() -> list[FeedOption]`
- `create_category(name: str) -> None`
- `set_rule(rule_name: str, rule_def: dict[str, object]) -> None`
- `remove_rule(rule_name: str) -> None`

### `MetadataClient`

- `lookup_by_imdb_id(imdb_id: str) -> MetadataResult`

### `RuleBuilder`

- `render_category(rule: Rule) -> str`
- `render_save_path(rule: Rule) -> str`
- `build_generated_pattern(rule: Rule) -> str`
- `build_qb_rule(rule: Rule) -> dict[str, object]`

`build_generated_pattern` composes the resolved title with optional release year matching, extra include keywords, and the selected quality include/exclude tags unless a manual `mustContain` override is supplied.

### `Importer`

- `preview_import_from_bytes(raw_bytes: bytes, mode: ImportMode) -> list[ImportPreviewEntry]`
- `apply_import_from_bytes(raw_bytes: bytes, mode: ImportMode, source_name: str) -> ImportResult`

### `SyncService`

- `sync_rule(rule_id: str) -> SyncResult`
- `sync_all() -> BatchSyncResult`
- `delete_rule(rule_id: str) -> SyncResult`
- `delete_remote_rule(rule_name: str) -> None`

## qBittorrent API endpoints used

- `POST /api/v2/auth/login`
- `GET /api/v2/rss/rules`
- `GET /api/v2/rss/items`
- `POST /api/v2/rss/setRule`
- `POST /api/v2/rss/removeRule`
- `POST /api/v2/torrents/createCategory`

## Error handling conventions

- Validation errors render the same page with inline messages and preserve user input.
- External service failures are returned as actionable messages, not raw stack traces.
- Sync failures do not roll back local saved rule changes.
- Import parsing errors do not partially write data.
