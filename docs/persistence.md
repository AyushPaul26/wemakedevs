# Durable storage and offline recovery

The active `render.yaml` still selects the free service and temporary storage. Its
replacement containers lose user changes. The image declares
`RELAY_STORAGE_MODE=ephemeral`, permits initialization only of an entirely new
graph with no existing private files, and never seeds an existing legacy graph.
No paid resource or active Render setting was changed by this preparation.

`deploy/render-persistent.yaml` is a separate **review-only paid** Blueprint. It
selects one Starter instance and a 10 GB persistent disk at `/app/.data`, with
automatic deployment off. Before activation, obtain the current account-specific
Starter and disk quote in Render's dashboard, record the monthly service/disk
totals, and obtain the owner's paid-hosting approval. No current price has been
verified here. Do not import or sync this Blueprint as a routine test. Provider
references: [persistent disks](https://render.com/docs/disks),
[Blueprint specification](https://render.com/docs/blueprint-spec), and
[pricing](https://render.com/pricing).

The review Blueprint also requests operator-supplied `FORWARDED_ALLOW_IPS`.
Verify the actual ingress proxy ranges/header handling and real HTTPS same-origin
sign-in before claiming hosted readiness; no wildcard trust or Render ingress
range is assumed. See [HTTPS proxy trust](deployment.md#https-proxy-trust-before-hosted-session-verification).

Set `RELAY_STORAGE_MODE=persistent` for a durable deployment. Missing storage
fails startup unless an operator explicitly requests first installation. The
data root contains `graph/`, `checkpoints.sqlite`, `uploads/`, `artifacts/`,
`backups/`, and private `storage.json`. The marker binds the mount to the graph's
storage identity. Startup verifies the schema, migration checksum, checkpoint
integrity, and every referenced upload/report hash before starting the API.
Wrong/newer schemas, incomplete migration, mismatched mounts, missing directories
or checkpoint files, and damaged referenced files prevent startup. Readiness
does not modify these records.

The container runs as UID/GID 10001. Named Docker volumes initialize from the
image-owned `/app/.data`; bind mounts and provider disks must be writable by that
identity before boot. Keep files private (directories 0700, files 0600). The
container never changes permissions on an unrelated host directory. Only expose
the web port; the embedded graph binds to loopback. Use one instance and one
executor, and allow 60 seconds for orderly API/executor/database shutdown.

## First installation

Use a newly chosen graph and private directory. On a quiesced development target:

```sh
RELAY_FALKORDB_GRAPH=relay_new RELAY_DATA_DIR=/absolute/private/relay-new \
  .venv/bin/python scripts/startup.py --initialize --quiesced
```

This seeds the versioned fictional fixture once, creates a quiesced backup,
restores that backup on an isolated graph, applies the explicit migration, and
checks readiness. It never overwrites an existing graph. Execution remains off.
Repeated initialization against the same valid marker is read-only.

For the separately approved persistent Render service, set
`RELAY_INITIALIZE_DATA=1` for the first empty-disk boot, then remove it or set it
to `0`. The review Blueprint defaults to `0` deliberately. A missing/unmounted
disk must not be mistaken for a new production workspace. The local optional
Compose profile follows the same contract:

```sh
RELAY_INITIALIZE_DATA=1 docker compose --profile persistent up -d relay-persistent
```

Supply `RELAY_ACCESS_PASSWORD` securely through the existing environment (at least
16 characters); do not put it in command arguments. This profile retains all
private data in `relay-private-data` and keeps the existing development database
volume unchanged. Do not run `docker compose down -v` on retained data.

## Existing data and upgrades

Stop all API and executor writers first, including any old binary. An assertion
flag cannot stop a process. Keep the selected graph name and private directory;
never clear or seed a graph to repair migration.

```sh
.venv/bin/python scripts/migrate.py --check
.venv/bin/python scripts/startup.py --upgrade --quiesced
.venv/bin/python scripts/startup.py --check
```

`--upgrade` preflights, saves a private consistent snapshot of graph, SQLite and
files, verifies isolated restoration, and invokes `MigrationService.apply`.
An already complete supported schema is a no-op. A failed/interrupted upgrade
stays offline; inspect the retained manifest and resume explicitly using
`--upgrade --quiesced --backup-manifest /absolute/path/manifest.json`.
For embedded hosted data, setting `RELAY_UPGRADE_DATA=1` requests that same offline
procedure before any HTTP process starts. Remove it after the successful upgrade.
No health request or ordinary application lifespan applies a migration.

If migration was performed separately, register the verified current storage:

```sh
.venv/bin/python scripts/startup.py --adopt-storage --quiesced
```

Adoption requires an existing checkpoint; it refuses to manufacture a replacement
for a missing one. `RELAY_CHECKPOINT_PATH` remains an explicit runtime override.
When it points outside the data root, adoption/readiness verify that exact file,
but the root-only backup helper cannot capture it. Offline initialization/upgrade
therefore refuses an external override: preserve that checkpoint separately and
place it inside the root for a consistent migration, or supply a separately
verified operator recovery procedure. This limitation prevents falsely claiming
that the external file was backed up.

Migration leaves `execution_enabled=false`. After application verification, opt
in explicitly while writers are stopped, then restart:

```sh
.venv/bin/python scripts/startup.py --adopt-storage --quiesced --enable-execution
```

Ordinary startup preserves the authoritative flag. Restores always turn it off.
The bootstrap owner uses `RELAY_ACCESS_PASSWORD` only for first-account creation;
Finance accounts/reviewer assignment are separate explicit administration.

## Provision members and the Finance reviewer

Run these commands from the repository root against the intended migrated graph.
Use the same `RELAY_FALKORDB_HOST`, `RELAY_FALKORDB_PORT` and
`RELAY_FALKORDB_GRAPH` as the application. To select a graph explicitly, place
`--graph 'your-graph-name'` before the CLI subcommand. This local administrator
tool needs trusted database access; it is not a public signup endpoint.

On the first application startup, when no members exist,
`RELAY_BOOTSTRAP_ADMIN_LOGIN` (default `owner`) and the securely configured
`RELAY_ACCESS_PASSWORD` provision the initial administrator. Existing accounts
are preserved. Seeded company people are not login accounts.

Create a separate requester and a separate Finance auditor:

```sh
PYTHONPATH=backend .venv/bin/python scripts/manage_members.py create requester \
  --display-name 'Invoice requester' --role operator --department general

PYTHONPATH=backend .venv/bin/python scripts/manage_members.py create auditor \
  --display-name 'Finance auditor' --role finance_auditor --department finance
```

Each command asks for a new password twice using a hidden prompt. Do not put
passwords in command arguments, shell history, logs or documentation. The output
contains the created member ID and role, not the password. Retain the complete
auditor member ID from the second command, then replace the placeholder below
with that ID:

```sh
PYTHONPATH=backend .venv/bin/python scripts/manage_members.py \
  assign-finance-reviewer 'PASTE_CREATED_AUDITOR_MEMBER_ID_HERE'
```

Finance membership and the `finance_auditor` role are both required. Assignment
creates a new Finance policy version and makes previous grants stale, so assign
the reviewer before creating the demo's invoice run. Requester and reviewer must
be distinct accounts; the requester cannot approve their own Finance access.
Use the created `requester` and `auditor` logins in separate browser sessions.
Use unique login names if these names already exist; rerunning `create` does not
reset their passwords or roles.

## Backup and restore

Keep the entire backup directory private and copy verified backups off the
service disk. Same-disk snapshots do not protect against disk/account loss.
Backups contain original protected evidence and restored credential hashes.

```sh
.venv/bin/python scripts/backup.py --quiesced
.venv/bin/python scripts/backup.py --verify /absolute/path/manifest.json
.venv/bin/python scripts/startup.py --resume-backup /absolute/path/manifest.json --quiesced
```

Backup sets maintenance before snapshotting. Its graph DUMP and SQLite online
backup are captured while writers are stopped; immutable file hashes and graph
fingerprints must remain stable. Verification restores onto a unique disposable
graph and checks graph fingerprints, file hashes, and SQLite integrity. The
private backup directory and all manifests remain ignored by Git.
The explicit resume command requires the exact unchanged graph fingerprint and
completed schema, checks private storage, reopens maintenance, and leaves
execution disabled. A backup-only pause therefore cannot accidentally resume
old workers through an ordinary readiness check.

Restore is an explicit recovery into a **new graph and empty directory**:

```sh
.venv/bin/python scripts/restore.py \
  --manifest /absolute/private/backup/manifest.json \
  --target-graph relay_recovered --confirm-graph relay_recovered \
  --target-data-dir /absolute/private/recovered --quiesced
```

It verifies the backup before writes, refuses existing destinations, and never
automatically deletes/replaces a live graph. It restores graph/files/checkpoints,
revokes all restored sessions and expires expired grants before traffic can
resume. Completed current-schema recovery receives a fresh matching marker;
legacy/incomplete recovery remains in maintenance for explicit offline upgrade.
Execution stays disabled until separately enabled. Point the application at the
recovered graph and directory only after readiness verification. Retain the old
target for rollback; never run both writers. Restore failures retain the partial
destination for inspection instead of destroying evidence.

Backups are portable at the application graph/file level. For a complete hosted
disk replacement, also retain an operator-managed disk snapshot or rebuild the
embedded Redis AOF from the verified graph restore before traffic. Graph DUMP
recovery does not require copying an old Redis AOF over a running database.
