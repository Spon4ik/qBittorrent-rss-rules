# Phase 17: Shared Watch-State Arbitration Foundation

## Status

- Plan baseline created on 2026-03-27 from the request to separate Stremio watched-history sync from Jellyfin and introduce a module that can decide what episode should count as watched across source adapters.
- Phase 17 is complete and release-validated as `v0.7.4`.
- Scope is intentionally narrow: extract the source-agnostic watched-state decision logic into a shared module, route the existing Jellyfin sync through it without changing behavior, and leave Stremio integration for a later phase.
- The shared module, Jellyfin adapter refactor, regression coverage, and remote release publication are all complete.

## Goal

Create a reusable watch-state arbitration layer that can take episode evidence from different providers and local libraries, then decide the next searchable floor to keep the app's rule state aligned with what the user has actually watched.

## Requested Scope (2026-03-27)

1. Extract the watched/known floor decision logic into a shared module.
2. Keep the current Jellyfin sync behavior unchanged while routing it through that shared module.
3. Document Stremio watched-history sync as a separate follow-up phase rather than mixing it into the Jellyfin work.

## In Scope

- Source-agnostic episode-key merging, sorting, and floor derivation helpers.
- Jellyfin service integration that delegates watched-state floor decisions to the shared module.
- Targeted regression coverage for the shared arbitration logic and Jellyfin parity.
- Release-prep version synchronization if the slice stays behavior-preserving.

## Out Of Scope

- Stremio watched-history sync implementation.
- New player integrations or local-library scanners beyond the generic arbitration helpers.
- Behavior changes to the existing Jellyfin sync contract unless a regression test proves they are required.

## Key Decisions

### Decision: ship this as `v0.7.4`

- Date: 2026-03-27
- Context: This slice extracts shared internal logic and adds regression coverage without changing the external release contract.
- Chosen option: patch release `0.7.4`.
- Reasoning: The user-facing behavior should stay the same while the code gains a reusable foundation for future providers.
- Consequences: Version touchpoints should move from `0.7.3` to `0.7.4` only after the new module and parity checks are green.

### Decision: keep Stremio sync in a later phase

- Date: 2026-03-27
- Context: Stremio and Jellyfin are distinct integration surfaces, with different APIs and watch-state semantics.
- Chosen option: create the shared arbitration layer now, then add Stremio source adapters later.
- Reasoning: Shared decision logic should be stable before a second provider starts feeding it data.
- Consequences: Phase 17 can stay focused and avoid turning into two unrelated integrations at once.

## Acceptance Criteria

- A shared watch-state arbitration module exists and is used by Jellyfin sync.
- Existing Jellyfin sync tests still pass with unchanged observable behavior.
- New targeted tests cover the shared watched-state floor derivation independently of Jellyfin I/O.
- The release commit/tag are published to the configured remote if validation stays green.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P17-01 | Extract source-agnostic watched-state decision helpers into a shared module. | Codex | 2026-03-27 | completed | The watched/known floor logic no longer lives only inside Jellyfin service internals. | Implemented in `app/services/watch_state.py`. |
| P17-02 | Route Jellyfin sync through the shared watched-state module. | Codex | 2026-03-27 | completed | Jellyfin behavior remains unchanged while using the shared arbitration module. | Implemented in `app/services/jellyfin.py` with the shared arbiter. |
| P17-03 | Add focused regression tests for the shared arbitration contract and Jellyfin parity. | Codex | 2026-03-27 | completed | The new module and the Jellyfin adapter are both covered by deterministic tests. | Implemented in `tests/test_watch_state.py`, `tests/test_jellyfin.py`, and `tests/test_rule_builder.py`. |
| P17-04 | Publish the patch release to the remote repository. | Codex | 2026-03-27 | completed | Release commit/tag are published to `origin`, or a concrete remote/auth blocker is captured. | Published `main` plus the `v0.7.4` tag to `origin` after local validation passed. |

## Risks And Follow-Up

### Risk: the abstraction may become too Jellyfin-shaped if we rush it

- Trigger: the new module mirrors Jellyfin internals instead of staying source-agnostic.
- Impact: Stremio and future player integrations would still need a second refactor later.
- Mitigation: keep the module callback-based and accept generic episode evidence rather than Jellyfin entity objects.
- Owner: Codex
- Review date: 2026-03-27
- Status: open

## Next Concrete Steps

1. Open a separate Stremio source-adapter phase after the shared arbiter lands.
