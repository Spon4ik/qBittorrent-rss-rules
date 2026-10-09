from __future__ import annotations

import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import scripts.promote_production as promotion_cli
from scripts.production_promotion import (
    compose_config_digest,
    create_compose_contract,
    exclusive_file_lock,
    parse_release_version,
    parse_remote_tag_sha,
    validate_approval_manifest,
    validate_audit_retry_evidence,
    validate_checkout_state,
    validate_compose_config,
    validate_compose_contract,
    validate_version_upgrade,
    verify_sqlite_backup,
)

SHA = "a" * 40
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
REPOSITORY = "Spon4ik/qBittorrent-rss-rules"
STABLE_CHECKOUT = r"C:\Users\test\deployments\qBittorrent-rss-rules"


def _manifest(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "tag": "v1.4.25",
        "commit_sha": SHA,
        "release_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.4.25",
        "ci_run_id": 10,
        "ci_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/10",
        "api_run_id": 11,
        "api_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/11",
        "approval_run_id": 12,
        "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/12",
        "approved_by": "Spon4ik",
        "approved_at": NOW.isoformat(),
        **overrides,
    }


def test_finalizer_timeout_terminates_and_reaps_process_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events: list[object] = []

    class TimedOutProcess:
        pid = 321

        def wait(self, *, timeout: int) -> int:
            events.append(("wait", timeout))
            if timeout == 10:
                raise subprocess.TimeoutExpired("finalizer", timeout)
            return -9

    monkeypatch.setattr(promotion_cli.subprocess, "Popen", lambda *_args, **_kwargs: TimedOutProcess())
    monkeypatch.setattr(
        promotion_cli,
        "_terminate_process_tree",
        lambda pid: events.append(("terminate-tree", pid)),
    )
    with (tmp_path / "finalizer.log").open("w", encoding="utf-8") as log:
        with pytest.raises(RuntimeError, match="process tree terminated"):
            promotion_cli._run_finalizer(["cmd.exe"], tmp_path, log, timeout=10)

    assert events == [("wait", 10), ("terminate-tree", 321), ("wait", 30)]


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe batch invocation is Windows-specific")
def test_finalizer_command_runs_batch_file_from_checkout_with_argument(tmp_path: Path) -> None:
    finalizer = tmp_path / "Finalize-Backend.cmd"
    args_file = tmp_path / "received-args.txt"
    finalizer.write_text(
        f'@echo off\r\n> "{args_file}" echo %*\r\nexit /b 0\r\n',
        encoding="utf-8",
    )
    command = promotion_cli._finalizer_command(finalizer)

    with (tmp_path / "finalizer.log").open("w", encoding="utf-8") as log:
        result = promotion_cli._run_finalizer(command, tmp_path, log, timeout=10)

    assert result.returncode == 0
    assert args_file.read_text(encoding="utf-8").strip() == "--no-pause"
    assert command == ["cmd.exe", "/d", "/c", "call", finalizer.name, "--no-pause"]


@pytest.mark.skipif(os.name != "nt", reason="production storage ACLs are Windows-specific")
def test_secure_private_root_preserves_reopenable_lock_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "production.lock"
    backup_path = tmp_path / "backups" / "backup.sqlite3"

    promotion_cli.secure_private_root(tmp_path)
    with exclusive_file_lock(lock_path):
        backup_path.parent.mkdir()
        backup_path.write_bytes(b"private backup")

    promotion_cli.secure_private_root(tmp_path)
    with exclusive_file_lock(lock_path):
        pass
    assert backup_path.read_bytes() == b"private backup"


def test_finalizer_timeout_requires_cleanup_before_reporting_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class TimedOutProcess:
        pid = 654

        def wait(self, *, timeout: int) -> int:
            raise subprocess.TimeoutExpired("finalizer", timeout)

    monkeypatch.setattr(promotion_cli.subprocess, "Popen", lambda *_args, **_kwargs: TimedOutProcess())
    monkeypatch.setattr(
        promotion_cli,
        "_terminate_process_tree",
        lambda _pid: (_ for _ in ()).throw(
            promotion_cli.FinalizerCleanupUncertainError("taskkill failed")
        ),
    )
    with (tmp_path / "finalizer.log").open("w", encoding="utf-8") as log:
        with pytest.raises(promotion_cli.FinalizerCleanupUncertainError, match="taskkill failed"):
            promotion_cli._run_finalizer(["cmd.exe"], tmp_path, log, timeout=10)


