# Jackett Failure Triage

## Common Failure Classes

- Auth/config: missing or invalid API key/base URL.
- Capability mismatch: indexer does not support requested params.
- Transport: timeout, connection reset, DNS, TLS.
- Provider-level rejection: Torznab XML `<error>` with explicit code/message.
- Empty result: valid request with no matches.

## Fallback Matrix

- IMDb strict fails with unsupported-param or `400`:
  - Keep IMDb if possible, remove secondary narrowing (`year`, strict type).
  - Try `q + imdbid`.
  - If aggregate fails, try only direct indexers advertising IMDb support.
- Timeout:
  - Retry same variant with backoff.
  - If still failing, continue remaining variants and show partial-results warning.
- XML provider error:
  - Mark variant failed with code/message.
  - Continue next fallback variant.

## Reporting Contract

Always include:

- Variant label and params summary.
- Failure reason category.
- Whether retry occurred.
- Whether results are partial.
