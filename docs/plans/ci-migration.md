# GitHub CI adoption

## Status and goal

**Status: IN PROGRESS.** Adopt the repository's maintained local validation into
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

## Acceptance and current blocker

The new workflow must pass on a pull request and on the exact resulting `main`
commit before `CI / required` is added to the main ruleset. Capture the workflow
run and tested SHA for both platforms and the Windows UI/desktop lanes. Never merge
or treat a red full-suite run as success.

The first full CI run exposed seven failures tracked by
[issue #50](https://github.com/Spon4ik/qBittorrent-rss-rules/issues/50). The
candidate repair restores the missing `240p`/`400p` packaged taxonomy entries,
replaces the startup timing threshold with an event-coordinated regression, and
isolates pytest from persistent checkout runtime data. Its local full gate passed;
the updated Windows and Ubuntu Actions runs are the acceptance proof still
pending. Keep this draft until both platform lanes, browser UI, desktop build, and
the aggregate job pass on the same PR head.

No application deployment, production runner access, release, or tag is part of
this CI change.
