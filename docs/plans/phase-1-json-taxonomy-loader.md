# Phase 1: JSON-Backed Quality Taxonomy Loader

## Status

- Implementation is in place in the repo.
- Remaining validation is limited to pytest/manual verification in a fully provisioned development environment.
- Follow-on phase plans are now documented in `docs/plans/phase-2-rich-taxonomy-schema.md`, `docs/plans/phase-3-taxonomy-management-ui.md`, and `docs/plans/phase-4-feed-selection-ux.md`.

## Goal

Replace the hardcoded quality taxonomy definitions with a validated JSON file while preserving current token IDs, order, grouping, regex behavior, UI behavior, and saved profile compatibility.

## In scope

- Add repo-persisted resumability and phase-tracking documentation.
- Add `app/data/quality_taxonomy.json` as the source of truth for current quality groups and options.
- Refactor `app/services/quality_filters.py` to load, validate, and cache taxonomy data from JSON.
- Preserve all existing public behavior and persisted rule/profile data.
- Add regression and validation tests for the loader.

## Out of scope

- Bundle or tree selectors
- Computed "at least resolution" logic
- New taxonomy groups or schema expansion
- Taxonomy management UI
- Feed selection UX changes
- DB schema or API changes

## File-by-file implementation

1. `AGENTS.md`
   - Add session startup, working rules, closeout, and resumability requirements.
2. `docs/plans/README.md`
   - Add an index of the active phase and the live status ledger.
3. `docs/plans/current-status.md`
   - Track current focus, implemented items, in-progress work, next actions, and deferred work.
4. `ROADMAP.md`
   - Record phase 1 through phase 4 taxonomy/feed UX work as phased roadmap items.
5. `README.md`
   - Link the planning docs and mention repo-local resumability instructions.
6. `app/data/quality_taxonomy.json`
   - Store the exact current quality groups and options with no schema expansion.
7. `app/services/quality_filters.py`
   - Replace hardcoded taxonomy source definitions with a validated cached loader.
8. `tests/test_quality_filters.py`
   - Add compatibility checks, cache checks, and validation failure coverage.

## Acceptance criteria

- The repo contains `AGENTS.md`, `docs/plans/README.md`, `docs/plans/current-status.md`, and this phase plan.
- `README.md` and `ROADMAP.md` reference the new planning structure and phased taxonomy work.
- `app/data/quality_taxonomy.json` fully represents the current quality taxonomy.
- `app/services/quality_filters.py` uses JSON-backed cached taxonomy data instead of hardcoded taxonomy constants as the source of truth.
- Current UI rendering and saved profile behavior remain unchanged.
- Tests cover behavior preservation and invalid taxonomy handling.

## Test matrix

- Existing default profile and profile-matching tests still pass.
- `quality_option_choices()` keeps the current option order and group keys.
- `normalize_quality_tokens()` still filters invalid tokens and deduplicates valid ones.
- `tokens_to_regex()` preserves representative regex output.
- Invalid JSON taxonomy inputs fail fast with descriptive errors.
- Cache clearing allows tests to swap in temp taxonomy files safely.

## Roll-forward notes for phase 2

- Introduce a richer taxonomy schema only after phase 1 compatibility is stable.
- Keep stored rule and filter-profile selections as flat leaf token IDs even if future UI adds bundle selectors.
- Record new schema decisions in a dedicated phase 2 plan before changing the phase 1 JSON contract.
