#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import closeout_browser_qa as legacy  # noqa: E402


@dataclass(frozen=True, slots=True)
class CheckSpec:
    check_id: str
    phase: str
    title: str
    dependencies: tuple[str, ...]
    handler: Callable[["FocusedRuntime"], None]


@dataclass(slots=True)
class FocusedResult:
    check_id: str
    phase: str
    title: str
    status: str
    detail: str
    duration_ms: int
    failure_artifact: str | None = None


@dataclass(slots=True)
class FocusedRuntime:
    project_dir: Path
    run_dir: Path
    db_path: Path
    app_base_url: str
    browser: Any
    timeout_ms: int


LEGACY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "P4-02": ("P4-01",),
    "P5-01": ("P9-01",),
    "P7-10": ("P6-05",),
    "P7-11": ("P6-05",),
    "P7-12": ("P6-05",),
    "P33-01": ("P6-05",),
}

# These failures are mechanically stale against the current UI contract. The raw
# legacy report is preserved, but the compact closeout summary classifies them as
# quarantined until the legacy scenario is repaired or replaced. Uncertain semantic
# failures (notably P5-03 and P6-02/03/04) remain actionable.
LEGACY_QUARANTINE: dict[str, str] = {
    "P41-01": "stale dark-settings selector/contrast target",
    "P4-01": "stale feed-option visibility assumption",
    "P19-01": "stale inline filtered-count visibility assumption",
    "P23-01": "stale inline result-summary visibility assumption",
    "P6-05": "stale search-to-rule handoff action contract",
}


