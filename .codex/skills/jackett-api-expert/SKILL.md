---
name: jackett-api-expert
description: Jackett Torznab integration and troubleshooting for search-driven workflows. Use when Codex needs to design, implement, or debug Jackett API calls, indexer capability handling, IMDb-aware query narrowing, fallback strategies, result normalization, timeout/retry behavior, and user-facing error reporting.
---

# Jackett API Expert

## Overview

Use this skill to build reliable Jackett search behavior that degrades safely under partial indexer support and transient failures.

## Workflow

1. Validate configuration and connectivity assumptions.
2. Choose the narrowest viable Torznab query shape.
3. Apply capability-aware fallbacks.
4. Normalize and merge results deterministically.
5. Surface precise diagnostics and next actions.

## 1) Validate Configuration

- Confirm base URL, API key, and endpoint path (`/api/v2.0/indexers/.../results/torznab/api`).
- Distinguish aggregate `all` indexer behavior from direct indexers.
- Preserve requested media context (`movie`, `series`, or generic) before constructing params.
- Fail fast with actionable setup errors when config is missing.

## 2) Build Query Shape

Prefer strict-to-broad execution order.

- If IMDb ID is available for movie/series, try IMDb-first variants before broad text-only search.
- Keep IMDb IDs in Jackett-expected full form (`tt1234567`).
- Use `q` as a fallback compatibility path when capability support is uncertain.
- Apply year/category narrowing only when it improves precision and does not over-constrain unsupported indexers.

Use `references/torznab-query-playbook.md` for request sequencing.

## 3) Capability-Aware Fallbacks

- Treat Torznab XML `<error ...>` payloads as request failures, not empty successes.
- On `400` or unsupported-param responses, drop the least critical narrowing first.
- If aggregate indexer rejects IMDb mode, probe direct indexer capabilities and retry only on indexers that advertise compatible inputs.
- Keep a final broad fallback path so the user still gets usable results when strict paths fail.

Use `references/failure-triage.md` for fallback matrix guidance.

## 4) Normalize And Merge Results

- Map heterogeneous Torznab XML fields into one internal result shape.
- Deduplicate by strongest stable key first: `infohash`, then GUID, then normalized title+size heuristic.
- Track provenance for each result (indexer, query variant, and fallback stage).
- Keep ranking deterministic to avoid flickering UI order between retries.

## 5) Report Errors Clearly

Include request context in user-facing errors:

- Query label (for example `imdbid`, `q+imdbid`, `title fallback`).
- Key params sent (`t`, `q`, `imdbid`, `cat`, `year` when applicable).
- Failure type (timeout, auth, unsupported param, provider error).
- What fallback ran next and whether partial results are being shown.

## Testing Expectations

When changing Jackett behavior:

- Add/update service tests for request construction and fallback transitions.
- Add/update route/UI tests for degraded flows and warning rendering.
- Cover timeout retry behavior and partial-success reporting.
- Verify deterministic dedupe under multi-query expansion.

## Quick Checklist

- Config validated
- Strict query attempted first
- Capability checks respected
- Fallbacks are staged and safe
- XML errors treated as failures
- Results deduped deterministically
- UI gets actionable warning/error context
