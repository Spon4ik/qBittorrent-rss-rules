# Phase 38 - Quota-safe Jackett feed validation

## Status

Implemented and release-validated for `v1.4.10` on 2026-08-07.

## Problem

`SyncService` treated a Jackett feed as healthy only after downloading the first
item's torrent enclosure. Private trackers count that request against the user's
daily torrent-file quota even though the app discarded the response and never
added the torrent to qBittorrent.

Live Kinozal evidence showed the account at `10/10`, a last-download title absent
from qBittorrent, and repeated Jackett download attempts during app rule sync.

## Decision

- Background feed validation may request only the Torznab/RSS feed URL.
- It must verify HTTP success and parseable XML without requesting an enclosure
  or item link.
- Torrent retrieval remains allowed only in an explicit Queue flow or when
  qBittorrent itself processes a matching enabled RSS rule.
- A feed whose XML works but whose download endpoint is broken will report the
  error at the real Queue or qB match boundary instead of spending quota during
  speculative validation.

## Acceptance criteria

- [x] A feed containing a private torrent enclosure causes exactly one health
  request, to the feed URL.
- [x] Search, saved snapshots, qB RSS synchronization, and explicit Queue retain
  their existing contracts.
- [x] Focused sync, Queue, and qB client regressions pass.
- [x] Full repository gate passes (`531 passed`; Ruff and mypy clean).
- [x] WinUI desktop builds with zero warnings/errors.
- [x] Shared Docker backend serves `v1.4.10`.
- [x] Live Kinozal-backed sync succeeds while Jackett's Kinozal torrent-download
  error count remains `0 -> 0`.
- [ ] Patch release is pushed and published.

## Validation commands

```powershell
cmd.exe /c scripts\check.bat
cmd.exe /c scripts\run_dev.bat desktop-build
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build -d qb-rss-rules
curl.exe http://127.0.0.1:8000/health
```
