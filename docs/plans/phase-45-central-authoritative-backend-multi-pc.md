# Phase 45 - Central authoritative backend and multi-PC access

## Status

Planned only. Do not start implementation from the `experiment/codex-token-efficiency`
work itself. This planning branch is stacked on that experiment because the experiment
contains the current roadmap and Phase 44 state. After the experiment is merged into
`main`, rebase this branch onto the updated `main` before implementation.

Phase 44 closeout remains the current execution priority. The real automatic `Ask Codex`
heartbeat pickup/status-readback path must be validated before Phase 44 is considered
closed.

## Problem

The same private rules and runtime database need to be usable from more than one PC.
Synchronizing the live SQLite files through Git, OneDrive, Google Drive, Resilio,
Syncthing, or another file replicator would create an unsafe distributed-file problem:
SQLite database/WAL/SHM state can be copied at different moments and two machines can
produce conflicting writers.

The application already has the right architectural boundary for a safer solution: a
FastAPI backend owns persistence and provider operations, while the WinUI shell is a
WebView client. The desktop also already accepts an HTTP/HTTPS backend override through
`QB_RSS_DESKTOP_URL` and validates `/health` contract/version/capabilities.

## Product decision

Use one authoritative qB RSS Rules backend and one authoritative SQLite database. Other
PCs are clients of that backend; they do not receive or synchronize a writable copy of
`qb_rules.db`.

The preferred deployment is the always-on NUC/Docker instance:

```text
PC 1 WinUI/Web ─┐
                ├── private network / VPN ──> NUC Docker FastAPI ──> data/qb_rules.db
PC 2 WinUI/Web ─┘                                      │
                                                       ├── qBittorrent
                                                       ├── Jackett
                                                       ├── Real-Debrid
                                                       ├── Jellyfin
                                                       └── Stremio/provider state
```

A rule changed from either PC is therefore immediately the same persisted rule seen by
the other PC. "Sync" occurs through normal backend transactions/API reads rather than
through database-file replication.

## Architecture contract

### Authoritative host

- Exactly one normal production backend owns the writable SQLite database.
- Keep `data/qb_rules.db` as runtime data and keep the existing Docker bind-mount/data
  location contract; do not commit the database to the public repository.
- qBittorrent, Jackett, Real-Debrid, Jellyfin, Stremio synchronization, schedulers,
  acceleration jobs, snapshots, and other provider/runtime work execute on the
  authoritative host, not on each desktop client.
- Existing local/single-PC operation remains supported. Remote mode is opt-in rather
  than a replacement for the current managed-local-backend behavior.

### WinUI client mode

- Promote the existing `QB_RSS_DESKTOP_URL` capability into a first-class connection
  mode instead of requiring an environment-variable-only setup.
- Persist the selected backend endpoint in desktop-local configuration, not in the
  server database; a client must know where the server is before it can read server
  settings.
- Preserve `QB_RSS_DESKTOP_URL` as an explicit override for development/automation.
- Distinguish two modes clearly:
  - **Local managed backend**: current loopback behavior, including automatic startup
    and local engine controls.
  - **Remote authoritative backend**: connect only to the configured remote endpoint.
- In remote mode, an unreachable backend must fail closed as "remote backend
  unavailable". It must never attempt to start a local Python backend bound to the
  remote hostname.
- Hide or disable local-only Start/Restart/Shut Down Engine actions while connected to a
  remote authoritative backend. A client must not imply that it controls the remote
  host process lifecycle unless a separate authenticated server-management feature is
  deliberately designed later.
- Disable repo-local freshness watching/reload assumptions for remote mode; local source
  edits on a client are unrelated to the deployed remote backend.
- Continue validating `/health` contract, app version, and capabilities before loading
  the WebView. Do not silently connect to an incompatible backend.

### Browser client mode

- A browser may use the same authoritative backend URL directly; it must observe the
  same rules/state as WinUI because both are only clients of the backend.
- Server-side settings that contain filesystem paths remain paths on the authoritative
  host. UI wording should not make a remote user think a client-local path will be read
  by the server.

### Network and security

Remote access must not turn the current local application into an unauthenticated
public Internet service.

Preferred initial transport:

