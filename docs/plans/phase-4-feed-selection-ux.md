# Phase 4: Feed Selection UX Improvements

## Status

- Code-complete in the current branch; manual validation remains pending.
- Initial slice implemented: rule-form bulk selection controls and create-flow remembered default feeds.
- Follow-up slice implemented: the remember-defaults toggle is now default-on and available on both create and edit forms.
- Final slice implemented: the rule form now uses a checkbox-based feed selector while preserving deterministic submission order.
- Independent from taxonomy management UI, but should follow phase 2 if taxonomy-driven defaults are introduced.

## Goal

Improve feed selection usability with bulk selection controls and remembered defaults while preserving deterministic sync behavior.

## In scope

- Add `Select all` / `Clear all` controls for rule feed selection.
- Replace the rule-form feed multi-select with explicit per-feed checkboxes.
- Add user-level remembered default feed selections used to prefill new rule forms.
- Ensure users can keep or skip updating remembered defaults from each rule form submission.
- Keep sync payloads explicit and deterministic.
- Add tests for form behavior and persistence.

## Out of scope

- Cross-user shared defaults.
- Automatic feed grouping heuristics from remote metadata.
- Background feed sync jobs.

## Proposed implementation

1. `app/templates/rule_form.html`, `app/static/app.js`
   - Render feed checkboxes plus selection controls, and keep refresh state deterministic.
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
- Feed choices render as checkbox inputs instead of a browser multi-select widget.
- New rules prefill feed selections from remembered defaults when configured.
- Existing rules load persisted feeds exactly as stored.
- Tests verify deterministic form serialization and sync payload behavior.

## Validation checklist

- Run route/form tests.
- Run full check script.
- Use the repo-local pytest wrapper so each validation run refreshes readable artifacts under `logs/tests/`.
- Manual verification on `/rules/new` for checkbox rendering, bulk controls, and default prefill behavior.

## Dependencies

- Clear UX decision on where remembered defaults are configured (`/settings` vs rule form).
- Existing feed fetch pipeline remains stable.


## Progress update

- Added rule-form `Select all` / `Clear all` controls for the feed selection UI.
- Replaced the browser multi-select with explicit feed checkboxes on the rule form.
- Added persisted `AppSettings.default_feed_urls` used to prefill `/rules/new`.
- Added a default-on rule-form checkbox to remember current selected feeds as new-rule defaults on both create and edit.
- Feed refresh now preserves currently selected saved-feed entries when the refreshed qBittorrent feed list does not include them.
- Added route tests for prefill, persistence, control visibility, and edit-mode checkbox rendering.
- Updated route tests to send repeated form values using `httpx`-compatible dict/list payloads instead of deprecated tuple-list bodies.
- Added repo-local pytest wrappers that always refresh `logs/tests/pytest-last.log` and `logs/tests/pytest-last.xml` for post-run debugging.
- Remaining: decide whether defaults should be editable in `/settings`, and add manual UX verification plus full pytest coverage in a fully provisioned development environment.
