"""Enforce a synchronized SemVer increment for deployable application changes."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence

DEPLOYABLE_PREFIXES = ("alembic/", "app/", "qbrssrulesdesktop/")
DEPLOYABLE_FILES = {
    ".dockerignore",
    "alembic.ini",
    "dockerfile",
    "pyproject.toml",
    "requirements-release.txt",
    "scripts/install_desktop_bundle.cmd",
    "scripts/install_desktop_bundle.ps1",
    "scripts/package_desktop_bundle.ps1",
}
SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
VERSION_TOUCHPOINTS = (
    "pyproject.toml",
    "app/main.py",
    "QbRssRulesDesktop/Views/MainPage.xaml.cs",
    "tests/test_routes.py",
)
VERSION_PATTERNS = {
    "app/main.py": re.compile(r'(?m)^\s*version="([^\"]+)"'),
    "QbRssRulesDesktop/Views/MainPage.xaml.cs": re.compile(
        r'(?m)^\s*private const string RequiredDesktopBackendAppVersion = "([^\"]+)";'
    ),
    "tests/test_routes.py": re.compile(
        r'(?m)^\s*assert payload\["app_version"\] == "([^\"]+)"$'
    ),
}


def is_deployable_change(path: str) -> bool:
    """Return whether a changed path contributes to the shipped app or package."""
    normalized = str(path).replace("\\", "/").casefold()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized in DEPLOYABLE_FILES or normalized.startswith(DEPLOYABLE_PREFIXES)


def check_version_policy(
    *,
    changed_paths: Sequence[str],
    base_version: str,
    head_versions: Mapping[str, str],
    changelog: str,
) -> list[str]:
    """Return deterministic policy failures for one base-to-head change."""
    deployable_paths = [path for path in changed_paths if is_deployable_change(path)]
    if not deployable_paths:
        return []

    errors: list[str] = []
    try:
        base_parts = _parse_semver(base_version)
        project_parts = _parse_semver(head_versions.get("pyproject.toml", ""))
    except ValueError as exc:
        return [str(exc)]

    if project_parts <= base_parts:
        errors.append(f"version must be greater than base version {base_version}")

    missing_touchpoints = [path for path in VERSION_TOUCHPOINTS if path not in head_versions]
    if missing_touchpoints:
        errors.append("missing version touchpoints: " + ", ".join(missing_touchpoints))
    else:
        versions = {head_versions[path] for path in VERSION_TOUCHPOINTS}
        if versions != {head_versions["pyproject.toml"]}:
            errors.append("version touchpoints disagree")

    new_version = head_versions.get("pyproject.toml", "")
    if new_version and not _has_release_notes(changelog, new_version):
        errors.append(f"CHANGELOG.md lacks release notes for {new_version}")

    if errors:
        errors.insert(0, "Deployable changes: " + ", ".join(sorted(deployable_paths)))
    return errors


def _parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_PATTERN.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError(f"Unsupported semantic version: {value!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def _has_release_notes(changelog: str, version: str) -> bool:
    lines = changelog.splitlines()
    heading_pattern = re.compile(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$"
    )
    heading_index = next(
        (index for index, line in enumerate(lines) if heading_pattern.fullmatch(line)),
        None,
    )
    if heading_index is None:
        return False
    next_heading_index = next(
        (
            index
            for index in range(heading_index + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    notes = [line.strip() for line in lines[heading_index + 1 : next_heading_index]]
    return any(line and line != "- Release prep in progress." for line in notes)


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _version_at_ref(ref: str, path: str) -> str:
    content = _git("show", f"{ref}:{path}")
    if path == "pyproject.toml":
        project = tomllib.loads(content).get("project", {})
        return str(project.get("version") or "")
    pattern = VERSION_PATTERNS[path]
    match = pattern.search(content)
    return match.group(1) if match else ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", default=os.environ.get("BASE_SHA"))
    parser.add_argument("--head-sha", default=os.environ.get("HEAD_SHA"))
    args = parser.parse_args(argv)

    try:
        head_sha = _git("rev-parse", args.head_sha or "HEAD").strip()
        base_ref = args.base_sha or f"{head_sha}^"
        base_sha = _git("rev-parse", base_ref).strip()
        changed_paths = _git(
            "diff", "--name-only", "--diff-filter=ACMR", base_sha, head_sha
        ).splitlines()
        base_version = _version_at_ref(base_sha, "pyproject.toml")
        head_versions = {
            path: _version_at_ref(head_sha, path) for path in VERSION_TOUCHPOINTS
        }
        changelog = _git("show", f"{head_sha}:CHANGELOG.md")
    except (subprocess.CalledProcessError, KeyError, tomllib.TOMLDecodeError) as exc:
        detail = getattr(exc, "stderr", "")
        print(f"Unable to evaluate version policy: {detail or exc}", file=sys.stderr)
        return 2

    errors = check_version_policy(
        changed_paths=changed_paths,
        base_version=base_version,
        head_versions=head_versions,
        changelog=changelog,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    deployable_paths = [path for path in changed_paths if is_deployable_change(path)]
    if deployable_paths:
        print(
            f"Version policy passed: {head_versions['pyproject.toml']} covers "
            f"{len(deployable_paths)} deployable path(s)."
        )
    else:
        print(
            f"Version policy passed: no deployable app change; commit {head_sha[:12]} "
            "is the source identity."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
