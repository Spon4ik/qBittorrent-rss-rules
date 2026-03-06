---
name: project-management
description: Plan and run software project execution with explicit scope, sequencing, risk tracking, and resumable handoffs. Use when Codex needs to create or update roadmap artifacts, active phase plans, current-status handoffs, delivery checklists, or decision/risk logs.
---

# Project Management

## Overview

Drive project work through decision-complete plans, short execution loops, and resumable handoffs.
Keep planning artifacts synchronized with real implementation state.

## Run Workflow

1. Build context first.
- Read roadmap, active phase plans, and current-status notes before proposing changes.
- Identify the active phase and the concrete acceptance criteria for that phase.
- Capture assumptions, dependencies, and constraints explicitly.

2. Define or revise scope.
- Break work into small, testable slices with clear outcomes.
- Write decisions where work happens, not in ad hoc chat notes.
- Update the active phase plan before or with code changes when scope diverges.

3. Execute and track progress.
- Implement against the active phase plan instead of improvising scope.
- Keep status language concrete: what is implemented, what is in progress, what is next.
- Record verification state for each slice: tested, manually validated, or pending.

4. Close out every meaningful session.
- Update current status with implemented work, in-progress work, and next concrete steps.
- Update the active phase plan with completion state, follow-ups, and changed assumptions.
- Update roadmap only for phase ordering or long-term direction changes.
- Leave handoff notes precise enough that another engineer can resume immediately.

## Write Standards

- Prefer concrete artifact paths, commands, and dates.
- Separate facts, assumptions, and open questions.
- Keep next actions directly actionable.
- Avoid vague statements like "work continues."

## Use References

- Use `references/status-and-phase-templates.md` for structured update templates and closeout checklists.
- Use `references/risk-and-decision-log.md` for concise risk and decision capture.
