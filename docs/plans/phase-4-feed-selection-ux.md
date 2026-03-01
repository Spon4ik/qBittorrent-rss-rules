# Phase 4: Feed Selection UX Improvements

## Status

- Planned.
- Independent from taxonomy management UI, but should follow phase 2 if taxonomy-driven defaults are introduced.

## Goal

Improve feed selection usability with bulk selection controls and remembered defaults while preserving deterministic sync behavior.

## In scope

- Add `Select all` / `Clear all` controls for rule feed selection.
- Add user-level remembered default feed selections used to prefill new rule forms.
- Ensure defaults can be overridden per rule without side effects.
- Keep sync payloads explicit and deterministic.
- Add tests for form behavior and persistence.

## Out of scope

- Cross-user shared defaults.
- Automatic feed grouping heuristics from remote metadata.
- Background feed sync jobs.

## Proposed implementation

1. `app/templates/rule_form.html`, `app/static/app.js`
   - Add selection controls and UX state handling.
2. `app/services/settings_service.py`, `app/models.py`
   - Persist remembered default feeds.
3. `app/routes/pages.py`, `app/routes/api.py`
   - Expose/update defaults and apply to new-rule form rendering.
4. `tests/test_routes.py`, `tests/test_rule_builder.py`
   - Add coverage for selection controls and default-application logic.
5. `docs/api.md`, `docs/architecture.md`
   - Document feed default behavior and contracts.

## Acceptance criteria

- Users can select or clear all feeds with one action.
- New rules prefill feed selections from remembered defaults when configured.
- Existing rules load persisted feeds exactly as stored.
- Tests verify deterministic form serialization and sync payload behavior.

## Validation checklist

- Run route/form tests.
- Run full check script.
- Manual verification on `/rules/new` for bulk controls and default prefill behavior.

## Dependencies

- Clear UX decision on where remembered defaults are configured (`/settings` vs rule form).
- Existing feed fetch pipeline remains stable.
