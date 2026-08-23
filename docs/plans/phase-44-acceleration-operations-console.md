# Phase 44 - Acceleration operations console and variant context

## Status

In implementation. UI/API behavior is implemented and live-smoke-tested; automatic
Codex heartbeat pickup remains pending end-to-end proof after the active task yields.

## Product decision

The global background strip is a progress surface, not an operations console. It
shows only currently queued/running transient work. If acceleration failures need
attention, it shows one compact count linking to `/acceleration`.

`/acceleration` is the centralized torrent-level maintenance screen. It provides:

- problem, active, finished, and all filters;
- torrent-name/hash search;
- full torrent name, provider state/error, update time, and secondary hash reference;
- Retry, Ask Codex, Dismiss, and Remove acceleration actions with explicit scope.

Rule search variants are correlated to acceleration jobs only through exact
infohash equality. A matching card/table row shows current acceleration state and
compact Retry/Ask Codex actions. Category or title inference is forbidden.

## Safety contract

- Retry affects only the exact acceleration job.
- Dismiss changes notification visibility only.
- Remove acceleration removes app-owned web seeds/job state but not torrent/files.
- Ask Codex persists a redacted, deduplicated job request.
- The short hash is diagnostic identity, never a rule label.
- Phase-specific action presentation does not override the repository-wide
  cross-surface action contract: Retry, Ask Codex, Dismiss, and Remove must retain
  the same terminology, destructive meaning, confirmation policy, and feedback
  lifecycle wherever those action families appear.

## Validation status

- The `v1.4.20` qB-diagnostics repair is persisted on the established
  `experiment/codex-token-efficiency` branch. Historical validation showed Docker
  `v1.4.20` and healthy deployed functional QA before the newer cross-surface work;
  that older deployment is not evidence for the current checkout.
- Follow-up `v1.4.20` fixed the deterministic `UI-02` rule-header contract:
  opening qB diagnostics had made the whole disclosure absolute, removing its
  flex slot and shifting the command bar by 573px at 1720px and 901px at
  2048px. The disclosure now keeps its stable header slot while its expanded
  panel overlays. The previous cross-test scheduler/fixture-state leak is also
  repaired: route fixtures stop/join the app-global queues, app shutdown owns the
  same queue lifecycle, and the startup sync thread is joined.
- The reusable UI-invariants audit has been strengthened beyond the earlier bounded
  generic check. `UI-04` exhaustively exercises visible generic disclosures/menus;
  `UI-05` expands ordinary initially closed disclosures, inventories all resulting
  interactive controls across light/dark themes and 390/1180/1720 widths, rejects
  unclassified component families, and checks readability/contrast, clipping,
  containment, keyboard focus, hover/focus states, open-panel occlusion, and
  reversible checkbox behavior.
- `scripts\browser_qa.bat --suite ui` now continues beyond those focused `UI-*`
  checks into `scripts/cross_surface_browser_qa.py`. That audit discovers stable
  application pages from the application's own navigation, applies component and
  computed-palette consistency contracts across pages, inventories action families,
  and accumulates sibling command/control failures rather than stopping at the
  first reported instance.
- Acceleration Retry/Ask Codex/Dismiss/Remove are registered action families under
  `scripts/cross_surface_contracts.py`. The cheap `scripts/cross_surface_guard.py`
  runs in the normal check gate and the browser audit validates rendered command
  terminology/safety/feedback contracts. Semantic inconsistencies discovered by
  those audits are actionable defects, not Phase 44 exceptions.
- The shared rule Language/feed checkbox-dropdown and search-multiselect surfaces
  inherit semantic theme palette styling from `app/static/components.css`. The
  cross-page design-token audit also rejects page-specific foreground/background
  drift in shared form/menu families even when each isolated instance remains
  technically readable.
- All cross-surface/UI strengthening described above is new checkout behavior and
  has not been executed locally by ChatGPT Web. It requires focused unit tests,
  `scripts\check.bat`, `scripts\browser_qa.bat --suite ui`, repair of every
  discovered family inconsistency, the normal completion gate, Docker deployment,
  and current-runtime proof before it can be reported PASS.
- Browser-QA iteration remains venv-aware. Use focused `--check`/`--phase` runs for
  narrow iteration and reserve `--suite ui` for the broader cross-surface UI
  consistency gate; screenshots remain failure evidence, not the primary oracle.
- The real queued Codex request is persisted but has not yet been claimed while
  this owning task is active. Completion still requires status transition and UI
  readback for the unrelated automatic-heartbeat acceptance item.
