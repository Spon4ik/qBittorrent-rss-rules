# ADR 003: SQLite as Local Source of Truth

## Context

Rules need structured local persistence, import tracking, and sync event history.

## Decision

Store app-managed state in a local SQLite database.

## Consequences

- Simple setup and backup story
- Good fit for localhost-only v0.1.0
- Future migrations need to be managed carefully

## Alternatives considered

- JSON files as the only storage layer
- In-memory only state
- External database server