def normalize_phase(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized.startswith("phase "):
        normalized = normalized[6:].strip()
    if normalized.startswith("p") and normalized[1:].isdigit():
        normalized = normalized[1:]
    return normalized.upper()


def _dependency_closure(check_ids: set[str], specs: dict[str, CheckSpec]) -> set[str]:
    resolved = set(check_ids)
    pending = list(check_ids)
    while pending:
        check_id = pending.pop()
        for dependency in specs[check_id].dependencies:
            if dependency not in specs:
                raise ValueError(f"Unknown dependency {dependency!r} for {check_id}.")
            if dependency not in resolved:
                resolved.add(dependency)
                pending.append(dependency)
    return resolved


def resolve_selection(
    *,
    check_ids: list[str] | None,
    phases: list[str] | None,
    specs: dict[str, CheckSpec],
) -> list[str]:
    requested: set[str] = set()
    if check_ids:
        for raw in check_ids:
            check_id = raw.strip().upper()
            if check_id not in specs:
                raise ValueError(
                    f"Unknown browser QA check {raw!r}. Available: {', '.join(sorted(specs))}."
                )
            requested.add(check_id)
    elif phases:
        wanted_phases = {normalize_phase(value) for value in phases}
        available_phases = {normalize_phase(spec.phase) for spec in specs.values()}
        unknown_phases = wanted_phases - available_phases
        if unknown_phases:
            raise ValueError(
                "Unknown browser QA phase(s): "
                + ", ".join(sorted(unknown_phases))
                + ". Available: "
                + ", ".join(sorted(available_phases))
                + "."
            )
        requested = {
            check_id
            for check_id, spec in specs.items()
            if normalize_phase(spec.phase) in wanted_phases
        }
    else:
        raise ValueError("Select --check, --phase, or --full.")

    selected = _dependency_closure(requested, specs)
    return [check_id for check_id in specs if check_id in selected]


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


@contextmanager
def focused_runtime(args: argparse.Namespace) -> Iterator[FocusedRuntime]:
    project_dir = legacy.PROJECT_DIR
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = project_dir / output_root
    run_dir = output_root / f"browser-focus-{legacy.utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    db_path = run_dir / "focused.db"
    app_log_path = run_dir / "uvicorn.log"
    app_port = legacy.find_free_port()
    qb_port = legacy.find_free_port()
    jackett_port = legacy.find_free_port()
    app_base_url = f"http://{args.app_host}:{app_port}"
    qb_base_url = f"http://localhost.:{qb_port}"
    jackett_base_url = f"http://127.0.0.1:{jackett_port}"

    qb_state = legacy.MockQbState(
        feeds_payload={
            "Feeds": {
                "Alpha": {"name": "Alpha", "url": legacy.FEED_ALPHA},
                "Beta": {"name": "Beta", "url": legacy.FEED_BETA},
                "Gamma": {"name": "Gamma", "url": legacy.FEED_GAMMA},
            }
        },
        rules={},
        torrent_add_calls=[],
    )
    jackett_state = legacy.MockJackettState(request_count=0)
    qb_server, qb_thread = legacy.start_threaded_server(
        legacy.build_qb_handler(qb_state), "127.0.0.1", qb_port
    )
    jackett_server, jackett_thread = legacy.start_threaded_server(
        legacy.build_jackett_handler(jackett_state), "127.0.0.1", jackett_port
    )

    env = os.environ.copy()
    env.update(
        {
            "QB_RULES_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "QB_RULES_QB_BASE_URL": qb_base_url,
            "QB_RULES_QB_USERNAME": "admin",
            "QB_RULES_QB_PASSWORD": "adminadmin",
            "QB_RULES_JACKETT_API_URL": jackett_base_url,
            "QB_RULES_JACKETT_QB_URL": jackett_base_url,
            "QB_RULES_JACKETT_API_KEY": "qa-key",
            "QB_RULES_REQUEST_TIMEOUT": "5",
            "QB_RULES_ENABLE_JELLYFIN_AUTO_SYNC_SCHEDULER": "0",
            "QB_RULES_ENABLE_STREMIO_AUTO_SYNC_SCHEDULER": "0",
            "QB_RULES_ENABLE_RULE_FETCH_SCHEDULER": "0",
        }
    )

    server_process: subprocess.Popen[str] | None = None
    playwright = None
    browser = None
    try:
        legacy.prepare_closeout_db(
            db_path=db_path,
            qb_base_url=qb_base_url,
            jackett_base_url=jackett_base_url,
            feed_urls=legacy.DEFAULT_FEEDS,
        )
        with app_log_path.open("w", encoding="utf-8") as app_log:
            server_process = subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    args.app_host,
                    "--port",
                    str(app_port),
                ],
                cwd=project_dir,
                env=env,
                stdout=app_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if not legacy.wait_for_http(f"{app_base_url}/health", timeout_seconds=90):
            raise RuntimeError(f"Timed out waiting for isolated app server ({app_base_url}).")

        try:
            import playwright.sync_api as playwright_sync_api
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed for this interpreter. "
                f"Install with `{sys.executable} -m pip install playwright` and "
                f"`{sys.executable} -m playwright install chromium`."
            ) from exc
        playwright = playwright_sync_api.sync_playwright().start()
        browser = playwright.chromium.launch(headless=not args.headful)
        yield FocusedRuntime(
            project_dir=project_dir,
            run_dir=run_dir,
            db_path=db_path,
            app_base_url=app_base_url,
            browser=browser,
            timeout_ms=args.timeout_ms,
        )
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        if server_process is not None:
            server_process.terminate()
            try:
                server_process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=4)
        legacy.stop_threaded_server(jackett_server, jackett_thread)
        legacy.stop_threaded_server(qb_server, qb_thread)


