---
name: qa-engineer
description: Risk-based software quality engineering for feature work, bug fixes, and releases. Use when Codex needs to design test strategy, build targeted test cases, execute validation, review changes for regressions, reproduce defects, or produce QA sign-off summaries with severity and next actions.
---

# QA Engineer

## Overview

Use this skill to run practical QA from request intake to decision-ready reporting. Prioritize high-risk behavior, fast feedback, and reproducible findings.

## Workflow

1. Define scope and quality bar.
2. Build a risk map.
3. Design focused test coverage.
4. Execute tests and collect evidence.
5. Report findings and release recommendation.

## 1) Define Scope And Quality Bar

- Extract the exact change under test, intended behavior, and non-goals.
- Identify impacted surfaces: API, UI, persistence, background jobs, integrations, migrations, and configuration.
- Confirm constraints: platform, environment, data shape, feature flags, and compatibility expectations.
- Set exit criteria in explicit pass/fail terms before running tests.

If the repository has process docs (for example `AGENTS.md`, roadmap, or phase plans), follow them before modifying code or test assets.

## 2) Build A Risk Map

Score each risk item by likelihood and impact, then test highest combined risk first.

Focus categories:

- Functional correctness: changed logic returns correct outputs.
- Regression risk: existing behavior or contracts break.
- Data integrity: writes, migrations, and idempotency are safe.
- Integration reliability: external services, retries, timeout handling, and error paths.
- UX and validation: invalid input handling, empty/error states, and recoverability.
- Security and safety: auth boundaries, secrets handling, and unsafe defaults.
- Performance sanity: obvious latency/throughput regressions on hot paths.

## 3) Design Focused Test Coverage

Create a lean test set that maximizes defect detection:

- Happy path for core user flow.
- Edge cases around boundaries, null/empty values, malformed input, and state transitions.
- Negative paths and failure injection for dependencies.
- Regression tests for previously stable behavior touched by this change.

Use the templates in:

- `references/test-plan-template.md`
- `references/bug-report-template.md`

## 4) Execute Tests And Collect Evidence

- Prefer existing project scripts and test commands first.
- Run narrow tests around modified modules before full-suite runs.
- Capture deterministic evidence: command, environment, output, and artifact paths.
- Reproduce failures with minimal steps and isolate root trigger.
- If a failure is flaky, document frequency and suspected source of nondeterminism.

## 5) Report Findings And Recommendation

Present results in this order:

1. Findings by severity (`critical`, `high`, `medium`, `low`) with file/path and reproduction steps.
2. Coverage summary: what was tested and what was intentionally not tested.
3. Residual risks and assumptions.
4. Recommendation: `ship`, `ship with mitigations`, or `do not ship`.

Keep findings concrete, reproducible, and action-oriented.

## Review Mode (When User Asks For A "Review")

Default to defect discovery, not code-style commentary.

- Lead with issues and behavioral risks.
- Include exact locations and why the behavior is risky.
- Suggest the smallest safe fix and a validating test when possible.
- State explicitly when no major issues are found and list remaining risk gaps.

## Quick Output Skeleton

Use this compact structure for QA updates:

```markdown
Scope
- <change under test>

Risk Map
- <risk>: likelihood <L/M/H>, impact <L/M/H>, priority <score>

Executed
- <test/command>: <pass/fail> (<evidence>)

Findings
1. <severity> - <issue> - <location> - <repro>

Recommendation
- <ship | ship with mitigations | do not ship>
- <required next actions>
```
