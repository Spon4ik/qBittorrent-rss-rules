# GitHub CI adoption

## Status and goal

**Status: COMPLETE.** Adopt the repository's maintained local validation into
GitHub Actions so every pull request and push to `main` runs the same checks on
clean workers. Keep CI separate from Docker deployment and release publication.

## Runner decision

Use standard GitHub-hosted Windows and Ubuntu runners. This repository is public;
GitHub documents standard hosted runners for public repositories as free and
unlimited, so this design does not consume billable Actions minutes. Windows is
included to match the maintainer environment and build the WinUI shell; Ubuntu
matches the Linux container target and qBittorrent Docker integration workflow.

Do not route arbitrary public pull-request code to the persistent shared runner
pool. Self-hosted adoption remains optional and requires a separately reviewed
trust boundary, repository/workflow access, and demonstrated hosted-runner need.

## CI lanes

- `backend-checks`: install `.[dev]`, then run `scripts/check.bat` on Windows and
  `scripts/check.sh` on Ubuntu. These run Ruff, mypy, and the full pytest suite.
- `browser-ui`: install Chromium and run `scripts/browser_qa.bat --suite ui` on
  Windows.
- `desktop-build`: restore and build the x64 WinUI application on Windows.
- `required`: aggregate all lane results and fail if any lane fails, is cancelled,
  or is skipped unexpectedly.
- Keep the real qBittorrent web-seed API integration as its own focused workflow.

Ruff excludes `.agents`, which contains vendored skill sources rather than project
code. Their lint findings must not break application CI, and vendored files are not
rewritten by repository checks.

The aggregate delegates its result check to `scripts/ci_required_gate.py`. Its
regression tests feed every required lane `failure`, `cancelled`, and `skipped`,
plus a missing result, and assert that each blocks the gate. The workflow invokes
the same helper with GitHub's `needs.<job>.result` values. Both workflows use only
read-only `GITHUB_TOKEN` permissions; PR workflows do not reference secrets or use
privileged `pull_request_target`. Third-party actions in both workflows are pinned
to reviewed commit SHAs.

## Acceptance evidence

The first CI run exposed backend failures tracked by
[issue #50](https://github.com/Spon4ik/qBittorrent-rss-rules/issues/50), plus two
test races on the first main run. PR #52 added the full workflow and taxonomy
repair; PR #53 stabilized startup-session coverage and qBittorrent's eventual
torrent-info readback. Both PR heads and the exact resulting main commit passed.

- PR #52 head `9f9b6fa4`: CI run `36208838978` and integration run
  `36208838975` passed.
- PR #53 head `e63ec9ad`: CI run `36209537199` and integration run
  `36209537313` passed.
- Exact main commit `c7cb4d5ffe93310251cdbbb5680d3dc7cce2ee4e`: CI run
  `36209791955` and integration run `36209791977` passed.
- Exact main commit `b49f937b92aad3c47bf029ee14b11c7c2f80ab98`: CI run
  `36210768660` passed Ubuntu/Windows backend checks, Browser UI, WinUI build, and
  `required`; integration run `36210768675` passed. Ruleset `24023362` requires
  contexts `required` and `real-qbittorrent-webseed-api` from Actions integration
  `15368`; repository merge settings allow squash only.
- Protected-main ruleset `24023362` now requires `required` and
  `real-qbittorrent-webseed-api`.

The fail-closed aggregate regression is covered by
`tests/test_ci_required_gate.py` and runs as part of the full backend suite. On
2026-09-26, the focused cases passed (`12 passed`), and `scripts/check.bat` passed
Ruff, mypy, and pytest (`597 passed, 0 failed, 0 errors, 1 skipped`). The actual
aggregate workflow invokes the tested helper with live lane results; GitHub
verification of this follow-up is pending its PR run.

The CI workflow validates code and UI; Docker deployment and release publication
remain separate delivery steps. Issue #50's v1.4.23 closeout passed the required
backend finalizer and deployed runtime-version check.

No application deployment, production runner access, release, or tag is part of
this CI change.
