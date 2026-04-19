from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.release_versioning import (
    VersionParts,
    apply_version_bump,
    current_version,
    ensure_changelog_entry,
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
def test_ensure_changelog_entry_scaffolds_release_heading(tmp_path: Path) -> None:
    _seed_release_files(tmp_path)

    changed = ensure_changelog_entry(
        tmp_path,
        new_version="0.9.1",
        release_date=date(2026, 4, 17),
    )

    assert changed is True
    text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in text
    assert "## [0.9.1] - 2026-04-17" in text
    assert "- Release prep in progress." in text
