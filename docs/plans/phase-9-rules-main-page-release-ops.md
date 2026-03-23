# Phase 9: Rules Main-Page Release Operations

## Status

- Planning baseline created on 2026-03-15 from post-v0.4.0 next-version feature requests.
- Phase implementation completed and release-validated on 2026-03-15 as `v0.5.0`.
- Post-release closeout wording cleanup + validation rerun completed on 2026-03-15 (`scripts/closeout_browser_qa.py` now reports phases `4/5/6/7/9` consistently).
- Post-release QA-gap bugfix pass completed on 2026-03-15 for rules main-page release counters (rule-local filter parity) and missing-poster backfill behavior.
- Post-release UX bugfix pass completed on 2026-03-15 for rules-table hover poster anchoring (tooltip now follows hovered row after scroll).
- Post-release hover anchoring regression follow-up completed on 2026-03-21 by moving the hover poster to a viewport-fixed tooltip that tracks the actual hover point, flips above lower rows when needed, and is closeout-validated against a long seeded rules list with multiple lower-row screenshots plus optional video evidence after scrolling.
- Post-release live hover verification follow-up completed on 2026-03-22 by switching hover placement to row-edge anchoring with tighter preview sizing, adding QA-only auto-scroll/auto-hover hooks for real WebView capture, and updating closeout validation to measure edge adjacency instead of loose center overlap.
- Post-release search relevance bugfix pass completed on 2026-03-16 for unified local-filter query/IMDb parity (rule/search cached rows now respect the same query gate used by backend filtering).
- Phase 8 remains the historical baseline for unified rule/search workspace behavior.

## Goal

Upgrade the rules main page into a release-operations workspace where users can quickly identify rules with new matches and run Jackett fetches on demand or on a schedule.

## Requested scope (2026-03-15)

1. Rules page should default to table layout.
2. Show poster preview on row hover in table mode.
3. Show poster media directly when cards mode is selected.
4. Add on-demand Jackett query execution for all or selected rules.
5. Add optional scheduled Jackett query execution.
6. Add rule sorting based on post-filter release availability state (for example match exists/new release vs no match).

## In scope

- Rules page IA refresh with table-first default and optional cards mode.
- Poster metadata wiring for table-hover and cards rendering.
- Batch Jackett run actions (`Run selected`, `Run all`) from rules page.
- Schedule configuration model + execution path for recurring Jackett runs.
- Rule-list derived state and sorting keys for release-availability status.
- Route/service regressions plus deterministic browser checks for new flows.

## Out of scope

- Replacing Jackett with a different provider.
- Multi-user scheduling ownership model.
- Background worker infra beyond local app runtime needs.

## Acceptance criteria

- Rules page opens in table mode by default.
- Table rows expose poster preview on hover without layout breakage.
- Cards mode shows poster images for each rule card.
- Users can run Jackett fetches for selected rules and all rules on demand.
- Users can configure and persist a schedule for recurring fetch runs.
- Rule sorting can prioritize rules with current release matches after filter application.
- New behavior is covered by route/unit tests and deterministic browser QA.

## Dated execution checklist (2026-03-15 baseline)

| ID | Step | Owner | Target date | Status | Exit criteria | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| P9-01 | Define rules-page UX contract (table default, hover poster, cards poster behavior). | Codex | 2026-03-16 | completed | Decision-complete markup/interaction contract captured before implementation. | `app/templates/index.html`, `app/static/app.css`, `app/static/app.js` (`data-rules-page` contract + view toggles + hover poster) |
| P9-02 | Add poster data plumbing for rules list and card/table surfaces. | Codex | 2026-03-17 | completed | Rules payload contains poster URLs and graceful fallbacks. | `app/models.py` (`Rule.poster_url`), `app/services/metadata.py` (`MetadataResult.poster_url`), `app/routes/pages.py` (`_rule_to_form_data`), `tests/test_metadata.py` |
| P9-03 | Implement on-demand Jackett runs for selected/all rules. | Codex | 2026-03-18 | completed | Main page can trigger scoped or global fetch runs with visible status. | `app/routes/api.py` (`POST /api/rules/fetch`), `app/services/rule_fetch_ops.py`, `app/static/app.js` (`runBatchFetch`), `tests/test_routes.py::test_run_rules_fetch_api_runs_selected_rules_and_saves_snapshot` |
| P9-04 | Add recurring schedule model + execution path for Jackett runs. | Codex | 2026-03-19 | completed | Schedule settings persist and scheduled runs execute deterministically. | `app/models.py` + `alembic/versions/0005_rules_main_page_release_ops.py`, `app/services/rule_fetch_scheduler.py`, `app/routes/api.py` (`/api/rules/fetch-schedule*`), `tests/test_routes.py::test_rules_fetch_schedule_api_save_and_run_now` |
| P9-05 | Implement rule sorting by release-availability status. | Codex | 2026-03-20 | completed | Rules list can sort by match-availability state after filters. | `app/routes/pages.py` (`release_state_from_snapshot` wiring + rules sorting), `app/templates/index.html` (release sort header + chips), `tests/test_routes.py::test_rules_page_renders_release_status_from_snapshots` |
| P9-06 | Extend deterministic browser closeout for phase-9 flows. | Codex | 2026-03-21 | completed | Browser closeout covers poster behaviors, batch runs, schedule UI, and release-status sorting. | `scripts/closeout_browser_qa.py` (`P9-01`), `./scripts/closeout_qa.sh` pass artifacts (`logs/qa/phase-closeout-20260315T004048Z/closeout-report.{md,json}`) |

