# ADR 005: Localhost Binding with No Separate App Auth in v0.1.0

## Context

The first release is intended for one trusted local machine and should stay simple.

## Decision

Bind the app to `127.0.0.1` by default and do not add a separate app login in v0.1.0.

## Consequences

- Lower setup complexity
- Clear local-only security posture
- Not suitable for exposed network use without future hardening

## Alternatives considered

- Built-in user accounts from the start
- LAN exposure by default
- Reverse proxy auth as a hard requirement

