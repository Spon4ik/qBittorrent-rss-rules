# Repository Instructions

## Session Startup

At the start of each meaningful work session:

1. Read `docs/plans/current-status.md`.
2. Read the active phase plan under `docs/plans/` before making changes that affect planned implementation scope, architecture, or incomplete phase work.
3. Read `ROADMAP.md` only when phase scope, sequencing, or long-term direction may be affected.

## Core Behavior

- Prefer correct design over fast implementation.
- Do not assume the user's requested implementation is automatically the best approach.
- If a request appears brittle, overly manual, lossy, inefficient, or contrary to platform capabilities or best practices, pause before coding and briefly propose a better approach.
- Think 1–2 steps ahead about maintainability, correctness, API capabilities, and edge cases.
- For non-trivial features or architecture changes, do light targeted research in the codebase and relevant docs/API surface before implementation.
- Prefer the simplest robust design that makes good use of the system’s actual capabilities and avoids unnecessary complexity, duplication, or workaround logic.

## Change Scope

- Default to the smallest safe change that solves the requested problem.
- Inspect and edit only the smallest set of files needed to complete the task safely.
- Prefer minimal diffs and avoid unrelated refactors.
- Do not broaden scope unless required for correctness, safety, or explicit user request.
- Identify the likely edit surface before making broader changes.

## Ambiguity and Planning

- If the request is materially ambiguous, underspecified, or has multiple valid implementations, do not start coding immediately.
- First ask brief clarifying question(s) or state explicit working assumptions.
- For complex work, produce a short plan before editing.
- If the likely intent is obvious and low-risk, proceed with the smallest reasonable interpretation and make the assumption explicit.

## Phase Discipline

- Confirm whether an active implementation phase already exists before making changes.
- Implement against the active phase plan instead of improvising scope.
- If implementation must diverge from the current phase plan, update the relevant plan document before or with the code change.
- Keep roadmap, plan, and status docs aligned with the actual codebase state.

## Quality Bar

- Do not stop at the first partial fix; continue until the reported problem is actually fixed or a concrete blocker is documented.
- Be proactive about logical bugs, weak assumptions, and non-optimal designs discovered while working when they are clearly in scope.
- Make hidden constraints and tradeoffs explicit.

## Session Closeout

Before ending a meaningful work session:

1. Update `docs/plans/current-status.md`.
2. Update the active phase plan with completion state, follow-up work, or changed assumptions.
3. Update `ROADMAP.md` only when phase scope, ordering, or long-term direction changes.

## Resumability

- Record what is already implemented.
- Record what is currently in progress.
- Record the next concrete steps.
- Keep phase plans decision-complete enough that another engineer or agent can resume work immediately.
- Treat `docs/plans/current-status.md` as the live short-form handoff and `docs/plans/` as the implementation-level source of truth.