def test_terminate_process_tree_uses_taskkill_tree_force(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs))
        or subprocess.CompletedProcess(args, 0, stdout="SUCCESS", stderr=""),
    )

    promotion_cli._terminate_process_tree(987)

    assert calls[0][0] == ["taskkill.exe", "/PID", "987", "/T", "/F"]
    assert calls[0][1]["timeout"] == 60


def test_terminate_process_tree_fails_closed_when_taskkill_does_not_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 128, stdout="", stderr="not found"),
    )

    with pytest.raises(promotion_cli.FinalizerCleanupUncertainError, match="not found"):
        promotion_cli._terminate_process_tree(987)


@pytest.mark.skipif(os.name != "nt", reason="taskkill process-tree behavior is Windows-specific")
def test_windows_finalizer_timeout_kills_real_descendant_process(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    launcher_code = (
        "import pathlib, subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )
    with (tmp_path / "finalizer-tree.log").open("w", encoding="utf-8") as log:
        with pytest.raises(RuntimeError, match="process tree terminated"):
            promotion_cli._run_finalizer(
                [sys.executable, "-c", launcher_code], tmp_path, log, timeout=2
            )

    child_pid = child_pid_path.read_text(encoding="utf-8")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        rows = list(csv.reader(result.stdout.splitlines()))
        if not any(len(row) > 1 and row[1] == child_pid for row in rows):
            return
        time.sleep(0.1)
    pytest.fail(f"Timed-out finalizer descendant process {child_pid} is still running")


def _compose_config(context: str = STABLE_CHECKOUT) -> dict[str, object]:
    return {
        "services": {
            "qb-rss-rules": {
                "build": {"context": context, "dockerfile": "Dockerfile"},
                "environment": {"APP_SECRET": "secret-value"},
                "volumes": [
                    {
                        "type": "bind",
                        "source": r"E:\GitHub\qBittorrent rss rules\data",
                        "target": "/app/data",
                        "read_only": False,
                    },
                    {
                        "type": "bind",
                        "source": r"C:\Users",
                        "target": "/host/C/Users",
                        "read_only": True,
                    },
                    {
                        "type": "bind",
                        "source": r"C:\ProgramData",
                        "target": "/host/C/ProgramData",
                        "read_only": True,
                    },
                ],
            }
        }
    }


def test_compose_contract_capture_allows_source_checkout_ahead_of_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path,
        compose_file=tmp_path / "docker-compose.yml",
        env_file=env_file,
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    config = _compose_config(r"E:\GitHub\qBittorrent rss rules")
    data_dir = tmp_path / "active-data"
    data_dir.mkdir()
    (data_dir / "qb_rules.db").write_bytes(b"test database")
    config["services"]["qb-rss-rules"]["volumes"][0]["source"] = str(data_dir)
    monkeypatch.setattr(manager, "_compose_config", lambda: config)
    monkeypatch.setattr(promotion_cli, "_read_health", lambda: {"app_version": "1.4.24"})

    manager.capture_compose_contract()

    assert manager.contract_file.is_file()
    assert manager.contract_key_file.is_file()

    missing_database_config = _compose_config(r"E:\GitHub\qBittorrent rss rules")
    missing_database_config["services"]["qb-rss-rules"]["volumes"][0]["source"] = str(
        tmp_path / "missing-data"
    )
    missing_paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path,
        compose_file=tmp_path / "docker-compose.yml",
        env_file=env_file,
        private_root=tmp_path / "private-missing",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    missing_manager = promotion_cli.PromotionManager(missing_paths)
    monkeypatch.setattr(missing_manager, "_compose_config", lambda: missing_database_config)
    with pytest.raises(RuntimeError, match="SQLite database is missing"):
        missing_manager.capture_compose_contract()


MOUNTS = [
    {
        "source": r"E:\GitHub\qBittorrent rss rules\data",
        "target": "/app/data",
        "read_only": False,
    },
    {"source": r"C:\Users", "target": "/host/C/Users", "read_only": True},
    {"source": r"C:\ProgramData", "target": "/host/C/ProgramData", "read_only": True},
]


def test_approval_manifest_must_match_requested_tag_sha_run_and_be_fresh() -> None:
    validate_approval_manifest(
        _manifest(),
        repository=REPOSITORY,
        tag="v1.4.25",
        commit_sha=SHA,
        approval_run_id=12,
        approver="Spon4ik",
        now=NOW,
    )

    for changed in (
        {"tag": "v1.4.24"},
        {"commit_sha": "b" * 40},
        {"approval_run_id": 13},
        {"repository": "attacker/repo"},
        {"approved_by": "someone-else"},
        {"approved_at": (NOW - timedelta(days=8)).isoformat()},
        {"approved_at": (NOW + timedelta(minutes=10)).isoformat()},
    ):
        with pytest.raises(ValueError):
            validate_approval_manifest(
                _manifest(**changed),
                repository=REPOSITORY,
                tag="v1.4.25",
                commit_sha=SHA,
                approval_run_id=12,
                approver="Spon4ik",
                now=NOW,
            )


def test_release_version_is_strict_semver_and_must_exceed_live_version() -> None:
    assert parse_release_version("v1.4.25") == (1, 4, 25)
    validate_version_upgrade("1.4.25", "1.4.24")

    for version in ("1.4.24", "1.4.23", "1.4.25-rc.1", "01.4.25", "latest"):
        with pytest.raises(ValueError):
            validate_version_upgrade(version, "1.4.24")


def test_release_checkout_must_be_clean_detached_exact_sha_at_stable_path() -> None:
    validate_checkout_state(
        checkout_root=STABLE_CHECKOUT,
        expected_root=STABLE_CHECKOUT,
        head_sha=SHA,
        expected_sha=SHA,
        branch_name="",
        clean=True,
    )

    for state in (
        {"checkout_root": r"E:\GitHub\qBittorrent rss rules", "clean": True, "branch_name": ""},
        {"checkout_root": STABLE_CHECKOUT, "clean": False, "branch_name": ""},
        {"checkout_root": STABLE_CHECKOUT, "clean": True, "branch_name": "main"},
        {"checkout_root": STABLE_CHECKOUT, "clean": True, "branch_name": "", "head_sha": "b" * 40},
    ):
        with pytest.raises(ValueError):
            validate_checkout_state(
                checkout_root=state["checkout_root"],
                expected_root=STABLE_CHECKOUT,
                head_sha=state.get("head_sha", SHA),
                expected_sha=SHA,
                branch_name=state["branch_name"],
                clean=state["clean"],
            )


def test_remote_tag_sha_peels_annotated_tags() -> None:
    annotated = f"{'b' * 40}\trefs/tags/v1.4.25\n{SHA}\trefs/tags/v1.4.25^{{}}\n"
    lightweight = f"{SHA}\trefs/tags/v1.4.25\n"

    assert parse_remote_tag_sha(annotated, "v1.4.25") == SHA
    assert parse_remote_tag_sha(lightweight, "v1.4.25") == SHA
    assert parse_remote_tag_sha("not-a-ref", "v1.4.25") is None


def test_compose_gate_requires_stable_context_and_all_expected_persistent_mounts() -> None:
    config = _compose_config()

    validate_compose_config(
        config,
        service="qb-rss-rules",
        expected_context=STABLE_CHECKOUT,
        expected_mounts=MOUNTS,
    )

    wrong_context = _compose_config(r"E:\GitHub\qBittorrent rss rules")
    wrong_db = _compose_config()
    wrong_db["services"]["qb-rss-rules"]["volumes"][0]["source"] = r"C:\empty\data"
    missing_host_mount = _compose_config()
    missing_host_mount["services"]["qb-rss-rules"]["volumes"].pop()

    for invalid in (wrong_context, wrong_db, missing_host_mount):
        with pytest.raises(ValueError):
            validate_compose_config(
                invalid,
                service="qb-rss-rules",
                expected_context=STABLE_CHECKOUT,
                expected_mounts=MOUNTS,
            )


def test_compose_digest_ignores_only_build_context_and_does_not_emit_secrets() -> None:
    key = b"test-only-local-contract-key"
    before = _compose_config(r"E:\GitHub\qBittorrent rss rules")
    after = _compose_config(STABLE_CHECKOUT)

    baseline = compose_config_digest(before, service="qb-rss-rules", key=key)
    assert compose_config_digest(after, service="qb-rss-rules", key=key) == baseline

    changed_environment = _compose_config(STABLE_CHECKOUT)
    changed_environment["services"]["qb-rss-rules"]["environment"]["APP_SECRET"] = "changed"
    assert compose_config_digest(changed_environment, service="qb-rss-rules", key=key) != baseline

    changed_mount = _compose_config(STABLE_CHECKOUT)
    changed_mount["services"]["qb-rss-rules"]["volumes"][0]["source"] = r"C:\empty\data"
    assert compose_config_digest(changed_mount, service="qb-rss-rules", key=key) != baseline

    assert "secret-value" not in baseline


def test_compose_contract_allows_persistent_data_mount_outside_build_context(
    tmp_path: Path,
) -> None:
    config = _compose_config(STABLE_CHECKOUT)
    config["services"]["qb-rss-rules"]["volumes"][0]["source"] = (
        r"E:\GitHub\qBittorrent rss rules\data"
    )

    contract = create_compose_contract(
        config,
        service="qb-rss-rules",
        repository=REPOSITORY,
        compose_file=str(tmp_path / "docker-compose.yml"),
        env_file=str(tmp_path / ".env"),
        key=b"test-only-local-contract-key",
        captured_at=NOW.isoformat(),
    )

    assert contract["mounts"][0]["source"] == r"e:\github\qbittorrent rss rules\data"
    assert contract["original_build_context"] == STABLE_CHECKOUT.lower()

    config["services"]["qb-rss-rules"]["volumes"][0]["source"] = "relative-data"
    with pytest.raises(ValueError, match="absolute host path"):
        create_compose_contract(
            config,
            service="qb-rss-rules",
            repository=REPOSITORY,
            compose_file=str(tmp_path / "docker-compose.yml"),
            env_file=str(tmp_path / ".env"),
            key=b"test-only-local-contract-key",
            captured_at=NOW.isoformat(),
        )


def test_private_compose_contract_allows_only_build_context_change(tmp_path: Path) -> None:
    key = b"test-only-local-contract-key"
    original = _compose_config(r"E:\GitHub\qBittorrent rss rules")
    promoted = _compose_config(STABLE_CHECKOUT)
    compose_file = str(tmp_path / "docker-compose.yml")
    env_file = str(tmp_path / ".env")
    contract = create_compose_contract(
        original,
        service="qb-rss-rules",
        repository=REPOSITORY,
        compose_file=compose_file,
        env_file=env_file,
        key=key,
        captured_at=NOW.isoformat(),
    )

    validate_compose_contract(
        contract,
        promoted,
        repository=REPOSITORY,
        compose_file=compose_file,
        env_file=env_file,
        expected_context=STABLE_CHECKOUT,
        key=key,
    )

    changed = _compose_config(STABLE_CHECKOUT)
    changed["services"]["qb-rss-rules"]["environment"]["APP_SECRET"] = "different"
    with pytest.raises(ValueError, match="Compose configuration differs"):
        validate_compose_contract(
            contract,
            changed,
            repository=REPOSITORY,
            compose_file=compose_file,
            env_file=env_file,
            expected_context=STABLE_CHECKOUT,
            key=key,
        )

    with pytest.raises(ValueError, match="contract is invalid"):
        validate_compose_contract(
            {**contract, "mounts": []},
            promoted,
            repository=REPOSITORY,
            compose_file=compose_file,
            env_file=env_file,
            expected_context=STABLE_CHECKOUT,
            key=key,
        )


def test_exclusive_lock_rejects_a_second_holder_and_releases_after_exit(tmp_path: Path) -> None:
    lock = tmp_path / "promotion.lock"
    contender = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "from scripts.production_promotion import exclusive_file_lock",
            "try:",
            "    with exclusive_file_lock(Path(sys.argv[1])):",
            "        raise SystemExit(7)",
            "except ValueError:",
            "    raise SystemExit(0)",
        ]
    )

    with exclusive_file_lock(lock):
        result = subprocess.run([sys.executable, "-c", contender, str(lock)], check=False)
        assert result.returncode == 0

    with exclusive_file_lock(lock):
        pass


