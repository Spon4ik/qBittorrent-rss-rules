# Codex Token-Efficiency Experiment

## Goal

Measure whether project-scoped task ownership, model specialization, deterministic evidence, and compact tool output reduce Codex token/credit consumption without reducing engineering quality.

This branch is intentionally experimental. Do not merge it based on subjective speed alone.

## Design

The experiment no longer uses a fixed `triage -> explore -> fix -> debug` ladder. Subagents cost additional context and model work, so one appropriately capable task owner should normally handle a task end to end.

The first question is always whether deterministic software can answer the current question. Use tests, assertions, JUnit, API/DB/DOM/state checks, and compact diagnostic scripts before model interpretation.

When model judgment is required, route by task type and uncertainty:

| Task | Preferred parent / owner | Specialist behavior |
| --- | --- | --- |
| Application-generated known incident | Luna/low parent; `incident_lead` is Luna/medium | Explicit route; no classification step |
| Human-reported behavioral bug | Terra/medium | Parent owns directly when already capable; otherwise `investigator` |
| Clear specified feature/change | Terra/medium | Parent owns directly when already capable; otherwise `builder` |
| Bounded open-ended design/invention | Terra/medium parent + `architect` GPT-5.6/high | Architect designs; Terra normally implements |
| Long interactive product/architecture discussion | GPT-5.6/high parent | Keep the high-capability model in the main context |
| Exceptional unresolved causal ambiguity | `deep_debugger` GPT-5.6/xhigh | Read-only; only after a concrete escalation packet |

Known task type beats model classification. The application's maintenance queue now emits `mode=incident` and `route=incident_lead`, so automatic failures do not spend model work deciding what they are.

## Project-scoped agents

- `.codex/agents/incident-lead.toml`: low-cost owner for explicit application-generated incidents; routine/local fixes are allowed.
- `.codex/agents/investigator.toml`: Terra/medium end-to-end owner for unexpected existing behavior.
- `.codex/agents/builder.toml`: Terra/medium end-to-end owner for sufficiently specified implementation work.
- `.codex/agents/architect.toml`: GPT-5.6/high read-only owner for product, UX, feature-concept, redesign, and architecture decisions; returns an implementation-ready design packet.
- `.codex/agents/deep-debugger.toml`: GPT-5.6/xhigh read-only specialist for unresolved competing hypotheses and non-local causal problems.

All custom agents disable recursive delegation. The parent decides whether another dispatch is justified after reading a compact result packet.

`.codex/config.toml` caps subagent concurrency at two and retains Luna/low as the fallback for otherwise unpinned spawned work. The task-owner agents pin their own model and reasoning effort.

## Routing rules

1. Do not delegate simply because a named role exists. If the current parent already has the appropriate capability, let it own the task.
2. Do not run a fixed agent pipeline.
3. Pass the user's original request verbatim to a more capable design/investigation owner whenever possible; do not replace it with a cheaper model's speculative diagnosis.
4. Escalate by uncertainty, not by failure count. A first failed hypothesis or fix is not sufficient reason to invoke `deep_debugger`.
5. Handoffs contain established facts and a specific unresolved question, not repeated raw logs or repository dumps.
6. Use at most two concurrent subagents, and only for genuinely independent work.

Useful result states are `solved`, `design_complete`, `needs_architect`, `needs_deep_debugger`, and `blocked`. Include confidence, evidence, decision/root cause, change surface, validation, unresolved question, and escalation reason only when applicable.

## Deterministic tooling

