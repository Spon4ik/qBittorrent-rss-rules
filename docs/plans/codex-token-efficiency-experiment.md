# Codex Token-Efficiency Experiment

## Goal

Measure whether the project-scoped Codex routing and compact test-output changes reduce token/credit consumption without reducing debugging success.

This branch is intentionally experimental. Do not merge it based on subjective speed alone.

## What changes on this branch

- `.codex/config.toml` caps spawned subagents at two concurrent threads and defaults spawned work to Luna/low.
- `.codex/agents/test-triage.toml` handles routine deterministic failure triage.
- `.codex/agents/explorer.toml` maps the narrow code path with Terra/medium.
- `.codex/agents/fixer.toml` applies focused fixes with Terra/medium.
- `.codex/agents/debugger.toml` reserves GPT-5.6/high for unresolved root-cause work.
- `scripts/test.sh` and `scripts/test.bat` capture full pytest output to `logs/tests/pytest-last.log` but print only a compact JUnit-derived summary by default.
- `QB_TEST_VERBOSE=1` restores the full pytest log to stdout when a human or agent explicitly needs it.
- `AGENTS.md` defines when to stay deterministic, when to delegate, and when to escalate.

## Routing hypothesis

Use the cheapest layer that can answer the current question:

1. deterministic command/test/assertion;
2. `test_triage` for routine failure classification;
3. `explorer` only when code ownership or execution path is unclear;
4. `fixer` after the failure mode is understood;
5. `debugger` only when competing hypotheses or non-local causality remain.

Do not automatically run every layer.

## A/B test protocol

Compare `main` with `experiment/codex-token-efficiency`.

For each scenario, start from the same commit state and use the same user prompt and parent model/intelligence setting. Use a fresh Codex chat for each run.

Recommended scenarios:

1. one deliberately failing unit test with a local cause;
2. one failure that produces a long traceback/log;
3. one cross-module backend bug requiring code-path exploration;
4. one UI behavior bug that can mostly be checked with DOM/API assertions;
5. one genuinely ambiguous bug expected to justify escalation to the `debugger`.

Run each scenario at least three times per branch if practical.

Record:

| Metric | Main | Experiment |
| --- | --- | --- |
| Task solved correctly | | |
| Input/output tokens or credits | | |
| Number of spawned subagents | | |
| Number of full-log reads | | |
| Number of screenshots interpreted | | |
| Test/tool calls | | |
| Wall-clock time | | |
| Unnecessary files read | | |

## Acceptance criteria

Keep the experiment only if it materially reduces token/credit consumption while preserving correctness.

A useful initial threshold is at least a 25% median reduction on routine debugging scenarios with no increase in failed or incomplete fixes. Hard debugging may cost the same or more when the GPT-5.6 debugger is correctly escalated; that is acceptable if escalation is rare and improves correctness.

Reject or revise the experiment if:

- subagents are spawned for routine work that a single deterministic command could resolve;
- the compact summary hides evidence often enough to cause repeated log reads;
- model routing creates more duplicated exploration than it saves;
- the two-thread cap materially harms independent read-heavy work without meaningful cost savings;
- fixes become less reliable.

## Manual override

Use full output only when needed.

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
