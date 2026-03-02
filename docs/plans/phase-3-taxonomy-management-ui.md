# Phase 3: Taxonomy Management UI

## Status

- Implementation is in progress in the repo.
- A first server-rendered editor flow exists for inspect, validate, and apply.
- Remaining work is validation in a full dev environment plus UX refinement if a richer client-side workflow is still desired.

## Goal

Provide a UI and API workflow to inspect, edit, validate, and safely apply taxonomy updates without requiring direct JSON file edits.

## In scope

- Read-only taxonomy inspection page for current schema contents.
- Admin-style local editing workflow for taxonomy JSON with pre-save validation.
- Dry-run preview of impact on known filter profiles and default presets.
- Save/apply flow that writes the taxonomy source of truth and refreshes loader cache.
- Guardrails preventing destructive edits that orphan persisted token IDs.
- Audit log or event trail entry for taxonomy changes.

## Out of scope

- Multi-user permissioning.
- Remote sync/distribution of taxonomy updates.
- Non-localhost deployment hardening.

## Proposed implementation

1. `app/routes/pages.py`, `app/routes/api.py`
   - Add endpoints for taxonomy read, validate, and apply actions.
2. `app/templates/` + `app/static/`
   - Add taxonomy editor and validation feedback UI.
   - Initial implementation may stay server-rendered; richer client-side polish can follow after workflow validation.
3. `app/services/quality_filters.py`
   - Add safe reload hooks and impact-analysis helpers.
4. `tests/test_routes.py`, `tests/test_quality_filters.py`
   - Cover UI/API flows and safety checks.
5. `docs/api.md`, `docs/architecture.md`
   - Document contracts and operational safety expectations.

## Acceptance criteria

- Taxonomy can be reviewed and edited from the app UI.
- Invalid taxonomy updates are rejected with clear field-level errors.
- Applying a taxonomy update does not silently break existing persisted rule/profile selections.
- Change history is visible enough to support local troubleshooting.

## Validation checklist

- Run route and service tests for taxonomy edit flows.
- Run full check script.
- Manual UI verification of edit/validate/apply lifecycle.

## Dependencies

- Phase 2 richer schema and validation helpers.
- Stable UX decisions for local-only edit flow.

## Roll-forward notes for phase 4

- Reuse taxonomy UI patterns for future selector improvements and preset tooling.
