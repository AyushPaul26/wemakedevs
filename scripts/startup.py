#!/usr/bin/env python3
"""Offline storage preparation and read-only readiness; run before API writers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from relay.database import GraphDatabase  # noqa: E402
from relay.graph_store import GraphStore  # noqa: E402
from relay.migrations import (SCHEMA_VERSION, MigrationService, create_backup, ensure_schema,
                              verify_backup, _graph_state, _hash, _json)  # noqa: E402

MARKER = 'storage.json'
DIRECTORIES = ('graph', 'uploads', 'artifacts', 'backups')


def checkpoint_path(root):
    return Path(os.getenv('RELAY_CHECKPOINT_PATH', str(root / 'checkpoints.sqlite'))).resolve()


def verify_files(database, root):
    """Reject missing mounts or damaged immutable files before accepting traffic."""
    for label, directory in (('SourceVersion', 'uploads'), ('Artifact', 'artifacts')):
        rows = database.read(f'MATCH (n:{label}) WHERE n.blob_key IS NOT NULL '
                             'RETURN n.blob_key,n.content_hash')
        for key, expected in rows:
            if not isinstance(key, str) or Path(key).name != key:
                raise RuntimeError('Invalid private file reference')
            path = root / directory / key
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Referenced private storage is missing')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Private storage checksum mismatch')
    checkpoint = checkpoint_path(root)
    if checkpoint.is_symlink() or not checkpoint.is_file():
        raise RuntimeError('Checkpoint storage is missing')
    with sqlite3.connect(f'file:{checkpoint}?mode=ro', uri=True) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('Checkpoint integrity failure')


def write_marker(database, root):
    rows = database.read("MATCH (w:Workspace {id:'meridian'}) RETURN w.storage_id")
    identity = rows[0][0] if rows and rows[0][0] else uuid4().hex
    database.query("MATCH (w:Workspace {id:'meridian'}) SET w.storage_id=$id", {'id': identity})
    payload = {'format': 1, 'graph': database.graph_name, 'storage_id': identity,
               'checkpoint': str(checkpoint_path(root))}
    temporary = root / f'.storage-{uuid4().hex}'
    try:
        with temporary.open('x') as output:
            os.chmod(temporary, 0o600)
            json.dump(payload, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, root / MARKER)
    finally:
        temporary.unlink(missing_ok=True)


def check_storage(database, root):
    """Read only: never create a graph, directories, schema, seed, or marker."""
    root = Path(root).absolute()
    marker = root / MARKER
    if root.is_symlink() or marker.is_symlink() or not marker.is_file():
        raise RuntimeError('Persistent storage marker is missing; explicitly initialize or adopt storage offline')
    try:
        metadata = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError('Invalid storage marker') from exc
    if metadata.get('format') != 1 or metadata.get('graph') != database.graph_name:
        raise RuntimeError('Persistent storage belongs to a different graph')
    for name in DIRECTORIES:
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError('Persistent storage directory is missing')
    ensure_schema(database)
    rows = database.read("MATCH (w:Workspace {id:'meridian'}) RETURN w.storage_id")
    if rows != [[metadata.get('storage_id')]] or not metadata.get('storage_id'):
        raise RuntimeError('Graph and private storage identity differ')
    if metadata.get('checkpoint') != str(checkpoint_path(root)):
        raise RuntimeError('Checkpoint path changed; explicitly adopt the verified storage offline')
    verify_files(database, root)


def prepare_storage(database, root, *, quiesced=False, initialize=False, upgrade=False,
                    adopt=False, backup_manifest=None, enable_execution=False):
    if not quiesced:
        raise RuntimeError('Preparation requires quiesced API and executor writers')
    root = Path(root).absolute()
    if root.is_symlink():
        raise RuntimeError('Private storage root must not be a symlink')
    exists = database.graph_name in database.db.list_graphs()
    if initialize and (root / MARKER).is_file():
        check_storage(database, root)
        return
    if initialize:
        if exists:
            raise RuntimeError('Initialization requires a new graph; existing data must be upgraded or adopted')
        if root.exists() and any(path.name not in DIRECTORIES for path in root.iterdir()):
            raise RuntimeError('Initialization refuses existing checkpoint or private workspace data')
        for name in ('uploads', 'artifacts', 'backups'):
            directory = root / name
            if directory.exists() and any(directory.iterdir()):
                raise RuntimeError('Initialization refuses existing private data')
    elif not exists:
        raise RuntimeError('Configured graph is missing; refusing an empty replacement workspace')
    report = MigrationService(database, root).inspect()
    if report.violations:
        raise RuntimeError('Schema preflight failed')
    if not (initialize or upgrade or adopt):
        raise RuntimeError('Select explicit initialization, upgrade, or storage adoption')
    if adopt and not checkpoint_path(root).is_file():
        raise RuntimeError('Checkpoint storage is missing; adoption must preserve existing storage')
    if checkpoint_path(root) != (root / 'checkpoints.sqlite').resolve() and (initialize or upgrade):
        raise RuntimeError('Migration backup requires checkpoint inside data root; preserve external checkpoints separately and adopt offline')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in DIRECTORIES:
        directory = root / name
        if directory.is_symlink():
            raise RuntimeError('Private storage directories must not be symlinks')
        directory.mkdir(exist_ok=True, mode=0o700)
    if initialize:
        store = GraphStore(database.graph_name)
        store.database = database
        store.seed()  # Only reachable for a verified entirely new graph.
    if (initialize or upgrade) and not (report.current_version == SCHEMA_VERSION
                                       and report.phase == 'complete'):
        manifest = backup_manifest or create_backup(database, root, quiesced=True)
        MigrationService(database, root).apply(manifest)
    ensure_schema(database)
    checkpoint = checkpoint_path(root)
    if not checkpoint.exists():
        if not initialize and report.current_version == SCHEMA_VERSION:
            raise RuntimeError('Checkpoint storage is missing; current-schema upgrade must preserve storage')
        # Fresh installs and explicit legacy upgrades can create their first DB.
        checkpoint.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(checkpoint) as connection:
            connection.execute('PRAGMA user_version=1')
        os.chmod(checkpoint, 0o600)
    verify_files(database, root)
    write_marker(database, root)
    if enable_execution:
        database.query("MATCH (w:Workspace {id:'meridian'}) SET w.execution_enabled=true")
    check_storage(database, root)


def resume_backup(database, root, manifest_path, *, quiesced=False):
    """Explicitly reopen a current-schema snapshot after a backup-only pause."""
    if not quiesced:
        raise RuntimeError('Backup resume requires quiesced writers')
    root = Path(root).absolute()
    manifest = verify_backup(database, manifest_path)
    if _hash(_json(_graph_state(database)).encode()) != manifest['graph_fingerprint']:
        raise RuntimeError('Graph changed since backup; resume refused')
    report = MigrationService(database, root).inspect()
    if report.violations or report.current_version != SCHEMA_VERSION or report.phase != 'complete':
        raise RuntimeError('Resume requires a completed current schema')
    verify_files(database, root)
    database.query("MATCH (w:Workspace {id:'meridian'}) SET w.maintenance=false,w.execution_enabled=false")
    try:
        ensure_schema(database)
        write_marker(database, root)
        check_storage(database, root)
    except Exception:
        database.query("MATCH (w:Workspace {id:'meridian'}) SET w.maintenance=true")
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph')
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('RELAY_DATA_DIR', '.data')))
    parser.add_argument('--quiesced', action='store_true')
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--check', action='store_true', help='Read-only default')
    operation.add_argument('--initialize', action='store_true', help='Seed a new empty graph once, then verified migration')
    operation.add_argument('--upgrade', action='store_true', help='Back up, restore-rehearse and migrate offline')
    operation.add_argument('--adopt-storage', action='store_true', help='Register verified existing current-schema storage')
    operation.add_argument('--resume-backup', type=Path, metavar='MANIFEST',
                           help='Reopen a verified unchanged current-schema backup pause')
    parser.add_argument('--backup-manifest', type=Path, help='Resume using an existing verified backup')
    parser.add_argument('--enable-execution', action='store_true', help='Explicit executor opt-in after preparation')
    args = parser.parse_args()
    try:
        database = GraphDatabase(args.graph)
        if args.resume_backup:
            if args.enable_execution or args.backup_manifest:
                parser.error('Backup resume leaves execution disabled; do not combine preparation options')
            resume_backup(database, args.data_dir, args.resume_backup, quiesced=args.quiesced)
        elif args.initialize or args.upgrade or args.adopt_storage:
            prepare_storage(database, args.data_dir, quiesced=args.quiesced,
                            initialize=args.initialize, upgrade=args.upgrade,
                            adopt=args.adopt_storage, backup_manifest=args.backup_manifest,
                            enable_execution=args.enable_execution)
        else:
            if args.enable_execution or args.backup_manifest:
                parser.error('Execution/backup options require an explicit preparation operation')
            check_storage(database, args.data_dir)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(f'Startup refused: {reason}. Check storage identity, schema, '
              'private files and explicit offline preparation.', file=sys.stderr)
        return 1
    print(json.dumps({'storage_ready': True, 'graph': database.graph_name}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
