# Current Status

## Current focus

### SQLite corruption recovery

The SQLite corruption incident is recovered and closed on
`experiment/codex-token-efficiency`.

Deterministic recovery preparation is complete:

- `scripts\db_bundle.bat` provides verified backup/restore bundles for the SQLite
  file family, including relevant sidecars.
- `scripts\db_qa.bat` provides compact deterministic database diagnostics.
- `scripts\db_recover.bat prepare` produced the current-state candidate at
  `logs/qa/db/incident-20260823-014358/current-recovery-2/qb_rules-recovered.db`.
- The candidate contains `355` rules, `341` snapshots, and `628` acceleration
  jobs. It omits only one proven orphan snapshot and one unreadable acceleration
  row that satisfies the maintained reconstructibility policy.
- Candidate DB QA is healthy: integrity check passes, foreign-key violations are
  zero, orphan snapshots are zero, and malformed DateTime findings are zero.
- Recovery-focused tests pass (`17 passed`) and the full deterministic suite
  passes (`647 passed`), including the Docker lifecycle wrapper regressions.
- Routine Docker lifecycle is now implemented through
  `scripts\docker_runtime.bat <status|start|stop|restart>`. It uses an exact
  Docker Desktop executable path, never a shell/open association for the token
  `docker`, waits deterministically for the engine/service health, and writes
  `logs/qa/docker-runtime.json`. Use the existing updater/finalizer for rebuilds.
  The focused regression `tests/test_docker_runtime.py` passes in the full gate.

- `scripts\\db_recover.bat activate` quiesced the owning service, created and
  verified `logs/qa/db/incident-20260823-014358/activation-rollback`, and
  activated the validated candidate. Post-activation DB QA reports `healthy`
  with `355` rules, `341` snapshots, `628` acceleration jobs, zero integrity
  errors, zero foreign-key violations, zero orphan snapshots, and zero
  malformed DateTime values.
- Docker was restarted with the maintained updater and is current on
  `v1.4.20`. Deployed functional QA passes F-01, F-02, and F-03 with zero
  unhandled API exceptions.
- Full-file DB QA is authoritative when the owning writer is quiesced; a scan
  taken concurrently with SQLite writes can report transient page references.

The recovery sequence and completion gate are complete. The verified rollback
bundle remains available if a later post-recovery issue requires reversal.

### Scheduled-fetch repair

The scheduler is operationally healthy after recovery, but the Rules page exposed
a follow-up presentation bug: persisted `last_status=partial` from the historical
275/1 scheduled run was still rendered as the active status even though deployed
F-01/F-02/F-03 and current snapshot freshness were healthy.

The branch now preserves the historical run result while deriving a separate
current scheduled-fetch state from runtime enablement, Jackett readiness, active
progress, and the same scheduled-scope snapshot freshness evidence used by runtime
QA. `runtime_health.js` leads with `Current status` and moves a superseded
`partial`/`error` result to secondary historical context instead of continuing to
present it as a current failure. This deliberately does not claim that a specific
failed rule was retried unless such identity evidence exists.

Generic regressions are added in `tests/test_scheduled_fetch_current_state.py` and
`tests/test_scheduled_fetch_status_ui.py`. This follow-up is not closed until those
focused tests pass, the normal backend gate passes, Docker is current, and the
Rules page/runtime diagnostics show the healthy current state rather than the old
partial result as active status.

### Phase 44

Phase 44 remains in implementation under
`docs/plans/phase-44-acceleration-operations-console.md`. Its remaining unrelated
acceptance work includes end-to-end automatic Codex heartbeat pickup/status
readback. Do not let that unrelated item block the scheduled-fetch status follow-up.

## Handoff discipline

`current-status.md` is a live short-form handoff, not a historical release ledger
or a second approval-policy layer. Historical completed-release detail belongs in
Git history, `CHANGELOG.md`, and the relevant phase plans. If status text ever
conflicts with `AGENTS.md` safety/autonomy rules, correct the stale status rather
than introducing a new approval boundary.