def test_sqlite_backup_passes_integrity_and_scratch_restore(tmp_path: Path) -> None:
    source = tmp_path / "production.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO items (value) VALUES ('representative')")
    backup = tmp_path / "private" / "backup.sqlite3"

    digest = verify_sqlite_backup(source, backup)

    assert backup.is_file()
    assert len(digest) == 64
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM items").fetchone() == ("representative",)


def test_sqlite_backup_failure_does_not_leave_a_partial_backup(tmp_path: Path) -> None:
    backup = tmp_path / "private" / "backup.sqlite3"

    with pytest.raises(ValueError, match="SQLite backup or scratch restore failed"):
        verify_sqlite_backup(tmp_path / "missing.sqlite3", backup)

    assert not backup.exists()


def test_source_rebuilt_fallback_manifest_requires_authorized_source_and_build_evidence(
    tmp_path: Path,
) -> None:
    manifest = {
        "schema_version": 1,
        "source_tag": "v1.4.31",
        "source_sha": "c2abf87db7172b8444fb3b8b7c159f6e21735c20",
        "image_id": "sha256:" + "b" * 64,
        "compose_sha256": "c" * 64,
        "dockerfile_sha256": "d" * 64,
        "scratch_database_integrity": "ok",
        "scratch_database_rule_count": 368,
        "container_health_check": "passed",
        "validated_app_version": "1.4.31",
    }
    path = tmp_path / "fallback.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    evidence = promotion_cli.validate_source_rebuilt_fallback(
        path,
        expected_compose_sha256="c" * 64,
        expected_dockerfile_sha256="d" * 64,
        expected_image_id="sha256:" + "b" * 64,
    )

    assert evidence["source_sha"] == "c2abf87db7172b8444fb3b8b7c159f6e21735c20"
    assert evidence["scratch_database_rule_count"] == 368
    with pytest.raises(ValueError, match="Compose/build inputs"):
        promotion_cli.validate_source_rebuilt_fallback(
            path,
            expected_compose_sha256="e" * 64,
            expected_dockerfile_sha256="d" * 64,
            expected_image_id="sha256:" + "b" * 64,
        )
    manifest["source_sha"] = "e" * 40
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="authorized v1.4.31 source"):
        promotion_cli.validate_source_rebuilt_fallback(
            path,
            expected_compose_sha256="c" * 64,
            expected_dockerfile_sha256="d" * 64,
            expected_image_id="sha256:" + "b" * 64,
        )
    manifest["source_sha"] = "c2abf87db7172b8444fb3b8b7c159f6e21735c20"
    manifest["container_health_check"] = "missing"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="health and version"):
        promotion_cli.validate_source_rebuilt_fallback(
            path,
            expected_compose_sha256="c" * 64,
            expected_dockerfile_sha256="d" * 64,
            expected_image_id="sha256:" + "b" * 64,
        )


