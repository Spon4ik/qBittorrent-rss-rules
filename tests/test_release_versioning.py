from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.release_versioning import (
    VersionParts,
    apply_version_bump,
    current_version,
    ensure_changelog_entry,
    validate_unreleased_changelog,
)


def _seed_release_files(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "QbRssRulesDesktop" / "Views").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.9.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "app" / "main.py").write_text(
        'app = FastAPI(\n    version="0.9.0",\n)\n',
        encoding="utf-8",
    )
    (tmp_path / "QbRssRulesDesktop" / "Views" / "MainPage.xaml.cs").write_text(
        'private const string RequiredDesktopBackendAppVersion = "0.9.0";\n',
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_routes.py").write_text(
        'def test_health_endpoint(app_client) -> None:\n'
        '    assert payload["app_version"] == "0.9.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n- No entries yet.\n",
        encoding="utf-8",
    )


def test_version_parts_bump_patch_minor_major() -> None:
    version = VersionParts.parse("0.9.0")

    assert str(version.bump("patch")) == "0.9.1"
    assert str(version.bump("minor")) == "0.10.0"
    assert str(version.bump("major")) == "1.0.0"


def test_apply_version_bump_updates_all_touchpoints(tmp_path: Path) -> None:
    _seed_release_files(tmp_path)

    changed_files = apply_version_bump(tmp_path, new_version="0.9.1")

    assert changed_files == [
        "pyproject.toml",
        "app/main.py",
        "QbRssRulesDesktop/Views/MainPage.xaml.cs",
        "tests/test_routes.py",
    ]
    assert current_version(tmp_path) == "0.9.1"
    assert 'version="0.9.1"' in (tmp_path / "app" / "main.py").read_text(encoding="utf-8")
    assert '"0.9.1";' in (
        tmp_path / "QbRssRulesDesktop" / "Views" / "MainPage.xaml.cs"
    ).read_text(encoding="utf-8")
    assert 'assert payload["app_version"] == "0.9.1"' in (
        tmp_path / "tests" / "test_routes.py"
    ).read_text(encoding="utf-8")


def test_validate_unreleased_changelog_returns_real_notes(tmp_path: Path) -> None:
    _seed_release_files(tmp_path)
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- Deterministic runtime checks.\n",
        encoding="utf-8",
    )

    notes = validate_unreleased_changelog(tmp_path)

    assert notes == "### Added\n\n- Deterministic runtime checks."


def test_ensure_changelog_entry_promotes_unreleased_notes_intact(tmp_path: Path) -> None:
    _seed_release_files(tmp_path)
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Added\n\n"
        "- Deterministic runtime checks.\n\n"
        "### Fixed\n\n"
        "- Preserve release notes.\n\n"
        "## [0.9.0] - 2026-04-11\n\n"
        "- Previous release.\n",
        encoding="utf-8",
    )

    changed = ensure_changelog_entry(
        tmp_path,
        new_version="0.9.1",
        release_date=date(2026, 4, 17),
    )

    assert changed is True
    text = changelog_path.read_text(encoding="utf-8")
    assert (
        "## [Unreleased]\n\n"
        "- No entries yet.\n\n"
        "## [0.9.1] - 2026-04-17\n\n"
        "### Added\n\n"
        "- Deterministic runtime checks.\n\n"
        "### Fixed\n\n"
        "- Preserve release notes.\n\n"
        "## [0.9.0] - 2026-04-11"
    ) in text
    assert "Release prep in progress" not in text


def test_ensure_changelog_entry_refuses_empty_unreleased_notes(tmp_path: Path) -> None:
    _seed_release_files(tmp_path)

    with pytest.raises(RuntimeError, match=r"\[Unreleased\] has no release notes"):
        ensure_changelog_entry(
            tmp_path,
            new_version="0.9.1",
            release_date=date(2026, 4, 17),
        )
