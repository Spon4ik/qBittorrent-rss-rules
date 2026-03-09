# Testing

## Test pyramid

The project uses a service-heavy architecture, so the test suite is weighted toward unit and integration tests:

- unit tests for rule generation, parsing, and helper logic
- integration-style tests for qBittorrent and metadata clients using mocked HTTP transports
- route tests for core HTML form flows and health checks

## Fixture strategy

- `tests/fixtures/qb_rules_export.json` mirrors the real qBittorrent export shape
- tests use a temporary SQLite database per test case
- environment variables are isolated through pytest monkeypatching

## Test logs

- Prefer `scripts/test.sh` on bash or `scripts/test.bat` on Windows `cmd.exe` when you want a reproducible artifact after each run.
- `scripts/test.sh` now prefers repo-local interpreters (`.venv/bin/python`, then `.venv-linux/bin/python`) before system Python and defaults to `--capture=sys` unless a capture arg is explicitly passed.
- Each wrapper overwrites two repo-local files on every invocation:
- `logs/tests/pytest-last.log` for the readable console transcript
- `logs/tests/pytest-last.xml` for structured JUnit results
- Pass normal `pytest` arguments through the wrapper, such as `scripts/test.bat tests\test_routes.py`.
- For Linux/WSL-native `python3 -m pytest` bootstrap and resume flow, use `docs/native-python-pytest.md`.

## Critical coverage areas

High-confidence coverage is required for:

- `app/services/rule_builder.py`
- `app/services/importer.py`
- `app/services/qbittorrent.py`
- `app/services/sync.py`

Minimum behavior expectations:

- import ignores runtime-only fields
- quality profiles generate stable patterns
- qBittorrent login and request failures surface cleanly
- local rule saves survive remote sync failures

## Mocking strategy

- Use `httpx.MockTransport` for HTTP client tests
- Avoid real network calls in automated tests
- Prefer deterministic payload fixtures over ad hoc inline blobs for importer tests

## Manual QA checklist

- Start the app and load `/`
- Save qBittorrent settings and verify connection test succeeds
- Save metadata settings and verify OMDb lookup test succeeds
- Import an exported qBittorrent rules JSON file
- Create a new series rule and confirm it appears in qBittorrent
- Create a new movie rule and confirm the movie category template is used
- Break qBittorrent connectivity and confirm local saves still persist while sync reports an error
- Edit and delete an imported rule
