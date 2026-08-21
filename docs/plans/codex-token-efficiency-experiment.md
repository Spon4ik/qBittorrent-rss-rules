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
- `scripts/browser_qa.bat` (Windows) and `scripts/browser_qa.sh` (Linux/WSL) are the maintained browser-QA entrypoints for iterative UI work. They prefer the repository virtual environment before falling back to a system interpreter. Use `--check <ID>` for the smallest relevant deterministic scenario or `--phase <N>` for the maintained focused checks in one phase. The first extracted scenario is `P44-03`.
- Use `scripts\browser_qa.bat --full` on Windows or `scripts/browser_qa.sh --full` on Linux/WSL only once at browser closeout. It runs the legacy broad harness once, preserves the raw report, and emits `codex-summary.json` / `codex-summary.md` that distinguish actionable failures from dependency cascades and explicitly quarantined stale contracts.
- Direct `python scripts/browser_qa.py ...` invocation remains available when the caller has deliberately activated the correct project environment, but automation and Codex should prefer the wrapper so a global Python does not silently bypass repo dependencies.
- Dependency-caused checks are reported as `blocked` in the compact evidence instead of being presented as additional root failures. Mechanically stale legacy checks are quarantined conservatively; uncertain semantic failures remain actionable until audited.
- The raw `scripts/closeout_browser_qa.py` command remains available as a compatibility/audit path, but it should not be the iterative debugging loop for a focused UI defect.
- `Finalize-Backend.cmd --no-pause` is the canonical shell-safe backend completion gate: Ruff -> mypy -> pytest -> Docker rebuild -> `/health`. Docker is not rebuilt if deterministic validation fails.
- `Finalize Backend.cmd` remains the human-friendly underlying entrypoint; the hyphenated wrapper avoids PowerShell quoting/call-operator requirements.
- `Update-Docker.cmd` is the canonical shell-safe Docker-only updater. `Update Docker.cmd` remains available for direct human double-click use.

## Browser-QA experiment finding

The first real `v1.4.19` Result-controls experiment exposed a tooling bottleneck rather than a model-routing failure: one focused P44 regression caused the monolithic browser harness to run four times, repeatedly exercising unrelated legacy scenarios and screenshot matrices. The new focused runner makes the efficient path explicit.

Windows / PowerShell:

```powershell
scripts\browser_qa.bat --check P44-03
```

or, for all maintained focused checks in the phase:

```powershell
scripts\browser_qa.bat --phase 44
```

Linux/WSL equivalents use `scripts/browser_qa.sh`.

During iteration, rerun only the relevant focused check/phase. After it passes, run the normal deterministic code gate and, when browser-wide regression coverage is warranted, run the wrapper with `--full` once. Consume the compact summary before opening raw logs or screenshots.

The current quarantine is deliberately narrow. It covers legacy checks whose August 2026 failures are mechanically stale (for example selectors waiting on controls that are present but intentionally hidden, or a removed handoff action). Result-count and other semantic P5/P6 failures are not automatically excused; they remain actionable until separately audited or replaced.

Live Windows validation on 2026-08-21 confirmed the wrapper selected the repository environment and executed only `P44-03`: `PASS P44-03 (2297 ms): OK`. The focused run wrote `logs/qa/browser-focus-20260821T101956Z/browser-qa-report.json` and did not invoke the legacy broad suite. This is the baseline behavior expected for future UI-debugging iterations.

## A/B test protocol

Compare `main` with `experiment/codex-token-efficiency`. Use fresh Codex chats and the same starting repository state for comparable runs.

Recommended scenarios:

1. application-generated Real-Debrid incident with a simple local cause;
2. human-described behavioral bug without an exception;
3. clear feature request whose design is already specified;
4. bounded feature request requiring genuine UX/product invention;
5. long/noisy failure where compact test output should prevent raw-log ingestion;
6. genuinely ambiguous cross-module or runtime bug that should justify `deep_debugger`.

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
| Wall-clock time | | |

## Acceptance criteria

Keep the experiment only if it materially reduces token/credit consumption while preserving correctness and appropriate product/architecture judgment.

A useful initial target is at least a 25% median token/credit reduction on routine debugging and implementation scenarios with no increase in failed or incomplete fixes. Expensive design or deep-debug sessions may cost the same or more when higher-capability work is genuinely required; the expected saving is that those models are not used for routine execution.

Reject or revise the experiment if:

- routine tasks spawn agents that duplicate work the parent could perform;
- a cheap parent frequently misroutes human requests;
- explicit incident requests fail to reach `incident_lead`;
- task owners repeatedly reread the same context after handoffs;
- `deep_debugger` is invoked without a concrete unresolved question;
- compact summaries hide evidence often enough to force repeated full-log reads;
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
