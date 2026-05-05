# Current Implementation Gap Analysis

Last updated: 2026-05-05

Legend:
- Risk: low / medium / high
- Complexity: small / medium / large

## GAP-001: Managed preset linkage can degrade into manual semantics
- Area: Rule form save/load + quality profile resolution.
- Current behavior: Existing mitigations exist for taxonomy-added resolution tokens, but mode identity still appears partially inferred from token snapshots and profile matching rather than explicit authoritative mode markers in all paths.
- Expected behavior: Managed preset linkage must remain explicit and stable unless user explicitly converts mode.
- Why it matters: Silent semantic drift is the highest user-trust failure.
- Impacted files: `app/services/quality_filters.py`, `app/routes/pages.py`, `app/routes/api.py`, `app/schemas.py`, quality tests.
- Likely root cause: Hybrid legacy representation (profile identity + token snapshots) and inference-heavy normalization paths.
- Fix direction: Introduce explicit mode contract and centralize save/read normalization.
- Risk: high.
- Complexity: medium.
- Independent: partially (touches shared rule save + render + search paths).
- Migration needed: likely compatibility bridge for legacy rows.
- Tests: mode-preservation under taxonomy/preset mutation.

## GAP-002: Preset management UI is high-friction and low-comparison
- Area: Settings -> Manage preset quality filters.
- Current behavior: repeated include/exclude checkbox groups per preset; long scroll and weak cross-preset comparison.
- Expected behavior: compact comparison-oriented control (matrix or equivalent).
- Why it matters: operators cannot quickly reason about policy deltas.
- Impacted files: `app/templates/settings.html`, `app/static/app.css`, `app/static/app.js`.
- Likely root cause: additive evolution from simpler two-profile model.
- Fix direction: tri-state matrix with group collapse and non-neutral filtering.
- Risk: medium.
- Complexity: medium.
- Independent: yes (after data contract hardening).
- Migration needed: no schema migration.
- Tests: UI component tests + preset save regression.

## GAP-003: Viewport utilization/responsive contract inconsistency
- Area: global shell/layout and dense pages.
- Current behavior: some pages cap practical width; narrow view degradation/wrapping remains rough.
- Expected behavior: robust narrow/medium/wide behavior with efficient width use.
- Why it matters: productivity loss via scrolling and truncation.
- Impacted files: `app/templates/base.html`, page templates, `app/static/app.css`.
- Likely root cause: mixed max-width patterns and legacy spacing assumptions.
- Fix direction: formal responsive tokens/breakpoints and page-specific density rules.
- Risk: medium.
- Complexity: medium.
- Independent: mostly yes.
- Migration needed: no.
- Tests: browser layout snapshots at key breakpoints.

## GAP-004: Contract documentation is missing as enforceable source of truth
- Area: product/data/UI behavior governance.
- Current behavior: behavior assumptions spread across phase docs and tests; no single enduring contract docs existed.
- Expected behavior: explicit contracts mapped to implementation and tests.
- Why it matters: regressions recur when intent is implicit.
- Impacted files: `docs/plans/*`.
- Likely root cause: rapid feature phases with local tactical fixes.
- Fix direction: maintain these new contract docs + roadmap + test strategy as living artifacts.
- Risk: high (organizational/product risk).
- Complexity: small.
- Independent: yes.
- Migration needed: no.
- Tests: N/A (process/document gate).

## GAP-005: External dependency outages can still influence semantic save decisions in edge flows (inference)
- Area: rule language/feed resolution + save paths.
- Current behavior: recent hardening avoids blocking saves, but edge handling still spans multiple fallback branches.
- Expected behavior: semantic intent fields persist independently from temporary runtime availability.
- Why it matters: transient outages should not mutate saved meaning.
- Impacted files: `app/routes/pages.py`, `app/routes/api.py`, `app/services/sync.py`, tests for language/feed fallback.
- Likely root cause: coupled passive-feed and active-search scope representation.
- Fix direction: explicit intent vs resolved-runtime-state fields.
- Risk: medium.
- Complexity: medium.
- Independent: partially.
- Migration needed: maybe additive fields only.
- Tests: outage simulation for create/edit/save/reload.

## Aligned areas (no refactor needed now)
- Runtime taxonomy persistence to `data/quality_taxonomy.json` and structured editor/audit-preview flow.
- Rules workspace operational actions (batch fetch/schedule + sync status surfacing).
- Search hidden-row diagnostic patterns and snapshot persistence baseline.
