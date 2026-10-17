"""Restore verifies graph/files/checkpoints and invalidates restored credentials."""
import hashlib
import sqlite3
import sys
import time
from uuid import uuid4

import pytest

from relay.database import GraphDatabase
from relay.migrations import create_backup
from test_startup import prepared, script_module  # noqa: F401, F811


def restore_module(monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    sys.modules.pop('startup', None)
    return script_module('restore')


def test_restore_preserves_waiting_outputs_versions_history_and_checkpoints(prepared, tmp_path, monkeypatch):  # noqa: F811
    startup, database, root = prepared
    content = b'private completed report'
    digest = hashlib.sha256(content).hexdigest()
    (root / 'artifacts' / f'{digest}.html').write_bytes(content)
    (root / 'uploads' / digest).write_bytes(content)
    with sqlite3.connect(root / 'checkpoints.sqlite') as connection:
        connection.execute('CREATE TABLE proof (state TEXT)')
        connection.execute("INSERT INTO proof VALUES ('waiting-approval')")
    database.query("CREATE (:Session {id:'old-session',revoked_at:0}),"
                   "(:Approval {id:'waiting',status:'pending',expires_at:$future}),"
                   "(:Approval {id:'expired',status:'approved',expires_at:1}),"
                   "(:WorkflowStep {id:'step',status:'waiting_approval'}),"
                   "(:Execution {id:'receipt',effect_key:'effect',status:'completed'}),"
                   "(:CaseRevision {id:'revision',case_id:'case'}),"
                   "(:SourceVersion {id:'uploaded',blob_key:$digest,content_hash:$digest}),"
                   "(:Artifact {id:'download',blob_key:$key,content_hash:$digest})",
                   {'future': int(time.time()) + 3600, 'digest': digest, 'key': f'{digest}.html'})
    manifest = create_backup(database, root, quiesced=True)
    name = 'relay_test_recovered_' + uuid4().hex
    target = tmp_path / 'recovered'
    restored = GraphDatabase(name)
    try:
        result = restore_module(monkeypatch).restore_snapshot(manifest, name, target,
                         confirm_graph=name, quiesced=True)
        assert result['storage_ready'] and result['execution_enabled'] is False
        startup.check_storage(restored, target)
        assert restored.read("MATCH (s:WorkflowStep {id:'step'}) RETURN s.status") == [['waiting_approval']]
        assert restored.read("MATCH (a:Approval {id:'waiting'}) RETURN a.status") == [['pending']]
        assert restored.read("MATCH (a:Approval {id:'expired'}) RETURN a.status") == [['expired']]
        assert restored.read('MATCH (s:Session) RETURN s.revoked_at')[0][0] > 0
        assert restored.read('MATCH (e:Execution) RETURN e.effect_key') == [['effect']]
        assert restored.read('MATCH (r:CaseRevision) RETURN r.id') == [['revision']]
        assert (target / 'artifacts' / f'{digest}.html').read_bytes() == content
        assert (target / 'uploads' / digest).read_bytes() == content
        with sqlite3.connect(target / 'checkpoints.sqlite') as connection:
            assert connection.execute('SELECT state FROM proof').fetchall() == [('waiting-approval',)]
    finally:
        if name in restored.db.list_graphs():
            restored.graph.delete()


def test_restore_never_replaces_existing_graph_or_unconfirmed_target(prepared, tmp_path, monkeypatch):  # noqa: F811
    _, database, root = prepared
    manifest = create_backup(database, root, quiesced=True)
    restore = restore_module(monkeypatch)
    before = database.read('MATCH (n) RETURN id(n),properties(n) ORDER BY id(n)')
    with pytest.raises(RuntimeError, match='already exists'):
        restore.restore_snapshot(manifest, database.graph_name, tmp_path / 'target',
                                 confirm_graph=database.graph_name, quiesced=True)
    with pytest.raises(RuntimeError, match='exact'):
        restore.restore_snapshot(manifest, 'relay_test_absent_' + uuid4().hex, tmp_path / 'target',
                                 confirm_graph='wrong', quiesced=True)
    assert database.read('MATCH (n) RETURN id(n),properties(n) ORDER BY id(n)') == before
    assert not (tmp_path / 'target').exists()
