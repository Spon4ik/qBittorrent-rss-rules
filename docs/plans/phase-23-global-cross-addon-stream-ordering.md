# Phase 23: Global Cross-Addon Stream Ordering

## Status

- Plan created on 2026-03-28 immediately after the `v0.8.2` phase-22 release closeout.
- Phase 23 is the next planned minor release target for `v0.9.0`.
- Implementation has not started yet.

## Goal

Present Torrentio-derived and qB RSS-derived streams as one combined list ordered globally by quality first and seeds second, while preserving local-playback acceleration and provider attribution.

## Context

- Phase 22 fixed qB RSS visibility and internal ordering inside the qB RSS addon rows, but the Stremio desktop client still renders separate provider/addon groups in the final UI.
- The user wants the best stream overall to appear first even when it comes from qB RSS and Torrentio is installed, which the current per-addon rendering model does not provide.
- Achieving that experience likely requires aggregation into one addon/provider surface instead of expecting the Stremio client to interleave rows from separate addons.

## Requested Scope (2026-03-28)

1. Merge qB RSS and Torrentio-compatible stream inputs into one ranked stream set.
2. Sort the merged set globally by quality first and seeds second.
3. Preserve local playback as a row-level upgrade so locally available variants stay fast without hiding remote fallbacks.
4. Keep enough provider attribution in the row text so the source remains understandable after merging.
5. Revalidate with backend smoke plus real desktop smoke against the merged ordering contract.

## In Scope

- Addon/provider aggregation design for Stremio stream delivery.
- Ranking and dedupe logic for merged provider rows.
- Row text/metadata changes needed to preserve provider attribution after aggregation.
- Focused regressions and smoke updates for merged ordering behavior.

## Out Of Scope

- Replacing qB RSS variant retention or local playback behavior already delivered in phase 22.
- Stremio watch-state synchronization changes.
- Catalog/provider expansion beyond what is needed to support merged stream ordering.
- Release automation beyond the normal repo validation/push flow.

## Key Decisions To Make

### Decision: choose the aggregation architecture

- Open question: whether to ingest Torrentio-compatible stream responses into the local addon and emit one merged qB RSS-owned stream list, or to build a broader provider abstraction that can later handle more than Torrentio.
- Why it matters: the Stremio UI groups by addon, so global ordering across separate addons is not under our control.

### Decision: define the merged-row attribution format

- Open question: how much source detail to keep in the visible row text once multiple providers are emitted from one addon.
- Why it matters: merged ordering is only useful if the user can still tell whether a row came from qB RSS, Torrentio, or a future provider.

## Acceptance Criteria

- The Stremio desktop UI shows one merged addon block for the relevant streams instead of a separate qB RSS block beneath Torrentio.
- The best overall quality row appears first in the merged set, regardless of whether it came from qB RSS or Torrentio.
- Locally available exact variants remain upgraded to local playback without removing remote fallbacks.
- Focused pytest plus addon/desktop smoke checks pass for the merged ordering behavior.

## Dated Execution Checklist (2026-03-28 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P23-01 | Decide the provider aggregation architecture for global ordering. | Codex | 2026-03-29 | pending | The phase records the chosen merge strategy and its constraints. | Pending. |
| P23-02 | Implement merged stream collection, ranking, and dedupe. | Codex | 2026-03-29 | pending | The addon can emit one globally ordered stream list across qB RSS and Torrentio-compatible inputs. | Pending. |
| P23-03 | Revalidate merged ordering in backend and real desktop smoke. | Codex | 2026-03-29 | pending | The merged ordering contract is green in both automated layers. | Pending. |

## Risks And Follow-Up

### Risk: third-party provider integration could be brittle or rate-limited

- Trigger: relying on external addon/provider responses may introduce schema drift, latency spikes, or availability failures.
- Impact: the merged addon could become less reliable than the current qB RSS-only path.
- Mitigation: isolate provider adapters, cache carefully, and keep qB RSS-only fallback behavior explicit.
- Owner: Codex
- Review date: 2026-03-29
- Status: open

### Risk: merged ordering may blur provider identity

- Trigger: combining sources into one addon block can hide where a stream came from.
- Impact: users may lose confidence in why one result outranks another.
- Mitigation: include provider attribution in row titles/descriptions and cover that in smoke assertions.
- Owner: Codex
- Review date: 2026-03-29
- Status: open

## Next Concrete Steps

1. Prove the Stremio grouping limitation with one focused design note tied to the existing desktop smoke evidence.
2. Choose the merge strategy for Torrentio plus qB RSS without regressing local playback.
3. Open implementation once the merged ordering contract is decision-complete.
