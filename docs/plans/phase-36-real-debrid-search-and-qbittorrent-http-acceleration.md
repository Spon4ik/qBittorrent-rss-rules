# Phase 36 - Real-Debrid Search and qBittorrent HTTP Acceleration

## Status

- Implemented and published as `v1.4.0` on 2026-08-03.
- Implementation is complete and automated, desktop, and Docker validation are green. Authenticated provider smoke tests remain blocked until Real-Debrid and MyJDownloader accounts are connected in Settings.
- Execution branch: `codex/real-debrid-v1.4.0` from published `v1.3.4` handoff `dadaf9d6`.

## Goal

Add Real-Debrid as a personal cloud/history search source and an HTTP acceleration source while keeping Jackett as public discovery and qBittorrent as the primary downloader with its normal category, save-path, file-priority, and verification behavior.

A SHA1 infohash can always be represented as a magnet, but a magnet alone does not guarantee that qBittorrent can obtain the torrent metadata required to use HTTP web seeds. When metadata is unavailable after a configurable wait, use the installed JDownloader 2 through MyJDownloader as the explicit fallback. No provider can recover content that Real-Debrid does not have and cannot acquire.

## Scope and Decisions

- Use only the official Real-Debrid REST and Device OAuth APIs; do not depend on undocumented global cache-search endpoints.
- Search the authenticated account's `/torrents` cloud and `/downloads` history alongside Jackett. Jackett failures remain fail-soft and do not suppress Real-Debrid or healthy-indexer results.
- Add Real-Debrid HTTP content to every eligible app-managed qBittorrent torrent, not only stalled torrents.
- Mark app-managed manual and RSS downloads with qBittorrent tag `qb-rss-rules`; do not automatically adopt existing untagged torrents. Provide an explicit adoption action for current incomplete torrents in synced rule categories.
- For public torrents, submit exact `.torrent` metadata to Real-Debrid. For private torrents or credential-bearing announce URLs, submit only a tracker-free `xt` magnet plus optional display name; never expose private metainfo, trackers, passkeys, or Jackett credential URLs.
- Retain successful Real-Debrid torrents after qBittorrent completes so cloud search and generated links remain available. Delete only failed temporary submissions or user-selected items.
- Default metadata wait is 120 seconds, configurable from 30 through 900 seconds.
- If metadata never arrives but Real-Debrid exposes file links, submit the files to the selected MyJDownloader device using qBittorrent's reported save path. Keep the qBittorrent placeholder, stop it, and tag it as a JDownloader fallback so it cannot later duplicate the download automatically.
- Real-Debrid standalone download-history rows are JDownloader-only because they have no torrent identity or piece metadata.
- Initial torrent identity support is BitTorrent v1 SHA1 and hybrid torrents with a v1 hash. Treat v2-only entries as JDownloader-only unless later provider APIs expose sufficient metadata.
- Store Real-Debrid credentials/tokens and the MyJDownloader password using real authenticated encryption. Replace the current base64-only secret encoding with a versioned Fernet envelope, a persistent ignored runtime key, and optional `QB_RULES_SECRET_KEY`; retain legacy read compatibility and migrate secrets safely.
- Use pinned `myjdapi==1.1.10` behind an internal adapter rather than maintaining a custom MyJDownloader cryptographic protocol implementation.

## Sprint Board

| Slice | Scope | Dependencies | Done condition | Status |
| --- | --- | --- | --- | --- |
| S1 | Persist roadmap, phase plan, decisions, risks, and handoff | none | Roadmap/phase/status agree and branch is recorded | done |
| S2 | Versioned encrypted secret store and integration settings schema/UI | S1 | Legacy secrets remain readable; new secrets round-trip encrypted; migrations/defaults tested | done |
| S3 | Real-Debrid Device OAuth and typed REST client | S2 | Connect/refresh/disconnect/account/torrent/download contracts and failures tested | done |
| S4 | Real-Debrid cloud/history search aggregation | S3 | Torrent/history results render with provenance, exact-hash dedupe, partial-provider warnings, and safe queue IDs | done |
| S5 | qBittorrent managed tags, export, web-seed, and save-path client contracts | S2 | Manual/RSS jobs are tagged and new qB endpoints have contract tests | done |
| S6 | Persistent acceleration jobs and idempotent background scheduler | S3, S5 | Restart-safe state machine discovers only managed jobs and avoids duplicate provider submissions | done |
| S7 | Range-capable Real-Debrid web-seed adapter | S6 | qB downloads exact single/multi-file bytes through GET/HEAD/Range with link refresh and traversal protection | done |
| S8 | MyJDownloader fallback and status lifecycle | S2, S6 | Metadata timeout queues safe path-preserving jobs, retains/stops qB placeholder, and retries without duplication | done |
| S9 | Operations UI, job retry/cleanup, explicit existing-torrent adoption | S4, S6, S8 | Loading/empty/error/success states and safe actions are covered | done |
| S10 | Full QA, Docker/desktop validation, `v1.4.0` release | S2-S9 | Automated, desktop, Docker, and live qB gates pass; PR, tag, and release are published; credential-dependent smoke is recorded | done |