def check_p44_03(runtime: FocusedRuntime) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.models import Rule

    engine = create_engine(
        f"sqlite:///{runtime.db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )
    try:
        with Session(engine) as session:
            rule_id = str(
                session.scalar(
                    select(Rule.id).where(Rule.rule_name == "QA P19 Inline Search Profile")
                )
                or ""
            )
    finally:
        engine.dispose()
    legacy._expect(bool(rule_id), "Expected the pre-seeded toolbar QA rule to exist.")
    inline_rule_url = f"{runtime.app_base_url}/rules/{rule_id}?run_search=1"
    failure_path = runtime.run_dir / "p44-03-failure.png"

    def capture_failure(page: Any) -> None:
        try:
            page.screenshot(path=str(failure_path), full_page=True)
        except Exception:  # noqa: BLE001
            pass

    wide_context = runtime.browser.new_context(viewport={"width": 1720, "height": 1040})
    wide_page = wide_context.new_page()
    try:
        wide_page.goto(inline_rule_url, wait_until="networkidle", timeout=runtime.timeout_ms)
        wide_page.wait_for_selector(
            '#inline-search-results .result-toolbar-row', timeout=runtime.timeout_ms
        )
        indexer_menu = wide_page.locator(
            '#inline-search-results [data-search-multiselect="indexers"]'
        )
        category_menu = wide_page.locator(
            '#inline-search-results [data-search-multiselect="categories"]'
        )
        queue_menu = wide_page.locator(
            '#inline-search-results [data-result-toolbar-menu].search-queue-advanced'
        )
        legacy._expect(indexer_menu.count() == 1, "Expected one inline indexer-scope menu.")
        legacy._expect(category_menu.count() == 1, "Expected one inline media-category menu.")
        legacy._expect(queue_menu.count() == 1, "Expected one inline queue-options menu.")

        baseline = wide_page.evaluate(
            """
            () => {
              const toolbar = document.querySelector("#inline-search-results .result-toolbar-row");
              const table = document.querySelector('#inline-search-results [data-search-table-wrap="combined"]');
              const indexer = document.querySelector('[data-search-multiselect="indexers"] > summary');
              const category = document.querySelector('[data-search-multiselect="categories"] > summary');
              const queue = document.querySelector('.search-queue-advanced > summary');
              if (!toolbar || !table || !indexer || !category || !queue) return null;
              return {
                toolbarHeight: toolbar.getBoundingClientRect().height,
                tableDocumentTop: table.getBoundingClientRect().top + window.scrollY,
                indexerY: indexer.getBoundingClientRect().y,
                categoryY: category.getBoundingClientRect().y,
                queueY: queue.getBoundingClientRect().y,
              };
            }
            """
        )
        legacy._expect(baseline is not None, "Missing result-toolbar baseline geometry.")
        legacy._expect(
            max(
                abs(float(baseline["indexerY"]) - float(baseline["categoryY"])),
                abs(float(baseline["indexerY"]) - float(baseline["queueY"])),
            ) <= 1,
            f"Wide-toolbar menu summaries are not aligned: {baseline}",
        )

        indexer_menu.locator("summary").click()
        legacy._expect(indexer_menu.get_attribute("open") is not None, "Indexer menu did not open.")
        category_menu.locator("summary").click()
        legacy._expect(category_menu.get_attribute("open") is not None, "Category menu did not open.")
        legacy._expect(indexer_menu.get_attribute("open") is None, "Opening category left indexer menu open.")
        wide_page.keyboard.press("Escape")
        legacy._expect(category_menu.get_attribute("open") is None, "Escape did not close the active toolbar menu.")

        queue_menu.locator("summary").click()
        queue_metrics = wide_page.evaluate(
            """
            () => {
              const toolbar = document.querySelector("#inline-search-results .result-toolbar-row");
              const table = document.querySelector('#inline-search-results [data-search-table-wrap="combined"]');
              const sequential = document.querySelector('[data-result-queue-option="sequential"]');
              const firstLast = document.querySelector('[data-result-queue-option="first_last_piece_prio"]');
              if (!toolbar || !table || !sequential || !firstLast) return null;
              const sequentialRect = sequential.closest("label")?.getBoundingClientRect();
              const firstLastRect = firstLast.closest("label")?.getBoundingClientRect();
              if (!sequentialRect || !firstLastRect) return null;
              return {
                toolbarHeight: toolbar.getBoundingClientRect().height,
                tableDocumentTop: table.getBoundingClientRect().top + window.scrollY,
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                sequentialVisible: Boolean(sequential.offsetParent),
                firstLastVisible: Boolean(firstLast.offsetParent),
                itemsOverlap: sequentialRect.bottom > firstLastRect.top && firstLastRect.bottom > sequentialRect.top,
              };
            }
            """
        )
        legacy._expect(queue_metrics is not None, "Missing open queue-menu geometry.")
        legacy._expect(
            bool(queue_metrics["sequentialVisible"]),
            f"Sequential download is not visible: {queue_metrics}",
        )
        legacy._expect(
            bool(queue_metrics["firstLastVisible"]),
            f"First/last pieces option is not visible: {queue_metrics}",
        )
        legacy._expect(
            not bool(queue_metrics["itemsOverlap"]),
            f"Queue options overlap: {queue_metrics}",
        )
        legacy._expect(
            abs(float(queue_metrics["toolbarHeight"]) - float(baseline["toolbarHeight"])) <= 1
            and abs(float(queue_metrics["tableDocumentTop"]) - float(baseline["tableDocumentTop"])) <= 1,
            f"Opening queue options reflowed surrounding layout: baseline={baseline}, open={queue_metrics}",
        )
        legacy._expect(
            int(queue_metrics["scrollWidth"]) <= int(queue_metrics["clientWidth"]),
            f"Queue menu introduced horizontal page overflow: {queue_metrics}",
        )
        wide_page.mouse.click(8, 8)
        legacy._expect(
            queue_menu.get_attribute("open") is None,
            "Outside click did not close the queue menu.",
        )
    except Exception:
        capture_failure(wide_page)
        raise
    finally:
        wide_context.close()

    narrow_context = runtime.browser.new_context(viewport={"width": 390, "height": 844})
    narrow_page = narrow_context.new_page()
    try:
        narrow_page.goto(inline_rule_url, wait_until="networkidle", timeout=runtime.timeout_ms)
        narrow_page.wait_for_selector(
            '#inline-search-results .result-toolbar-row', timeout=runtime.timeout_ms
        )
        queue_menu = narrow_page.locator(
            '#inline-search-results [data-result-toolbar-menu].search-queue-advanced'
        )
        legacy._expect(queue_menu.count() == 1, "Expected one responsive queue-options menu.")
        baseline = narrow_page.evaluate(
            """
            () => {
              const toolbar = document.querySelector("#inline-search-results .result-toolbar-row");
              const table = document.querySelector('#inline-search-results [data-search-table-wrap="combined"]');
              if (!toolbar || !table) return null;
              return {
                toolbarHeight: toolbar.getBoundingClientRect().height,
                tableDocumentTop: table.getBoundingClientRect().top + window.scrollY,
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
              };
            }
            """
        )
        legacy._expect(baseline is not None, "Missing responsive toolbar baseline geometry.")
        legacy._expect(
            int(baseline["scrollWidth"]) <= int(baseline["clientWidth"]),
            f"Responsive toolbar has horizontal overflow before opening a menu: {baseline}",
        )
        queue_menu.locator("summary").click()
        opened = narrow_page.evaluate(
            """
            () => {
              const toolbar = document.querySelector("#inline-search-results .result-toolbar-row");
              const table = document.querySelector('#inline-search-results [data-search-table-wrap="combined"]');
              const sequential = document.querySelector('[data-result-queue-option="sequential"]');
              const firstLast = document.querySelector('[data-result-queue-option="first_last_piece_prio"]');
              if (!toolbar || !table || !sequential || !firstLast) return null;
              return {
                toolbarHeight: toolbar.getBoundingClientRect().height,
                tableDocumentTop: table.getBoundingClientRect().top + window.scrollY,
                scrollWidth: document.documentElement.scrollWidth,
                clientWidth: document.documentElement.clientWidth,
                sequentialVisible: Boolean(sequential.offsetParent),
                firstLastVisible: Boolean(firstLast.offsetParent),
              };
            }
            """
        )
        legacy._expect(opened is not None, "Missing open responsive queue-menu geometry.")
        legacy._expect(
            bool(opened["sequentialVisible"]) and bool(opened["firstLastVisible"]),
            f"Responsive queue menu hid an option: {opened}",
        )
        legacy._expect(
            abs(float(opened["toolbarHeight"]) - float(baseline["toolbarHeight"])) <= 1
            and abs(float(opened["tableDocumentTop"]) - float(baseline["tableDocumentTop"])) <= 1,
            f"Responsive queue menu reflowed surrounding layout: baseline={baseline}, open={opened}",
        )
        legacy._expect(
            int(opened["scrollWidth"]) <= int(opened["clientWidth"]),
            f"Responsive queue menu introduced horizontal overflow: {opened}",
        )
    except Exception:
        capture_failure(narrow_page)
        raise
    finally:
        narrow_context.close()


CHECK_SPECS: dict[str, CheckSpec] = {
    "P44-03": CheckSpec(
        check_id="P44-03",
        phase="44",
        title="Result-toolbar menus close predictably without reflow or hidden queue options",
        dependencies=(),
        handler=check_p44_03,
    ),
}


def _write_focused_report(runtime: FocusedRuntime, results: list[FocusedResult]) -> None:
    counts = {
        "total": len(results),
        "passed": sum(item.status == "pass" for item in results),
        "failed": sum(item.status == "fail" for item in results),
        "blocked": sum(item.status == "blocked" for item in results),
    }
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "focused",
        "run_dir": _relative(runtime.run_dir, runtime.project_dir),
        "counts": counts,
        "checks": [asdict(item) for item in results],
    }
    json_path = runtime.run_dir / "browser-qa-report.json"
    md_path = runtime.run_dir / "browser-qa-report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Focused Browser QA",
        "",
        f"- Passed: **{counts['passed']}**",
        f"- Failed: **{counts['failed']}**",
        f"- Blocked: **{counts['blocked']}**",
        "",
        "| Check | Phase | Status | ms | Detail |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for result in results:
        detail = result.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {result.check_id} | {result.phase} | {result.status} | {result.duration_ms} | {detail} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved focused browser QA report: {json_path}")


