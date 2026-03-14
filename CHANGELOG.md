# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and the project follows Semantic Versioning.

## [Unreleased]

- No entries yet.

## [0.4.0] - 2026-03-15

- Released the phase-8 persistent rule-search snapshot workflow: saved rules now replay centralized DB-backed unified results by default and support explicit snapshot refresh.
- Unified IMDb-first and title-fallback rows into one result table with source-key attribution, compact empty states, and no standalone filter-impact panel.
- Shipped rule-page workspace modernization with a sticky split layout, denser queue controls, active local-filter chips, and interactive header-driven sorting.
- Added inline affected-feed dual behavior: feed selection continues to define RSS listener scope and now also narrows inline result visibility immediately by indexer.
- Restored inline consolidated category filtering controls and compacted result controls to a table-only workflow with `Save sort as default`.

## [0.3.0] - 2026-03-13

- Released the phase-7 cached-refinement + category-catalog slice, including persisted indexer/category mapping and scoped category multiselect diagnostics on `/search`.
- Shipped rule-page inline search as the default saved-rule run flow with feed-aware scoping, queue-to-qB actions, and `/search`-parity table/sort controls.
- Added episode-progress floor filtering (`Start season` + `Start episode`) and grouped quality include semantics so multi-group selections (for example `4K` + `HDR`) apply deterministically across backend and local refinement.
- Hardened qB add-paused compatibility by posting both `paused` and `stopped` flags for queue add actions across WebUI API versions.
- Expanded deterministic browser closeout coverage with phase-7 inline checks (pattern local recompute, queue paused semantics, and table/sort parity) and stale-category scope-status regression assertions.

## [0.2.0] - 2026-03-11

- Released the phase-6 Jackett active-search workflow as the v0.2.0 feature slice, including IMDb-first plus title-fallback result sections and richer local refinement controls.
- Delivered the second-pass `/search` UX density improvements: wider layout, rule-style include/exclude checkboxes, compact filter-impact rendering, and synchronized dual result-view panels.
- Added deterministic browser closeout automation (`scripts/closeout_qa.sh` / `.bat`) and repeatable UI screenshot capture tooling (`scripts/capture_ui.sh` / `.bat`).
- Added WSL-aware qBittorrent host resolution so `localhost`/`127.0.0.1` qB base URLs are rewritten to `host.docker.internal` when running inside WSL.
- Captured release evidence across static/test gates, deterministic browser closeout, DB-backed matrix QA, and optional live-provider smoke checks.

## [0.1.0] - 2026-03-10

- Initial public release.
- Local FastAPI app with SQLite-backed rule storage, import flows, and qBittorrent WebUI sync.
- Taxonomy-driven quality filtering with media-aware rule authoring, reusable profiles, and metadata lookup integrations.
- Jackett-backed active search workspace with rule-derived queries, IMDb-first fallback behavior, and search-to-rule handoff.
- Regression-tested release path with `ruff`, `mypy`, full `pytest`, and DB-driven phase-6 search QA evidence.