## Interfaces and Data Flow

### Settings and authentication

- Add settings for Real-Debrid enablement and encrypted OAuth client/access/refresh credentials, web-seed callback base URL, metadata wait, MyJDownloader enablement/email/encrypted password/device, and connection status.
- Add integration routes for starting/polling Device OAuth, disconnecting, testing MyJDownloader, and listing/selecting devices. Browser responses contain only opaque flow/provider IDs and redacted status.
- Validate Real-Debrid Premium status before enabling acceleration. Refresh access tokens before expiry and obey documented request limits with bounded `429`/`5xx` retry and `Retry-After` handling.

### Search

- Extend `SearchSourceKind` with `real_debrid_torrent` and `real_debrid_download`.
- Normalize Real-Debrid results into the existing unified search workspace using title/year/season filtering and deterministic order.
- Deduplicate only by exact v1 infohash. A matching Jackett row gains an `In Real-Debrid` badge; otherwise provider rows remain separate.
- Include actionable Real-Debrid torrent states (`downloaded`, `waiting_files_selection`, and in-progress jobs) with status labels; keep terminal provider-error rows disabled. Standalone history rows expose only JDownloader queue capability.
- Extend queue input with source kind plus opaque provider item ID. Resolve all privileged provider links server-side.

### qBittorrent acceleration

1. Manual queues add the managed tag directly. Synced RSS rules set `torrentParams.tags` so new automatic matches are discoverable without category guessing.
2. Create one persistent job per qBittorrent infohash. Read qBittorrent file priorities and reported `save_path` as authoritative.
3. Use the original public `.torrent` when available; otherwise wait for metadata and export exact metainfo from qBittorrent. Sensitive/private metainfo always uses a tracker-free magnet to Real-Debrid.
4. Match qBittorrent and Real-Debrid files by normalized safe relative path plus size, then select only enabled qBittorrent files.
5. Unrestrict provider file links and expose each through `/webseeds/real-debrid/{opaque-token}/{torrent-relative-path}`.
6. Attach the local route with qBittorrent `addWebSeeds`. Preserve user-owned web seeds and remove only app-owned URLs during cleanup.

### Web-seed adapter

- Support `HEAD`, full `GET`, single byte ranges, `206`, `Content-Range`, and correct lengths while forwarding only safe response headers.
- Keep Real-Debrid bearer tokens and generated links server-side; refresh an expired generated link once and retry the same range safely.
- Use high-entropy path tokens without query parameters, reject traversal/unknown paths, do not provide directory listings, and keep mappings restart-safe while the qB torrent exists.
- Probe range and byte-length compatibility before attachment. If raw-byte service is unsuitable, record an actionable job error rather than feeding HTML or mismatched bytes to qBittorrent.

### JDownloader fallback

- Trigger only when the qB placeholder has no metadata and no downloaded payload at timeout. Never auto-switch a job that has metadata or pieces.
- Resolve the destination from qBittorrent's own `save_path`. Group multi-file links by sanitized relative parent folder so JDownloader preserves the torrent layout.
- Submit with autostart, explicit destination/package mapping, stable job IDs, and Packagizer override. Persist and poll job state through MyJDownloader.
- Once accepted, stop and retain the qB placeholder and add a fallback-status tag. MyJDownloader failures leave the placeholder intact and retry with bounded backoff.

### Persistence and operations

- Add a resumable acceleration-job table keyed by qB infohash or Real-Debrid history ID. Store source/rule IDs, provider torrent/download ID, selected-file mapping, web-seed token, MyJDownloader job IDs, state, retry count, timestamps, and sanitized error details.
- States cover discovery, metadata wait, provider submission, file selection, provider download, web-seed attachment, fallback submission/progress, completion, skip, and terminal error.
- Start one background worker only when integration is enabled. Every state transition is idempotent and reconciles qB/provider reality after restart.
- Publish active/recent progress through the existing operations console and add safe retry, cleanup, and explicit adoption actions.

