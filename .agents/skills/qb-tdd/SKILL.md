---
name: qb-tdd
description: Use when implementing or repairing application behavior in this repository, choosing regression tests, or deciding whether validation proves a fix.
---

# Deterministic TDD for this repository

Read `AGENTS.md`, `docs/plans/current-status.md`, and the relevant active phase plan before changing implementation scope.

1. Reproduce the reported behavior from explicit persisted state, inputs, or failure transitions. Record the expected and actual result.
2. Add or adapt the smallest deterministic test that fails for the reported reason. For a confirmed defect, this regression is required before closure.
3. Make the smallest implementation change that makes the regression pass. Preserve adjacent contracts and existing provider data.
4. Run the narrowest relevant test/check first. Broaden only as required by `AGENTS.md`; use `scripts\test.bat` or `scripts\check.bat` as appropriate.
5. For backend closeout, run `Finalize-Backend.cmd --no-pause` only after a coherent change is ready. It is the required full test, Docker rebuild and deployed-version freshness gate.

Never report a fix from source inspection alone. Distinguish focused validation, full gate, live provider evidence, Docker deployment, GitHub persistence, and release state. Do not use AI polling as issue detection or substitute an LLM judgement for a deterministic assertion.