- `scripts/test.sh` and `scripts/test.bat` capture full pytest output in `logs/tests/pytest-last.log` and print a compact JUnit-derived summary by default.
- `QB_TEST_VERBOSE=1` restores full pytest output only when explicitly needed.
- `scripts/browser_qa.bat` (Windows) and `scripts/browser_qa.sh` (Linux/WSL) are the maintained browser-QA entrypoints. They prefer the repository virtual environment before falling back to a system interpreter.
- `--check <ID>` runs the smallest maintained focused scenario; `--phase <N>` keeps phase-scoped checks available; `--suite ui` runs the reusable deterministic UI-invariants audit without requiring screenshots or LLM vision.
- The UI suite is deliberately class-based rather than screenshot exhaustive. `UI-01` checks representative core pages for document-level horizontal overflow and common action-group safety; `UI-02` checks the rule-header qB-diagnostics closed/open transition for containment, overlap, and unexpected desktop horizontal movement; `UI-03` reuses the maintained Result-toolbar interaction/reflow regression; `UI-04` discovers a bounded set of actionable generic disclosure/menu surfaces across representative pages and checks their closed/open state transitions without re-auditing the stronger dedicated scenarios.
- `scripts/ui_invariants.py` provides reusable DOM/browser assertions for page overflow, element/group visibility and viewport containment, pairwise overlap, action-group safety, and before/after geometry stability. Synthetic unit coverage proves a 1px tolerance passes while a deliberate 3px movement fails deterministically.
- Each general UI scenario records bounded `UI-*-metrics.json` evidence. Screenshots are generated only as failure artifacts for human review and are not the pass/fail oracle. Codex should consume the structured report/metrics before opening an image.
- Focused browser QA runs an isolated temporary application process from the checkout. Its PASS state validates source behavior but does not prove that the user's Docker runtime was rebuilt.
- `scripts/runtime_state.bat` / `scripts/runtime_state.sh` report checkout version/HEAD, worktree and tracked-upstream persistence state, plus deployed `/health` version in `logs/qa/runtime-state.json`. `--require-runtime-current` returns non-zero when the deployed version differs from the checkout; `--require-upstream-synced` is available when pushed persistence is a required closeout condition.
- Use `scripts\browser_qa.bat --full` on Windows or `scripts/browser_qa.sh --full` on Linux/WSL only once at browser closeout. It runs the legacy broad harness once, preserves the raw report, and emits `codex-summary.json` / `codex-summary.md` that distinguish actionable failures from dependency cascades and explicitly quarantined stale contracts.
- Direct Python invocation remains available only when the correct project environment is deliberately activated; automation and Codex should prefer the wrappers so a global Python cannot silently bypass repo dependencies.
- Dependency-caused checks are reported as `blocked` in compact legacy evidence instead of being presented as additional root failures. Mechanically stale legacy checks are quarantined conservatively; uncertain semantic failures remain actionable until audited.
- The raw `scripts/closeout_browser_qa.py` command remains available as a compatibility/audit path, but it should not be the iterative debugging loop for a focused UI defect.
- `Finalize-Backend.cmd --no-pause` is the canonical shell-safe backend completion gate: Ruff -> mypy -> pytest -> Docker rebuild -> runtime freshness verification. If deterministic validation fails, Docker deployment is explicitly `NOT ATTEMPTED` and the checkout/upstream/runtime state is printed instead of implying that a local fix is deployed.
- `Finalize Backend.cmd` remains the human-friendly underlying entrypoint; the hyphenated wrapper avoids PowerShell quoting/call-operator requirements.
- `Update-Docker.cmd` is the canonical shell-safe Docker-only updater. `Update Docker.cmd` remains available for direct human double-click use, but it now requires the same deployed-version freshness check before reporting success.

## Browser-QA experiment finding

The first real `v1.4.19` Result-controls experiment exposed a tooling bottleneck rather than a model-routing failure: one focused P44 regression caused the monolithic browser harness to run four times, repeatedly exercising unrelated legacy scenarios and screenshot matrices. The focused runner removed that repeated broad-suite cost.

Windows / PowerShell targeted iteration:

```powershell
scripts\browser_qa.bat --check P44-03
```

General deterministic UI audit before spending model context on individual visual symptoms:

```powershell
scripts\browser_qa.bat --suite ui
```

Linux/WSL equivalents use `scripts/browser_qa.sh`.

During implementation, rerun only the relevant focused check. For a broad UI cleanup request, run `--suite ui` once, consume its report/metrics, group failures by shared root cause, and only then decide what to fix. Do not attach or inspect screenshots merely to rediscover geometry the browser already reports exactly. After relevant focused/UI checks pass, run the normal deterministic code gate and, when browser-wide regression coverage is warranted, run `--full` once.

The current quarantine is deliberately narrow. It covers legacy checks whose August 2026 failures are mechanically stale. Result-count and other semantic P5/P6 failures are not automatically excused; they remain actionable until separately audited or replaced.

Live Windows validation on 2026-08-21 confirmed the focused wrapper selected the repository environment and executed only `P44-03`: `PASS P44-03 (2297 ms): OK`. The focused run wrote `logs/qa/browser-focus-20260821T101956Z/browser-qa-report.json` and did not invoke the legacy broad suite. This is the baseline behavior expected for future UI-debugging iterations.

