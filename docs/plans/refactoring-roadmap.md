# Refactoring Roadmap (Contract-Driven)

Last updated: 2026-05-07

Packaging status: Phases R1.5-R7 are packaged for review on branch `codex/package-contract-roadmap-r1-5-r7`. Phase R8 is now the pre-feature stabilization gate for qB rule enforcement parity before Phase 25 feature work continues.

Ordering principle: dependency + risk first, then UX optimization.

Execution loop:
- complete only the active phase scope;
- run the focused validation and required Docker/live probes for that phase;
- update `docs/plans/current-status.md` and this roadmap with evidence;
- inspect what the phase revealed about later phases, including bugs, invalid assumptions, missing QA, or changed integration behavior;
- adjust later roadmap steps before continuing when new facts make the old plan weaker;
- keep proceeding through packaging, commit, push, PR, and release handoff once validation is green, pausing only for destructive/data-loss/credential-exposure risk or a decision that cannot be derived from repo evidence.

## Phase R1 — Safety & data integrity guardrails
- Status: implemented on 2026-05-05.
- Goal: eliminate silent rule semantic drift risks.
- Scope:
  - explicit managed/manual mode authority,
  - centralized normalization contract,
  - compatibility behavior for legacy rows.
- Delivered:
  - added explicit `Rule.quality_mode` persistence with managed/manual authority and nullable legacy compatibility;
  - carried `quality_mode` through rule-form posts without changing visible UI layout;
  - made effective quality-token resolution honor explicit manual snapshots and explicit managed preset inheritance;
  - preserved existing managed token snapshots during no-op saves so unchanged form roundtrips do not rewrite stored semantics;
  - added mode-preservation, no-op-save idempotency, and legacy-post bridge tests.
- Likely files: `app/models.py`, `app/schemas.py`, `app/services/quality_filters.py`, `app/routes/api.py`, `app/routes/pages.py`, tests.
- Acceptance:
  - taxonomy/preset changes cannot auto-convert managed rules,
  - unchanged save roundtrips are idempotent.
- Tests: mode-preservation, save idempotency, legacy-bridge tests.
- Risks: compatibility bugs on existing rows.
- Rollback: feature-flagged interpretation fallback + migration-safe additive columns only.
- Must not change: user-facing routing and existing rule IDs.

## Phase R1.5 - Runtime config & validation guardrails
- Status: implemented and validated on 2026-05-06.
- Goal: remove environment/config ambiguity before deeper taxonomy and preset behavior work.
- Why now:
  - Phase R1 exposed a Docker qB username override that masked saved app settings;
  - qBittorrent `v5.2.0` returns successful auth as `204 No Content` plus a session cookie instead of the older `Ok.` body;
  - the broader quality/routes validation run was blocked by runtime-taxonomy-dependent ordering state.
- Scope:
  - document and test qB connection precedence between explicit env vars and saved DB settings;
  - keep qB WebUI auth response compatibility covered for both legacy `Ok.` and `204` + cookie success paths;
  - isolate runtime taxonomy state in tests that assert seed/default ordering, or update those tests to assert contract behavior without depending on local user-added tail tokens;
  - add a concise Docker validation checklist for rebuild, `/health`, qB login, and Jackett reachability.
- Delivered:
  - added qB env-vs-DB precedence coverage for empty env fallback and explicit env override behavior;
  - added explicit qB auth compatibility coverage for legacy `Ok.` and qB `v5.2.0` `204` + cookie success responses;
  - changed the seed/default taxonomy order test to use a temp packaged-seed taxonomy, leaving runtime taxonomy persistence behavior untouched;
  - added README Docker validation commands for shared Compose rebuild, `/health`, qB login, and Jackett reachability from inside the running container.
- Likely files: `app/services/settings_service.py`, `app/services/qbittorrent.py`, `tests/test_settings_service.py`, `tests/test_qbittorrent_client.py`, `tests/test_quality_filters.py`, README/docs/plans.
- Acceptance:
  - saved qB settings are not shadowed by empty/default Docker env values;
  - qB login tests cover both supported success response shapes;
  - `tests/test_quality_filters.py tests/test_routes.py` can run without failing due to machine-local taxonomy additions;
  - Docker validation steps are explicit and repeatable from the repo handoff docs.
