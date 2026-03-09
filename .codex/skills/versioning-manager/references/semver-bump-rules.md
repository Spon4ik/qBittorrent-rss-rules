# SemVer Bump Rules

## Patch (`x.y.Z`)

- Fix defects or regressions without changing expected contracts.
- Improve internals or performance while preserving user-facing behavior.
- Update docs/tests only, with no API/schema/config behavior changes.

## Minor (`x.Y.0`)

- Add backward-compatible features or optional settings.
- Add endpoints/fields with safe defaults that do not break existing clients.
- Extend workflows without removing or reinterpreting prior behavior.

## Major (`X.0.0`)

- Break API, schema, configuration, or workflow compatibility.
- Remove or rename routes, fields, settings, or required inputs.
- Change defaults in ways that can break existing automation.

## Compatibility Questions

1. Can existing users upgrade without mandatory config or data changes?
2. Can existing clients continue to work unchanged?
3. Can prior data remain readable and writable without destructive migration?

If any answer is "no", treat the change as major unless a full compatibility path exists.

## Pre-release and Build Metadata

- Use prerelease labels for staged cuts (`1.4.0-rc.1`, `1.4.0-beta.2`).
- Increment prerelease numbers monotonically for the same base version.
- Use build metadata only for traceability (`+build.20260309`), not precedence.