## Validation evidence (2026-03-15)

- `source .venv-linux/bin/activate && ruff check tests/test_routes.py` (`All checks passed`, 2026-03-16).
- `./scripts/test.sh tests/test_routes.py -k "inline_local_generated_pattern_uses_raw_title_surface or inline_feed_scope_indexer_matching_uses_key_variants or inline_local_filters_enforce_query_and_imdb_parity"` (`3 passed`, `74 deselected`, 2026-03-16).
- `./scripts/test.sh tests/test_routes.py` (`77 passed`, `51 warnings`, 2026-03-16).
- `source .venv-linux/bin/activate && ./scripts/check.sh` (`All checks passed`).
- `./scripts/test.sh tests/test_routes.py` (`75 passed`).
- `./scripts/test.sh tests/test_metadata.py tests/test_settings_service.py tests/test_routes.py -k "rules_page or rules_fetch or schedule or save_rules_page_preferences or run_rules_fetch or metadata_client_omdb_supports_title_lookup or get_or_create_normalizes_rules_page_and_schedule_defaults"` (`8 passed`, targeted phase-9 regressions).
- `./scripts/closeout_qa.sh` (`All browser closeout checks passed`; artifacts at `logs/qa/phase-closeout-20260315T004048Z/closeout-report.{md,json}`).
- `source .venv-linux/bin/activate && ruff check scripts/closeout_browser_qa.py` (`All checks passed`).
- `./scripts/test.sh tests/test_routes.py -k "rules_page_renders_release_status_from_snapshots or run_rules_fetch_api_runs_selected_rules_and_saves_snapshot or rules_fetch_schedule_api_save_and_run_now"` (`3 passed`, `72 deselected`).
- `./scripts/closeout_qa.sh` (`All browser closeout checks passed`; artifacts at `logs/qa/phase-closeout-20260315T010345Z/closeout-report.{md,json}`).
- `source .venv-linux/bin/activate && ruff check app/services/rule_fetch_ops.py app/routes/pages.py tests/test_routes.py` (`All checks passed`).
- `source .venv-linux/bin/activate && mypy app/services/rule_fetch_ops.py app/routes/pages.py` (`Success: no issues found in 2 source files`).
- `./scripts/test.sh tests/test_routes.py -k "rules_page_renders_release_status_from_snapshots or rules_page_backfills_missing_posters_from_metadata_lookup or run_rules_fetch_api_runs_selected_rules_and_saves_snapshot"` (`3 passed`, `73 deselected`).
- `./scripts/test.sh tests/test_routes.py` (`76 passed`).
- `./scripts/closeout_qa.sh` (`All browser closeout checks passed`; artifacts at `logs/qa/phase-closeout-20260315T014155Z/closeout-report.{md,json}`).
- `source .venv-linux/bin/activate && ./scripts/check.sh` (`All checks passed`).
- `source .venv-linux/bin/activate && ruff check app/routes/pages.py app/services/rule_fetch_ops.py tests/test_routes.py scripts/closeout_browser_qa.py` (`All checks passed`).
- `./scripts/test.sh tests/test_routes.py -k "rules_page_renders_release_status_from_snapshots or rules_page_backfills_missing_posters_from_metadata_lookup"` (`2 passed`, `74 deselected`).
- `./scripts/closeout_qa.sh` (`All browser closeout checks passed`; artifacts at `logs/qa/phase-closeout-20260315T015957Z/closeout-report.{md,json}`).
- `.\.venv\Scripts\python.exe scripts\closeout_browser_qa.py` (`All browser closeout checks passed`; artifacts at `logs/qa/phase-closeout-20260321T214301Z/closeout-report.{md,json}`).
