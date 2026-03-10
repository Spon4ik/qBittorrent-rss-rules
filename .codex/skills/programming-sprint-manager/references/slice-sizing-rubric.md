# Slice Sizing Rubric

## Target Slice Size

- Aim for slices that can be implemented and validated in `30-120 minutes`.
- Split before implementation if expected effort exceeds half a day.
- Split when work touches more than three subsystems in one step.

## Definition of Ready

A slice is ready only when all are true:

- Scope is one behavior change or one coherent refactor boundary.
- Done condition is explicit (test command, manual check, docs update, or combination).
- Dependencies are known and referenced by slice ID.
- Rollback or fallback is clear for risky changes.

## Split Patterns by Work Type

Bug fix:

- Reproduce and isolate defect.
- Implement fix.
- Add or update regression coverage.

Feature:

- Add data/model contract.
- Implement service or business logic.
- Implement API/UI integration.
- Add tests and docs for the user-visible flow.

Improvement or refactor:

- Capture baseline behavior.
- Refactor one boundary at a time.
- Re-run baseline checks after each boundary.

## Oversize Signals

Split immediately when any signal appears:

- Slice has multiple unrelated acceptance criteria.
- Multiple unknowns appear during implementation.
- Validation plan is vague or depends on "full regression only."
- Scope grows more than 25 percent from original estimate.

## Estimation Tags

- `XS`: under 30 minutes; no new dependency risk.
- `S`: 30-90 minutes; isolated change path.
- `M`: 90-240 minutes; moderate integration risk.
- `L`: over 240 minutes or high uncertainty; split into `S`/`M` slices before coding.

## Replanning Rule

- If blocked for 20+ minutes on unknown behavior, stop and reslice.
- If new scope appears, create follow-up slices instead of extending the current slice indefinitely.
- Record the replanning decision in the sprint board before continuing.
