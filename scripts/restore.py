#!/usr/bin/env python3
"""Explicit recovery into an absent graph and empty private directory, never replace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from relay.database import GraphDatabase  # noqa: E402
from relay.migrations import (MigrationService, SCHEMA_VERSION, _binary_client, _graph_state,
                              _hash, _json,
                              verify_backup, ensure_schema)  # noqa: E402
from startup import DIRECTORIES, verify_files, write_marker  # noqa: E402


def restore_snapshot(manifest_path, target_graph, target_dir, *, confirm_graph, quiesced=False):
    if not quiesced or not target_graph or confirm_graph != target_graph:
        raise RuntimeError('Restore requires quiescence and exact --confirm-graph target')
    manifest_path = Path(manifest_path).absolute()
    metadata = json.loads(manifest_path.read_text())
    source = GraphDatabase(metadata['graph_name'])
    manifest = verify_backup(source, manifest_path)
    database = GraphDatabase(target_graph)
    if target_graph in database.db.list_graphs():
        raise RuntimeError('Target graph already exists; restore into a new explicit graph')
    target = Path(target_dir).absolute()
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise RuntimeError('Target data directory must be absent or empty')
    if os.getenv('RELAY_CHECKPOINT_PATH'):
        raise RuntimeError('Unset checkpoint override; restore all files together under target data directory')
    # All verification happens before creating the destination. Partial failures
    # leave a maintenance graph for explicit inspection, never automatic removal.
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in DIRECTORIES:
        (target / name).mkdir(mode=0o700)
    for name in ('uploads', 'artifacts'):
        saved = manifest_path.parent / 'files' / name
        if saved.exists():
            shutil.copytree(saved, target / name, dirs_exist_ok=True)
    saved_checkpoint = manifest_path.parent / 'files' / 'checkpoints.sqlite'
    if saved_checkpoint.exists():
        shutil.copy2(saved_checkpoint, target / 'checkpoints.sqlite')
    else:
        with sqlite3.connect(target / 'checkpoints.sqlite') as connection:
            connection.execute('PRAGMA user_version=1')
    client = _binary_client(database)
    staging_graph = 'relay_test_restore_stage_' + uuid4().hex
    try:
        client.restore(staging_graph, 0, (manifest_path.parent / 'graph.dump').read_bytes())
        # FalkorDB v4.22.1 restores the original internal graph name. Redis's
        # rename notification updates it; a direct RESTORE under another name
        # permits reads but fails indexed writes. NX also guards target races.
        if not client.renamenx(staging_graph, target_graph):
            raise RuntimeError('Target graph appeared during recovery')
        if _hash(_json(_graph_state(database)).encode()) != manifest['graph_fingerprint']:
            raise RuntimeError('Restored target fingerprint mismatch; maintenance retained')
    finally:
        if client.exists(staging_graph):
            temporary = GraphDatabase(staging_graph)
            temporary.graph.delete()
        client.close()
    now = int(time.time())
    database.query("MATCH (w:Workspace {id:'meridian'}) SET w.maintenance=true,w.execution_enabled=false")
    database.query('MATCH (s:Session) SET s.revoked_at=$now', {'now': now})
    database.query("MATCH (a:Approval) WHERE a.status IN ['pending','approved'] AND a.expires_at<=$now "
                   "SET a.status='expired',a.revision=coalesce(a.revision,0)+1", {'now': now})
    report = MigrationService(database, target).inspect()
    if report.violations:
        raise RuntimeError('Restored schema preflight failed; maintenance retained')
    verify_files(database, target)
    if report.current_version == SCHEMA_VERSION and report.phase == 'complete':
        database.query("MATCH (w:Workspace {id:'meridian'}) SET w.maintenance=false")
        try:
            ensure_schema(database)
        except Exception:
            database.query("MATCH (w:Workspace {id:'meridian'}) SET w.maintenance=true")
            raise
        write_marker(database, target)
        return {'restored': True, 'storage_ready': True, 'execution_enabled': False}
    return {'restored': True, 'storage_ready': False, 'maintenance': True,
            'next': 'Explicit offline startup.py --upgrade is required for this schema'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--target-graph', required=True)
    parser.add_argument('--confirm-graph', required=True)
    parser.add_argument('--target-data-dir', required=True, type=Path)
    parser.add_argument('--quiesced', action='store_true')
    args = parser.parse_args()
    try:
        result = restore_snapshot(args.manifest, args.target_graph, args.target_data_dir,
                                  confirm_graph=args.confirm_graph, quiesced=args.quiesced)
    except Exception as exc:
        print(f'Restore refused ({type(exc).__name__}); verify manifest, empty target, confirmation and quiescence.', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
