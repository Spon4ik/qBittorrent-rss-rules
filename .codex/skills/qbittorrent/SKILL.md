---
name: qbittorrent
description: qBittorrent WebUI RSS-rule integration and troubleshooting for this repository. Use when Codex needs to implement, debug, or test qBittorrent connection settings, RSS feed/rule sync (`rss/items`, `rss/setRule`, `rss/removeRule`), torrent queue actions (`torrents/add` with paused/stopped and queue options), WSL localhost rewrite behavior, import mapping for qB rule fields, or qB-related route/service regressions.
---

# qBittorrent

## Overview

Implement and validate qBittorrent-facing behavior for this app while preserving the local-first save contract.

## Workflow

1. Validate connection resolution.
- Read `app/services/settings_service.py` to confirm qB URL resolution and WSL localhost rewrite behavior.
- Read `app/services/qbittorrent.py` to confirm endpoint paths, auth behavior, and payload conventions.
- Keep `QB_RULES_QB_BASE_URL`, username, and password handling aligned with `SettingsService.resolve_qb_connection`.

2. Preserve local-first sync semantics.
- Save rule/settings changes locally first.
- Execute remote qB sync after local persistence.
- Surface sync failures without discarding local changes.
- Keep behavior aligned with `app/services/sync.py` and route error responses.

3. Keep app-to-qB payload mapping exact.
- Keep rule export mapping in `app/services/rule_builder.py` aligned with qB keys such as `affectedFeeds`, `mustContain`, `mustNotContain`, and `addPaused`.
- Keep queue add mapping explicit in `app/services/qbittorrent.py`: send both `paused` and `stopped`, and pass `sequentialDownload`/`firstLastPiecePrio`.
- Keep feed URL values normalized and ordered when round-tripping forms and persistence.

4. Handle qB API failures explicitly.
- Authenticate with `POST /api/v2/auth/login` and treat non-`Ok.` body responses as auth failures.
- Convert transport and status failures into actionable `QbittorrentClientError` messages.
- Keep category creation idempotent by allowing `409` for `POST /api/v2/torrents/createCategory`.
- Avoid silent fallback behavior that can mask configuration problems.

5. Validate with targeted tests.
- Run `./scripts/test.sh tests/test_qbittorrent_client.py`.
- Run `./scripts/test.sh tests/test_routes.py -k "queue_search_result_api or test_qb or feed_urls"` when routes/settings are touched.
- Run `./.venv-linux/bin/ruff check <touched-files>`.
- Run `./scripts/check.sh` when integration semantics change broadly.

## Common task playbooks

### Adjust qB API payload fields

- Update `app/services/qbittorrent.py`.
- Update related schemas/routes if API input/output changed.
- Add or update tests in `tests/test_qbittorrent_client.py` and `tests/test_routes.py`.

### Change rule mapping sent to qB

- Update `app/services/rule_builder.py`.
- Confirm importer/sync parity in `app/services/importer.py` and `app/services/sync.py`.
- Add a regression covering mapping compatibility.

### Debug connectivity and environment mismatches

- Check resolved qB settings via `SettingsService.resolve_qb_connection`.
- Confirm localhost rewrite expectations on WSL (`localhost`/`127.0.0.1` -> `host.docker.internal`).
- Re-run settings connection tests and, when needed, the live-provider smoke gate.

## Guardrails

- Keep qB manual JSON import optional; do not make it a required path for routine sync.
- Keep local data authoritative when qB is temporarily unreachable.
- Preserve paused/stopped compatibility unless qB version support decisions explicitly change.
- Return specific user-facing failures (config, auth, connectivity, API status).

## References

- Read `references/qbittorrent-contracts.md` for endpoint contracts, mapping notes, and a focused regression checklist.
