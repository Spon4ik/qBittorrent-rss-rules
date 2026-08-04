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
- Follow-up on 2026-06-14: rule `1a76faff-9a4a-4e06-984b-e01ee181ff55` (`Office Space`) exposed that precise title recovery applied quality/year/episode filters before rows entered `raw_results`. Kinozal returned details ID `1628537`, but its SDR title failed the HDR keyword group inside `_search_precise_title_primary()` and was discarded before snapshot persistence, so hidden fetched rows could not show it. Precise title recovery now prefilters only identity/scope; ordinary local filters are applied afterward when deriving visible results.
- Follow-up correction on 2026-06-14: after the fetched-row persistence fix, Kinozal details ID `1628537` was present in the saved snapshot but the edit page still marked it visible. The browser grouped-quality regex used the raw `dv` alias without release-token boundaries, so `DVO` and `DVDRip` falsely satisfied the HDR/Dolby Vision group. Group members now receive the same alphanumeric boundaries as individual quality tokens. The edit page also hydrates its saved exact/visible/results summaries from the same transactional `Rule.last_*` snapshot projection used by the rules grid, removing the stale duplicate counter path.
- Follow-up cleanup note: on 2026-05-19, rule `9dfce6d6-f44d-4dc7-9634-32f942b43740` exposed that valid Adventure Time full-series packs were hidden because the episode-floor regex did not understand multi-season ranges ending at the floor season (`S01-10`, `S1-10E1-290`) or absolute full-pack labels (`S1E283 of 283`), and strict IMDb-backed title identity did not accept the known alias form `Adventure Time with Finn & Jake`. The shared builder, browser helper, and identity classifier were updated with focused regressions.
- Follow-up cleanup note: on 2026-05-19, configured Jackett indexers without detected language were kept in discovery as `Other`, The Pirate Bay metadata gained English detection, and client-side title filtering was tightened from loose substring matching to whole-token/phrase matching for examples such as `Hacks` and `Ghosts`.
- Post-phase runtime note: on 2026-05-13, a Docker-only SQLite bind-mount issue was fixed by using rollback journal mode when `QB_RULES_APP_ENV=docker`, because WAL sidecars on the Windows-mounted `/app/data/qb_rules.db` could become unreadable to fresh Docker SQLite connections and break Jellyfin auto-sync/settings reads. This does not change Phase 30 Jackett result semantics.
- Partial-failure follow-up on 2026-07-31: scoped multi-indexer searches now keep working-tracker results when sibling trackers time out, are unreachable, reject the query, or return HTTP failures. Those failures remain visible as per-indexer warnings, but no longer abort a successful aggregate result, and warning text no longer stores API-key-bearing request URLs. The qB sync path also probes affected-feed health through a bounded parallel batch instead of waiting on down trackers sequentially.
- Manual-refresh latency follow-up on 2026-08-01: IMDb-capable direct recovery probes now run concurrently, and precise-title/broad-fallback recovery stops after the first query-surface variant that actually returns rows. This prevents down indexers and equivalent punctuation/title variants from serially stretching a manual refresh across several minutes. Live Docker validation advanced the reported Grogu snapshot from `2026-07-11 08:57:34 UTC` to `2026-07-31 23:10:46 UTC`.
- RuTracker completeness follow-up on 2026-08-02: rule `59d66ba9-0616-473a-b968-43eaa4a78c3a` showed that a non-empty aggregate `all` response is not proof that every selected indexer contributed. RuTracker returned zero rows for the IMDb-enforced request but three for direct title `tvsearch`; aggregate title recovery returned other trackers and prevented the selected direct group from running. The direct results also identify the indexer as `RuTracker.org`, which the local scope filter rejected against the saved slug `rutracker`. Precise-title recovery now retains aggregate rows and runs selected direct indexers as a bounded parallel completeness pass, standard fallback direct batches are also bounded in parallel, and indexer filtering uses normalized key variants. Version touchpoints are synchronized for the `v1.3.1` patch; the full gate passed (`489 passed`, `302 warnings`); the WinUI desktop build passed with zero warnings/errors; Docker rebuilt healthy on `v1.3.1`; and the forced live snapshot refresh increased fetched rows from 9 to 16 with all three RuTracker topics visible, including `6887212`.
- Refresh enforcement follow-up on 2026-08-03: a live selected refresh of Grogu did force and persist a new snapshot, but took 131.8 seconds because four unavailable Jackett request surfaces each consumed three 10-second timeout attempts, while per-rule refresh links never registered backend progress. All active-search request surfaces now fail soft after one timeout, and the per-rule inline refresh path registers success/failure in the shared operation service. On the rebuilt `v1.3.2` container, selected fetch stayed visibly active, completed `1/1` in 54.6 seconds, and advanced the snapshot from `22:56:00` to `23:04:24 UTC`; the separate per-rule refresh then exposed a named running operation, completed `1/1`, and advanced it again to `23:05:24 UTC`, preserving 44 fetched rows.
- Saved-scope authority follow-up on 2026-08-03: the Grogu refresh exposed an aggregate `indexer=all t=movie imdbid=tt30825738` Torznab `[100] Invalid API Key` failure even though the rule persisted eleven explicit search indexers. Explicit saved scope is now authoritative at the remote request boundary: IMDb-first and title/standard fallbacks call only the selected direct indexer endpoints, while unscoped searches retain aggregate `all`. Direct per-indexer provider errors remain fail-soft warnings when a sibling selected indexer succeeds. The live app credential was also stale and was synchronized to Jackett's active key without exposing it. Version touchpoints are synchronized for the `v1.3.4` patch; the full gate passed (`491 passed`, `302 warnings`), WinUI built with zero warnings/errors, Docker rebuilt healthy on `v1.3.4`, and a forced live Grogu refresh completed in 39.2 seconds, advanced the snapshot to `2026-08-03 13:08:51 UTC`, retained 2 `seleZen` rows despite three direct-indexer warnings, and emitted no aggregate `all` movie/title failure. PR `#18` merged at `da7a1d91`; tag `v1.3.4` and the GitHub Release are published.
- Managed-quality consistency follow-up on 2026-08-04: the two retained seleZen Grogu rows were backend-hidden but became visible and queueable after page load because both saved non-Plain managed profile definitions were empty. The edit page correctly used the Settings-owned managed profile while the snapshot projector used taxonomy defaults, creating a browser/backend split. Empty managed HD/UHD presets now normalize to taxonomy defaults and are persisted on settings access; Plain remains the explicit no-quality-filter option. The full gate passed (`520 passed`, Ruff/mypy clean), WinUI built with zero warnings/errors, Docker rebuilt healthy on `v1.4.2`, and live Playwright confirmed both rows remain hidden after JavaScript recomputation with `Missing required quality tags.` and zero visible cards. PR `#21`, tag `v1.4.2`, and the GitHub Release are published.
- Scheduled-refresh stale-snapshot follow-up on 2026-08-04: the daily enabled-rule run executed but completed only `126/253`, leaving Silo and 126 other failed rules on their 2026-08-02 snapshots. A live selected refresh reproduced an immediate fatal `Selected Jackett indexers do not advertise IMDb-enforced search` result: scoped direct search propagated the capability diagnostic before exact-title fallback could run. Scoped IMDb-first search now records that state as a warning and continues into exact-title fallback while preserving the rule that saved direct indexer scope never searches aggregate `all`. The focused regression passes; the full gate passes with Ruff/mypy clean and `521 passed`; WinUI builds with zero warnings/errors; Docker `/health` serves `v1.4.3`; a deployed Silo refresh advanced the snapshot from `2026-08-02 08:24:05 UTC` to `2026-08-04 19:08:38 UTC` with `75` fetched rows and `4` matches; and the subsequent live enabled-rule schedule completed `253/253` successfully in 27m39s, replacing the previous `126 succeeded / 127 failed` result. Silo advanced again to `19:36:23 UTC`, and the next daily run is scheduled for `2026-08-05 19:36:30 UTC`.

