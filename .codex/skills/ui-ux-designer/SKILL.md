---
name: ui-ux-designer
description: UI and UX design workflow for product features, pages, and flows with implementation-ready outputs. Use when Codex needs to shape interaction design, information architecture, wireframes, visual direction, accessibility behavior, responsive behavior, or frontend handoff specs before or during development.
---

# UI UX Designer

## Workflow

1. Define goals, users, and constraints.
2. Map information architecture and end-to-end flows.
3. Draft wireframe structure and interaction states.
4. Specify visual language and component behavior.
5. Run accessibility and responsive checks.
6. Produce implementation handoff artifacts.

## 1) Define Scope And Constraints

- Capture business goal, user task, and success metric.
- Confirm platform constraints, existing design system constraints, and engineering limits.
- Explicitly call out non-goals to avoid scope drift.

## 2) Map IA And User Flows

- Break the feature into screens, sections, and key user decisions.
- Document entry points, primary path, empty states, errors, and recovery routes.
- Prefer small flow diagrams or bullet flow steps over prose.

## 3) Define Layout And Interaction

- Provide desktop and mobile wireframe structure.
- Define component states: default, hover/focus, loading, empty, disabled, error, success.
- Specify interaction details: click targets, validation timing, confirmations, and undo paths.

## 4) Define Visual Direction

- Reuse current product language when one exists.
- If no system exists, propose a compact token set: typography, spacing, radius, color roles, and motion guidance.
- Keep style guidance implementation-oriented and map styles to component usage.

## 5) Validate Accessibility And Responsiveness

- Validate keyboard navigation and visible focus behavior.
- Validate semantic labeling and readable contrast.
- Confirm behavior across small, medium, and large breakpoints.
- Document acceptable content wrapping and truncation behavior.

## 6) Produce Handoff Package

- Use `references/output-templates.md` to produce delivery artifacts:
  - problem statement
  - user flows
  - wireframe spec
  - component/state spec
  - accessibility checklist
  - implementation notes
- Use `references/ui-ux-checklist.md` as a final QA gate before handoff.

## Output Rules

- Keep outputs concrete and buildable, not conceptual.
- Prefer tables and bullet specs over long narrative.
- Tie every UX recommendation to user outcome or implementation consequence.