- Tests: settings precedence, qB auth compatibility, runtime-taxonomy isolation, focused route/quality suite rerun.
- Validation: focused new qB precedence tests and qB auth tests passed; `tests/test_quality_filters.py tests/test_routes.py` passed; Ruff on touched Python tests passed; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: accidentally weakening intentional env override behavior; over-normalizing tests so they stop catching taxonomy ordering regressions.
- Rollback: retain current env-precedence behavior while documenting explicit override requirements.
- Must not change: rule semantics, taxonomy persistence behavior, qB saved credential storage format.

## Phase R2 - Behavior contract hardening (taxonomy/preset/rule coupling)
- Prerequisite: Phase R1.5 validation guardrails complete or explicitly waived.
- Status: implemented on 2026-05-06.
- Goal: deterministic inheritance behavior across taxonomy and preset updates.
- Scope: effective-token derivation pipeline + preview diagnostics.
- Delivered:
  - factored rank-derived default profile calculation so taxonomy previews can compare current and draft managed preset effects without mutating runtime taxonomy;
  - taxonomy draft preview now reports rank-derived managed profile include/exclude token deltas;
  - taxonomy page renders the managed preset impact section when a draft would change inherited preset tokens;
  - added contract coverage for managed preset-edit inheritance versus manual snapshot stability.
- Likely files: `app/services/quality_filters.py`, taxonomy routes/templates, tests.
- Acceptance: managed inheritance predictable and explainable; manual untouched.
- Tests: taxonomy add/remove/rank changes, preset edit propagation.
- Validation: focused R2 service/route tests passed; `tests/test_quality_filters.py tests/test_routes.py` passed; `tests/test_settings_service.py tests/test_qbittorrent_client.py` passed; Ruff passed on touched Python files; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: false positives in drift detection.
- Rollback: keep previous resolver path behind switch.
- Must not change: persisted user-added taxonomy values.

## Phase R3 — Rule/profile intent vs runtime resolution split
- Status: implemented on 2026-05-06.
- Goal: decouple saved intent from transient feed/indexer availability.
- Scope: represent semantic scope separately from resolved operational feed URLs.
- Delivered:
  - added additive `Rule.feed_resolution_status` and `Rule.feed_resolution_message` fields;
  - create/update saves now persist language intent when Jackett language metadata is temporarily unavailable instead of blocking or erasing semantic state;
  - saved operational feed URLs are preserved for same-language edits during metadata outages, while changed/new language saves can persist with an empty resolved feed list and an unavailable status;
  - real no-match language selections still block when Jackett metadata is available and proves no configured indexer matches.
- Likely files: models/schemas/routes/sync service.
- Acceptance: outages do not erase semantic intent.
- Tests: offline qB/Jackett save-edit-reload scenarios.
- Validation: focused offline language-save tests passed; no-matching-language regression passed; `tests/test_routes.py tests/test_sync_service.py tests/test_rule_builder.py` passed; Ruff passed for touched route/model/db/sync/rule-builder test slices; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: additional state complexity.
- Rollback: continue current fallback behavior while retaining new fields.
- Must not change: existing sync endpoints and rule names.

## Phase R4 — UI layout foundations
- Status: implemented on 2026-05-06.
- Goal: fix viewport usage and responsive consistency globally.
- Scope: shell width tokens, breakpoints, spacing/density utilities.
- Delivered:
  - added global CSS tokens for shell gutters, normal/wide max widths, content padding, density gaps, and shared control height;
  - replaced hard-coded shell width/padding with tokenized normal and wide shell behavior;
  - added contract breakpoints for narrow `900px` behavior and medium `901px` to `1400px` density tuning;
  - added small layout/density utility classes for future page-level work without changing current navigation or template structure;
  - contained the rules operational table inside its wrapper so narrow/medium pages do not gain document-level horizontal overflow.
