# Torznab Query Playbook

## Priority Order

1. IMDb-first (`imdbid`) when available and relevant.
2. Hybrid (`q + imdbid`) when strict IMDb-only returns nothing or fails.
3. Narrow text query (`q` + optional year/category) if supported.
4. Broad title fallback (`q` only).

## Parameter Notes

- `imdbid`: Keep `tt` prefix.
- `q`: Use cleaned title/keywords, not raw regex.
- `cat`: Apply media-appropriate category set only when known.
- `year`: Treat as optional narrowing; remove first on compatibility failures.
- `t`: Set search type explicitly if implementation depends on it.

## Retry Strategy

- Retry transient timeouts before marking a variant failed.
- Degrade per variant; do not abort full search if later variants can still succeed.
- Preserve warning context for skipped/failed variants.
