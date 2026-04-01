# Phase 24: Stremio Long-Running Series Year Hotfix

## Status

- Plan created on 2026-03-28 after reproducing a post-`v0.8.2` Stremio addon regression for long-running series such as `Death in Paradise`.
- Phase 24 is the active patch slice for the next `v0.8.3` hotfix.
- Implementation landed locally on 2026-03-28 and is validated against the direct route repro plus a real desktop smoke on `Death in Paradise` season 14 episode 1.
- A user-directed phase-23 precursor follow-up started on 2026-03-30 before the `v0.8.3` release decision, but the phase-24 year-filter fix itself remains implemented and validated exactly as scoped here.
- Release closeout is now completed in `v0.8.3`.

## Goal

Restore Stremio addon episode discovery for long-running series by stopping episode/season Jackett lookups from being over-constrained by the series start year.

## Context

- The current Stremio addon episode path uses `metadata.year` for exact episode, text episode, and season fallback Jackett searches.
- For long-running series, `metadata.year` is the original series year rather than the aired year of a later season episode.
- Reproduction on 2026-03-28 shows `Death in Paradise` season 14/15 routes returning zero streams while season 1 still works:
  - `http://127.0.0.1:8000/stremio/stream/series/tt1888075:14:1.json` returned `0` streams.
  - `logs/search-debug.log` shows `raw_results` in the `48..57` range for `Death in Paradise S14E01/S14E02/S14E03/S15E05/S15E08` while `filtered_results` stayed `0` with `release_year=2011`.

## Requested Scope (2026-03-28)

1. Remove or relax the series start-year constraint for Stremio episode lookups.
2. Keep movie lookups and other already-working Stremio flows unchanged.
3. Add focused regression coverage for long-running series episode discovery.
4. Revalidate the failing `Death in Paradise` episode routes after the fix.

## In Scope

- `app/services/stremio_addon.py` episode Jackett request construction.
- Focused tests for Stremio addon episode lookup behavior.
- Direct route validation for the known failing IMDb/episode IDs.

## Out Of Scope

- Cross-addon merged ordering work planned for phase 23 / `v0.9.0`.
- Local playback architecture changes beyond what the fixed episode lookup already unlocks.
- Stremio catalog/provider expansion or watch-state changes.

## Acceptance Criteria

- Long-running series episode lookups no longer send the original series year as a hard filter.
- `Death in Paradise` later-season episode routes return at least one stream where matching releases exist.
- Focused pytest coverage passes for the new query contract.
- Existing known-good Stremio paths such as `The Beauty` remain green.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P24-01 | Update the Stremio episode query contract so long-running series are not year-filtered by the original series year. | Codex | 2026-03-28 | completed | Episode searches no longer send `release_year=metadata.year` for series episode/season requests. | `app/services/stremio_addon.py` now omits `release_year` for series episode exact/text/season-fallback Jackett requests. |
| P24-02 | Add focused regressions for the new series-episode year behavior. | Codex | 2026-03-28 | completed | Tests fail before the fix and pass after it. | `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_stremio_addon.py -q` (`13 passed`) including the `Death in Paradise` year-filter regression. |
| P24-03 | Revalidate the known failing `Death in Paradise` routes plus focused Stremio checks. | Codex | 2026-03-28 | completed | Direct route repro and focused pytest are green. | Direct `:8000` routes for `tt1888075:14:1`, `tt1888075:14:2`, `tt1888075:14:3`, `tt1888075:13:1`, and `tt1888075:15:8` now return streams, and `.\\.venv\\Scripts\\python.exe scripts\\stremio_desktop_smoke.py --manifest-url http://127.0.0.1:8000/stremio/manifest.json --detail-url https://web.stremio.com/#/detail/series/tt1888075/tt1888075%3A14%3A1 --json` passed in reruns with artifacts under `logs/qa/stremio-desktop-smoke-20260328T181024Z/` and `logs/qa/stremio-desktop-smoke-20260328T181339Z/`, confirming visible qB RSS rows in the desktop client. |

## Risks And Follow-Up

### Risk: removing year narrowing may broaden ambiguous series searches

- Trigger: some short or common series titles may produce noisier results without the year filter.
- Impact: Jackett could return more irrelevant releases for ambiguous series names.
- Mitigation: keep IMDb-only search first, keep season/episode tokens, and add broader fallback only where needed.
- Owner: Codex
- Review date: 2026-03-28
- Status: mitigated locally; the fix keeps IMDb-only plus season/episode narrowing and only drops the over-constraining year filter for series episode lookups.

## Next Concrete Steps

1. Keep `Death in Paradise` season 14/15 routes in the manual/live regression set for future Stremio addon changes.
2. Advance the active `v0.9.0` cross-addon ordering work in Phase 23.
