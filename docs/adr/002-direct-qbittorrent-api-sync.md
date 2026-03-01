# ADR 002: Direct qBittorrent API Sync

## Context

The main product requirement is to avoid manual qBittorrent JSON import after bootstrap.

## Decision

Use qBittorrent WebUI API endpoints for create, update, and delete operations.

## Consequences

- The app can sync immediately on save
- qBittorrent becomes an execution target instead of the primary editing surface
- The app must handle connectivity and auth failures explicitly

## Alternatives considered

- Write JSON exports only
- Depend on manual qBittorrent import
- Modify qBittorrent config files directly