- Likely files: `app/static/app.css`, `app/templates/base.html`.
- Acceptance: narrow/medium/wide snapshots meet contract.
- Tests: browser screenshot/layout checks at representative widths.
- Validation: CSS contract test passed after failing on missing shell tokens; `tests/test_routes.py tests/test_static_assets.py` passed; Ruff and `py_compile` passed for `scripts/closeout_browser_qa.py` / `tests/test_static_assets.py`; `R4-01` in `logs/qa/phase-closeout-20260506T194654Z/closeout-report.md` passed with `/`, `/rules/new`, `/settings`, `/taxonomy`, and `/search` screenshots at `390px`, `1180px`, and `1720px`; full legacy closeout still exits nonzero only because `P4-01` expects the old feed-checkbox source; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`; in-app browser `/health` smoke loaded with no warning/error logs.
- Risks: regressions in page-specific layouts.
- Rollback: scoped CSS flags/class toggles.
- Must not change: navigation structure.

## Phase R5 — Page-level preset/profile UX redesign
- Status: implemented on 2026-05-06.
- Goal: compact and robust preset management UX.
- Scope: settings preset editor (matrix or approved alternative), clear managed/manual indicators in rule form.
- Delivered:
  - replaced the tall settings profile token editor with a compact comparison matrix backed by the existing tri-state token controls and persisted hidden field names;
  - added explicit managed/manual authority indicators and conversion buttons on the rule form;
  - kept preset keys, route payloads, and stored token semantics unchanged;
  - added deterministic route and browser interaction coverage for the matrix, rule-form authority controls, and save/reload roundtrip.
- Likely files: settings/rule form templates, JS, CSS, API payload normalization/tests.
- Acceptance: reduced scroll, faster cross-profile comparison, explicit mode conversion controls.
- Tests: interaction tests for tri-state operations and save roundtrip.
- Validation: focused R5 route/UI tests passed after failing first; broader settings/quality route slice passed; `tests/test_routes.py tests/test_static_assets.py` passed; `node --check app/static/app.js`, Ruff, and `py_compile` passed for touched files; `R5-01` in `logs/qa/phase-closeout-20260506T195945Z/closeout-report.md` passed; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: JS complexity and accessibility regressions.
- Rollback: keep legacy editor behind toggle during rollout.
- Must not change: preset keys and persisted token semantics.

## Phase R6 — Search/matching correctness + explainability refinements
- Status: implemented on 2026-05-06.
- Goal: preserve exact/fallback reliability and transparent filter reasoning.
- Scope: diagnostics polish, queue-link resiliency, snapshot metadata alignment.
- Delivered:
  - stale rule-snapshot queue retries now match refreshed links across primary, fallback, raw-primary, and raw-fallback result lanes;
  - rule snapshot refresh now persists first-blocker hidden-row reason counts in `rule_local_hidden_reasons` alongside existing local filtered/fetched metadata;
  - unified search hidden-row summaries now surface the top blocker reasons without requiring the user to expand hidden rows first;
  - browser closeout now includes `R6-01` for rendered hidden-row blocker summary behavior.
- Likely files: jackett/rule builder/search snapshot services + templates.
- Acceptance: hidden-row reasons and queue behavior remain trustworthy under refresh.
- Tests: regression suite for known edge repros.
- Validation: focused R6 tests passed after failing first; `tests/test_routes.py tests/test_rule_fetch_ops.py tests/test_selective_queue.py` passed; `node --check app/static/app.js`, Ruff, and `py_compile` passed for touched files; `R6-01` in `logs/qa/phase-closeout-20260506T201033Z/closeout-report.md` passed; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: performance on large result sets.
- Rollback: disable expensive diagnostics paths.
- Must not change: existing search routes and baseline result schema.

## Phase R7 — Cleanup after stability
- Status: implemented on 2026-05-06.
- Goal: reduce maintenance burden once behavior is locked.
- Scope: modular splits in large files, dead-path pruning.
- Delivered:
  - pruned unused private rule-snapshot filter helpers made redundant by the R6 diagnostics path;
  - avoided behavior-moving refactors and preserved public API contracts.
- Likely files: `app/static/app.js`, route/service monoliths.
- Acceptance: no behavior change; test suite green.
- Tests: full regression + lint/type checks.
- Validation: reference search confirms the removed helpers are unused; `tests/test_rule_fetch_ops.py tests/test_routes.py tests/test_selective_queue.py` passed; Ruff passed for the touched cleanup slice; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=12`.
- Risks: accidental coupling breaks.
- Rollback: incremental commits with revertable slices.
- Must not change: public API contracts.

