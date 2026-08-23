from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import ui_invariants as ui

# These families are intended to inherit one shared palette contract across pages.
# Geometry can legitimately vary with compact/responsive presentation, so this
# layer compares design tokens rather than demanding pixel-identical dimensions.
STRICT_PALETTE_FAMILIES = frozenset(
    {
        "checkbox-dropdown",
        "search-multiselect",
        "native-select",
        "input",
        "textarea",
    }
)


@dataclass(frozen=True, slots=True)
class PaletteObservation:
    bucket: str
    signature: tuple[str, str]
    label: str


def palette_bucket(
    control: Mapping[str, Any],
    *,
    theme: str,
    state: str,
) -> str | None:
    family = str(control.get("family") or "").strip()
    if family not in STRICT_PALETTE_FAMILIES:
        return None
    disabled = "disabled" if bool(control.get("disabled")) else "enabled"
    subtype = ""
    if family == "input":
        subtype = str(control.get("type") or "text").strip().casefold() or "text"
    return ":".join(item for item in (theme, family, subtype, disabled, state) if item)


def palette_signature(metric: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(metric.get("color") or "").strip(),
        str(metric.get("background") or "").strip(),
    )


def add_palette_observation(
    observations: list[PaletteObservation],
    *,
    control: Mapping[str, Any],
    metric: Mapping[str, Any],
    theme: str,
    state: str,
    label: str,
) -> None:
    bucket = palette_bucket(control, theme=theme, state=state)
    if bucket is None:
        return
    observations.append(
        PaletteObservation(
            bucket=bucket,
            signature=palette_signature(metric),
            label=label,
        )
    )


def assert_palette_consistency(
    observations: Sequence[PaletteObservation],
) -> None:
    by_bucket: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(lambda: defaultdict(list))
    for observation in observations:
        by_bucket[observation.bucket][observation.signature].append(observation.label)

    failures: list[str] = []
    for bucket, signatures in sorted(by_bucket.items()):
        if len(signatures) <= 1:
            continue
        variants: list[str] = []
        for signature, labels in sorted(signatures.items(), key=lambda item: item[0]):
            sample = ", ".join(labels[:2])
            variants.append(f"{signature} at {sample}")
        failures.append(f"{bucket}: " + " | ".join(variants[:4]))

    if failures:
        suffix = "" if len(failures) <= 6 else f"; +{len(failures) - 6} more"
        raise ui.UIInvariantError(
            "Shared component palette drift detected: " + "; ".join(failures[:6]) + suffix
        )
