# Phase 18: Rule Form Filter-Profile Live Recompute and Patch Release

## Status

- Plan baseline created on 2026-03-27 from the request to make chosen filter profiles apply immediately in the rule form instead of only updating after another field changes.
- Phase 18 is complete and release-validated as `v0.7.5`.
- Scope was intentionally narrow: make the rule-form filter-profile selection recompute the derived quality state immediately, add regression coverage, and publish the patch release once validation stayed green.

## Goal

Fix the rule-form interaction so choosing a filter profile immediately updates the derived minimum-quality state, the token controls, and the generated pattern preview without requiring a second unrelated field edit.

## Requested Scope (2026-03-27)

1. Make filter-profile selection apply immediately when the user changes the dropdown.
2. Keep the existing quality token and pattern derivation behavior otherwise unchanged.
3. Add regression coverage for the immediate-update path.
4. If validation stays green, synchronize the next patch release and publish it.

## In Scope

- Rule-form JavaScript event handling for filter-profile selection.
- Browser-visible derived state updates for quality tokens and pattern preview.
- Regression coverage in the existing QA/test harness.
- Patch-version synchronization and release documentation updates if the fix is green.

## Out Of Scope

- New quality-profile semantics or backend storage changes.
- Changes to Jellyfin, Stremio, or watch-state arbitration.
- Broader rule-form redesign beyond the filter-profile interaction bug.

## Key Decisions

### Decision: ship this as `v0.7.5`

- Date: 2026-03-27
- Context: This is a compatibility-preserving bug fix that corrects an immediate rule-form interaction without changing the rule schema or public API.
- Chosen option: patch release `0.7.5`.
- Reasoning: Users should receive the UI fix as a small, low-risk maintenance release.
- Consequences: Version touchpoints moved from `0.7.4` to `0.7.5` after the fix and validation pass.

### Decision: make the profile selection handler respond immediately to browser input, not only blur-driven change events

- Date: 2026-03-27
- Context: The current rule-form behavior leaves the selected filter profile inert until another field change occurs.
- Chosen option: wire the same profile-application logic to immediate selection updates so the rule preview recomputes as soon as the user changes the profile.
- Reasoning: The bug is UI-facing and should be fixed at the event-binding layer rather than by adding extra manual refresh steps.
- Consequences: The fix should stay idempotent so repeated selection events do not corrupt the derived state.

## Acceptance Criteria

- Changing the rule-form filter profile immediately updates the quality token controls and generated pattern preview.
- The rule form no longer requires a second unrelated field change, such as episode number, to apply the new minimum-quality state.
- Regression coverage proves the immediate-update path.
- The patch release is validated and published to the configured remote if the checks stay green.

## Dated Execution Checklist (2026-03-27 Baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P18-01 | Wire the filter-profile selection handler so the chosen profile applies immediately. | Codex | 2026-03-27 | completed | The rule-form profile selector updates the derived state as soon as the selection changes. | Implemented in `app/static/app.js` with immediate `input`/`change` handling; covered by `tests/test_routes.py` and `scripts/closeout_browser_qa.py`. |
| P18-02 | Add regression coverage for the immediate-update behavior. | Codex | 2026-03-27 | completed | A deterministic test proves the profile change updates the preview without waiting for another field. | Implemented in `tests/test_routes.py` and `scripts/closeout_browser_qa.py`. |
| P18-03 | Run validation and release closeout checks. | Codex | 2026-03-27 | completed | Targeted checks, full release gates, and browser QA pass. | `cmd.exe /c scripts\check.bat` (`230 passed`, `1 skipped`), `cmd.exe /c scripts\closeout_qa.bat` (`all browser closeout checks passed`), and `cmd.exe /c scripts\run_dev.bat desktop-build` (`0 Warning(s)`, `0 Error(s)`). |
| P18-04 | Publish the patch release to the remote repository. | Codex | 2026-03-27 | completed | Release commit/tag are published to `origin`, or a concrete remote/auth blocker is captured. | Published `main` plus the `v0.7.5` tag to `origin`. |

## Risks And Follow-Up

### Risk: select event behavior can differ across browsers

- Trigger: some browsers may emit `input` and `change` at different times for `<select>` elements.
- Impact: the profile update could still feel delayed in one browser if we only bind one event type.
- Mitigation: keep the handler idempotent and bind the immediate update path to the event that fires earliest in the target browser. The live browser QA check now verifies the immediate update path directly.
- Owner: Codex
- Review date: 2026-03-27
- Status: closed

## Next Concrete Steps

1. No further implementation work remains in phase 18.
2. Open the next active phase before the next code change.
