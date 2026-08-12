# Phase 39 - Real-Debrid live acceleration hardening

## Status

Implemented, live-validated, and published as `v1.4.11` on 2026-08-13.

## Problem

The first authenticated Phase 36 smoke test queued the reported Eternal Sunshine
UHD torrent in qBittorrent but did not produce a usable HTTP source. Live state
exposed four gaps that disconnected-provider tests could not exercise:

- first connection advanced the whole managed backlog in one scheduler tick and
  hit Real-Debrid request limits before reaching the newest active torrent;
- Real-Debrid rejected qBittorrent's otherwise parseable exported metainfo with
  `torrent_file_invalid (30)`, with no tracker-free magnet fallback;
- the worker attached the web-seed URL before committing its token/file mapping,
  allowing qBittorrent's immediate first request to receive `404`;
- single-file torrents received a directory-style token base instead of a full
  file URL, so opening the displayed source produced `Invalid web-seed path`;
- the provider returned `206` for bounded ranges while continuing to stream the
  rest of the 79.7 GB file, and the proxy buffered that unbounded response.

## Decision

- Process at most five acceleration jobs per scheduler tick, prioritizing the
  newest actively downloading qBittorrent torrents.
- When a safe public metainfo upload is rejected specifically as
  `torrent_file_invalid`, submit the same v1 infohash as a tracker-free magnet.
- Commit web-seed token, selected-file mapping, and app-owned URL before calling
  qBittorrent's `addWebSeeds` endpoint.
- Attach the complete quoted file URL for single-file torrents and retain a
  directory-style token base only for multi-file torrents.
- Read only the requested number of bytes from provider range responses and
  close the upstream stream immediately, even when its `Content-Length` and body
  incorrectly describe/contain the rest of the file.

## Acceptance criteria

- [x] Scheduler fan-out is bounded and newest active downloads are processed first.
- [x] Invalid exported public metainfo falls back to a tracker-free magnet.
- [x] Web-seed mappings are committed before qBittorrent can request them.
- [x] Single-file qBittorrent readback exactly matches the complete MKV URL.
- [x] Overlong provider range bodies are truncated to the requested byte count.
- [x] Live Real-Debrid Premium Device OAuth connection succeeds.
- [x] The reported torrent has one qBittorrent HTTP source and a persisted
  `webseed_attached` acceleration job.
- [x] The app returns `206`, `Content-Length: 1`, and exactly one byte for a
  `bytes=0-0` request in under one second.
- [x] qBittorrent itself requests the mapped movie path and receives `206 Partial Content`.
- [x] Full repository gate, desktop build, and versioned Docker health pass.
- [x] PR `#35` is merged; annotated tag and GitHub Release `v1.4.11` are published.

## Validation evidence

- Target qB hash: `55af83cd0e15aa63819d6d8b407ca40e8a7d42f6`.
- Target job reached `webseed_attached` with zero retries after the repaired run.
- qBittorrent web-seed readback returned exactly one app-owned URL.
- Live proxy probe returned `206`, `Content-Range: bytes 0-0/79691629228`,
  `Content-Length: 1`, one response byte, and completed in 0.8 seconds.
- Docker access logs recorded qBittorrent's host request for the exact MKV path
  returning `206 Partial Content`.
- `cmd.exe /c scripts\check.bat` passes with Ruff and mypy clean and `535 passed`.
- `scripts\run_dev.bat desktop-build` passes with zero warnings and zero errors.
- Shared Docker `/health` reports `app_version=1.4.11`.
