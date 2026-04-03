# Repository Instructions

## Session Startup

At the start of each work session:

1. Read `AGENTS.md`.
2. Read `ROADMAP.md`.
3. Read `docs/plans/current-status.md`.
4. Read the active phase plan under `docs/plans/` before changing code.

## Working Rules

- Confirm whether an active implementation phase already exists before making changes.
- Implement against the active phase plan instead of improvising scope.
- Use a dedicated git branch for each implementation slice, which in this repo normally means one branch per active phase.
- Do not create an additional branch just because the target version changes if that version is the release vehicle for the same active phase; create a separate version branch only when parallel maintenance or hotfix work needs to diverge from the main phase track.
- Do not stop at the first partial fix; keep iterating until the reported problem is actually fixed or a concrete blocker is documented.
- Be proactive about logical bugs, weak assumptions, and non-optimal designs discovered while working; fix them when they are in scope for the active slice, and explicitly propose the better design when it materially improves precision, resilience, or user trust.
- If implementation must diverge from the current phase plan, update the relevant plan document before or with the code change.
- Keep roadmap, plan, and status docs aligned with the actual codebase state.

## Session Closeout

Before ending a meaningful work session:

1. Update `docs/plans/current-status.md`.
2. Update the active phase plan with completion state, follow-up work, or changed assumptions.
3. Update `ROADMAP.md` only when phase scope, ordering, or long-term direction changes.

## Resumability Standard

- Record what is already implemented.
- Record what is currently in progress.
- Record the next concrete steps.
- Keep phase plans decision-complete enough that another engineer or agent can resume work immediately.
- Treat `docs/plans/current-status.md` as the live short-form handoff and `docs/plans/` as the implementation-level source of truth.
