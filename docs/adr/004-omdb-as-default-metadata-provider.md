# ADR 004: OMDb as Default Metadata Provider

## Context

The app needs a stable public API that can resolve title and media type from an IMDb ID.

## Decision

Use OMDb as the default metadata provider in v0.1.0.

## Consequences

- Straightforward lookup by IMDb ID
- Requires an API key
- Provider failures must fall back to manual entry

## Alternatives considered

- No metadata provider
- Custom scraping
- Multiple providers in v0.1.0