def test_failed_preflight_stops_before_deployment_backup_or_docker_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path,
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    mutation_calls: list[str] = []

    def reject_preflight(_tag: str, _run_id: int) -> dict[str, object]:
        raise ValueError("invalid approval fixture")

    def mutation(*_args: object, **_kwargs: object) -> int:
        mutation_calls.append("deployment")
        return 1

    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(manager, "_validate_approval", reject_preflight)
    monkeypatch.setattr(manager, "_create_deployment", mutation)

    with pytest.raises(ValueError, match="invalid approval fixture"):
        manager.promote("v1.4.25", 123)

    assert mutation_calls == []


def test_initial_journal_failure_marks_created_deployment_failed_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path / "stable",
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    evidence = {
        "tag": "v1.4.25",
        "commit_sha": SHA,
        "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/12",
        "target_version": "1.4.25",
        "database_path": str(tmp_path / "production.sqlite3"),
        "previous_image_id": "sha256:" + "b" * 64,
    }
    status_calls: list[tuple[str, str]] = []
    mutation_calls: list[str] = []
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(manager, "preflight", lambda _tag, _run_id, **_kwargs: evidence)
    monkeypatch.setattr(manager, "_create_deployment", lambda _evidence: 99)

    def write_status(_deployment_id: int, *, state: str, **_kwargs: str) -> None:
        status_calls.append((state, "record status"))

    def fail_journal(_record: dict[str, object]) -> Path:
        raise OSError("private storage is unavailable")

    monkeypatch.setattr(manager, "_set_deployment_status", write_status)
    monkeypatch.setattr(manager, "_write_journal", fail_journal)
    monkeypatch.setattr(
        promotion_cli,
        "verify_sqlite_backup",
        lambda *_args, **_kwargs: mutation_calls.append("backup") or "a" * 64,
    )
    monkeypatch.setattr(promotion_cli, "_run", lambda *_args, **_kwargs: mutation_calls.append("docker"))
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: mutation_calls.append("finalizer")
        or subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="Could not persist the private deployment journal"):
        manager.promote("v1.4.25", 12)

    assert status_calls == [("failure", "record status")]
    assert mutation_calls == []


