# Current Status

## Current focus

### SQLite corruption recovery

The active blocker is the physically corrupted production SQLite database on
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
  passes (`638 passed`).
- Docker is current on `v1.4.20`, but the untouched production DB is still
  corrupt, so the final F-03 runtime invariant correctly continues to fail on
  `/api/operations/status` with `DatabaseError`.

Per the `AGENTS.md` reversible-change contract, candidate activation is **not an
approval gate** once the maintained tooling has established and verified the
rollback path. The words `production` or `live database` alone do not create an
approval boundary. Codex should continue autonomously with the maintained
recovery flow and stop only if the tooling can no longer prove safe rollback or
would discard non-reconstructible/user data.

The next recovery sequence is:

1. Quiesce the owning Docker service if required by the recovery tool.
2. Activate the validated current-state candidate with the maintained reversible
   recovery tooling; create/verify a fresh rollback bundle as part of activation.
3. Restart the supported Docker runtime using repository-maintained tooling.
4. Run DB QA and the affected API/runtime checks.
5. Run functional QA and require F-01/F-02/F-03 to pass.
6. Run the canonical backend completion gate. If post-activation validation
   fails, restore the verified pre-change SQLite state automatically and validate
   the rollback before continuing investigation.

The incident is not complete until the recovered database is active in the
running Docker service and the deterministic runtime/finalizer gates pass.

### Scheduled-fetch repair

The scheduled-fetch corruption handling and snapshot timestamp repair are
implemented on the experiment branch. The final snapshot recovery regression
covers malformed JSON plus malformed `fetched_at`, `created_at`, and
`updated_at`. Live targeted fetch validation succeeded before the separate
physical SQLite corruption was discovered. Final closeout of this work is
therefore coupled to successful database recovery/runtime validation above.

### Phase 44

Phase 44 remains in implementation under
`docs/plans/phase-44-acceleration-operations-console.md`. Its remaining unrelated
acceptance work includes end-to-end automatic Codex heartbeat pickup/status
readback. Do not let that unrelated item block the SQLite recovery incident.

## Handoff discipline

`current-status.md` is a live short-form handoff, not a historical release ledger
or a second approval-policy layer. Historical completed-release detail belongs in
Git history, `CHANGELOG.md`, and the relevant phase plans. If status text ever
conflicts with `AGENTS.md` safety/autonomy rules, correct the stale status rather
than introducing a new approval boundary.
