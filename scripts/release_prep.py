from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.services.release_versioning import (
    VersionParts,
    apply_version_bump,
    current_version,
    ensure_changelog_entry,
    repository_root_from_script_path,
    suggested_release_branch,
    suggested_release_tag,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a patch/minor/major release by synchronizing repo version touchpoints.",
    )
    parser.add_argument(
        "bump",
        choices=("patch", "minor", "major"),
        help="Semantic version component to increment.",
    )
    parser.add_argument(
        "--date",
        dest="release_date",
        default=date.today().isoformat(),
        help="Release date to stamp in CHANGELOG.md (default: today).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the version updates to disk. Without this flag, the script is a dry run.",
    )
    parser.add_argument(
        "--no-changelog",
        action="store_true",
        help="Skip CHANGELOG.md scaffolding.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = repository_root_from_script_path(Path(__file__))
    detected_current_version = current_version(root)
    next_version = str(VersionParts.parse(detected_current_version).bump(args.bump))
    parsed_release_date = date.fromisoformat(args.release_date)

    changed_files: list[str] = []
    if args.apply:
        changed_files.extend(apply_version_bump(root, new_version=next_version))
        if not args.no_changelog and ensure_changelog_entry(
            root,
            new_version=next_version,
            release_date=parsed_release_date,
        ):
            changed_files.append("CHANGELOG.md")

    print(
        json.dumps(
            {
                "current_version": detected_current_version,
                "target_version": next_version,
                "release_date": parsed_release_date.isoformat(),
                "apply": bool(args.apply),
                "changed_files": changed_files,
                "suggested_branch": suggested_release_branch(next_version),
                "suggested_tag": suggested_release_tag(next_version),
                "suggested_pr_title": f"Prepare {suggested_release_tag(next_version)} release",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