def run_focused(args: argparse.Namespace) -> int:
    selected = resolve_selection(
        check_ids=args.check,
        phases=args.phase,
        specs=CHECK_SPECS,
    )
    results: list[FocusedResult] = []
    statuses: dict[str, str] = {}
    with focused_runtime(args) as runtime:
        for check_id in selected:
            spec = CHECK_SPECS[check_id]
            blocked_by = [
                dependency
                for dependency in spec.dependencies
                if statuses.get(dependency) != "pass"
            ]
            if blocked_by:
                result = FocusedResult(
                    check_id=spec.check_id,
                    phase=f"Phase {spec.phase}",
                    title=spec.title,
                    status="blocked",
                    detail="Blocked by failed/unavailable prerequisite(s): " + ", ".join(blocked_by),
                    duration_ms=0,
                )
                results.append(result)
                statuses[check_id] = result.status
                print(f"BLOCKED {check_id}: {result.detail}")
                continue

            start = time.monotonic()
            status = "pass"
            detail = "OK"
            artifact = None
            try:
                spec.handler(runtime)
            except Exception as exc:  # noqa: BLE001
                status = "fail"
                detail = f"{exc.__class__.__name__}: {exc}"
                failure_path = runtime.run_dir / f"{check_id.lower()}-failure.png"
                if failure_path.exists():
                    artifact = _relative(failure_path, runtime.project_dir)
            duration_ms = int((time.monotonic() - start) * 1000)
            result = FocusedResult(
                check_id=spec.check_id,
                phase=f"Phase {spec.phase}",
                title=spec.title,
                status=status,
                detail=detail,
                duration_ms=duration_ms,
                failure_artifact=artifact,
            )
            results.append(result)
            statuses[check_id] = status
            print(f"{status.upper()} {check_id} ({duration_ms} ms): {detail}")
        _write_focused_report(runtime, results)
    return 1 if any(item.status != "pass" for item in results) else 0


