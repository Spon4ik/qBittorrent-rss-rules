from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActionContract:
    family: str
    canonical_verb: str
    destructive: bool = False
    long_running: bool = False
    description: str = ""


ACTION_CONTRACTS: dict[str, ActionContract] = {
    "sync": ActionContract(
        "sync",
        "Sync",
        long_running=True,
        description="Synchronize app-owned rule/provider state.",
    ),
    "save-sync": ActionContract(
        "save-sync",
        "Save + Sync",
        long_running=True,
        description="Persist provider settings and immediately run that provider sync.",
    ),
    "fetch-snapshot": ActionContract(
        "fetch-snapshot",
        "Fetch",
        long_running=True,
        description="Fetch or refresh persisted rule-search snapshots.",
    ),
    "create-rule": ActionContract("create-rule", "Create"),
    "save-rule": ActionContract("save-rule", "Save"),
    "save-settings": ActionContract("save-settings", "Save"),
    "save-preferences": ActionContract("save-preferences", "Save"),
    "save-profile": ActionContract("save-profile", "Save"),
    "save-schedule": ActionContract("save-schedule", "Save"),
    "apply-quality": ActionContract("apply-quality", "Apply"),
    "queue": ActionContract("queue", "Queue", long_running=True),
    "metadata-lookup": ActionContract("metadata-lookup", "Lookup", long_running=True),
    "refresh-feeds": ActionContract("refresh-feeds", "Refresh", long_running=True),
    "refresh-view": ActionContract("refresh-view", "Refresh"),
    "import-preview": ActionContract("import-preview", "Preview", long_running=True),
    "import-apply": ActionContract("import-apply", "Apply", long_running=True),
    "taxonomy-add": ActionContract("taxonomy-add", "Add"),
    "taxonomy-move": ActionContract("taxonomy-move", "Move"),
    "taxonomy-remove": ActionContract("taxonomy-remove", "Remove", destructive=True),
    "taxonomy-validate": ActionContract("taxonomy-validate", "Validate"),
    "taxonomy-apply": ActionContract("taxonomy-apply", "Apply"),
    "adopt-acceleration": ActionContract("adopt-acceleration", "Adopt", long_running=True),
    "retry-acceleration": ActionContract("retry-acceleration", "Retry", long_running=True),
    "ask-codex": ActionContract("ask-codex", "Ask", long_running=True),
    "dismiss-acceleration": ActionContract("dismiss-acceleration", "Dismiss"),
    "remove-acceleration": ActionContract(
        "remove-acceleration",
        "Remove",
        destructive=True,
    ),
    "delete-rule": ActionContract("delete-rule", "Delete", destructive=True),
    "provider-command": ActionContract("provider-command", "Run", long_running=True),
}


_INTERNAL_ENDPOINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/debug/"),
)

