---
name: project-design-documentation-engineer
description: Engineer project and design documentation with implementation-ready structure, explicit decisions, and resumable handoffs. Use when Codex needs to draft, revise, or synchronize roadmap entries, phase plans, current-status notes, PRDs, technical design specs, UX handoffs, ADRs, QA plans, or risk and decision logs.
---

# Project Design Documentation Engineer

## Overview

Plan, write, and maintain project and design documents as production artifacts.
Keep documentation synchronized with implementation state so another engineer can resume work immediately.

## Run Workflow

1. Identify the document objective and consumer.
- Confirm whether the output is for product planning, technical implementation, UX handoff, QA release gating, or decision tracking.
- State the target reader explicitly: engineering, product, design, QA, or mixed.

2. Build context before drafting.
- Read current source artifacts first: roadmap, active phase plan, current status, and touched code paths.
- Extract `facts`, `assumptions`, `open questions`, and constraints into concise bullets.

3. Select the correct template.
- Use `references/document-routing-and-templates.md` to choose the minimal template for the requested outcome.
- Prefer the smallest artifact that can still hold required decisions and acceptance criteria.

4. Produce decision-complete content.
- Include concrete paths, commands, owners, dependencies, and acceptance criteria.
- Record tradeoffs whenever rejecting a plausible alternative.
- Use exact dates (`YYYY-MM-DD`) for milestones, review points, and risk checks.

5. Synchronize related artifacts.
- If scope or sequencing changes, update roadmap and active phase plan in the same session.
- If implementation state changes, update current status and active phase plan together.
- Remove contradictory statements between docs before finishing.

6. Run a final quality gate.
- Apply `references/document-quality-checklist.md`.
- Ensure next actions are directly executable by another engineer without extra discovery.

## Writing Standards

- Prefer short sections, checklists, and tables over long narrative.
- Keep claims traceable to code, tests, logs, or explicit stakeholder input.
- Separate confirmed behavior from proposals and open questions.
- Tie every recommendation to implementation impact, delivery risk, or user outcome.

## Use References

- Use `references/document-routing-and-templates.md` to map request type to the right artifact and start from compact templates.
- Use `references/document-quality-checklist.md` as a release gate before publishing or closing a session.