## Phase R8 - qB rule enforcement parity stabilization
- Status: implemented and validated on 2026-05-07.
- Goal: make visible app rule semantics, generated qB RSS payloads, and observed remote qB RSS rule state auditable as one contract.
- Why now:
  - the reported `The Boys` rule showed `400p` visibly excluded in the app while qB still queued `The.Boys.S05.400p.Kerob`;
  - local effective tokens and generated app payload already included the `400p` exclusion, so the missing guardrail was remote qB parity/drift evidence and targeted regression coverage.
- Scope:
  - preserve current effective token semantics and taxonomy persistence behavior;
  - record the last app-generated qB RSS rule payload after successful sync;
  - record the last observed remote qB RSS rule payload when `sync_all` detects drift before it repairs qB;
  - surface qB enforcement diagnostics on the edit-rule page;
  - add focused regressions for `400p` exclusion enforcement and qB payload/drift diagnostics.
- Delivered:
  - added additive rule diagnostics fields for last synced payload, last observed remote payload, drift message, and drift timestamp;
  - `SyncService.sync_rule` now persists the exact qB payload it sent;
  - `SyncService.sync_all` now records stale remote payload evidence before repairing qB from local rule semantics;
  - edit-rule pages now expose qB enforcement diagnostics, including last synced and last observed remote `mustContain` patterns;
  - added regression coverage proving `The.Boys.S05.400p.Kerob` does not match the generated app pattern and that qB payload/drift diagnostics are stored and rendered.
- Likely files: `app/models.py`, `app/db.py`, `app/services/sync.py`, rule-form route/template, tests, docs.
- Acceptance:
  - local effective exclusions, generated qB payload, and live qB remote rule can be compared for a reported rule;
  - the known bad `400p` release title does not pass generated rule semantics;
  - remote qB drift is detected, recorded, and repaired by sync;
  - Phase 25 remains unstarted in this package.
- Validation: `tests/test_rule_builder.py tests/test_sync_service.py tests/test_quality_filters.py` passed; `tests/test_routes.py` passed; Ruff passed for touched Python files; shared Docker Compose rebuild passed; Docker `/health` reports `app_version=1.1.2`; inside-container qB login reports `qb_test=ok`; inside-container Jackett discovery reports `jackett_indexers=18`; live readback for rule `584372ae-1d88-4c01-be8d-4b43b9fc822c` reports effective exclusions include `400p`, generated qB `mustContain` includes `400p`, remote qB `mustContain` includes `400p`, and app-managed remote fields match after the same Jackett feed-health filtering used by sync.
- Risks: qB can still have already-queued torrents from a previous stale rule state; R8 makes future drift/audit evidence visible and repairs remote rule payloads but does not remove existing torrents from qB.
- Must not change: qB rule semantics, taxonomy persistence behavior, saved rule IDs, Phase 25 scope.

## Post-R8 packaging and release handoff
- Status: active.
- Goal: turn the completed R1.5-R8 contract-roadmap work into a coherent GitHub review/release package before Phase 25 resumes.
- Scope:
  - review the full uncommitted diff by subsystem and confirm it remains scoped to R1.5-R8 plus autonomous workflow documentation;
  - rerun focused validation and browser closeout because UI, JS, CSS, and browser QA files changed;
  - accept browser closeout only if `P4-01` remains the sole known legacy failure and no new R4/R5/R6/R8 or route/static/qB failures appear;
  - commit with `Complete contract roadmap R1.5-R8 guardrails and qB parity`;
  - push the branch and open a draft PR/release handoff noting Phase 25 was not started.
- Discovery review before Phase 25:
  - R8 showed qB remote parity must compare app-managed keys after sync-time feed-health filtering, so future qB phases must include live remote readback when rule payloads or feed filtering are touched;
  - R8 did not require a Phase 25 scope change, but Phase 25 must not remove or obscure qB enforcement diagnostics while splitting Stremio responsibilities.
- Acceptance:
  - final validation evidence is recorded in `current-status.md`;
  - branch is pushed to GitHub with a draft PR or documented GitHub handoff;
  - no Phase 25 implementation code is included in this package.
