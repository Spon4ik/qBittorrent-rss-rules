# ADR 001: Local Web App with FastAPI

## Context

The project needs a maintainable local UI with server-side HTML pages, form handling, and HTTP integrations.

## Decision

Use FastAPI with Jinja2 templates as the v0.1.0 application framework.

## Consequences

- Fast local iteration
- Straightforward form and JSON route support
- Python-native path fits the current workspace and tooling

## Alternatives considered

- Desktop-first framework
- Notebook-driven UI
- Separate frontend SPA plus API

