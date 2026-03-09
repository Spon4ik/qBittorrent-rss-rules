# Document Routing and Templates

## Routing Guide

| Need | Primary artifact | Minimum sections |
|---|---|---|
| Ongoing execution handoff | Current status update | Current focus, implemented, in progress, next actions |
| Mid-phase scope or execution change | Active phase plan update | Status, in scope, implementation, acceptance criteria, validation |
| Release or sequencing change | Roadmap update | Release target, phase ordering, rationale, non-goals |
| Feature definition before build | PRD | Problem, users, outcomes, scope, non-goals, risks |
| Engineering implementation direction | Technical design spec | Context, architecture, data flow, rollout, testing |
| UI behavior and interaction contract | UX handoff spec | Flows, screen states, interactions, accessibility, responsive rules |
| Architectural decision with tradeoffs | ADR | Context, options, decision, consequences |
| Release confidence gate | QA/release plan | Scenario matrix, risk ranking, pass/fail gate, evidence capture |
| Operational uncertainty tracking | Risk and decision log | Trigger, impact, mitigation, owner, review date |

## Template: Current Status Update

```md
## Current focus
- <active phase and concrete objective>

## Implemented
- <completed work with file paths or commands>

## In progress
- <work in flight and remaining gap>

## Next actions
- <next concrete step 1>
- <next concrete step 2>
```

## Template: Active Phase Plan Update

```md
## Status
- <what changed since previous update>
- <what is complete>
- <what remains>

## In scope
- <capability 1>
- <capability 2>

## Proposed implementation
1. <slice and touched paths>
2. <slice and touched paths>

## Acceptance criteria
- <testable outcome 1>
- <testable outcome 2>

## Validation checklist
- [ ] <automated check>
- [ ] <manual validation>
```

## Template: PRD

```md
## Problem
<user or business problem to solve>

## Target users
- <user type 1>
- <user type 2>

## Outcomes and success metrics
- <metric and target>

## Scope
- In: <explicitly included behavior>
- Out: <explicit non-goals>

## Risks and dependencies
- <risk/dependency and mitigation>
```

## Template: Technical Design Spec

```md
## Context
<current behavior and constraints>

## Proposed design
- Components/services touched: <list>
- Data model/API changes: <list>
- Failure and fallback behavior: <list>

## Rollout and migration
- <sequence, toggles, data migration notes>

## Validation
- Automated: <tests and commands>
- Manual: <manual checks>
```

## Template: UX Handoff Spec

```md
## User flow
1. <entry point>
2. <main path>
3. <outcome>

## Screen and state requirements
- Screen: <name>
- States: default, loading, empty, error, success
- Primary and secondary actions: <actions>

## Accessibility and responsive rules
- Keyboard and focus behavior: <notes>
- Labels and error messaging: <notes>
- Breakpoints and wrapping/truncation: <notes>
```

## Template: ADR

```md
## Context
<decision pressure and constraints>

## Options considered
1. <option A>
2. <option B>

## Decision
<chosen option>

## Consequences
- Positive: <benefits>
- Negative: <tradeoffs>
- Follow-up: <required actions>
```

## Template: QA/Release Plan

```md
## Scope
<feature area and release boundary>

## Risk-ranked scenario matrix
| Severity | Scenario | Expected behavior | Evidence |
|---|---|---|---|
| High | <scenario> | <expected> | <artifact/log> |

## Exit criteria
- No critical or high defects open
- <project-specific gate>

## Execution notes
- Environment: <where tested>
- Known gaps: <what remains>
```

## Template: Risk and Decision Log Entry

```md
### Risk: <name>
- Trigger: <condition>
- Impact: <delivery or quality impact>
- Mitigation: <action now>
- Owner: <role/person>
- Review date: <YYYY-MM-DD>
- Status: <open|monitoring|closed>

### Decision: <name>
- Date: <YYYY-MM-DD>
- Context: <what needed a decision>
- Chosen option: <decision>
- Reasoning: <why>
- Consequences: <tradeoffs and follow-up>
```