def test_failure_status_is_attempted_when_failure_journal_update_also_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path / "stable",
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    evidence = {
        "tag": "v1.4.25",
        "commit_sha": SHA,
        "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/12",
        "target_version": "1.4.25",
        "database_path": str(tmp_path / "production.sqlite3"),
        "previous_image_id": "sha256:" + "b" * 64,
    }
    journal_writes = 0
    states: list[str] = []
    mutation_calls: list[str] = []
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(manager, "preflight", lambda _tag, _run_id, **_kwargs: evidence)
    monkeypatch.setattr(manager, "_create_deployment", lambda _evidence: 99)

    def write_journal(_record: dict[str, object]) -> Path:
        nonlocal journal_writes
        journal_writes += 1
        if journal_writes == 3:
            raise OSError("disk became unavailable")
        return manager.journal_dir / "fixture.json"

    def write_status(_deployment_id: int, *, state: str, **_kwargs: str) -> None:
        states.append(state)

    def fail_backup(*_args: object, **_kwargs: object) -> str:
        raise ValueError("backup integrity failed")

    monkeypatch.setattr(manager, "_write_journal", write_journal)
    monkeypatch.setattr(manager, "_set_deployment_status", write_status)
    monkeypatch.setattr(promotion_cli, "verify_sqlite_backup", fail_backup)
    monkeypatch.setattr(promotion_cli, "_run", lambda *_args, **_kwargs: mutation_calls.append("docker"))
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: mutation_calls.append("finalizer"),
    )

    with pytest.raises(ValueError, match="backup integrity failed"):
        manager.promote("v1.4.25", 12)

    assert journal_writes == 3
    assert states == ["in_progress", "failure"]
    assert mutation_calls == []


