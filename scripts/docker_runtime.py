from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

DEFAULT_COMPOSE_FILE = Path(r"C:\Users\nucc\docker-config\docker-compose.yml")
DEFAULT_SERVICE = "qb-rss-rules"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/health"
DEFAULT_DOCKER_EXE = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
DEFAULT_DOCKER_DESKTOP_EXE = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")


def _run_process(
    executable: Path,
    arguments: Sequence[str],
    *,
    timeout_seconds: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
    )


def _compose_base_args(compose_file: Path) -> list[str]:
    args = ["compose"]
    env_file = compose_file.parent / ".env"
    if env_file.is_file():
        args.extend(["--env-file", str(env_file)])
    args.extend(["-f", str(compose_file)])
    return args


def _docker(
    docker_exe: Path,
    arguments: Sequence[str],
    *,
    timeout_seconds: int = 60,
) -> subprocess.CompletedProcess[str]:
    if not docker_exe.is_file():
        raise FileNotFoundError(docker_exe)
    return _run_process(docker_exe, arguments, timeout_seconds=timeout_seconds)


def _engine_ready(docker_exe: Path) -> bool:
    try:
        result = _docker(
            docker_exe,
            ["info", "--format", "{{.ServerVersion}}"],
            timeout_seconds=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _launch_docker_desktop(docker_desktop_exe: Path) -> None:
    if not docker_desktop_exe.is_file():
        raise FileNotFoundError(docker_desktop_exe)
    # A concrete executable path plus shell=False prevents Windows from treating
    # the word "docker" as a document/protocol and showing an Open With dialog.
    subprocess.Popen(
        [str(docker_desktop_exe)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def _wait_for_engine(
    docker_exe: Path,
    *,
    timeout_seconds: int,
    poll_seconds: float = 2.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _engine_ready(docker_exe):
            return True
        time.sleep(poll_seconds)
    return _engine_ready(docker_exe)


def _ensure_engine(
    docker_exe: Path,
    docker_desktop_exe: Path,
    *,
    timeout_seconds: int,
) -> bool:
    if _engine_ready(docker_exe):
        return False
    _launch_docker_desktop(docker_desktop_exe)
    if not _wait_for_engine(docker_exe, timeout_seconds=timeout_seconds):
        raise RuntimeError(
            f"Docker engine did not become ready within {timeout_seconds} seconds"
        )
    return True


def _service_running(
    docker_exe: Path,
    compose_file: Path,
    service: str,
) -> bool:
    result = _docker(
        docker_exe,
        [*_compose_base_args(compose_file), "ps", "--status", "running", "--services"],
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Docker Compose status failed: " + _bounded(result.stderr or result.stdout)
        )
    return service in {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _health_probe(url: str, *, timeout_seconds: int = 5) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            body = response.read(64 * 1024)
            status_code = int(getattr(response, "status", 200))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status_code": None,
            "app_version": None,
            "error": _bounded(str(exc)),
        }

    app_version: str | None = None
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        if isinstance(payload, dict) and payload.get("app_version") is not None:
            app_version = str(payload["app_version"])
    except json.JSONDecodeError:
        pass
    return {
        "ok": 200 <= status_code < 300,
        "status_code": status_code,
        "app_version": app_version,
        "error": None,
    }


def _wait_for_health(
    url: str,
    *,
    timeout_seconds: int,
    poll_seconds: float = 2.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last = _health_probe(url)
    while time.monotonic() < deadline:
        if bool(last["ok"]):
            return last
        time.sleep(poll_seconds)
        last = _health_probe(url)
    return last


def _bounded(value: str, *, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _compose_action(
    docker_exe: Path,
    compose_file: Path,
    arguments: Sequence[str],
) -> None:
    result = _docker(docker_exe, [*_compose_base_args(compose_file), *arguments])
    if result.returncode != 0:
        raise RuntimeError(
            "Docker Compose command failed: " + _bounded(result.stderr or result.stdout)
        )


def inspect_runtime(
    *,
    docker_exe: Path,
    compose_file: Path,
    service: str,
    health_url: str,
) -> dict[str, object]:
    if not _engine_ready(docker_exe):
        return {
            "engine": "unavailable",
            "service": "unknown",
            "health": {"ok": False, "status_code": None, "app_version": None, "error": "engine unavailable"},
        }
    running = _service_running(docker_exe, compose_file, service)
    health = _health_probe(health_url) if running else {
        "ok": False,
        "status_code": None,
        "app_version": None,
        "error": "service not running",
    }
    return {
        "engine": "ready",
        "service": "running" if running else "stopped",
        "health": health,
    }


def run_action(
    action: str,
    *,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
    service: str = DEFAULT_SERVICE,
    health_url: str = DEFAULT_HEALTH_URL,
    docker_exe: Path = DEFAULT_DOCKER_EXE,
    docker_desktop_exe: Path = DEFAULT_DOCKER_DESKTOP_EXE,
    engine_timeout_seconds: int = 120,
    health_timeout_seconds: int = 90,
) -> tuple[dict[str, object], int]:
    compose_file = compose_file.resolve()
    docker_exe = docker_exe.resolve()
    docker_desktop_exe = docker_desktop_exe.resolve()

    if not compose_file.is_file():
        raise FileNotFoundError(compose_file)

    desktop_started = False
    if action == "status":
        runtime = inspect_runtime(
            docker_exe=docker_exe,
            compose_file=compose_file,
            service=service,
            health_url=health_url,
        )
        ok = runtime["engine"] == "ready" and runtime["service"] == "running" and bool(
            runtime["health"]["ok"]  # type: ignore[index]
        )
        return {
            "status": "ok" if ok else "not_ready",
            "action": action,
            "runtime": runtime,
        }, 0 if ok else 1

    if action == "stop":
        if not _engine_ready(docker_exe):
            return {
                "status": "stopped",
                "action": action,
                "runtime": {
                    "engine": "unavailable",
                    "service": "stopped",
                    "health": {"ok": False, "status_code": None, "app_version": None, "error": "engine unavailable"},
                },
            }, 0
        _compose_action(docker_exe, compose_file, ["stop", service])
        if _service_running(docker_exe, compose_file, service):
            raise RuntimeError(f"Docker service {service!r} is still running after stop")
        return {
            "status": "stopped",
            "action": action,
            "runtime": inspect_runtime(
                docker_exe=docker_exe,
                compose_file=compose_file,
                service=service,
                health_url=health_url,
            ),
        }, 0

    desktop_started = _ensure_engine(
        docker_exe,
        docker_desktop_exe,
        timeout_seconds=engine_timeout_seconds,
    )

    if action == "start":
        _compose_action(docker_exe, compose_file, ["up", "-d", service])
    elif action == "restart":
        if _service_running(docker_exe, compose_file, service):
            _compose_action(docker_exe, compose_file, ["restart", service])
        else:
            _compose_action(docker_exe, compose_file, ["up", "-d", service])
    else:
        raise ValueError(f"Unsupported Docker runtime action: {action}")

    health = _wait_for_health(health_url, timeout_seconds=health_timeout_seconds)
    running = _service_running(docker_exe, compose_file, service)
    ok = running and bool(health["ok"])
    report = {
        "status": "ready" if ok else "failed",
        "action": action,
        "docker_desktop_started": desktop_started,
        "runtime": {
            "engine": "ready",
            "service": "running" if running else "stopped",
            "health": health,
        },
    }
    if not ok:
        raise RuntimeError(
            f"Docker service {service!r} did not become healthy: "
            + _bounded(str(health.get("error") or health.get("status_code")))
        )
    return report, 0


def _write_report(report: dict[str, object], output: Path | None) -> None:
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic qB RSS Docker runtime lifecycle wrapper."
    )
    parser.add_argument("action", choices=("status", "start", "stop", "restart"))
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--docker-exe", type=Path, default=DEFAULT_DOCKER_EXE)
    parser.add_argument(
        "--docker-desktop-exe",
        type=Path,
        default=DEFAULT_DOCKER_DESKTOP_EXE,
    )
    parser.add_argument("--engine-timeout", type=int, default=120)
    parser.add_argument("--health-timeout", type=int, default=90)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report, exit_code = run_action(
            args.action,
            compose_file=args.compose_file,
            service=str(args.service),
            health_url=str(args.health_url),
            docker_exe=args.docker_exe,
            docker_desktop_exe=args.docker_desktop_exe,
            engine_timeout_seconds=int(args.engine_timeout),
            health_timeout_seconds=int(args.health_timeout),
        )
    except Exception as exc:
        report = {
            "status": "failed",
            "action": args.action,
            "error": f"{type(exc).__name__}: {_bounded(str(exc))}",
        }
        exit_code = 1
    _write_report(report, args.output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
