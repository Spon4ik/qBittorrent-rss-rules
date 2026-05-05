# Refactoring Roadmap (Contract-Driven)

Last updated: 2026-05-05

Ordering principle: dependency + risk first, then UX optimization.

## Phase R1 — Safety & data integrity guardrails
- Goal: eliminate silent rule semantic drift risks.
- Scope:
  - explicit managed/manual mode authority,
  - centralized normalization contract,
  - compatibility behavior for legacy rows.
- Likely files: `app/models.py`, `app/schemas.py`, `app/services/quality_filters.py`, `app/routes/api.py`, `app/routes/pages.py`, tests.
- Acceptance:
  - taxonomy/preset changes cannot auto-convert managed rules,
  - unchanged save roundtrips are idempotent.
- Tests: mode-preservation, save idempotency, legacy-bridge tests.
- Risks: compatibility bugs on existing rows.
- Rollback: feature-flagged interpretation fallback + migration-safe additive columns only.
- Must not change: user-facing routing and existing rule IDs.

## Phase R2 — Behavior contract hardening (taxonomy/preset/rule coupling)
- Goal: deterministic inheritance behavior across taxonomy and preset updates.
- Scope: effective-token derivation pipeline + preview diagnostics.
- Likely files: `app/services/quality_filters.py`, taxonomy routes/templates, tests.
- Acceptance: managed inheritance predictable and explainable; manual untouched.
- Tests: taxonomy add/remove/rank changes, preset edit propagation.
- Risks: false positives in drift detection.
- Rollback: keep previous resolver path behind switch.
- Must not change: persisted user-added taxonomy values.

## Phase R3 — Rule/profile intent vs runtime resolution split
- Goal: decouple saved intent from transient feed/indexer availability.
- Scope: represent semantic scope separately from resolved operational feed URLs.
- Likely files: models/schemas/routes/sync service.
- Acceptance: outages do not erase semantic intent.
- Tests: offline qB/Jackett save-edit-reload scenarios.
- Risks: additional state complexity.
- Rollback: continue current fallback behavior while retaining new fields.
- Must not change: existing sync endpoints and rule names.

## Phase R4 — UI layout foundations
- Goal: fix viewport usage and responsive consistency globally.
- Scope: shell width tokens, breakpoints, spacing/density utilities.
- Likely files: `app/static/app.css`, `app/templates/base.html`.
- Acceptance: narrow/medium/wide snapshots meet contract.
- Tests: browser screenshot/layout checks at representative widths.
- Risks: regressions in page-specific layouts.
- Rollback: scoped CSS flags/class toggles.
- Must not change: navigation structure.

## Phase R5 — Page-level preset/profile UX redesign
- Goal: compact and robust preset management UX.
- Scope: settings preset editor (matrix or approved alternative), clear managed/manual indicators in rule form.
- Likely files: settings/rule form templates, JS, CSS, API payload normalization/tests.
- Acceptance: reduced scroll, faster cross-profile comparison, explicit mode conversion controls.
- Tests: interaction tests for tri-state operations and save roundtrip.
- Risks: JS complexity and accessibility regressions.
- Rollback: keep legacy editor behind toggle during rollout.
- Must not change: preset keys and persisted token semantics.

## Phase R6 — Search/matching correctness + explainability refinements
- Goal: preserve exact/fallback reliability and transparent filter reasoning.
- Scope: diagnostics polish, queue-link resiliency, snapshot metadata alignment.
- Likely files: jackett/rule builder/search snapshot services + templates.
- Acceptance: hidden-row reasons and queue behavior remain trustworthy under refresh.
- Tests: regression suite for known edge repros.
- Risks: performance on large result sets.
- Rollback: disable expensive diagnostics paths.
- Must not change: existing search routes and baseline result schema.

## Phase R7 — Cleanup after stability
- Goal: reduce maintenance burden once behavior is locked.
- Scope: modular splits in large files, dead-path pruning.
- Likely files: `app/static/app.js`, route/service monoliths.
- Acceptance: no behavior change; test suite green.
- Tests: full regression + lint/type checks.
- Risks: accidental coupling breaks.
- Rollback: incremental commits with revertable slices.
- Must not change: public API contracts.
