# Phase 30 - IMDb-Backed Jackett Precision Hardening

## Summary

Phase 30 hardens IMDb-backed Jackett result visibility for short and common titles such as `You` and `Ghosts`. The immediate implementation is strict app-side identity filtering: rows only become visible/countable when Jackett returns a matching IMDb ID or when the title itself passes strict exact-title identity. Broad token-only fallback rows remain available as hidden/debug evidence, but they must not count as relevant matches or become queue candidates.

## Context

- User repro on 2026-05-08: rule `b28743ab-9612-4b65-964f-ad7e984e7416` (`You`, IMDb `tt7335184`) showed visible fallback rows whose titles merely contained the word `you`.
- Live Jackett capability probing showed configured indexers differ in whether they advertise `imdbid`; the implementation must use capability-driven behavior across all configured indexers and must not special-case one tracker.
- Some tracker web pages expose IMDb links even when Jackett does not advertise or return IMDb metadata. That is long-term exactness work, not the immediate safe fix.

## Scope

- Add a shared result identity classifier in `app/services/jackett.py`.
- Use that classifier for Jackett primary/fallback filtering and for saved snapshot rule-local filtering in `app/services/rule_fetch_ops.py`.
- Hide broad title fallback rows for IMDb-backed movie/series searches unless strict title identity passes.
- Add generic capability warnings when the selected indexer scope cannot remotely enforce IMDb for the current media/search mode.
- Keep the current Jackett request sequencing and indexer scope authority; do not lock behavior to a specific tracker.

## Non-Goals

- Do not implement detail-page scraping in this phase.
- Do not modify local Jackett definitions or require an upstream Jackett patch for this phase.
- Do not change qB RSS payload semantics, rule quality profiles, or saved `search_indexers` ownership.
- Do not remove hidden/debug fallback rows; only change their visible/countable status.

## Implementation Plan

1. Add failing service regressions in `tests/test_jackett.py` for:
   - `You` with broad fallback titles such as `They Will Kill You`, which must remain hidden from visible results;
   - `You` exact-title no-IMDb rows, which may remain visible when strict title identity passes;
   - `Ghosts` with conflicting IMDb IDs and same-title/year-assisted no-IMDb rows.
2. Add failing snapshot regressions in `tests/test_rule_fetch_ops.py` proving release counts exclude broad fallback rows for IMDb-backed rules.
3. Add route/UI coverage in `tests/test_routes.py` proving capability warnings are rendered and broad fallback diagnostics remain hidden/debug only.
4. Implement the shared classifier and wire it into Jackett filtering and snapshot filtering.
5. Add capability warning text using configured indexer capabilities, without naming any tracker as a fixed starting point.
6. Update `docs/plans/current-status.md` and `ROADMAP.md` with Phase 30 state and deferred exactness follow-ups.

## Long-Term Exactness

- Follow-up track: upstream or custom Jackett definition improvements for trackers whose pages expose IMDb links but whose Torznab caps/output do not expose `imdbid`.
- Later opt-in detail-page enrichment fallback:
  - disabled by default;
  - per-indexer allowlist;
  - bounded top-N candidates;
  - short timeout and cache by details URL / GUID / infohash;
  - extract only IMDb IDs from returned detail pages;
  - never promote a row unless the detail page confirms the requested IMDb ID.

## Acceptance Criteria

- IMDb-backed visible/search results no longer accept token-only fallback matches for short/common titles.
- Saved snapshots, edit-page replay, and rules-grid release counts use the same identity logic.
- Hidden diagnostics still show broad fallback evidence and explain capability limitations.
- The implementation is tracker-generic and capability-driven.

## Validation Checklist

- [x] `cmd.exe /c scripts\test.bat tests\test_jackett.py tests\test_rule_fetch_ops.py tests\test_routes.py -q`
- [x] `cmd.exe /c scripts\check.bat`
- [x] Shared Docker rebuild:
  `& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose -f C:\Users\nucc\docker-config\docker-compose.yml up --build -d qb-rss-rules`
- [x] Docker health:
  `Invoke-WebRequest http://127.0.0.1:8000/health`

## Status

- Status: implemented and locally validated on 2026-05-09.
- Release target: post-Phase 29 precision hardening slice.

## Validation Evidence

- Focused Phase 30 regression gate passed on 2026-05-09:
  `cmd.exe /c scripts\test.bat tests\test_jackett.py::test_jackett_client_hides_broad_token_fallback_rows_for_imdb_backed_short_title tests\test_jackett.py::test_jackett_client_uses_strict_title_identity_and_year_for_common_title_fallback tests\test_rule_fetch_ops.py::test_refresh_snapshot_release_cache_rejects_broad_imdb_backed_fallback_rows tests\test_routes.py::test_edit_rule_saved_snapshot_hides_broad_imdb_title_fallback_rows -q`
- Focused Jackett/rule-fetch/routes gate passed on 2026-05-09:
  `cmd.exe /c scripts\test.bat tests\test_jackett.py tests\test_rule_fetch_ops.py tests\test_routes.py -q`
- Full local gate passed on 2026-05-09:
  `cmd.exe /c scripts\check.bat` (`392 passed`, `276 warnings`)
- Shared Docker Compose rebuild passed on 2026-05-09.
- Docker `/health` passed on 2026-05-09 with `status=ok`, `app_version=1.1.6`, and container status `healthy`.
