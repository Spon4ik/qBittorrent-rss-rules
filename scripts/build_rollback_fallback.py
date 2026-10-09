"""Build and verify the owner-approved source-rebuilt production rollback image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.production_promotion import compose_config_digest  # noqa: E402
from scripts.promote_production import (  # noqa: E402
    FALLBACK_SOURCE_SHA,
    FALLBACK_SOURCE_TAG,
)


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 900) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed with exit code {result.returncode}")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_database(source: Path, target: Path) -> int:
    source_db = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_db = sqlite3.connect(target)
    try:
        source_db.backup(target_db)
        integrity = target_db.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError("Private scratch SQLite integrity check failed")
        count = int(target_db.execute("SELECT COUNT(*) FROM rules").fetchone()[0])
        if count < 1:
            raise ValueError("Private scratch database contains no rules")
        return count
    finally:
        target_db.close()
        source_db.close()


def _health(port: int) -> dict[str, Any]:
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("Fallback image returned an invalid health payload")
            if payload.get("status") != "ok":
                raise ValueError("Fallback image health/database readiness check failed")
            return payload
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def build_fallback(
    *, repository_root: Path, compose_file: Path, env_file: Path, scratch_source: Path,
    private_root: Path, docker: str,
) -> dict[str, Any]:
    os.environ["DOCKER_CONFIG"] = str(Path.home() / ".docker")
    config = json.loads(
        _run(
            [
                docker,
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(compose_file),
                "config",
                "--format",
                "json",
            ]
        )
    )
    service = config["services"]["qb-rss-rules"]
    build = service.get("build", {})
    if build.get("dockerfile") != "Dockerfile" or build.get("args") or build.get("target"):
        raise ValueError("Production Compose build inputs exceed the verified fallback builder contract")
    private_contract = private_root / "compose-contract.json"
    private_key = private_root / "compose-contract.key"
    if not private_contract.is_file():
        raise ValueError("Captured private Compose contract is missing")
    if not private_key.is_file() or len(private_key.read_bytes()) != 32:
        raise ValueError("Captured private Compose contract key is missing or invalid")
    expected_contract = json.loads(private_contract.read_text(encoding="utf-8"))
    compose_sha = compose_config_digest(config, service="qb-rss-rules", key=private_key.read_bytes())
    if not isinstance(expected_contract, dict) or expected_contract.get("compose_hmac") != compose_sha:
        raise ValueError("Private Compose contract does not match the recorded production build contract")

    private_root.mkdir(parents=True, exist_ok=True)
    rollback_dir = private_root / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = rollback_dir / "v1.4.31-source-fallback-verified.json"

    with tempfile.TemporaryDirectory(prefix="qbrss-v1.4.31-fallback-") as temp_name:
        temp = Path(temp_name)
        source_checkout = temp / "source"
        _run(["git", "clone", "--no-checkout", str(repository_root), str(source_checkout)], timeout=180)
        _run(["git", "-C", str(source_checkout), "checkout", "--detach", FALLBACK_SOURCE_SHA], timeout=180)
        resolved = _run(["git", "-C", str(source_checkout), "rev-parse", "HEAD"])
        if resolved != FALLBACK_SOURCE_SHA:
            raise ValueError("Fallback source checkout does not match protected v1.4.31 SHA")
        project = json.loads(
            _run(
                [
                    "python",
                    "-c",
                    "import json,tomllib;print(json.dumps(tomllib.load(open('pyproject.toml','rb'))['project']['version']))",
                ],
                cwd=source_checkout,
            )
        )
        if project != "1.4.31":
            raise ValueError("Fallback source project version is not v1.4.31")

        image_tag = "qbrss-v1.4.31-source-fallback:verified"
        _run(
            [
                docker,
                "build",
                "--tag",
                image_tag,
                "--file",
                str(source_checkout / "Dockerfile"),
                str(source_checkout),
            ],
            timeout=1800,
        )
        image_id = _run([docker, "image", "inspect", "--format", "{{.Id}}", image_tag])

        scratch = temp / "scratch.sqlite3"
        expected_rules = _copy_database(scratch_source, scratch)
        port = 18743
        container = f"qbrss-v1.4.31-fallback-check-{time.time_ns()}"
        _run(
            [
                docker,
                "create",
                "--name",
                container,
                "--publish",
                f"127.0.0.1:{port}:8000",
                "--volume",
                f"{scratch}:/app/data/qb_rules.db",
                "--env",
                "QB_RULES_APP_ENV=docker",
                "--env",
                "QB_RULES_SYNC_RULES_ON_STARTUP=false",
                "--env",
                "QB_RULES_ENABLE_RULE_FETCH_SCHEDULER=false",
                "--env",
                "QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER=false",
                "--env",
                "QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER=false",
                "--env",
                "QB_RULES_ENABLE_DOWNLOAD_ACCELERATION_SCHEDULER=false",
                image_id,
            ]
        )
        try:
            _run([docker, "start", container])
            health = _health(port)
            if health.get("app_version") != "1.4.31":
                raise ValueError("Fallback image did not report app version v1.4.31")
            db = sqlite3.connect(f"file:{scratch}?mode=ro", uri=True)
            try:
                integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
                observed_rules = int(db.execute("SELECT COUNT(*) FROM rules").fetchone()[0])
            finally:
                db.close()
            if integrity != "ok" or observed_rules != expected_rules:
                raise ValueError("Fallback container changed or failed to read the private scratch database")
        finally:
            _run([docker, "stop", "--time", "10", container], timeout=30)
            _run([docker, "rm", container], timeout=30)

        evidence = {
            "schema_version": 1,
            "source_tag": FALLBACK_SOURCE_TAG,
            "source_sha": FALLBACK_SOURCE_SHA,
            "image_tag": image_tag,
            "image_id": image_id,
            "compose_sha256": compose_sha,
            "dockerfile_sha256": _sha256(source_checkout / "Dockerfile"),
            "scratch_database_integrity": integrity,
            "scratch_database_rule_count": observed_rules,
            "container_health_check": "passed",
            "scratch_source_sha256": _sha256(scratch_source),
            "validated_app_version": health["app_version"],
            "guarantee": "source/version lineage only; not byte-identical to missing production image",
        }
        if manifest_path.exists():
            existing_evidence = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing_evidence == evidence:
                return evidence
            raise ValueError("A different verified source fallback exists; refusing to overwrite it")
        temporary_manifest = manifest_path.with_suffix(".json.tmp")
        temporary_manifest.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary_manifest.replace(manifest_path)
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--scratch-source", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    args = parser.parse_args()
    try:
        evidence = build_fallback(
            repository_root=args.repository_root,
            compose_file=args.compose_file,
            env_file=args.env_file,
            scratch_source=args.scratch_source,
            private_root=args.private_root,
            docker=args.docker,
        )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Rollback fallback verification stopped: {exc}\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
