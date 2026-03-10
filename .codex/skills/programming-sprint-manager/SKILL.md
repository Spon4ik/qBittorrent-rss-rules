---
name: programming-sprint-manager
description: Manage programming sprint execution for small fixes, features, and improvements by splitting requests into scoped implementation slices, sequencing work, tracking progress, and closing sessions with resumable handoffs. Use when Codex needs to plan or run short engineering sprints, decompose backlog items, execute a queue of small code changes, or keep sprint docs and status synchronized with implementation.
---

# Programming Sprint Manager

## Overview

Run short programming sprints as a sequence of small, validated slices.
Keep scope explicit, WIP limited, and status artifacts synchronized with code state.

## Run Workflow

1. Frame the sprint request.
- Extract goal, non-goals, constraints, and acceptance checks from the request.
- Read repository planning artifacts before coding when project policy requires it.
- Convert ambiguity into explicit assumptions and record them in sprint notes.

2. Build the sprint backlog.
- Split work into slices that are independently implementable and verifiable.
- Keep each slice to one behavior change or one coherent refactor boundary.
- Assign each slice a concrete done condition (tests, manual validation, docs, or all).
- Use `references/slice-sizing-rubric.md` to size slices and avoid overstuffed tasks.

3. Sequence and control WIP.
- Order slices by dependency and risk, highest-risk first when feasible.
- Keep one implementation slice in progress at a time unless safe parallelism is explicit.
- Mark blocked slices with the unblock condition instead of leaving them ambiguous.
- Track state using `references/sprint-board-template.md`.

4. Execute each slice end-to-end.
- Implement the slice directly in code, not as speculative pseudo-plans.
- Run the smallest verifying checks first, then broader checks before closeout.
- Update sprint status immediately after each slice: `done`, `in_progress`, `blocked`, or `deferred`.
- If scope changes, update sprint notes and impacted plan/status artifacts in the same session.

5. Manage replanning and carryover.
- When a slice expands, split it again rather than continuing as an oversized task.
- Move non-critical overflow into explicit carryover entries with rationale.
- Record decisions and tradeoffs so another engineer can resume without rediscovery.

6. Close the sprint session.
- Summarize implemented work, in-progress work, and next concrete slices.
- Record validation evidence (commands, pass/fail, artifact paths).
- Synchronize roadmap/phase/status artifacts required by repository workflow.
- Leave a decision-complete handoff using `references/sprint-board-template.md`.

## Execution Standards

- Prefer small, testable increments over large unverified batches.
- Keep status claims evidence-backed and date-stamped.
- Separate facts, assumptions, and open questions.
- Prevent hidden scope creep by updating sprint artifacts before or with code changes.

## Use References

- Use `references/sprint-board-template.md` for backlog board structure, update cadence, blocker logging, and closeout handoffs.
- Use `references/slice-sizing-rubric.md` to split oversized work into implementable slices with explicit done criteria.
