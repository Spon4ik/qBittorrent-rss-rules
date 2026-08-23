#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from cross_surface_contracts import (
    canonical_label_matches,
    classify_endpoint,
    is_internal_endpoint,
    normalize_endpoint,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_DIR / "app" / "templates"
STATIC_DIR = PROJECT_DIR / "app" / "static"
REPORT_PATH = PROJECT_DIR / "logs" / "qa" / "cross-surface-guard.json"

_FORM_RE = re.compile(r"<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"(?P<name>[A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*([\"'])(?P<value>.*?)\2", re.DOTALL)
_BUTTON_RE = re.compile(r"<button\b[^>]*>(?P<body>.*?)</button>", re.IGNORECASE | re.DOTALL)
_FETCH_RE = re.compile(r"(?:window\.)?fetch\(\s*([`\"'])(?P<endpoint>.*?)\1", re.DOTALL)
_POST_METHOD_RE = re.compile(r"method\s*:\s*[\"']POST[\"']", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_JINJA_RE = re.compile(r"\{[%{].*?[}%]\}", re.DOTALL)
_WS_RE = re.compile(r"\s+")

# These families are semantically narrow enough that a common leading verb is a
# reliable cross-surface UX invariant. Broad provider/settings families are still
# classified, but their controls legitimately use verbs such as Test/Connect/Save.
STRICT_LABEL_FAMILIES = frozenset(
    {
        "sync",
        "delete-rule",
        "save-rule",
        "adopt-acceleration",
        "retry-acceleration",
        "ask-codex",
        "dismiss-acceleration",
        "remove-acceleration",
    }
)


@dataclass(frozen=True, slots=True)
class CommandSurface:
    source: str
    line: int
    transport: str
    endpoint: str
    family: str | None
    label: str | None = None
    internal: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    source: str
    line: int
    kind: str
    detail: str


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _attrs(raw: str) -> dict[str, str]:
    return {match.group("name").casefold(): match.group("value") for match in _ATTR_RE.finditer(raw)}


def _visible_text(raw: str) -> str:
    value = _JINJA_RE.sub(" ", raw)
    value = _TAG_RE.sub(" ", value)
    return _WS_RE.sub(" ", value).strip()


def _scan_template(path: Path) -> list[CommandSurface]:
    text = path.read_text(encoding="utf-8")
    surfaces: list[CommandSurface] = []
    for match in _FORM_RE.finditer(text):
        attrs = _attrs(match.group("attrs"))
        if attrs.get("method", "get").casefold() != "post":
            continue
        endpoint = attrs.get("action", "").strip()
        if not endpoint:
            surfaces.append(
                CommandSurface(
                    source=str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                    line=_line_number(text, match.start()),
                    transport="form-post",
                    endpoint="",
                    family=None,
                    label=None,
                )
            )
            continue
        button_match = _BUTTON_RE.search(match.group("body"))
        label = _visible_text(button_match.group("body")) if button_match else None
        normalized = normalize_endpoint(endpoint)
        internal = is_internal_endpoint(normalized)
        surfaces.append(
            CommandSurface(
                source=str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                line=_line_number(text, match.start()),
                transport="form-post",
                endpoint=normalized,
                family=None if internal else classify_endpoint(normalized),
                label=label or None,
                internal=internal,
            )
        )
    return surfaces


def _scan_javascript(path: Path) -> list[CommandSurface]:
    text = path.read_text(encoding="utf-8")
    surfaces: list[CommandSurface] = []
    for match in _FETCH_RE.finditer(text):
        # Keep the window tight enough that a later unrelated fetch cannot donate
        # its method, while covering headers/body setup in ordinary command calls.
        tail = text[match.end() : match.end() + 900]
        if not _POST_METHOD_RE.search(tail):
            continue
        endpoint = normalize_endpoint(match.group("endpoint"))
        internal = is_internal_endpoint(endpoint)
        surfaces.append(
            CommandSurface(
                source=str(path.relative_to(PROJECT_DIR)).replace("\\", "/"),
                line=_line_number(text, match.start()),
                transport="fetch-post",
                endpoint=endpoint,
                family=None if internal else classify_endpoint(endpoint),
                internal=internal,
            )
        )
    return surfaces


def collect_surfaces() -> list[CommandSurface]:
    surfaces: list[CommandSurface] = []
    for path in sorted(TEMPLATE_DIR.glob("*.html")):
        surfaces.extend(_scan_template(path))
    for path in sorted(STATIC_DIR.glob("*.js")):
        surfaces.extend(_scan_javascript(path))
    return surfaces


def evaluate_surfaces(surfaces: list[CommandSurface]) -> list[Finding]:
    findings: list[Finding] = []
    for surface in surfaces:
        if surface.internal:
            continue
        if not surface.endpoint:
            findings.append(
                Finding(surface.source, surface.line, "missing-endpoint", "POST form has no action endpoint.")
            )
            continue
        if surface.family is None:
            findings.append(
                Finding(
                    surface.source,
                    surface.line,
                    "unclassified-command",
                    f"No maintained action family classifies {surface.endpoint!r}.",
                )
            )
            continue
        if (
            surface.transport == "form-post"
            and surface.family in STRICT_LABEL_FAMILIES
            and surface.label
            and not canonical_label_matches(surface.family, surface.label)
        ):
            findings.append(
                Finding(
                    surface.source,
                    surface.line,
                    "inconsistent-command-label",
                    f"{surface.family!r} surface label {surface.label!r} does not use its canonical verb.",
                )
            )
    return findings


def _write_report(surfaces: list[CommandSurface], findings: list[Finding]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    family_counts: dict[str, int] = {}
    for surface in surfaces:
        key = "internal" if surface.internal else (surface.family or "unclassified")
        family_counts[key] = family_counts.get(key, 0) + 1
    REPORT_PATH.write_text(
        json.dumps(
            {
                "status": "pass" if not findings else "fail",
                "surface_count": len(surfaces),
                "family_counts": dict(sorted(family_counts.items())),
                "findings": [asdict(item) for item in findings],
                "surfaces": [asdict(item) for item in surfaces],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    try:
        surfaces = collect_surfaces()
        findings = evaluate_surfaces(surfaces)
        _write_report(surfaces, findings)
    except Exception as exc:  # noqa: BLE001
        print(f"CROSS-SURFACE GUARD ERROR: {exc}", file=sys.stderr)
        return 2

    if findings:
        print(f"CROSS-SURFACE FAIL: {len(findings)} command-contract finding(s).")
        for finding in findings[:12]:
            print(f"- {finding.source}:{finding.line} {finding.kind}: {finding.detail}")
        if len(findings) > 12:
            print(f"- +{len(findings) - 12} more; see {REPORT_PATH.relative_to(PROJECT_DIR)}")
        return 1

    print(f"CROSS-SURFACE PASS: {len(surfaces)} POST command surface(s) classified.")
    print(f"Report: {REPORT_PATH.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
