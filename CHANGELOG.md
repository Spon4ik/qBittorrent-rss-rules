# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and the project follows Semantic Versioning.

## [Unreleased]

- No entries yet.

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