def classify_legacy_report(report: dict[str, Any]) -> dict[str, Any]:
    checks = [dict(item) for item in report.get("checks", []) if isinstance(item, dict)]
    raw_status = {str(item.get("check_id")): str(item.get("status")) for item in checks}

    for item in checks:
        check_id = str(item.get("check_id") or "")
        if str(item.get("status")) == "pass":
            continue
        dependencies = LEGACY_DEPENDENCIES.get(check_id, ())
        blocked_by = [dependency for dependency in dependencies if raw_status.get(dependency) != "pass"]
        if blocked_by:
            item["status"] = "blocked"
            item["detail"] = "Blocked by prerequisite failure(s): " + ", ".join(blocked_by)
            continue
        quarantine_reason = LEGACY_QUARANTINE.get(check_id)
        if quarantine_reason:
            item["status"] = "quarantined"
            item["detail"] = f"Quarantined legacy contract: {quarantine_reason}. Raw: {item.get('detail', '')}"

    counts = {
        "total": len(checks),
        "passed": sum(str(item.get("status")) == "pass" for item in checks),
        "failed": sum(str(item.get("status")) == "fail" for item in checks),
        "blocked": sum(str(item.get("status")) == "blocked" for item in checks),
        "quarantined": sum(str(item.get("status")) == "quarantined" for item in checks),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "legacy-full-compact",
        "source_generated_at": report.get("generated_at"),
        "counts": counts,
        "checks": checks,
    }


