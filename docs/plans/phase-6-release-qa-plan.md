# Phase 6 Release QA Plan (DB-Driven)

## Scope

- Validate phase-6 Jackett active search behavior against real saved rules in `data/qb_rules.db`.
- Focus on release blockers: relevance, fallback correctness, IMDb-first behavior, local filter consistency, and rule-derivation safety.

## Quality Bar

- No `critical` or `high` defects in search relevance, fallback behavior, or rule-derivation.
- No regression where valid results are hidden or unrelated results are shown in primary/fallback sections.
- Search-to-rule handoff remains correct for representative movie/series/music/audiobook rules.

## Log Analysis Baseline

- `logs/search-debug.log` currently has two runs for `The Rip` (`2026-03-07T00:20:14Z` and `2026-03-07T00:33:59Z`).
- Both runs show very broad fallback pools (`raw_fallback_results=95`), indicating fallback relevance is the highest-risk path.
- Prior mismatch behavior from these logs is now addressed in code by:
- title/query local matching
- short include token matching hardening (`hdr`)
- Unicode-safe matching for non-Latin rules/titles
- IMDb-match exception for localized titles in IMDb-first flows

## DB-Backed QA Matrix

| Scenario | Rule ID | Rule Name | Expected Focus |
|---|---|---|---|
| IMDb-first + fallback split + UHD filters | `f858784c-3d61-4644-a546-33993e09c51e` | The Rip | No unrelated fallback titles in filtered results |
| IMDb-first localized title tolerance | `13278651-d96d-41b8-bd40-ec3d382b9c77` | The Godfather | IMDb-matched localized titles remain visible |
| Series IMDb-first with year | `8eff33de-cca4-4314-b3d4-03abcbe25999` | Ghosts | Primary/fallback counts and section labeling stay coherent |
| Season shorthand required keyword matching | `8eff33de-cca4-4314-b3d4-03abcbe25999` | Ghosts | `s3` / `e7` / `s3e1` filters match zero-padded title tokens |
| Series with known IMDb + year and heavy feed set | `d45711b9-3f1b-4a8e-babb-59208c41ccb9` | American Classic | Fallback results remain relevant after local filters |
| Legacy sentinel override value | `2ad0f84c-5723-43fd-a87f-33a816447640` | Ghosts GB | `must_contain_override="None"` does not become keyword `none` |
| Punctuation-heavy movie title | `074c02e3-424a-4172-916c-2e5cbaef296e` | Mike & Nick & Nick & Alice | Query normalization preserves matching quality |
| Apostrophe and ampersand title | `7af1ab04-85cb-468c-a0ec-9e3e3dbe7ec0` | Georgie & Mandy's First Marriage | Query/title matching handles punctuation correctly |
| Normalized title diverges from rule name | `8326481b-0703-48d5-939e-5d2dd6f036ab` | The Sheep Detectives | Rule-derived query uses intended canonical title |
| Full-regex override rule | `a39a2ad3-de32-4a68-8d9b-284aa88f2b74` | sunny | Regex-derived keyword groups degrade safely |
| No IMDb series | `b4637b21-b836-4fe2-b75d-261d456068b4` | The Studio | Non-IMDb path still returns stable search behavior |
| Non-Latin audiobook | `eb4c40e3-d012-4835-bdf2-39c34c064eba` | Пелевин | Non-Latin query filters work correctly |
| Non-Latin music rule with release year | `4d5c9afb-38d4-48d5-b8ec-491aea830be8` | Успокоительный сбор № 3 | Unicode title/year filtering remains correct |

## Execution Steps

1. Pre-flight:
- Snapshot `data/qb_rules.db`.
- Clear/rotate `logs/search-debug.log` before the run.
2. Per-matrix item:
- Open `/rules/{rule_id}/search`.
- Capture primary/fallback fetched vs filtered counts.
- Toggle card/table and adjust local filters (`release_year`, keyword groups, excluded tokens, category/indexer) without triggering new requests.
- Validate `Use In New Rule` prefill payload.
3. Log verification:
- Confirm one structured debug line per run in `logs/search-debug.log`.
- Flag anomalies where filtered relevance is unexpectedly low for exact-title IMDb-backed rules.
4. Regression checks:
- Manual `/search` query with grouped any-of keywords (`|`) and short tokens (`hdr`, `sd`, `ts`).
- Manual `/search` non-Latin query check.

## Execution Log (2026-03-09)

- DB snapshot created: `logs/qa/qb_rules-20260309T220744Z.db`.
- Previous debug log rotated: `logs/qa/search-debug-pre-20260309T220744Z.log`.
- Matrix evidence recorded in `logs/qa/phase6-matrix-20260309T220744Z.json` and `logs/qa/phase6-matrix-20260309T220744Z.md`.
- Matrix scope executed: 13 DB-backed rule scenarios and 2 direct `/search` regression scenarios (grouped any-of + short tokens, non-Latin query).
- Matrix results: `15/15` pass, `0 critical`, `0 high`, `0 medium`, `0 low`.
- For all 15 scenarios: `/search` returned HTTP `200`, no inline UI errors/warnings were shown, and one structured JSON debug line was appended per run in `logs/search-debug.log`.
- Primary/fallback fetched-vs-filtered counters rendered when applicable, and `Use In New Rule` prefill payload validation passed for all result-bearing scenarios (12 cases).
- Linux release-gate rerun also passed on 2026-03-09 via `source .venv-linux/bin/activate && ./scripts/check.sh` (`ruff check .`, `mypy app`, `pytest` with `117 passed`, `24 warnings`).

## Release Gate Decision

- Ship: all matrix items pass and no `critical/high`.
- Ship with mitigations: only `medium/low`, with explicit follow-up owners.
- Do not ship: any reproducible relevance regression, IMDb-first correctness break, or rule-derivation defect.

### Decision For This Run (2026-03-09)

- Recommendation: **Ship** (no `critical`/`high` defects found in the DB-backed matrix or automated gates).
- Follow-up (non-blocking): complete remaining manual browser UX validation listed in `docs/plans/current-status.md` for phase-4/phase-5 closeout and phase-6 interaction polish.
