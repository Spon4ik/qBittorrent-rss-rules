# Phase 5: Media-Aware Rule Form and Multi-Provider Metadata Lookup

## Status

- Implementation is in progress in the repo.
- The rule form now carries media-aware filter visibility, audio-focused filter presets, and provider-specific metadata lookup controls.
- Remaining work is environment-level validation in a fully provisioned development setup plus any follow-up fixes from that validation.
- Jackett-backed active search is explicitly deferred to phase 6 so v0.1.0 can close validation without widening scope again.

## Goal

Expand the rule form so it adapts to the selected media type, supports audio-focused filtering for audiobooks and music, and can query multiple metadata providers without changing the persisted database schema.

## In scope

- Extend the quality taxonomy to include media-aware group and option metadata plus audiobook/music codec and format tags.
- Add media-scoped built-in and saved filter profiles while keeping leaf token persistence unchanged.
- Filter visible rule-form quality options, saved profile choices, and metadata lookup providers by the selected media type.
- Add warning-and-clear behavior when switching media types would invalidate current selections.
- Expand metadata lookup beyond OMDb to MusicBrainz, OpenLibrary, and Google Books.
- Add a persistent top-level `Create Rule` action on the Rules page.
- Update tests and user-facing docs for the new lookup and filter behavior.

## Out of scope

- Database migrations or enum changes.
- New secret storage for non-OMDb providers.
- Rich provider-specific browse UIs beyond the normalized lookup field.
- Automatic migration of existing rules away from stored IMDb IDs.
- Jackett-backed active search or torrent-result browsing.

## Proposed implementation

1. `app/data/quality_taxonomy.json`, `app/services/quality_filters.py`
   - Move the taxonomy to schema version `3`.
   - Add media-aware option metadata and audio groups.
   - Add media-aware built-in filter profile catalog and legacy profile-scope inference.
2. `app/schemas.py`, `app/services/metadata.py`
   - Add normalized metadata lookup request/response models.
   - Dispatch lookup calls to OMDb, MusicBrainz, OpenLibrary, and Google Books.
3. `app/routes/pages.py`, `app/routes/api.py`, `app/templates/rule_form.html`, `app/static/app.js`, `app/templates/index.html`
   - Render media-aware form controls.
   - Add the warning-and-clear client behavior for incompatible media-type switches.
   - Surface the new top-level `Create Rule` button on the Rules page.
4. `tests/test_quality_filters.py`, `tests/test_routes.py`, `tests/test_metadata.py`
   - Cover taxonomy v3 validation, media-scoped presets, metadata route compatibility, and provider dispatch.
5. `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/plans/current-status.md`, `ROADMAP.md`
   - Align product docs and resumability notes with the new feature set.

## Acceptance criteria

- The rule form hides non-relevant quality options and saved filter profiles based on the selected media type.
- Audiobook and music authoring flows expose codec/format tags and built-in audio presets.
- Switching media types warns before clearing incompatible filters and presets.
- Metadata lookup accepts the new normalized payload and still accepts the legacy IMDb payload.
- Rules page header always exposes a `Create Rule` button.

## Validation checklist

- Run targeted service and route tests for quality filters, metadata lookup, and rule form rendering.
- Run the full pytest suite through `scripts/test.sh` or `scripts/test.bat`.
- Manually verify media switching on `/rules/new` and `/rules/{rule_id}`.
- Manually verify provider filtering, lookup population, and the Rules page header action on desktop and mobile.

## Dependencies

- Python dependencies for pytest, SQLAlchemy, and the FastAPI test stack must be installed in the local development environment.
- Public metadata providers remain available and within their anonymous usage limits.

## Roll-forward notes

- If provider-specific auth or richer search UIs are needed later, keep the current normalized route contract and add optional provider capabilities on top of it.
- If audio filtering grows further, keep persisting normalized leaf tokens rather than promoting stored bundle IDs.
- Keep Jackett-backed active search in a dedicated phase-6 slice so the current rule-form and metadata work can stabilize first.