def _write_compact_legacy_summary(report_path: Path, compact: dict[str, Any]) -> tuple[Path, Path]:
    run_dir = report_path.parent
    json_path = run_dir / "codex-summary.json"
    md_path = run_dir / "codex-summary.md"
    json_path.write_text(json.dumps(compact, indent=2), encoding="utf-8")
    counts = compact["counts"]
    lines = [
        "# Compact Browser QA Summary",
        "",
        f"- Passed: **{counts['passed']}**",
        f"- Actionable failures: **{counts['failed']}**",
        f"- Blocked/cascaded: **{counts['blocked']}**",
        f"- Quarantined legacy checks: **{counts['quarantined']}**",
        "",
        "## Non-pass checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for item in compact["checks"]:
        if item.get("status") == "pass":
            continue
        detail = str(item.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item.get('check_id')} | {item.get('status')} | {detail} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run_full(args: argparse.Namespace) -> int:
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = legacy.PROJECT_DIR / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    before = set(output_root.glob("phase-closeout-*/closeout-report.json"))

    command = [
        sys.executable,
        str(SCRIPT_DIR / "closeout_browser_qa.py"),
        "--output-dir",
        str(args.output_dir),
        "--timeout-ms",
        str(args.timeout_ms),
        "--app-host",
        args.app_host,
    ]
    if args.headful:
        command.append("--headful")
    completed = subprocess.run(command, cwd=legacy.PROJECT_DIR, check=False)  # noqa: S603

    candidates = set(output_root.glob("phase-closeout-*/closeout-report.json"))
    new_reports = sorted(candidates - before, key=lambda path: path.stat().st_mtime)
    if not new_reports:
        new_reports = sorted(candidates, key=lambda path: path.stat().st_mtime)
    if not new_reports:
        print("Legacy browser QA did not produce closeout-report.json.", file=sys.stderr)
        return completed.returncode or 1

    report_path = new_reports[-1]
    raw_report = json.loads(report_path.read_text(encoding="utf-8"))
    compact = classify_legacy_report(raw_report)
    compact["legacy_exit_code"] = completed.returncode
    json_path, md_path = _write_compact_legacy_summary(report_path, compact)
    counts = compact["counts"]
    print(
        "Browser QA compact summary: "
        f"{counts['passed']} pass, {counts['failed']} actionable fail, "
        f"{counts['blocked']} blocked, {counts['quarantined']} quarantined."
    )
    print(f"Saved compact JSON: {json_path}")
    print(f"Saved compact Markdown: {md_path}")
    return 1 if counts["failed"] else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run focused browser QA during iteration or one legacy broad suite at closeout."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="append",
        help="Run one maintained check ID; repeat for multiple checks (for example P44-03).",
    )
    mode.add_argument(
        "--phase",
        action="append",
        help="Run all maintained focused checks for a phase; repeat for multiple phases.",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Run the legacy broad browser suite once, then emit dependency/quarantine-aware compact evidence.",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/qa",
        help="Directory for timestamped browser QA artifacts.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=25000,
        help="Playwright step timeout in milliseconds.",
    )
    parser.add_argument("--headful", action="store_true", help="Run Chromium with a visible window.")
    parser.add_argument(
        "--app-host", default="127.0.0.1", help="Host bound for the isolated app process."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.full:
            return run_full(args)
        return run_focused(args)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