@pytest.mark.parametrize(
    ("docker_available", "expected_error"),
    [
        (False, "Docker Desktop CLI is missing"),
        (True, "Previous production image .* is not inspectable for rollback retention"),
    ],
    ids=["missing-docker-cli", "orphaned-previous-image"],
)
def test_docker_preflight_rejects_missing_cli_or_orphaned_image_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    docker_available: bool,
    expected_error: str,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path / "stable",
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "missing-docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    database_dir = tmp_path / "production-data"
    database_dir.mkdir()
    (database_dir / "qb_rules.db").write_bytes(b"sqlite fixture")
    manager.contract_file.parent.mkdir(parents=True)
    manager.contract_file.write_text(
        json.dumps(
            {
                "mounts": [{"target": "/app/data", "source": str(database_dir)}],
                "compose_hmac": "digest",
            }
        ),
        encoding="utf-8",
    )
    manager.contract_key_file.write_bytes(b"k" * 32)
    if docker_available:
        paths.docker_exe.write_text("docker fixture", encoding="utf-8")
    manifest = _manifest()
    release_url = str(manifest["release_url"])
    run_url = str(manifest["approval_run_url"])
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(
        manager,
        "_validate_approval",
        lambda _tag, _run_id: (manifest, SHA, {"html_url": run_url}),
    )
    monkeypatch.setattr(
        promotion_cli,
        "validate_release",
        lambda _tag, _repo: (
            SHA,
            release_url,
            {"databaseId": 10, "url": manifest["ci_run_url"]},
            {"databaseId": 11, "url": manifest["api_run_url"]},
        ),
    )
    monkeypatch.setattr(promotion_cli, "validate_approval_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(promotion_cli, "_project_version", lambda _root: "1.4.25")
    monkeypatch.setattr(manager, "_checkout_preflight", lambda _tag, _sha: None)
    monkeypatch.setattr(manager, "_compose_config", lambda: {})
    monkeypatch.setattr(promotion_cli, "validate_compose_contract", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(promotion_cli, "_read_health", lambda: {"app_version": "1.4.24"})
    deployment_calls: list[dict[str, object]] = []
    command_calls: list[list[str]] = []
    backup_calls: list[Path] = []
    monkeypatch.setattr(manager, "_create_deployment", lambda evidence: deployment_calls.append(evidence) or 99)

    def run_command(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command_calls.append(args)
        if args[1:3] == ["image", "inspect"]:
            raise RuntimeError("docker.exe failed with exit code 1")
        if args[1:3] == ["inspect", "--format"]:
            return subprocess.CompletedProcess(args, 0, stdout="sha256:" + "b" * 64, stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(promotion_cli, "_run", run_command)
    monkeypatch.setattr(
        promotion_cli,
        "verify_sqlite_backup",
        lambda _source, backup: backup_calls.append(backup) or "a" * 64,
    )

    with pytest.raises(ValueError, match=expected_error):
        manager.promote("v1.4.25", 12)

    assert deployment_calls == []
    if docker_available:
        assert [args[1:3] for args in command_calls] == [
            ["info"],
            ["inspect", "--format"],
            ["image", "inspect"],
        ]
    else:
        assert command_calls == []
    assert backup_calls == []
    assert not manager.journal_dir.exists()
    assert not any(args[1:2] == ["tag"] or args[1:2] == ["compose"] for args in command_calls)


@pytest.mark.parametrize(
    ("backup_fails", "finalizer_exit_code", "health_version", "cleanup_uncertain"),
    [
        (False, 1, "1.4.25", False),
        (False, 0, "1.4.24", False),
        (True, 0, "1.4.25", False),
        (False, 0, "1.4.25", True),
    ],
    ids=["finalizer-failure", "health-version-mismatch", "backup-failure", "finalizer-cleanup-uncertain"],
)
def test_failed_promotion_records_failure_without_database_or_image_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    backup_fails: bool,
    finalizer_exit_code: int,
    health_version: str,
    cleanup_uncertain: bool,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path / "stable",
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    previous_image = "sha256:" + "b" * 64
    docker_commands: list[list[str]] = []
    deployment_states: list[str] = []
    backup_calls: list[Path] = []
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(
        manager,
        "preflight",
        lambda _tag, _run_id, **_kwargs: {
            "tag": "v1.4.25",
            "commit_sha": SHA,
            "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/12",
            "database_path": str(tmp_path / "production.sqlite3"),
            "previous_image_id": previous_image,
            "target_version": "1.4.25",
            "release_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.4.25",
            "approval_run_id": 12,
            "ci_run_id": 10,
            "api_run_id": 11,
        },
    )
    monkeypatch.setattr(manager, "_create_deployment", lambda _evidence: 99)

    def set_status(_deployment_id: int, *, state: str, **_kwargs: str) -> None:
        deployment_states.append(state)

    monkeypatch.setattr(manager, "_set_deployment_status", set_status)

    def docker_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_commands.append(args)
        output = previous_image if "image" in args else previous_image
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(promotion_cli, "_run", docker_run)
    def verify_backup(_source: Path, backup: Path) -> str:
        backup_calls.append(backup)
        if backup_fails:
            raise ValueError("backup integrity gate rejected the backup")
        return "c" * 64

    monkeypatch.setattr(promotion_cli, "verify_sqlite_backup", verify_backup)
    finalizer_calls: list[list[str]] = []

    def run_finalizer(
        args: list[str], _cwd: Path, _log: object
    ) -> subprocess.CompletedProcess[str]:
        finalizer_calls.append(args)
        if cleanup_uncertain:
            raise promotion_cli.FinalizerCleanupUncertainError("process-tree termination could not be confirmed")
        exit_code = finalizer_exit_code if len(finalizer_calls) == 1 else 0
        return subprocess.CompletedProcess(args, exit_code, stdout="", stderr="")

    monkeypatch.setattr(promotion_cli, "_run_finalizer", run_finalizer)
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )
    monkeypatch.setattr(promotion_cli, "_read_health", lambda: {"app_version": health_version})

    expected_error = ValueError if backup_fails else RuntimeError
    with pytest.raises(expected_error):
        manager.promote("v1.4.25", 12)

    journal = json.loads(next(manager.journal_dir.glob("*.json")).read_text(encoding="utf-8"))
    if cleanup_uncertain:
        assert journal["stage"] == "finalizer-cleanup-required"
        assert "do not retry" not in journal["failure"].lower()
        assert deployment_states == ["in_progress"]
        assert journal["finalizer_exit_code"] is None
        assert len(finalizer_calls) == 1
        return
    assert journal["stage"] == "failure"
    assert journal["private_backup_path"]
    assert len(backup_calls) == 1
    assert deployment_states == ["in_progress", "failure"]
    if backup_fails:
        assert journal["backup_sha256"] == ""
        assert docker_commands == []
        assert finalizer_calls == []
        return
    assert journal["backup_sha256"] == "c" * 64
    assert len(docker_commands) == 2
    assert docker_commands[0][1:3] == ["image", "tag"]
    assert docker_commands[1][1:3] == ["image", "inspect"]
    assert len(finalizer_calls) == 1
    if finalizer_exit_code != 0:
        assert journal["finalizer_exit_code"] == finalizer_exit_code
        assert journal["deployed_image_id"] == ""
    else:
        assert journal["failure"].startswith("RuntimeError:")


def test_success_status_failure_retries_audit_without_repeating_promotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = promotion_cli.PromotionPaths(
        home=tmp_path,
        checkout=tmp_path / "stable",
        compose_file=tmp_path / "docker-compose.yml",
        env_file=tmp_path / ".env",
        private_root=tmp_path / "private",
        stable_checkout=tmp_path / "stable",
        docker_exe=tmp_path / "docker.exe",
    )
    manager = promotion_cli.PromotionManager(paths)
    previous_image = "sha256:" + "b" * 64
    deployed_image = "sha256:" + "d" * 64
    docker_commands: list[list[str]] = []
    deployment_states: list[str] = []
    backup_calls: list[Path] = []
    finalizer_calls: list[list[str]] = []
    monkeypatch.setattr(promotion_cli, "WINDOWS_HOST", True)
    monkeypatch.setattr(promotion_cli, "secure_private_root", lambda _path: None)
    monkeypatch.setattr(promotion_cli, "exclusive_file_lock", lambda _path: nullcontext())
    monkeypatch.setattr(
        manager,
        "preflight",
        lambda _tag, _run_id, **_kwargs: {
            "tag": "v1.4.25",
            "commit_sha": SHA,
            "approval_run_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/actions/runs/12",
            "database_path": str(tmp_path / "production.sqlite3"),
            "previous_image_id": previous_image,
            "target_version": "1.4.25",
            "release_url": "https://github.com/Spon4ik/qBittorrent-rss-rules/releases/tag/v1.4.25",
            "approval_run_id": 12,
            "ci_run_id": 10,
            "api_run_id": 11,
        },
    )
    monkeypatch.setattr(manager, "_create_deployment", lambda _evidence: 99)

    def set_status(_deployment_id: int, *, state: str, **_kwargs: str) -> None:
        deployment_states.append(state)
        if state == "success" and deployment_states.count("success") == 1:
            raise RuntimeError("GitHub status endpoint unavailable")

    monkeypatch.setattr(manager, "_set_deployment_status", set_status)

    def run_command(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_commands.append(args)
        output = deployed_image if "{{.Image}}" in args else previous_image
        if "rev-parse" in args:
            output = SHA
        elif "branch" in args:
            output = ""
        elif "status" in args:
            output = ""
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(promotion_cli, "_run", run_command)
    monkeypatch.setattr(
        promotion_cli,
        "verify_sqlite_backup",
        lambda _source, backup: backup_calls.append(backup) or "c" * 64,
    )
    monkeypatch.setattr(
        promotion_cli,
        "_read_health",
        lambda: {"app_version": "1.4.25"},
    )

    def run_process(
        args: list[str], _cwd: Path, _log: object
    ) -> subprocess.CompletedProcess[str]:
        finalizer_calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(promotion_cli, "_run_finalizer", run_process)
    monkeypatch.setattr(
        promotion_cli.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError, match="Retry audit recording without redeploying"):
        manager.promote("v1.4.25", 12)

    journal_path = next(manager.journal_dir.glob("*.json"))
    record = json.loads(journal_path.read_text(encoding="utf-8"))
    assert record["stage"] == "audit-pending"
    assert record["health_version"] == "1.4.25"
    assert record["deployed_image_id"] == deployed_image
    docker_commands.clear()
    finalizer_count = len(finalizer_calls)

    def api(path: str) -> object:
        if path.endswith("/deployments/99"):
            return {"environment": "production", "ref": SHA}
        if path.endswith("/statuses?per_page=100"):
            return []
        raise AssertionError(f"Unexpected GitHub API request: {path}")

    monkeypatch.setattr(manager, "_api", api)
    manager.retry_audit(journal_path)

    updated = json.loads(journal_path.read_text(encoding="utf-8"))
    assert updated["stage"] == "deployment-recorded"
    assert deployment_states == ["in_progress", "success", "success"]
    assert len(backup_calls) == 1
    assert len(finalizer_calls) == finalizer_count
    docker_cli_calls = [command for command in docker_commands if str(paths.docker_exe) in command[0]]
    assert len(docker_cli_calls) == 1
    assert "inspect" in docker_cli_calls[0]
    assert not any("tag" in command for command in docker_cli_calls)


def test_audit_retry_requires_current_production_sha_version_and_image() -> None:
    record = {
        "stage": "audit-pending",
        "commit_sha": SHA,
        "target_version": "1.4.25",
        "health_version": "1.4.25",
        "deployed_image_id": "sha256:" + "b" * 64,
    }
    deployment = {"environment": "production", "ref": SHA}

    validate_audit_retry_evidence(
        record,
        deployment,
        running_version="1.4.25",
        running_image_id="sha256:" + "b" * 64,
    )
    with pytest.raises(ValueError, match="Live production health"):
        validate_audit_retry_evidence(
            record,
            deployment,
            running_version="1.4.24",
            running_image_id="sha256:" + "b" * 64,
        )
    with pytest.raises(ValueError, match="image no longer matches"):
        validate_audit_retry_evidence(
            record,
            deployment,
            running_version="1.4.25",
            running_image_id="sha256:" + "c" * 64,
        )


def test_runbook_commands_match_local_tool_and_production_boundaries() -> None:
    runbook = Path("docs/production-promotion-runbook.md").read_text(encoding="utf-8")

    assert "--capture-compose-contract --confirm-current-mounts" in runbook
    assert "--tag v1.4.28 --approval-run-id 12345678901" in runbook
    assert "--retry-audit-record <journal-path>" in runbook
    assert "`/app/data` database bind mount" in runbook
    assert "`/host/C/Users` and `/host/C/ProgramData` mounts" in runbook
    assert "Database restoration is separate and destructive" in runbook
    assert "A failed promotion attempt remains incomplete" in runbook