## Failure and Safety Rules

- Real-Debrid is not a public indexer. If neither Jackett nor the user's Real-Debrid account contains a release, search returns no source.
- A valid magnet does not imply metadata availability. Without torrent metadata, qBittorrent cannot verify or map HTTP bytes; use JDownloader only when provider file links exist.
- If Real-Debrid lacks the content and cannot acquire it, leave qBittorrent stalled and report the provider state. Do not claim guaranteed availability.
- Keep successful results from healthy providers when another Jackett indexer, Real-Debrid, or MyJDownloader fails.
- Never log OAuth tokens, MyJDownloader passwords, unrestricted URLs, Jackett API keys, tracker passkeys, or opaque web-seed tokens.
- Never delete qBittorrent payload files automatically. Cleanup of qB placeholders uses `deleteFiles=false` if the user later requests removal.

## Acceptance Criteria

- A search with no Jackett results can return and queue a matching Real-Debrid cloud torrent.
- A controlled torrent with metadata and zero swarm seeds completes in qBittorrent through the HTTP adapter at the normal qB save path, with piece verification succeeding.
- Public single-file and multi-file torrents preserve qB file priorities, category, save path, and layout.
- Private/passkey torrents send only a sanitized hash magnet to Real-Debrid and retain their original qB tracker state locally.
- Metadata-less magnets fall back after the configured timeout to the selected JDownloader device, preserve directory layout, and leave a stopped tagged qB placeholder.
- Standalone Real-Debrid history downloads are clearly JDownloader-only.
- Provider/indexer failures remain isolated warnings when another source succeeds.
- Restarting the backend during every non-terminal job state creates no duplicate qB, Real-Debrid, web-seed, or JDownloader submission.
- Existing settings and secrets upgrade without mandatory re-entry; missing/wrong encryption keys fail explicitly without data destruction.
- No sensitive credential or generated-link value appears in API payloads, rendered HTML, logs, operations status, or persisted plaintext.

## Validation Checklist

- [x] Focused secret-storage, settings, migration, OAuth, Real-Debrid, MyJDownloader, qB client, scheduler, proxy, route, and UI regressions pass.
- [x] Jackett multi-indexer partial-success regressions continue to pass.
- [x] Range/expiry/path-traversal and private-torrent leak tests pass.
- [x] Restart/idempotency and duplicate-submission tests pass for every implemented state boundary.
- [x] Ruff and mypy pass; full pytest passes with 517 tests.
- [x] `cmd.exe /c scripts\run_dev.bat desktop-build` passes with the `v1.4.0` desktop contract.
- [x] Shared Docker service rebuilds from `C:\Users\nucc\docker-config\docker-compose.yml`; `/health` reports `1.4.0` and both new capabilities.
- [x] Live qB rule sync completed 341/341; all 254 locally enabled remote rules retain the managed tag and have no sync errors.
- [ ] Live Real-Debrid Device OAuth and Premium account test passes without exposing credentials.
- [ ] Live qB web-seed controlled fixture and MyJDownloader fallback smoke pass at normal Windows media paths.
- [x] Changelog, roadmap, phase plan, current status, version touchpoints, commit, push, tag, PR, and GitHub Release are complete.

## Risks

### Risk: provider links are not stable web seeds

- Trigger: generated links expire or fail byte-range semantics under concurrent qB requests.
- Impact: stalled or corrupt-looking qB downloads.
- Mitigation: local range adapter, exact size/range probes, one-time refresh, and qB piece verification.
- Owner: implementation/QA.
- Review date: 2026-08-03.
- Status: open.

### Risk: metadata never becomes available

- Trigger: hash-only magnet has no metadata peers and Real-Debrid does not expose original metainfo.
- Impact: qB cannot attach a valid web seed.
- Mitigation: configurable timeout and MyJDownloader direct-file fallback while retaining the stopped qB placeholder.
- Owner: implementation/QA.
- Review date: 2026-08-03.
- Status: open.

### Risk: secrets migration loses access

- Trigger: legacy base64 values, a missing runtime key, or DB restore without its key.
- Impact: integrations cannot authenticate.
- Mitigation: versioned envelopes, legacy read compatibility, atomic migration, explicit key backup documentation, and fail-closed errors.
- Owner: implementation/QA.
- Review date: 2026-08-03.
- Status: open.
