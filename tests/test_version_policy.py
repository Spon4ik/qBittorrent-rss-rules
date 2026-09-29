from __future__ import annotations

import pytest

from scripts.check_version_policy import (
    check_version_policy,
    is_deployable_change,
)


@pytest.mark.parametrize(
    "path",
    [
        "alembic/versions/001_new_column.py",
        "./.dockerignore",
        "alembic.ini",
        "app/services/stremio.py",
        "app/static/app.js",
        "Dockerfile",
        "QbRssRulesDesktop/Views/MainPage.xaml.cs",
        "pyproject.toml",
        "requirements-release.txt",
        "scripts/install_desktop_bundle.cmd",
        "scripts/install_desktop_bundle.ps1",
        "scripts/package_desktop_bundle.ps1",
    ],
)
def test_deployable_changes_require_an_app_version(path: str) -> None:
    assert is_deployable_change(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/plans/current-status.md",
        "tests/test_stremio.py",
        ".github/workflows/ci.yml",
        "scripts/update_docker.ps1",
    ],
)
def test_non_deployable_changes_use_the_commit_as_their_identity(path: str) -> None:
    assert not is_deployable_change(path)


def test_deployable_change_accepts_a_new_synchronized_patch_version() -> None:
    errors = check_version_policy(
        changed_paths=["app/services/stremio.py"],
        base_version="1.4.29",
        head_versions={
            "pyproject.toml": "1.4.30",
            "app/main.py": "1.4.30",
            "QbRssRulesDesktop/Views/MainPage.xaml.cs": "1.4.30",
            "tests/test_routes.py": "1.4.30",
        },
        changelog="## [Unreleased]\n\n## [1.4.30] - 2026-09-29\n\n- Fix playback and queue handling.\n",
    )

    assert errors == []


@pytest.mark.parametrize("head_version", ["1.4.29", "1.4.28"])
def test_deployable_change_requires_a_strictly_higher_version(head_version: str) -> None:
    errors = check_version_policy(
        changed_paths=["app/services/stremio.py"],
        base_version="1.4.29",
        head_versions={
            "pyproject.toml": head_version,
            "app/main.py": head_version,
            "QbRssRulesDesktop/Views/MainPage.xaml.cs": head_version,
            "tests/test_routes.py": head_version,
        },
        changelog="## [1.4.29] - 2026-09-29\n",
    )

    assert "version must be greater than base version 1.4.29" in " ".join(errors)


def test_deployable_change_rejects_touchpoint_drift_and_missing_changelog_entry() -> None:
    errors = check_version_policy(
        changed_paths=["app/main.py"],
        base_version="1.4.29",
        head_versions={
            "pyproject.toml": "1.4.30",
            "app/main.py": "1.4.30",
            "QbRssRulesDesktop/Views/MainPage.xaml.cs": "1.4.29",
            "tests/test_routes.py": "1.4.30",
        },
        changelog="## [Unreleased]\n",
    )

    joined = " ".join(errors)
    assert "version touchpoints disagree" in joined
    assert "CHANGELOG.md lacks release notes for 1.4.30" in joined


def test_deployable_change_rejects_placeholder_release_notes() -> None:
    errors = check_version_policy(
        changed_paths=["app/services/stremio.py"],
        base_version="1.4.29",
        head_versions={
            "pyproject.toml": "1.4.30",
            "app/main.py": "1.4.30",
            "QbRssRulesDesktop/Views/MainPage.xaml.cs": "1.4.30",
            "tests/test_routes.py": "1.4.30",
        },
        changelog=(
            "## [Unreleased]\n\n## [1.4.30] - 2026-09-29\n\n"
            "- Release prep in progress.\n"
        ),
    )

    assert "CHANGELOG.md lacks release notes for 1.4.30" in " ".join(errors)


def test_docs_and_tests_do_not_require_a_release_bump() -> None:
    errors = check_version_policy(
        changed_paths=["docs/plans/current-status.md", "tests/test_version_policy.py"],
        base_version="1.4.29",
        head_versions={},
        changelog="## [Unreleased]\n",
    )

    assert errors == []