- use a private overlay/VPN such as Tailscale or WireGuard, or an equivalently restricted
  private network/firewall policy;
- expose the backend only to the intended private interface/clients;
- do not add router port-forwarding or a public `0.0.0.0` exposure as the default path;
- keep provider credentials and integration secrets server-side; clients should not
  receive them merely because they can render the application UI.

Before supporting unrestricted LAN or Internet-reachable access, add an explicit
application-authentication design and CSRF/session protections appropriate to the
server-rendered UI and write endpoints. Network location alone must not accidentally
become a long-term authorization model.

## Implementation slices

### Slice 1 - Formal remote desktop connection mode

1. Add a small desktop-local connection configuration model with local-managed and
   remote-authoritative modes.
2. Keep `QB_RSS_DESKTOP_URL` as the highest-priority explicit override.
3. Make auto-start/restart/shutdown/freshness behavior conditional on local-managed
   mode.
4. Improve offline/incompatible-backend messaging so a remote connection failure does
   not recommend starting a local backend.
5. Add focused unit/source tests around configuration resolution and lifecycle guards.

### Slice 2 - Private-host deployment contract

1. Document the authoritative NUC/Docker topology and supported private-network
   exposure.
2. Add deterministic health/connectivity diagnostics that report endpoint, contract,
   version, and capabilities without logging credentials.
3. Make the intended listen/publish interface explicit in deployment documentation and
   prevent accidental public exposure in the recommended configuration.
4. Verify server-side provider paths and Docker host-path translation continue to be
   resolved on the NUC host.

### Slice 3 - Multi-client behavior and regression coverage

1. Connect two independent client sessions to the same authoritative backend.
2. Create/edit/delete a test rule from one client and prove the other client sees the
   persisted change after normal refresh/navigation without copying any DB file.
3. Exercise simultaneous non-destructive reads and representative writes so SQLite
   concurrency remains bounded inside the single backend host.
4. Prove remote clients do not create/use a local `data/qb_rules.db`, launch a managed
   Python backend, or run duplicate schedulers/provider synchronization.
5. Reconnect a client after network interruption and verify authoritative state is
   recovered from the server rather than from stale client state.

### Slice 4 - Safe backup follow-up

Multi-PC access and backup are separate concerns. Do not solve backup by synchronizing
the live SQLite file.

- Add/retain a consistent SQLite backup/snapshot path that runs on the authoritative
  host.
- Only completed backup artifacts may be copied to OneDrive, Google Drive, NAS,
  Resilio/Syncthing, or another backup target.
- A later logical rules/config export may use a private repository if useful, but it is
  not the live synchronization mechanism and secrets must not be committed in
  plaintext.

## Deterministic validation

The phase is not complete until the following are proven:

- one authoritative database contains the expected rule count before and after remote
  client operations;
- a rule mutation from PC/client A is visible from PC/client B through the backend with
  no file-copy step;
- remote mode never starts, restarts, or shuts down a local backend as a fallback;
- remote mode never reads or writes a client-local `qb_rules.db`;
- the authoritative host remains the only scheduler/provider-operation owner;
- incompatible backend contract/version/capability checks still fail closed;
- temporary network loss does not corrupt or fork state;
- no credential/token/private provider payload appears in client diagnostics or logs;
- the recommended deployment is unreachable from unintended public interfaces;
- local-managed mode still passes its existing desktop startup/shutdown/reconnect
  regression coverage;
- the full backend gate, WinUI build, and relevant browser/live Docker checks pass.

## Explicit non-goals

- Bidirectional SQLite file synchronization.
- Committing rules/database/secrets to the public GitHub repository.
- Multi-user accounts, RBAC, or collaborative conflict resolution in this phase.
- Public cloud hosting as the default deployment.
- Remote process administration beyond ordinary application/API use.
- Replacing SQLite solely to obtain multi-PC access; a single authoritative host avoids
  that requirement.

## Later extensions

After the central-backend model is stable, evaluate independently:

- application-level authenticated LAN access without requiring an overlay VPN;
- encrypted logical rules/config export to a private repository;
- automated off-host SQLite snapshots with retention/restore testing;
- a client connection selector/status surface with discovered/recent endpoints;
- contract-compatible desktop/backend version skew if exact-version coupling becomes a
  maintenance burden.