## Validation Evidence

- Focused Phase 30 regression gate passed on 2026-05-09:
  `cmd.exe /c scripts\test.bat tests\test_jackett.py::test_jackett_client_hides_broad_token_fallback_rows_for_imdb_backed_short_title tests\test_jackett.py::test_jackett_client_uses_strict_title_identity_and_year_for_common_title_fallback tests\test_rule_fetch_ops.py::test_refresh_snapshot_release_cache_rejects_broad_imdb_backed_fallback_rows tests\test_routes.py::test_edit_rule_saved_snapshot_hides_broad_imdb_title_fallback_rows -q`
- Focused Jackett/rule-fetch/routes gate passed on 2026-05-09:
  `cmd.exe /c scripts\test.bat tests\test_jackett.py tests\test_rule_fetch_ops.py tests\test_routes.py -q`
- Full local gate passed on 2026-05-09:
  `cmd.exe /c scripts\check.bat` (`392 passed`, `276 warnings`)
- Shared Docker Compose rebuild passed on 2026-05-09.
- Docker `/health` passed on 2026-05-09 with `status=ok`, `app_version=1.1.6`, and container status `healthy`.
- Docker SQLite/Jellyfin runtime hotfix validation passed on 2026-05-13:
  `cmd.exe /c scripts\test.bat tests\test_config.py -q` (`8 passed`), shared Docker Compose rebuild passed, Docker `/health` returned `status=ok` / `app_version=1.1.6`, Docker SQLite reported `journal=delete`, and inside-container saved-settings Jellyfin sync resolved `/host/C/ProgramData/Jellyfin/Server/data/jellyfin.db` for user `Spon4ik` with `0` errors.
- Jackett language/manual-indexer cleanup validation passed on 2026-05-19:
  focused regressions for The Pirate Bay English detection, unknown indexers as `Other`, and tokenized query filtering passed; `cmd.exe /c scripts\test.bat tests\test_jackett.py tests\test_routes.py -q` passed; `node --check app/static/app.js` passed; Ruff passed for touched Python service/test files; `cmd.exe /c scripts\check.bat` passed (`394 passed`, `276 warnings`); shared Docker Compose rebuild passed; and Docker `/health` returned `status=ok` / `app_version=1.1.6`.
- Adventure Time pack-range cleanup validation passed on 2026-05-19:
  focused regressions for generated episode-floor pack ranges, saved-snapshot release counts, and connector-title IMDb identity passed; focused rule-builder/rule-fetch/Jackett/routes tests passed; `node --check app/static/app.js` passed; Ruff passed for touched Python service/test files; `cmd.exe /c scripts\check.bat` passed (`397 passed`, `276 warnings`); shared Docker Compose rebuild passed; and Docker `/health` returned `status=ok` / `app_version=1.1.6`.
- Office Space fetched-row/summary correction validation passed on 2026-06-14: the clean full suite passed (`475 passed`); the shared Docker service rebuilt successfully; live browser verification showed the Kinozal SDR row hidden by default, revealed only by `Show hidden fetched rows` with `Missing required quality tags.`, and the rules grid reported `No exact` plus `0/0/34` from the persisted rule summary.
