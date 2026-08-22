from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SEMVER_RE = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")
UNRELEASED_HEADER = "## [Unreleased]"
EMPTY_UNRELEASED_MARKER = "- No entries yet."
RELEASE_HEADER_RE = re.compile(r"(?m)^## \[(?!Unreleased\])[^\]]+\](?: - .+)?$")


@dataclass(frozen=True, slots=True)
class VersionParts:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> VersionParts:
        cleaned = str(value or "").strip()
        match = SEMVER_RE.fullmatch(cleaned)
        if not match:
            raise ValueError(f"Unsupported semantic version: {value!r}")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
        )

    def bump(self, part: str) -> VersionParts:
        normalized = str(part or "").strip().lower()
        if normalized == "patch":
            return VersionParts(self.major, self.minor, self.patch + 1)
        if normalized == "minor":
            return VersionParts(self.major, self.minor + 1, 0)
        if normalized == "major":
            return VersionParts(self.major + 1, 0, 0)
        raise ValueError(f"Unsupported bump kind: {part!r}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class VersionTouchpoint:
    relative_path: str
    pattern: re.Pattern[str]
    replacement_template: str

    def apply(self, root: Path, *, old_version: str, new_version: str) -> bool:
        path = root / self.relative_path
        original_text = path.read_text(encoding="utf-8")
        expected_old = self.pattern.search(original_text)
        if expected_old is None:
            raise RuntimeError(
                f"Could not find version touchpoint {old_version!r} in {self.relative_path}."
            )
        updated_text, replacements = self.pattern.subn(
            self.replacement_template.format(version=new_version),
            original_text,
            count=1,
        )
        if replacements != 1:
            raise RuntimeError(f"Unexpected replacement count in {self.relative_path}: {replacements}")
        if updated_text == original_text:
            return False
        path.write_text(updated_text, encoding="utf-8")
        return True


VERSION_TOUCHPOINTS: tuple[VersionTouchpoint, ...] = (
    VersionTouchpoint(
        relative_path="pyproject.toml",
        pattern=re.compile(r'(?m)^version = "([^"]+)"$'),
        replacement_template='version = "{version}"',
    ),
    VersionTouchpoint(
        relative_path="app/main.py",
        pattern=re.compile(r'(?m)^(?P<prefix>\s*version=")(?P<version>[^"]+)(?P<suffix>",?)$'),
        replacement_template='\\g<prefix>{version}\\g<suffix>',
    ),
    VersionTouchpoint(
        relative_path="QbRssRulesDesktop/Views/MainPage.xaml.cs",
        pattern=re.compile(
            r'(?m)^(?P<prefix>\s*private const string RequiredDesktopBackendAppVersion = ")(?P<version>[^"]+)(";)'
        ),
        replacement_template='\\g<prefix>{version}\\3',
    ),
    VersionTouchpoint(
        relative_path="tests/test_routes.py",
        pattern=re.compile(
            r'(?m)^(\s*assert payload\["app_version"\] == ")([^"]+)(")$'
        ),
        replacement_template='\\g<1>{version}\\g<3>',
    ),
)


def repository_root_from_script_path(script_path: Path) -> Path:
    return script_path.resolve().parent.parent


def current_version(root: Path) -> str:
    pyproject_path = root / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"$', text)
    if match is None:
        raise RuntimeError("Could not detect the current version from pyproject.toml.")
    return match.group(1)


def apply_version_bump(root: Path, *, new_version: str) -> list[str]:
    old_version = current_version(root)
    changed_files: list[str] = []
    for touchpoint in VERSION_TOUCHPOINTS:
        if touchpoint.apply(root, old_version=old_version, new_version=new_version):
            changed_files.append(touchpoint.relative_path)
    return changed_files


def _unreleased_bounds(changelog_text: str) -> tuple[int, int, int]:
    unreleased_index = changelog_text.find(UNRELEASED_HEADER)
    if unreleased_index < 0:
        raise RuntimeError("CHANGELOG.md is missing the [Unreleased] section.")

    content_start = unreleased_index + len(UNRELEASED_HEADER)
    next_release = RELEASE_HEADER_RE.search(changelog_text, content_start)
    content_end = next_release.start() if next_release is not None else len(changelog_text)
    return unreleased_index, content_start, content_end


def validate_unreleased_changelog(root: Path) -> str:
    changelog_path = root / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")
    _unreleased_index, content_start, content_end = _unreleased_bounds(changelog_text)
    unreleased_notes = changelog_text[content_start:content_end].strip()
    if not unreleased_notes or unreleased_notes == EMPTY_UNRELEASED_MARKER:
        raise RuntimeError(
            "CHANGELOG.md [Unreleased] has no release notes. Add notable changes before "
            "release prep or pass --no-changelog only when intentionally bypassing it."
        )
    return unreleased_notes


def ensure_changelog_entry(root: Path, *, new_version: str, release_date: date) -> bool:
    changelog_path = root / "CHANGELOG.md"
    original_text = changelog_path.read_text(encoding="utf-8")
    version_header = f"## [{new_version}] - {release_date.isoformat()}"
    if version_header in original_text:
        return False

    unreleased_notes = validate_unreleased_changelog(root)
    unreleased_index, _content_start, content_end = _unreleased_bounds(original_text)
    replacement = (
        f"{UNRELEASED_HEADER}\n\n"
        f"{EMPTY_UNRELEASED_MARKER}\n\n"
        f"{version_header}\n\n"
        f"{unreleased_notes}\n\n"
    )
    updated_text = (
        original_text[:unreleased_index]
        + replacement
        + original_text[content_end:].lstrip("\n")
    )
    changelog_path.write_text(updated_text, encoding="utf-8")
    return True


def suggested_release_branch(version: str) -> str:
    return f"codex/release-v{version}"


def suggested_release_tag(version: str) -> str:
    return f"v{version}"
