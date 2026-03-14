# Phase 9: Rules Main-Page Release Operations

## Status

- Planning baseline created on 2026-03-15 from post-v0.4.0 next-version feature requests.
- This phase is the active track for `v0.5.0`.
- Phase 8 is release-validated in `v0.4.0` and now acts as regression baseline.

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
| P9-01 | Define rules-page UX contract (table default, hover poster, cards poster behavior). | Codex | 2026-03-16 | pending | Decision-complete markup/interaction contract captured before implementation. | `app/templates/index.html`, `app/static/app.css`, browser QA checklist updates |
| P9-02 | Add poster data plumbing for rules list and card/table surfaces. | Codex | 2026-03-17 | pending | Rules payload contains poster URLs and graceful fallbacks. | `app/routes/pages.py`, `app/services/metadata.py`, route tests |
| P9-03 | Implement on-demand Jackett runs for selected/all rules. | Codex | 2026-03-18 | pending | Main page can trigger scoped or global fetch runs with visible status. | API/route handlers, frontend actions, test coverage |
| P9-04 | Add recurring schedule model + execution path for Jackett runs. | Codex | 2026-03-19 | pending | Schedule settings persist and scheduled runs execute deterministically. | models/migrations/services/tests |
| P9-05 | Implement rule sorting by release-availability status. | Codex | 2026-03-20 | pending | Rules list can sort by match-availability state after filters. | route sorting logic + UI control + tests |
| P9-06 | Extend deterministic browser closeout for phase-9 flows. | Codex | 2026-03-21 | pending | Browser closeout covers poster behaviors, batch runs, schedule UI, and release-status sorting. | `scripts/closeout_browser_qa.py`, `scripts/closeout_qa.sh` artifacts |
