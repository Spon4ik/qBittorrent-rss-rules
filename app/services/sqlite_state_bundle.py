from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_BUNDLE_VERSION = 1
_SIDECAR_SUFFIXES = ("", "-wal", "-shm", "-journal")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _family(path: Path) -> dict[str, Path]:
    return {
        suffix: Path(str(path) + suffix)
        for suffix in _SIDECAR_SUFFIXES
        if Path(str(path) + suffix).exists()
    }


def _fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _source_snapshot(path: Path) -> dict[str, dict[str, object]]:
    return {suffix: _fingerprint(item) for suffix, item in _family(path).items()}


def _default_bundle_dir(source: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return source.parent / "recovery" / f"rollback-{stamp}"


def create_bundle(source: Path, bundle_dir: Path | None = None) -> dict[str, object]:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination = (bundle_dir or _default_bundle_dir(source)).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    before = _source_snapshot(source)
    if "" not in before:
        raise FileNotFoundError(source)

    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=str(destination.parent))
    )
    try:
        files: list[dict[str, object]] = []
        for suffix, item in _family(source).items():
            target = staging / f"database{suffix}"
            shutil.copy2(item, target)
            files.append(
                {
                    "suffix": suffix,
                    "name": target.name,
                    "size": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )

        after = _source_snapshot(source)
        if before != after:
            raise RuntimeError("SQLite file family changed while the rollback bundle was copied")

        for entry in files:
            suffix = str(entry["suffix"])
            original = Path(str(source) + suffix)
            if _sha256(original) != entry["sha256"]:
                raise RuntimeError(f"SQLite source changed while hashing suffix {suffix!r}")

        manifest = {
            "version": _BUNDLE_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "source_name": source.name,
            "files": files,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    verification = verify_bundle(destination)
    return {
        "status": "verified",
        "action": "backup",
        "source": str(source),
        "bundle": str(destination),
        "files": verification["files"],
    }


def _load_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != _BUNDLE_VERSION:
        raise ValueError("Unsupported or malformed SQLite rollback manifest")
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("SQLite rollback manifest contains no files")
    return raw


def verify_bundle(bundle_dir: Path) -> dict[str, object]:
    bundle_dir = bundle_dir.resolve()
    manifest = _load_manifest(bundle_dir)
    verified: list[dict[str, object]] = []
    suffixes: set[str] = set()
    for raw_entry in manifest["files"]:
        if not isinstance(raw_entry, dict):
            raise ValueError("Malformed rollback file entry")
        suffix = str(raw_entry.get("suffix", ""))
        if suffix not in _SIDECAR_SUFFIXES or suffix in suffixes:
            raise ValueError(f"Unexpected or duplicate SQLite suffix: {suffix!r}")
        suffixes.add(suffix)
        name = str(raw_entry.get("name", ""))
        path = bundle_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_size = int(raw_entry.get("size", -1))
        expected_hash = str(raw_entry.get("sha256", ""))
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != expected_size or actual_hash != expected_hash:
            raise RuntimeError(f"Rollback bundle verification failed for {name}")
        verified.append(
            {
                "suffix": suffix,
                "size": actual_size,
                "sha256": actual_hash,
            }
        )
    if "" not in suffixes:
        raise ValueError("Rollback bundle does not contain the main SQLite database")
    return {
        "status": "verified",
        "action": "verify",
        "bundle": str(bundle_dir),
        "files": verified,
    }


def restore_bundle(bundle_dir: Path, target: Path) -> dict[str, object]:
    bundle_dir = bundle_dir.resolve()
    target = target.resolve()
    verification = verify_bundle(bundle_dir)
    manifest = _load_manifest(bundle_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    guard = Path(tempfile.mkdtemp(prefix=f".{target.name}-pre-restore-", dir=str(target.parent)))
    staged: list[Path] = []
    moved: dict[str, Path] = {}
    try:
        for suffix, current in _family(target).items():
            guarded = guard / f"database{suffix}"
            os.replace(current, guarded)
            moved[suffix] = guarded

        for raw_entry in manifest["files"]:
            suffix = str(raw_entry["suffix"])
            source = bundle_dir / str(raw_entry["name"])
            staged_path = target.parent / f".{target.name}{suffix}.restore.tmp"
            if staged_path.exists():
                staged_path.unlink()
            shutil.copy2(source, staged_path)
            if _sha256(staged_path) != str(raw_entry["sha256"]):
                raise RuntimeError(f"Staged restore verification failed for suffix {suffix!r}")
            staged.append(staged_path)

        for raw_entry in manifest["files"]:
            suffix = str(raw_entry["suffix"])
            staged_path = target.parent / f".{target.name}{suffix}.restore.tmp"
            os.replace(staged_path, Path(str(target) + suffix))

        restored = _family(target)
        expected_suffixes = {str(entry["suffix"]) for entry in manifest["files"]}
        if set(restored) != expected_suffixes:
            raise RuntimeError("Restored SQLite file family does not match the rollback bundle")
        for raw_entry in manifest["files"]:
            suffix = str(raw_entry["suffix"])
            if _sha256(restored[suffix]) != str(raw_entry["sha256"]):
                raise RuntimeError(f"Restored SQLite verification failed for suffix {suffix!r}")
    except Exception:
        for staged_path in staged:
            staged_path.unlink(missing_ok=True)
        for item in _family(target).values():
            item.unlink(missing_ok=True)
        for suffix, guarded in moved.items():
            os.replace(guarded, Path(str(target) + suffix))
        shutil.rmtree(guard, ignore_errors=True)
        raise

    shutil.rmtree(guard, ignore_errors=True)
    return {
        "status": "restored",
        "action": "restore",
        "bundle": str(bundle_dir),
        "target": str(target),
        "files": verification["files"],
    }


def _print_report(report: dict[str, object], output: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, verify, and restore SQLite rollback bundles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("database", type=Path)
    backup.add_argument("--bundle", type=Path)
    backup.add_argument("--output", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--output", type=Path)

    restore = subparsers.add_parser("restore")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("database", type=Path)
    restore.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "backup":
        report = create_bundle(args.database, args.bundle)
    elif args.command == "verify":
        report = verify_bundle(args.bundle)
    else:
        report = restore_bundle(args.bundle, args.database)
    _print_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
