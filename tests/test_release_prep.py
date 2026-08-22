from __future__ import annotations

from pathlib import Path

import pytest

from scripts import release_prep


def _seed_release_tree(root: Path) -> dict[str, str]:
    (root / "app").mkdir()
    (root / "QbRssRulesDesktop" / "Views").mkdir(parents=True)
    (root / "tests").mkdir()
    files = {
        "pyproject.toml": '[project]\nversion = "0.9.0"\n',
        "app/main.py": 'app = FastAPI(\n    version="0.9.0",\n)\n',
        "QbRssRulesDesktop/Views/MainPage.xaml.cs": (
            'private const string RequiredDesktopBackendAppVersion = "0.9.0";\n'
        ),
        "tests/test_routes.py": (
            'def test_health_endpoint(app_client) -> None:\n'
            '    assert payload["app_version"] == "0.9.0"\n'
        ),
        "CHANGELOG.md": "# Changelog\n\n## [Unreleased]\n\n- No entries yet.\n",
    }
    for relative_path, text in files.items():
        (root / relative_path).write_text(text, encoding="utf-8")
    return files


def test_release_prep_rejects_empty_changelog_before_any_version_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_files = _seed_release_tree(tmp_path)
    monkeypatch.setattr(
        release_prep,
        "repository_root_from_script_path",
        lambda _script_path: tmp_path,
    )

    with pytest.raises(RuntimeError, match=r"\[Unreleased\] has no release notes"):
        release_prep.main(["patch", "--date", "2026-08-22", "--apply"])

    for relative_path, original_text in original_files.items():
        assert (tmp_path / relative_path).read_text(encoding="utf-8") == original_text
