# qBittorrent Integration Contracts

## Core integration files

- `app/services/qbittorrent.py`: HTTP client and endpoint payload contract.
- `app/services/sync.py`: local-first persistence then remote sync behavior.
- `app/services/rule_builder.py`: app rule -> qB RSS rule JSON mapping.
- `app/services/importer.py`: qB export JSON -> app rule mapping.
- `app/services/settings_service.py`: resolved qB connection config and WSL URL rewrite.
- `app/routes/api.py`: queue endpoint, settings test endpoint, and rule mutation routes.

## qB WebUI endpoints used

| Endpoint | Purpose | Notes |
| --- | --- | --- |
| `POST /api/v2/auth/login` | Authenticate session | Require body text `Ok.`; treat anything else as auth failure. |
| `GET /api/v2/rss/rules` | Read remote RSS rules | Expect JSON object keyed by rule name. |
| `GET /api/v2/rss/items` | Read feed tree | Flatten nested structure into unique feed options. |
| `POST /api/v2/rss/setRule` | Create/update RSS rule | Send `ruleName` + JSON-encoded `ruleDef`. |
| `POST /api/v2/rss/removeRule` | Remove RSS rule | Send `ruleName`. |
| `POST /api/v2/torrents/createCategory` | Ensure category exists | Accept `409` conflict as non-fatal (already exists). |
| `POST /api/v2/torrents/add` | Queue result/torrent URL | Send `paused` and `stopped` for cross-version pause compatibility. |

## Mapping reminders

- Rule mapping fields live in `build_qb_rule_definition` (`app/services/rule_builder.py`).
- Keep `affectedFeeds` sourced from normalized `rule.feed_urls`.
- Keep `addPaused` sourced from rule/settings queue defaults.
- Preserve literal include/exclude behavior when mapping free-text fields.
- Keep default queue toggles (`default_add_paused`, `default_sequential_download`, `default_first_last_piece_prio`) aligned with settings persistence and queue action payloads.

## Known compatibility behaviors

- qB add-pause semantics differ by WebUI/API version; this project sends both `paused` and `stopped`.
- On WSL runtime, qB base URLs with `localhost` or `127.0.0.1` are rewritten to `host.docker.internal` in settings resolution.
- qB sync failures must not erase local edits.

## Focused regression checklist

1. Run `./scripts/test.sh tests/test_qbittorrent_client.py`.
2. Run `./scripts/test.sh tests/test_routes.py -k "queue_search_result_api or test_qb or feed_urls"`.
3. Run `./.venv-linux/bin/ruff check app/services/qbittorrent.py app/routes/api.py app/services/sync.py tests/test_qbittorrent_client.py tests/test_routes.py` for touched paths.
4. Run `./scripts/check.sh` for broader semantic changes.

## Optional debug commands

- Inspect pending worktree scope: `git status --short`.
- Find qB touch points: `rg -n "qBittorrent|/api/v2|add_paused|feed_urls|stopped" app tests docs`.
