"""Preflight contracts for a locally approved Windows production promotion."""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import json
import ntpath
import os
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

RELEASE_VERSION = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TAG_SHA = re.compile(r"^[0-9a-f]{40}$")
APPROVAL_MAX_AGE = timedelta(days=7)
APPROVAL_FUTURE_TOLERANCE = timedelta(minutes=5)
REQUIRED_MOUNT_TARGETS = {
    "/app/data": False,
    "/host/C/Users": True,
    "/host/C/ProgramData": True,
}


def parse_release_version(version: str) -> tuple[int, int, int]:
    match = RELEASE_VERSION.fullmatch(version)
    if match is None:
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH release version")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def validate_version_upgrade(target_version: str, current_version: str) -> None:
    target = parse_release_version(target_version if target_version.startswith("v") else f"v{target_version}")
    current = parse_release_version(current_version if current_version.startswith("v") else f"v{current_version}")
    if target <= current:
        raise ValueError("Promotion target must be newer than the running production version")


def validate_approval_manifest(
    manifest: dict[str, Any],
    *,
    repository: str,
    tag: str,
    commit_sha: str,
    approval_run_id: int,
    approver: str,
    now: datetime | None = None,
) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported approval manifest schema")
    expected = {
        "repository": repository,
        "tag": tag,
        "commit_sha": commit_sha,
        "approval_run_id": approval_run_id,
    }
    for field, expected_value in expected.items():
        if manifest.get(field) != expected_value:
            raise ValueError(f"Approval manifest {field} does not match the promotion request")
    manifest_approver = manifest.get("approved_by")
    if not isinstance(manifest_approver, str) or manifest_approver.casefold() != approver.casefold():
        raise ValueError("Approval manifest approved_by does not match the promotion request")
    if not TAG_SHA.fullmatch(str(manifest.get("commit_sha", ""))):
        raise ValueError("Approval manifest commit SHA is invalid")
    for field in ("release_url", "ci_run_url", "api_run_url", "approval_run_url"):
        if not isinstance(manifest.get(field), str) or not manifest[field].startswith(
            "https://github.com/"
        ):
            raise ValueError(f"Approval manifest {field} is invalid")
    for field in ("ci_run_id", "api_run_id"):
        if not isinstance(manifest.get(field), int) or manifest[field] <= 0:
            raise ValueError(f"Approval manifest {field} is invalid")
    try:
        approved_at = datetime.fromisoformat(str(manifest["approved_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Approval manifest timestamp is invalid") from exc
    if approved_at.tzinfo is None:
        raise ValueError("Approval manifest timestamp must include a timezone")
    current = now or datetime.now(UTC)
    age = current - approved_at.astimezone(UTC)
    if age < -APPROVAL_FUTURE_TOLERANCE:
        raise ValueError("Approval manifest timestamp is in the future")
    if age > APPROVAL_MAX_AGE:
        raise ValueError("Approval manifest has expired")


def validate_checkout_state(
    *,
    checkout_root: str,
    expected_root: str,
    head_sha: str,
    expected_sha: str,
    branch_name: str,
    clean: bool,
) -> None:
    if normalize_windows_path(checkout_root) != normalize_windows_path(expected_root):
        raise ValueError("Promotion must run from the stable deployment checkout")
    if head_sha != expected_sha:
        raise ValueError("Stable checkout HEAD does not match the approved release SHA")
    if branch_name:
        raise ValueError("Stable deployment checkout must be detached at the release tag")
    if not clean:
        raise ValueError("Stable deployment checkout must be clean")


def parse_remote_tag_sha(output: str, tag: str) -> str | None:
    refs: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2:
            refs[parts[1]] = parts[0]
    peeled = refs.get(f"refs/tags/{tag}^{{}}")
    sha = peeled or refs.get(f"refs/tags/{tag}")
    return sha if sha and TAG_SHA.fullmatch(sha) else None


def validate_audit_retry_evidence(
    record: dict[str, Any],
    deployment: dict[str, Any],
    *,
    running_version: str,
    running_image_id: str,
) -> None:
    if record.get("stage") not in {"health-verified", "audit-pending"}:
        raise ValueError("Local record is not awaiting an audit-only retry")
    if deployment.get("environment") != "production" or deployment.get("ref") != record.get(
        "commit_sha"
    ):
        raise ValueError("GitHub Deployment record does not match the local release evidence")
    if record.get("health_version") != running_version or record.get("target_version") != running_version:
        raise ValueError("Live production health no longer matches the verified promotion")
    if record.get("deployed_image_id") != running_image_id or not running_image_id.startswith(
        "sha256:"
    ):
        raise ValueError("Live production image no longer matches the verified promotion")
    if not TAG_SHA.fullmatch(str(record.get("commit_sha", ""))):
        raise ValueError("Local deployment record source SHA is invalid")


def normalize_windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(str(PureWindowsPath(value))))


def _mounts_for_service(service_data: dict[str, Any]) -> list[dict[str, Any]]:
    volumes = service_data.get("volumes")
    if not isinstance(volumes, list):
        raise ValueError("Compose service has no resolved bind mounts")
    mounts: list[dict[str, Any]] = []
    for volume in volumes:
        if not isinstance(volume, dict) or volume.get("type") != "bind":
            raise ValueError("Compose service contains an unexpected non-bind mount")
        source = volume.get("source")
        target = volume.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("Compose bind mount is missing its resolved source or target")
        mounts.append(
            {
                "source": normalize_windows_path(source),
                "target": target,
                "read_only": bool(volume.get("read_only", False)),
            }
        )
    return mounts


def validate_compose_config(
    config: dict[str, Any],
    *,
    service: str,
    expected_context: str,
    expected_mounts: list[dict[str, Any]],
) -> None:
    services = config.get("services")
    service_data = services.get(service) if isinstance(services, dict) else None
    if not isinstance(service_data, dict):
        raise ValueError(f"Compose service {service} is missing")
    build = service_data.get("build")
    context = build.get("context") if isinstance(build, dict) else None
    if not isinstance(context, str) or normalize_windows_path(context) != normalize_windows_path(
        expected_context
    ):
        raise ValueError("Compose build context does not match the stable checkout")
    expected = [
        {
            "source": normalize_windows_path(str(mount["source"])),
            "target": str(mount["target"]),
            "read_only": bool(mount["read_only"]),
        }
        for mount in expected_mounts
    ]
    actual = _mounts_for_service(service_data)
    if sorted(actual, key=lambda item: str(item["target"])) != sorted(
        expected, key=lambda item: str(item["target"])
    ):
        raise ValueError("Compose bind mounts differ from the captured production contract")


def compose_config_digest(
    config: dict[str, Any], *, service: str, key: bytes
) -> str:
    """HMAC the resolved Compose contract without persisting any resolved secrets."""
    normalized = copy.deepcopy(config)
    services = normalized.get("services")
    service_data = services.get(service) if isinstance(services, dict) else None
    build = service_data.get("build") if isinstance(service_data, dict) else None
    if not isinstance(build, dict) or not isinstance(build.get("context"), str):
        raise ValueError("Compose service has no build context")
    build["context"] = "<stable-promotion-context>"
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def create_compose_contract(
    config: dict[str, Any],
    *,
    service: str,
    repository: str,
    compose_file: str,
    env_file: str,
    key: bytes,
    captured_at: str,
) -> dict[str, Any]:
    services = config.get("services")
    service_data = services.get(service) if isinstance(services, dict) else None
    if not isinstance(service_data, dict):
        raise ValueError(f"Compose service {service} is missing")
    build = service_data.get("build")
    context = build.get("context") if isinstance(build, dict) else None
    if not isinstance(context, str):
        raise ValueError("Compose service has no resolved build context")
    mounts = _mounts_for_service(service_data)
    if sorted((mount["target"], mount["read_only"]) for mount in mounts) != sorted(
        REQUIRED_MOUNT_TARGETS.items()
    ):
        raise ValueError("Current Compose mounts do not match the production path contract")
    database_mount = next(mount for mount in mounts if mount["target"] == "/app/data")
    if database_mount["source"] != normalize_windows_path(ntpath.join(context, "data")):
        raise ValueError("Current production database mount is not the active checkout data directory")
    contract = {
        "schema_version": 1,
        "repository": repository,
        "service": service,
        "compose_file": str(Path(compose_file).resolve()),
        "env_file": str(Path(env_file).resolve()),
        "captured_at": captured_at,
        "original_build_context": normalize_windows_path(context),
        "mounts": mounts,
        "compose_hmac": compose_config_digest(config, service=service, key=key),
    }
    contract["contract_hmac"] = _contract_signature(contract, key)
    return contract


def _contract_signature(contract: dict[str, Any], key: bytes) -> str:
    unsigned = {name: value for name, value in contract.items() if name != "contract_hmac"}
    payload = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def validate_compose_contract(
    contract: dict[str, Any],
    config: dict[str, Any],
    *,
    repository: str,
    compose_file: str,
    env_file: str,
    expected_context: str,
    key: bytes,
) -> None:
    signature = contract.get("contract_hmac")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _contract_signature(contract, key)
    ):
        raise ValueError("Private Compose contract is invalid or has been modified")
    expected_paths = {
        "repository": repository,
        "service": "qb-rss-rules",
        "compose_file": str(Path(compose_file).resolve()),
        "env_file": str(Path(env_file).resolve()),
    }
    for field, expected_value in expected_paths.items():
        if contract.get(field) != expected_value:
            raise ValueError(f"Private Compose contract {field} does not match this host")
    validate_compose_config(
        config,
        service="qb-rss-rules",
        expected_context=expected_context,
        expected_mounts=contract.get("mounts", []),
    )
    digest = compose_config_digest(config, service="qb-rss-rules", key=key)
    if not hmac.compare_digest(str(contract.get("compose_hmac", "")), digest):
        raise ValueError("Compose configuration differs from the captured contract")


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold a process-released exclusive lock on Windows or POSIX hosts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another production promotion currently holds the host lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = importlib.import_module("fcntl")
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def verify_sqlite_backup(source_path: Path, backup_path: Path) -> str:
    """Create an online SQLite backup, check integrity, restore it to scratch, and hash it."""
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise ValueError("Refusing to overwrite an existing production backup")
    try:
        source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            destination = sqlite3.connect(backup_path, timeout=30)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

        with closing(sqlite3.connect(backup_path, timeout=30)) as backup:
            integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("SQLite backup failed its integrity check")

        with tempfile.TemporaryDirectory(
            prefix="qbrss-restore-check-", dir=backup_path.parent
        ) as scratch_dir:
            restored_path = Path(scratch_dir) / "restored.sqlite3"
            with closing(sqlite3.connect(backup_path, timeout=30)) as backup:
                with closing(sqlite3.connect(restored_path, timeout=30)) as restored:
                    backup.backup(restored)
            with closing(sqlite3.connect(restored_path, timeout=30)) as restored:
                restored_integrity = restored.execute("PRAGMA integrity_check").fetchone()
            if not restored_integrity or restored_integrity[0] != "ok":
                raise ValueError("SQLite scratch restore failed its integrity check")
    except (OSError, sqlite3.Error, ValueError) as exc:
        backup_path.unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"SQLite backup or scratch restore failed: {exc.__class__.__name__}") from exc

    digest = hashlib.sha256()
    with backup_path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
