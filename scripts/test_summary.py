#!/usr/bin/env python3
"""Print a compact, LLM-friendly summary of a pytest JUnit XML report."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _compact_text(value: str | None, *, max_chars: int) -> str:
    if not value:
        return ""
    value = ANSI_RE.sub("", value)
    lines = [" ".join(line.strip().split()) for line in value.splitlines()]
    lines = [line for line in lines if line]
    text = " | ".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _case_id(case: ET.Element) -> str:
    classname = case.attrib.get("classname", "").strip()
    name = case.attrib.get("name", "").strip()
    return "::".join(part for part in (classname, name) if part) or "<unknown test>"


def _failure_payload(case: ET.Element) -> tuple[str, ET.Element] | None:
    failure = case.find("failure")
    if failure is not None:
        return "FAIL", failure
    error = case.find("error")
    if error is not None:
        return "ERROR", error
    return None


def summarize(
    xml_path: Path,
    *,
    log_path: Path | None = None,
    max_failures: int = 8,
    max_detail_chars: int = 900,
) -> int:
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError) as exc:
        print(f"PYTEST SUMMARY UNAVAILABLE: {exc}")
        if log_path is not None:
            print(f"Full log: {log_path}")
        return 2

    cases = list(tree.getroot().iter("testcase"))
    failures: list[tuple[str, ET.Element, ET.Element]] = []
    skipped = 0
    total_time = 0.0

    for case in cases:
        try:
            total_time += float(case.attrib.get("time", "0") or 0)
        except ValueError:
            pass
        if case.find("skipped") is not None:
            skipped += 1
        payload = _failure_payload(case)
        if payload is not None:
            kind, node = payload
            failures.append((kind, case, node))

    total = len(cases)
    failed = sum(1 for kind, _, _ in failures if kind == "FAIL")
    errors = sum(1 for kind, _, _ in failures if kind == "ERROR")
    passed = max(total - failed - errors - skipped, 0)
    status = "PASS" if not failures else "FAIL"

    print(
        f"PYTEST {status}: {passed} passed, {failed} failed, "
        f"{errors} errors, {skipped} skipped ({total_time:.2f}s test time)"
    )

    for index, (kind, case, node) in enumerate(failures[:max_failures], start=1):
        message = _compact_text(node.attrib.get("message"), max_chars=max_detail_chars)
        detail = _compact_text(node.text, max_chars=max_detail_chars)
        if message and detail.startswith(message):
            detail = detail[len(message) :].lstrip(" :|-")
        print(f"{index}. [{kind}] {_case_id(case)}")
        if message:
            print(f"   message: {message}")
        if detail:
            print(f"   detail: {detail}")

    hidden = len(failures) - max_failures
    if hidden > 0:
        print(f"... {hidden} additional failing test(s) omitted from the compact summary.")

    print(f"JUnit XML: {xml_path}")
    if log_path is not None:
        print(f"Full log: {log_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize pytest JUnit XML without dumping the full test log."
    )
    parser.add_argument("xml_path", type=Path)
    parser.add_argument("--log", dest="log_path", type=Path)
    parser.add_argument("--max-failures", type=int, default=8)
    parser.add_argument("--max-detail-chars", type=int, default=900)
    args = parser.parse_args()

    if args.max_failures < 1:
        parser.error("--max-failures must be at least 1")
    if args.max_detail_chars < 80:
        parser.error("--max-detail-chars must be at least 80")

    return summarize(
        args.xml_path,
        log_path=args.log_path,
        max_failures=args.max_failures,
        max_detail_chars=args.max_detail_chars,
    )


if __name__ == "__main__":
    sys.exit(main())