The general UI-invariants suite was then implemented and calibrated on Windows before the next visual-fix task. The final calibration produced `PASS UI-01`, the expected deterministic `FAIL UI-02` with measured qB-diagnostics movement of `+572.8px` at 1720px and `+900.8px` at 2048px, `PASS UI-03`, and `PASS UI-04`. The generic interaction audit was tuned from an initial 104-second QA-infrastructure failure to roughly 6-7 seconds by using Playwright's own actionability semantics and skipping disabled controls without waiting on click timeouts.

The first screenshot-free broad UI repair then used the deterministic suite as the source of truth. Codex discovered only `UI-02`, identified the flex-flow root cause, fixed the checkout, and completed the final four-check UI suite in about 10.9 seconds without screenshot or LLM-vision use. The user's displayed weekly allowance moved from about 95% remaining to 93% remaining during this task. That ~2 percentage-point change is useful directional evidence but not a controlled A/B result because the compared UI tasks were not identical and the product meter is coarse.

That run also exposed a separate closeout flaw: the focused/UI suite validated an isolated checkout process, while the release finalizer later stopped on unrelated pytest isolation failures before Docker rebuild. The user's running Docker container therefore remained stale even though Codex summarized the UI repair as complete. The experiment now treats implementation, focused validation, GitHub persistence, Docker deployment, and release/tag as separate states. A blocked release does not imply that validated work should remain uncommitted; conversely, a local UI PASS must never be presented as deployed-runtime evidence.

## A/B test protocol

Compare `main` with `experiment/codex-token-efficiency`. Use fresh Codex chats and the same starting repository state for comparable runs.

Recommended scenarios:

1. application-generated Real-Debrid incident with a simple local cause;
2. human-described behavioral bug without an exception;
3. clear feature request whose design is already specified;
4. bounded feature request requiring genuine UX/product invention;
5. long/noisy failure where compact test output should prevent raw-log ingestion;
6. genuinely ambiguous cross-module or runtime bug that should justify `deep_debugger`;
7. broad UI cleanup driven first by `--suite ui`, without supplying screenshots, to measure whether deterministic layout evidence reduces repeated visual investigations.

Run each representative scenario multiple times when practical.

Record:

| Metric | Main | Experiment |
| --- | --- | --- |
| Task solved correctly | | |
| Input/output tokens or credits | | |
| Parent model/effort | | |
| Spawned agents and models | | |
| Routing/escalation was appropriate | | |
| Full-log reads | | |
| Screenshot interpretations | | |
| Test/tool calls | | |
| Unnecessary files read | | |
| Final completion gate passed | | |
| GitHub persistence state | | |
| Docker deployment state | | |
| Release/tag state | | |
| Wall-clock time | | |

## Acceptance criteria

Keep the experiment only if it materially reduces token/credit consumption while preserving correctness and appropriate product/architecture judgment.

A useful initial target is at least a 25% median token/credit reduction on routine debugging and implementation scenarios with no increase in failed or incomplete fixes. Expensive design or deep-debug sessions may cost the same or more when higher-capability work is genuinely required; the expected saving is that those models are not used for routine execution.

For the UI-invariant layer specifically, keep it only if it catches layout/state regressions with low false-positive cost, reports exact measurements, and lets later UI work begin from deterministic failures rather than screenshot interpretation. It is not intended to prove subjective aesthetics, color quality, or every possible visual property.

Reject or revise the experiment if:

- routine tasks spawn agents that duplicate work the parent could perform;
- a cheap parent frequently misroutes human requests;
- explicit incident requests fail to reach `incident_lead`;
- task owners repeatedly reread the same context after handoffs;
- `deep_debugger` is invoked without a concrete unresolved question;
- compact summaries hide evidence often enough to force repeated full-log reads;
- the UI suite produces enough false positives that models must repeatedly inspect screenshots to understand normal responsive behavior;
- local validation is repeatedly conflated with deployed-runtime state;
- reliability or design quality decreases.

## Manual verbose override

Windows:

```bat
set QB_TEST_VERBOSE=1
scripts\test.bat <pytest args>
```

PowerShell:

```powershell
$env:QB_TEST_VERBOSE = "1"
scripts\test.bat <pytest args>
```

Linux/WSL:

```bash
QB_TEST_VERBOSE=1 scripts/test.sh <pytest args>
```