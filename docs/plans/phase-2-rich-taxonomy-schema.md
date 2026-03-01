# Phase 2: Richer Taxonomy Schema

## Status

- Implementation is in progress in the repo.
- The loader now preserves compatibility with schema versions 1 and 2 so phase 2 work can land safely before full phase 1 manual verification is complete.
- Remaining work is regression validation in a fully provisioned development environment and any follow-up fixes.

## Goal

Expand the quality taxonomy contract to support reusable bundles, ordered ranking metadata, and alias families while preserving backward compatibility for existing stored rule/profile token selections.

## Why this phase exists

Phase 1 moved taxonomy definitions into JSON without changing behavior. Phase 2 defines a richer schema so future UX and rule-authoring features can build on explicit, versioned taxonomy semantics rather than ad-hoc hardcoded logic.

## In scope

- Introduce a versioned taxonomy JSON schema with:
  - leaf token definitions (existing token IDs retained)
  - optional bundle/group presets that map to leaf token IDs
  - rank metadata for resolution/quality ordering
  - alias families for equivalent release naming variants
- Add schema validation for the new structure and clear startup-time errors.
- Add compatibility loading to preserve current behavior when only leaf token selections are used.
- Add migration-safe helper functions that resolve bundles and aliases into flat leaf token IDs.
- Add tests covering schema validation, compatibility guarantees, and bundle/alias expansion behavior.
- Document schema contract and extension rules.

## Out of scope

- UI for managing taxonomy definitions.
- Replacing the existing selector with tree/bundle controls.
- Automatic migration of existing saved profiles to bundle-based storage.
- Feed-selection UX changes.

## Proposed implementation

1. `app/data/quality_taxonomy.json`
   - Introduce explicit schema version metadata.
   - Add optional sections for `bundles`, `ranks`, and `aliases` while preserving existing groups/options.
2. `app/services/quality_filters.py`
   - Extend validation and caching logic to parse the richer schema.
   - Add expansion helpers:
     - bundle -> leaf tokens
     - alias -> canonical token
   - Preserve existing public APIs that expect flat token IDs.
3. `tests/test_quality_filters.py`
   - Add schema evolution tests and regression checks for old behavior.
   - Validate deterministic ordering and deduplication after expansions.
4. `docs/architecture.md`
   - Document the richer taxonomy model and compatibility policy.
5. `docs/api.md`
   - Clarify that API payload token storage remains flat leaf IDs in this phase.

## Acceptance criteria

- Existing stored rule/profile selections remain valid without migration.
- Default profile behavior remains unchanged unless explicitly updated.
- Taxonomy loader fails fast on invalid bundles/aliases/ranks with actionable messages.
- Public rule-generation behavior remains equivalent for existing token-only inputs.
- New tests prove backward compatibility and deterministic expansion behavior.

## Validation checklist

- Run targeted taxonomy service tests.
- Run full pytest suite.
- Manually verify `/rules/new` quality selector still renders and saves as before.
- Verify representative regex output before/after schema expansion for unchanged selections.

## Dependencies

- Schema version 1 compatibility remains intact while phase 1 manual verification is still pending.
- Agreement on schema versioning strategy for future phases.

## Roll-forward notes for phase 3

- Keep storage payloads stable as leaf token IDs even if phase 3 introduces richer UI controls.
- Ensure bundles/aliases are represented as authoring conveniences, not persisted canonical state.
