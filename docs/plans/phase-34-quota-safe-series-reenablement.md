# Phase 34 - Quota-Safe Series Re-Enablement

## Summary

Fix finished-series auto-disable so still-open or revived shows are not left disabled when new catalog evidence appears. Series completion proof now uses Stremio/Cinemeta IMDb-backed episode inventory first, with OMDb only as an allowed fallback, and never scrapes IMDb pages.

## Scope

- Add a shared series catalog lookup for known and released episode numbers by IMDb ID and season.
- Use Cinemeta as the primary quota-free source for series inventory and Stremio watched-bitfield episode IDs.
- Keep OMDb season lookup as fallback only when metadata requests are allowed and an OMDb key is configured.
- Apply the same finished-series proof to Jellyfin and Stremio rule sync.
- Re-enable watch-state-auto-disabled series when later episode or next-season catalog evidence appears.

## Acceptance Criteria

- Still-open series stay enabled when catalog evidence shows a later episode or season.
- Previously auto-disabled series re-enable when a revived season is known or released.
- Finished watched series still auto-disable when catalog evidence proves no later inventory.
- Missing catalog evidence does not disable a series from local library data alone.
- Background sync can use Cinemeta without spending OMDb quota.

## Validation Checklist

- [x] Focused metadata/catalog, Jellyfin, Stremio, watch-state, qB sync cleanup, rule-fetch, and route tests pass.
- [x] Full `cmd.exe /c scripts\check.bat` passes.
- [x] Desktop build passes.
- [x] Shared Docker backend rebuild passes.
- [x] Docker `/health` returns `status=ok` and the current release `app_version`.

## Status

- Status: implemented and locally/Docker validated for release target `v1.2.16` on 2026-06-02.
- Implemented: shared `SeriesCatalogClient`, Cinemeta-first season inventory and video-id lookup, OMDb fallback behind `allow_metadata_requests`, Jellyfin/Stremio shared completion proof, Stremio completion status priority for re-enable/disable outcomes, and focused regressions for missing catalog evidence plus revived next-season evidence.
- Validation evidence: focused metadata/Jellyfin/Stremio/watch-state/sync/rule-fetch/routes slice passed; Ruff passed for touched backend/test files; full `cmd.exe /c scripts\check.bat` passed (`468 passed`, `292 warnings`); desktop build passed (`0 Warning(s)`, `0 Error(s)`); shared Docker Compose rebuild passed; Docker `/health` returned `status=ok` / `app_version=1.2.16` via `curl.exe` after PowerShell `Invoke-WebRequest` hit the known local `NullReferenceException`.
- Follow-up fix for `v1.2.17` on 2026-06-02: Cinemeta `status=Continuing`, scheduled videos, and open-ended `releaseInfo` / `year` values now prevent finished-series auto-disable and clear previous watch-state auto-disable. This covers Death in Paradise-style cases where the latest known episode is watched but the show is explicitly still continuing even though the next season is not yet listed.
- Validation evidence for `v1.2.17`: focused metadata/Jellyfin/Stremio tests and Ruff passed; full `cmd.exe /c scripts\check.bat` passed (`470 passed`, `292 warnings`) after a one-off order-sensitive sync-queue assertion passed on rerun; desktop build passed; shared Docker rebuild passed; Docker `/health` returned `app_version=1.2.17`; Docker Stremio sync and qB sync repaired rule `7d534f3d-ec7e-4bdf-ab16-5c994871a00c` so Death in Paradise is enabled, no longer completion-auto-disabled, and synced OK.
- qB queue follow-up on 2026-06-03: duplicate torrent add attempts now treat qBittorrent `/api/v2/torrents/add` `409 Conflict` responses as idempotent success for both URL/magnet and uploaded `.torrent` handoffs, while leaving other unexpected qB status failures strict. This fixes the already-present torrent failure observed on rule `5207fbac-b5bc-4591-b114-2ea5052a0766`.
- Validation evidence for qB queue follow-up: duplicate-add regressions failed red before the fix and passed after it; `tests/test_qbittorrent_client.py` passed (`17 passed`); `tests/test_routes.py -k "queue_search_result_api or test_qb or feed_urls"` passed (`16 passed`, `32 warnings`); `tests/test_selective_queue.py` passed (`16 passed`); Ruff passed on touched files; shared Docker rebuild passed; Docker `/health` returned `app_version=1.2.17`.
