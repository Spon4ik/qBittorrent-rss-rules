# Phase 22: Stremio Variant Parity And Local Marking

## Status

- Plan created on 2026-03-28 as the active follow-up immediately after the `v0.8.1` phase-21 release closeout.
- Phase 22 is now closed and release-validated in `v0.8.2`.
- Implementation landed on 2026-03-28 and the default `http://127.0.0.1:8000/stremio/manifest.json` runtime is now green in the real desktop smoke for both `tt33517752:1:1` and `tt33517752:1:4`.

## Goal

Preserve the full qB RSS variant set in Stremio, sort it globally by quality then seeds, and only upgrade individual rows to local playback when that exact variant is already available locally in qB.

## Requested Scope (2026-03-28)

1. Keep all viable qB RSS variants instead of capping the addon to a tiny target subset.
2. Sort qB RSS rows globally by quality first and seeds second so the strongest rows naturally rise to the top.
3. If a specific qB RSS variant is available locally, mark and serve that exact row as local playback instead of injecting a special best-local row that suppresses the rest of the set.
4. Keep local playback as an implementation detail of a row, not as a separate ranking path that hides other qB RSS variants.
5. Revalidate with the backend addon smoke and the real Stremio desktop smoke before closing the patch.

## In Scope

- qB RSS stream collection/ranking changes in `app/services/stremio_addon.py`.
- Any stream-shape or local-resolution helper updates needed to attach local playback to exact variants.
- Focused pytest updates for variant retention, ordering, and local-row marking behavior.
- Live addon smoke plus real desktop smoke reruns for the known regression items.

## Out Of Scope

- Stremio catalog/provider work beyond the existing addon lookup path.
- Jellyfin/Stremio watch-state arbitration changes.
- Desktop shell lifecycle or packaging work unrelated to addon stream rendering.
- Publishing/tagging/release automation.

## Key Decisions

### Decision: collect variants first, then decorate individual rows with local playback

- Date: 2026-03-28
- Context: The current phase-21 logic pre-inserts a single best local row and then fills only a tiny target stream count, which can hide other qB RSS variants entirely.
- Chosen option: build the global qB RSS candidate set first, then upgrade any candidate whose exact torrent/file maps to a local qB file into a local-playback row without removing unrelated variants.
- Reasoning: This preserves variant parity while still making the locally available row fast and playable.
- Consequences: The collector can no longer treat local playback as a separate pre-ranked source; dedupe and ordering need to happen across one combined list.

### Decision: ranking should be quality-first, seeder-second across the visible qB RSS set

- Date: 2026-03-28
- Context: The user explicitly wants a global order by quality and then seeds, not a compatibility-first or “best local plus one fallback” ordering.
- Chosen option: make quality the primary sort key, seeders the next key, then peers/publication/title as later tie-breakers.
- Reasoning: That matches the stated Stremio expectation and is easier to reason about than interleaving transport heuristics ahead of quality.
- Consequences: Existing focused tests and smoke expectations need to assert the broader, quality-first ordering contract.

## Acceptance Criteria

- The addon retains the viable qB RSS variant set instead of truncating to the current tiny target count.
- qB RSS rows are globally sorted by quality then seeds for the visible addon payload.
- A locally available variant is still present as part of that ordered set and is marked/served as local playback without suppressing unrelated qB RSS rows.
- Focused pytest coverage passes for variant retention, ordering, and local-row marking.
- `scripts/stremio_addon_smoke.py` passes for the known Stremio regression items.
- `scripts/stremio_desktop_smoke.py` remains green while showing qB RSS rows under the new ordering/retention contract.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P22-01 | Replace the tiny-target collector with a full variant collector that keeps the qB RSS set. | Codex | 2026-03-28 | completed | The addon no longer stops after the current tiny target count when viable qB RSS variants remain. | `app/services/stremio_addon.py` now keeps the broader variant set; `.\\.venv\\Scripts\\python.exe scripts\\stremio_addon_smoke.py --mode service --min-streams 2 --require-4k --max-cold-ms 12000 --json` returned `7` streams for episode `1` and `5` for episode `4`, each including `2160p`. |
| P22-02 | Rework row-local playback handling so exact variants are upgraded in-place instead of injecting a separate best-local row. | Codex | 2026-03-28 | completed | A locally available variant remains in the ordered set and is marked/served as local playback without hiding the rest. | The default `:8000` stream route now returns `qB RSS Rules Local 2160p` plus multiple `qB RSS Rules 1080p` rows for `tt33517752:1:1`, and the real desktop smoke captured the same visible rows under `logs/qa/stremio-desktop-smoke-20260328T162948Z/`. |
| P22-03 | Update focused regressions plus addon/desktop smoke acceptance for the new contract. | Codex | 2026-03-28 | completed | Pytest plus live backend/desktop Stremio evidence are green for the new ordering and retention behavior. | Focused regressions, `scripts\\check.bat`, `scripts\\run_dev.bat desktop-build`, `scripts\\closeout_qa.bat`, addon smokes, and real desktop smokes on the default `:8000` runtime all passed on 2026-03-28. |

## Risks And Follow-Up

### Risk: keeping more qB RSS rows could reintroduce slow live lookups

- Trigger: collecting a broader variant set may push the addon back toward the old slow path if too many `.torrent` downloads are attempted serially.
- Impact: Stremio may time out again even if the returned set is more complete.
- Mitigation: keep the response budget, prefer cheap/magnet candidates first, and only probe expensive HTTP torrent rows while there is real budget left.
- Owner: Codex
- Review date: 2026-03-28
- Status: mitigated in `v0.8.2`; cold service smoke remains below the explicit `12s` gate and warm/default-runtime HTTP lookups are now fast.

### Risk: local marking may create duplicates if exact-variant matching is too loose

- Trigger: a local torrent could match multiple result rows with the same hash or ambiguous file hints.
- Impact: the addon could show redundant local/torrent duplicates for what is effectively one variant.
- Mitigation: dedupe on stable identifiers (`infoHash`, resolved `fileIdx`, filename where available) after local-upgrade decisions are applied.
- Owner: Codex
- Review date: 2026-03-28
- Status: mitigated in `v0.8.2`; default-runtime desktop smoke shows the expected local `2160p` row without duplicated local/remote twins.

## Next Concrete Steps

1. Keep `scripts\\stremio_addon_smoke.py` and `scripts\\stremio_desktop_smoke.py` as the acceptance pair for future addon changes.
2. Repair the mock-addon install path in `scripts\\stremio_desktop_variant_matrix.py` so payload-shape bisects can stay fully automated.
3. Decide whether the next Stremio-focused phase should target watched-progress arbitration, richer catalog/provider coverage, or native addon metadata/configuration expansion.
