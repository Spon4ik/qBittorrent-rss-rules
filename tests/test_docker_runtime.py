from __future__ import annotations

import subprocess
from pathlib import Path

import scripts.docker_runtime as runtime


def test_run_process_uses_exact_executable_without_shell(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "docker.exe"
    executable.write_bytes(b"stub")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    result = runtime._run_process(executable, ["info", "--format", "x"])

    assert result.returncode == 0
    assert captured["command"] == [str(executable), "info", "--format", "x"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True


def test_launch_docker_desktop_uses_exact_executable_without_shell(
    tmp_path: Path,
    monkeypatch,
) -> None:
    desktop = tmp_path / "Docker Desktop.exe"
    desktop.write_bytes(b"stub")
    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)

    runtime._launch_docker_desktop(desktop)

    assert captured["command"] == [str(desktop)]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


def test_compose_base_args_uses_env_file_when_present(tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("A=B\n", encoding="utf-8")

    assert runtime._compose_base_args(compose) == [
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose),
    ]


def test_start_uses_existing_compose_service_without_build_or_recreate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    docker = tmp_path / "docker.exe"
    desktop = tmp_path / "Docker Desktop.exe"
    calls: list[list[str]] = []

    monkeypatch.setattr(runtime, "_ensure_engine", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        runtime,
        "_compose_action",
        lambda _docker, _compose, arguments: calls.append(list(arguments)),
    )
    monkeypatch.setattr(
        runtime,
        "_wait_for_health",
        lambda *args, **kwargs: {
            "ok": True,
            "status_code": 200,
            "app_version": "1.2.3",
            "error": None,
        },
    )
    monkeypatch.setattr(runtime, "_service_running", lambda *args, **kwargs: True)

    report, exit_code = runtime.run_action(
        "start",
        compose_file=compose,
        docker_exe=docker,
        docker_desktop_exe=desktop,
    )

    assert exit_code == 0
    assert calls == [["start", "qb-rss-rules"]]
    assert report["status"] == "ready"
    assert report["docker_desktop_started"] is True


def test_restart_starts_existing_stopped_service_without_recreate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    docker = tmp_path / "docker.exe"
    desktop = tmp_path / "Docker Desktop.exe"
    calls: list[list[str]] = []
    running = iter([False, True])

    monkeypatch.setattr(runtime, "_ensure_engine", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        runtime,
        "_compose_action",
        lambda _docker, _compose, arguments: calls.append(list(arguments)),
    )
    monkeypatch.setattr(
        runtime,
        "_wait_for_health",
        lambda *args, **kwargs: {
            "ok": True,
            "status_code": 200,
            "app_version": None,
            "error": None,
        },
    )
    monkeypatch.setattr(runtime, "_service_running", lambda *args, **kwargs: next(running))

    report, exit_code = runtime.run_action(
        "restart",
        compose_file=compose,
        docker_exe=docker,
        docker_desktop_exe=desktop,
    )

    assert exit_code == 0
    assert calls == [["start", "qb-rss-rules"]]
    assert report["status"] == "ready"


def test_restart_running_service_uses_compose_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(runtime, "_ensure_engine", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        runtime,
        "_compose_action",
        lambda _docker, _compose, arguments: calls.append(list(arguments)),
    )
    monkeypatch.setattr(
        runtime,
        "_wait_for_health",
        lambda *args, **kwargs: {
            "ok": True,
            "status_code": 200,
            "app_version": None,
            "error": None,
        },
    )
    monkeypatch.setattr(runtime, "_service_running", lambda *args, **kwargs: True)

    report, exit_code = runtime.run_action(
        "restart",
        compose_file=compose,
        docker_exe=tmp_path / "docker.exe",
        docker_desktop_exe=tmp_path / "Docker Desktop.exe",
    )

    assert exit_code == 0
    assert calls == [["restart", "qb-rss-rules"]]
    assert report["status"] == "ready"


def test_stop_is_idempotent_when_engine_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    compose_called = False

    monkeypatch.setattr(runtime, "_engine_ready", lambda _docker: False)

    def unexpected_compose(*args, **kwargs):
        nonlocal compose_called
        compose_called = True

    monkeypatch.setattr(runtime, "_compose_action", unexpected_compose)

    report, exit_code = runtime.run_action(
        "stop",
        compose_file=compose,
        docker_exe=tmp_path / "docker.exe",
        docker_desktop_exe=tmp_path / "Docker Desktop.exe",
    )

    assert exit_code == 0
    assert compose_called is False
    assert report["status"] == "stopped"
    assert report["runtime"]["service"] == "stopped"  # type: ignore[index]


def test_status_does_not_start_docker_desktop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    launched = False

    monkeypatch.setattr(runtime, "_engine_ready", lambda _docker: False)

    def unexpected_launch(_desktop: Path) -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr(runtime, "_launch_docker_desktop", unexpected_launch)

    report, exit_code = runtime.run_action(
        "status",
        compose_file=compose,
        docker_exe=tmp_path / "docker.exe",
        docker_desktop_exe=tmp_path / "Docker Desktop.exe",
    )

    assert exit_code == 1
    assert launched is False
    assert report["status"] == "not_ready"
    assert report["runtime"]["engine"] == "unavailable"  # type: ignore[index]


def test_windows_entrypoints_delegate_to_maintained_helper() -> None:
    root = Path(__file__).resolve().parents[1]
    powershell = (root / "scripts" / "docker_runtime.ps1").read_text(encoding="utf-8")
    batch = (root / "scripts" / "docker_runtime.bat").read_text(encoding="utf-8")

    executable_lines = [
        line.strip().casefold()
        for line in powershell.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "docker_runtime.py" in powershell
    assert not any(line.startswith("start-process") for line in executable_lines)
    assert not any(line.startswith("& docker") for line in executable_lines)
    assert "docker_runtime.ps1" in batch
