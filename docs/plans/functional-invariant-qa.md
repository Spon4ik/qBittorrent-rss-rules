# Functional invariant QA

## Purpose

Reduce reliance on the user manually discovering functional defects before deterministic automation can reproduce them.

The browser `UI-*` suite covers deterministic layout and interaction contracts. The functional `F-*` suite is the corresponding deployed-runtime layer for behavioral/state contracts that are not primarily visual.

A new bug should not require inventing a new testing mechanism. New coverage should normally be a small invariant added to the shared runner and backed by reusable runtime telemetry or an existing API/DB contract.

## Layers

1. **Unit/integration contracts** - pytest proves local algorithms, routes, persistence, and lifecycle behavior in isolated test state.
2. **Deployed-runtime invariants** - `scripts/functional_qa.bat --suite core` (or `.sh`) reads bounded, secret-free runtime diagnostics and proves important live state contracts without screenshots or raw logs.
3. **Pre-deploy evidence capture** - `Finalize-Backend.cmd --no-pause` first runs the core suite in non-gating observation mode before it changes Docker. This preserves evidence from the currently running runtime so a restart cannot erase the defect being investigated.
4. **Post-deploy gate** - after Docker rebuild and runtime-version freshness, the finalizer runs the core functional suite as a gate. A current Docker deployment can therefore still fail closeout when live functional behavior is wrong.
5. **Periodic in-app watchdog** - implemented on `experiment/codex-token-efficiency`. The running application evaluates the same shared `F-*` contracts every five minutes by default, tracks consecutive failures and recovery, and promotes a check to an in-memory structured incident after three consecutive failures. It is an independent runtime service, controlled by `QB_RULES_ENABLE_FUNCTIONAL_WATCHDOG` and `QB_RULES_FUNCTIONAL_WATCHDOG_INTERVAL_SECONDS`, so it can detect an enabled persisted schedule whose scheduler runtime feature is itself disabled. The watchdog is read-only: it classifies runtime state but does not rewrite credentials, provider configuration, schedules, or historical failure records.
6. **Runtime-aware status reconciliation** - the diagnostics payload carries a process `runtime.instance_id` and `runtime.started_at`, while scheduler telemetry exposes its own `started_at`. The Rules page reads those diagnostics and can distinguish a failure produced by the current runtime from historical state inherited from a replaced container. A known previous-runtime Jackett-readiness error is rendered as recovered/awaiting verification when the current runtime deterministically resolves Jackett successfully; the original persisted error remains intact for diagnostics.
7. **Safe synthetic provider probes** - add only where a real external-provider contract cannot be inferred from internal state. Probes must be read-only or explicitly non-destructive and must respect provider quotas.

## F-01 - Scheduled fetch liveness

`F-01` covers the scheduled rule-fetch state machine rather than the rendered status text.

Runtime evidence is exposed at `GET /api/diagnostics/runtime` under `components.scheduled_rule_fetch`:

- persisted schedule enabled/interval/last-run/next-run state;
- runtime feature-switch state (`QB_RULES_ENABLE_RULE_FETCH_SCHEDULER`);
- scheduler thread creation/liveness;
- scheduler start time and poll interval;
- tick-in-progress state;
- last tick start/completion time;
- last tick result;
- secret-free last exception type;
- schedule overdue duration.

The invariant behaves as follows:

- intentionally disabled schedule -> `SKIP`;
- enabled persisted schedule with runtime scheduler disabled -> `FAIL`;
- scheduler thread not running -> `FAIL`;
- swallowed scheduler exception -> `FAIL`;
- no/recently stale tick evidence -> `FAIL`;
- next run overdue beyond a bounded polling grace -> `FAIL`;
- an active scheduler tick -> `PENDING`, never an immediate `PASS`;
- a tick running longer than the bounded active-work limit -> `FAIL`;
- post-deploy runner polls `PENDING` checks until they settle or the settle timeout expires;
- recent healthy completed tick with a non-overdue next run -> `PASS`.

The endpoint and runner are read-only. F-01 does not trigger a fetch or mutate schedule state.

The first live calibration exposed why this distinction matters: rebuilding Docker restarted the overdue scheduler and the initial implementation reported PASS merely because the catch-up tick was active. That was too weak; a hung tick would also have passed. The runner now treats active work as provisional and the finalizer captures the pre-rebuild runtime before restart.

## F-02 - Scheduled fetch effectiveness

`F-02` separates useful scheduled work from mechanical scheduler liveness.

It consumes only bounded runtime state:

- whether the schedule is enabled;
- current Jackett app-search readiness after environment/DB resolution;
- persisted last scheduled status/run time;
- current runtime instance/start time.

The invariant behaves as follows:

- intentionally disabled schedule -> `SKIP`;
- current runtime cannot resolve required Jackett app search -> `FAIL`;
- latest scheduled run belongs to the current runtime and has `error` status -> `FAIL`;
- previous-runtime Jackett-readiness error plus currently healthy readiness -> `PASS` with `effectiveness_state=recovered_historical`;
- other previous-runtime errors plus healthy current prerequisites -> non-incident historical/degraded state, retained for diagnostics until a current runtime run verifies recovery;
- `partial` remains effective but degraded rather than being confused with scheduler failure;
- ready runtime with no completed scheduled run yet -> `PASS` as `ready_not_run`.

The persisted last error is never deleted just to make QA green. Reconciliation changes the effective presentation only when the current deterministic state proves that a known historical readiness condition is no longer true.

## Watchdog incident contract

The in-app watchdog runs the shared `CHECKS` registry rather than a second copy of the logic. For each check it records:

- current result and bounded metrics;
- observed time;
- consecutive failures;
- first/last failure time;
- recovery time;
- whether the persistent-failure incident threshold is active.

Three consecutive failures activate an incident. A later non-failing observation clears the active incident and records recovery. `GET /api/diagnostics/runtime` exposes the current watchdog state under `functional_watchdog`; it also exposes an instantaneous `invariants` snapshot so CLI, browser status reconciliation, and the watchdog are all explainable from the same evidence.

Automatic Codex dispatch is deliberately not part of this step. Phase 44 still requires end-to-end heartbeat pickup/status readback proof before persistent functional incidents should be allowed to create autonomous maintenance work.

## Extension contract

Future functional checks should use IDs `F-03`, `F-04`, ... and be registered in `app/services/functional_invariants.py`. Prefer subsystem-level contracts over symptom-specific assertions. Good candidates include:

- background worker/scheduler liveness;
- queue work that must eventually leave `queued/running`;
- persisted-vs-provider reconciliation invariants;
- stale synchronization timestamps beyond configured service-level expectations;
- required configuration present but runtime service disabled;
- lifecycle resources that survive shutdown/restart unexpectedly;
- data freshness/monotonicity contracts;
- safe provider reachability/capability checks.

Do not add an invariant merely because a particular string or screenshot changed. Assert the underlying product contract.

## Output contract

The CLI runner prints one compact line per invariant and writes `logs/qa/functional-*/functional-qa-report.json` containing exact bounded metrics. On failure, Codex should consume this JSON before reading full logs or requesting screenshots.

`--observe-only --settle-timeout 0` captures the instantaneous state without failing the caller. Normal post-deploy execution waits for provisional checks to settle and fails if they remain unresolved beyond the configured timeout.

A functional-suite failure after Docker rebuild means:

- local deterministic validation may be green;
- Docker deployment may be current;
- application behavior is still not accepted.

Those states must remain separate in closeout reporting.