_ENDPOINT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/api/sync/all(?:\?.*)?$"), "sync"),
    (re.compile(r"^/api/rules/[^/]+/sync(?:\?.*)?$"), "sync"),
    (re.compile(r"^/api/rules/fetch(?:\?.*)?$"), "fetch-snapshot"),
    (re.compile(r"^/api/rules/fetch-schedule/run-now(?:\?.*)?$"), "fetch-snapshot"),
    (re.compile(r"^/api/rules/fetch-schedule(?:\?.*)?$"), "save-schedule"),
    (re.compile(r"^/api/rules/page-preferences(?:\?.*)?$"), "save-preferences"),
    (re.compile(r"^/api/rules/batch-quality-profile(?:\?.*)?$"), "apply-quality"),
    (re.compile(r"^/api/rules/[^/]+/delete(?:\?.*)?$"), "delete-rule"),
    (re.compile(r"^/api/rules/[^/]+(?:\?.*)?$"), "save-rule"),
    (re.compile(r"^/api/rules(?:\?.*)?$"), "create-rule"),
    (re.compile(r"^/api/search/preferences(?:\?.*)?$"), "save-preferences"),
    (re.compile(r"^/api/search/queue(?:\?.*)?$"), "queue"),
    (re.compile(r"^/api/filter-profiles(?:\?.*)?$"), "save-profile"),
    (re.compile(r"^/api/metadata/lookup(?:\?.*)?$"), "metadata-lookup"),
    (re.compile(r"^/api/feeds/refresh(?:\?.*)?$"), "refresh-feeds"),
    (re.compile(r"^/api/acceleration/adopt(?:\?.*)?$"), "adopt-acceleration"),
    (re.compile(r"^/api/acceleration/jobs/[^/]+/retry(?:\?.*)?$"), "retry-acceleration"),
    (re.compile(r"^/api/acceleration/jobs/[^/]+/ask-codex(?:\?.*)?$"), "ask-codex"),
    (re.compile(r"^/api/acceleration/jobs/[^/]+/dismiss(?:\?.*)?$"), "dismiss-acceleration"),
    (re.compile(r"^/api/acceleration/jobs/[^/]+/cleanup(?:\?.*)?$"), "remove-acceleration"),
    (re.compile(r"^/api/(?:import|imports)(?:/.*)?$"), "import-apply"),
    (re.compile(r"^/api/taxonomy/options/add(?:\?.*)?$"), "taxonomy-add"),
    (re.compile(r"^/api/taxonomy/options/move(?:\?.*)?$"), "taxonomy-move"),
    (re.compile(r"^/api/taxonomy/options/remove(?:\?.*)?$"), "taxonomy-remove"),
    (re.compile(r"^/api/taxonomy/validate(?:\?.*)?$"), "taxonomy-validate"),
    (re.compile(r"^/api/taxonomy/apply(?:\?.*)?$"), "taxonomy-apply"),
    (re.compile(r"^/api/settings/sync-(?:jellyfin|stremio)(?:\?.*)?$"), "save-sync"),
    (re.compile(r"^/api/settings/sync-watch-progress(?:\?.*)?$"), "sync"),
    (re.compile(r"^/api/settings/(?:test-[^/]+|real-debrid/(?:connect|disconnect))(?:\?.*)?$"), "provider-command"),
    (re.compile(r"^/api/settings(?:/.*)?$"), "save-settings"),
    (re.compile(r"^/settings(?:/.*)?$"), "save-settings"),
    (re.compile(r"^/api/(?:real-debrid|myjdownloader|jellyfin|stremio|qbittorrent|jackett)(?:/.*)?$"), "provider-command"),
)


_JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}")


def normalize_endpoint(endpoint: str) -> str:
    """Normalize dynamic UI source URLs without retaining concrete IDs."""

    value = str(endpoint or "").strip()
    # The shared rule form selects create/update action with a Jinja block. The
    # source-level guard only needs a safe known-family representative; rendered
    # browser QA checks create and edit pages separately with their actual URLs.
    if "{%" in value and "/api/rules" in value:
        return "/api/rules/{id}"
    value = _JINJA_EXPR_RE.sub("{id}", value)
    value = re.sub(r"\$\{[^}]+\}", "{id}", value)
    return value


def is_internal_endpoint(endpoint: str) -> bool:
    normalized = normalize_endpoint(endpoint)
    return any(pattern.search(normalized) for pattern in _INTERNAL_ENDPOINT_PATTERNS)


def classify_endpoint(endpoint: str) -> str | None:
    normalized = normalize_endpoint(endpoint)
    for pattern, family in _ENDPOINT_PATTERNS:
        if pattern.search(normalized):
            return family
    return None


def refine_family(family: str | None, label: str | None) -> str | None:
    """Refine endpoints whose semantic action is encoded by the submit control."""

    normalized_label = str(label or "").strip().casefold()
    if family == "import-apply" and normalized_label.startswith("preview"):
        return "import-preview"
    if family == "save-rule" and normalized_label.startswith("create"):
        return "create-rule"
    return family


def contract_for_family(family: str) -> ActionContract:
    try:
        return ACTION_CONTRACTS[family]
    except KeyError as exc:
        raise ValueError(f"Unknown cross-surface action family {family!r}.") from exc


def canonical_label_matches(family: str, label: str) -> bool:
    """Check only the shared leading verb; scope/detail text may legitimately differ."""

    contract = contract_for_family(family)
    normalized = str(label or "").strip().casefold()
    return normalized.startswith(contract.canonical_verb.casefold())
