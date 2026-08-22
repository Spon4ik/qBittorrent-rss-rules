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
6. **Runtime-aware status reconciliation** - the diagnostics payload carries a process `runtime.instance_id` and `runtime.started_at`, while scheduler telemetry exposes its own `started_at`. The Rules page reads those diagnostics and can distinguish a failure produced by the current runtime from historical state inherited from a replaced container. A known previous-runtime Jackett-readiness error is rendered as recovered/awaiting verification only when current deterministic evidence is healthy; stale or missing rule snapshots now prevent that optimistic recovery state.
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

## F-02 - Scheduled fetch effectiveness and snapshot freshness

`F-02` separates useful scheduled work from mechanical scheduler liveness. Provider readiness by itself is not enough: scheduled fetching is effective only when the in-scope rule snapshots are actually kept current.

It consumes bounded runtime state:

- whether the schedule is enabled;
- current Jackett app-search readiness after environment/DB resolution;
- persisted last scheduled status/run time;
- current runtime instance/start time;
- scalar snapshot-freshness aggregates for the exact scheduled rule scope.

Snapshot freshness is computed without materializing `payload` or `inline_search` JSON. Runtime diagnostics join the in-scope rules to `rule_search_snapshots` and read only aggregate/count values and `fetched_at`. This preserves the corruption isolation established by the F-01 repair: malformed legacy snapshot JSON cannot break the freshness check itself.

The scope matches scheduled fetch behavior: `enabled` includes only enabled rules; `all` includes manually disabled rules; completion-auto-disabled movie/Jellyfin rules are excluded in either case. A snapshot is stale after two configured schedule intervals. The two-interval window is deliberately conservative to avoid treating a single slightly late run as stale data; the five-minute watchdog still promotes a continuing violation after three observations.

The invariant behaves as follows:

- intentionally disabled schedule -> `SKIP`;
- current runtime cannot resolve required Jackett app search -> `FAIL`;
- latest scheduled run belongs to the current runtime and has `error` status -> `FAIL`;
- current runtime advertises snapshot-freshness telemetry but omits it -> `FAIL`;
- after any completed scheduled run, one or more in-scope snapshots are missing or older than two configured intervals -> `FAIL` with `effectiveness_state=stale_snapshots` and bounded counts/timestamps;
- previous-runtime Jackett-readiness error plus currently healthy readiness -> `PASS` with `effectiveness_state=recovered_historical` only when snapshot freshness is also healthy;
- other previous-runtime errors plus healthy current prerequisites -> non-incident historical/degraded state only when snapshot freshness is healthy;
- `partial` remains effective-but-degraded only while snapshots satisfy the freshness contract;
- ready runtime with no completed scheduled run yet -> `PASS` as `ready_not_run`.

The persisted last error is never deleted just to make QA green. Reconciliation changes the effective presentation only when current deterministic state proves both provider readiness and data freshness.

The Rules page consumes the instantaneous F-02 result every minute. An F-02 failure is shown immediately as `runtime warning`, before the watchdog's persistence threshold. If the same failure remains for three watchdog observations, the existing persistent-incident path escalates the presentation to `runtime problem`. Codex is not required to discover that the snapshots are stale.

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

## Live validation - 2026-08-21

The first end-to-end deployment on `experiment/codex-token-efficiency` validated the intended historical-error reconciliation contract against the real Jackett incident. Before deployment, the observation-only functional baseline preserved the old container's state: F-01 passed while F-02 failed with `effectiveness_state=unhealthy_readiness`, `jackett_app_ready=false`, and no runtime identity fields because that container predated the new diagnostics.

After the deterministic project gate passed (`603 passed`, Ruff clean, mypy clean), `Finalize-Backend.cmd --no-pause` rebuilt only `qb-rss-rules`, verified `/health` on `v1.4.20`, confirmed the deployed runtime matched checkout commit `107fc6a0`, and then ran the live core functional suite. The post-deploy result was:

- `PASS F-01`: scheduler alive, recent ticks, non-overdue next run;
- `PASS F-02`: the previous-runtime Jackett-readiness error was retained as historical evidence while the current runtime resolved Jackett successfully and had not reproduced the failure.

That calibration proved runtime-aware historical reconciliation, but the 2026-08-22 observation exposed an important missing effectiveness dimension: the UI could say `ready` while rule snapshots such as the reported 2026-08-13 snapshot were still far older than the daily schedule. F-02 now requires snapshot freshness as well as readiness so that state cannot silently recur.

## Extension contract

Future functional checks should use IDs `F-04`, `F-05`, ... and be registered in `app/services/functional_invariants.py`. Prefer subsystem-level contracts over symptom-specific assertions. Good candidates include:

- background worker/scheduler liveness;
- queue work that must eventually leave `queued/running`;
- persisted-vs-provider reconciliation invariants;
- stale synchronization timestamps beyond configured service-level expectations;
- required configuration present but runtime service disabled;
- lifecycle resources that survive shutdown/restart unexpectedly;
- additional data freshness/monotonicity contracts not already owned by F-02;
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
