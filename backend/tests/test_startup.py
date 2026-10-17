"""Real disposable graph checks for explicit startup and persisted storage identity."""
import importlib.util
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from relay.database import GraphDatabase
from relay.migrations import ensure_schema


def script_module(name):
    path = Path(__file__).resolve().parents[2] / 'scripts' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.delenv('RELAY_CHECKPOINT_PATH', raising=False)
    database = GraphDatabase('relay_test_startup_' + uuid4().hex)
    startup = script_module('startup')
    root = tmp_path / 'data'
    startup.prepare_storage(database, root, initialize=True, quiesced=True)
    try:
        yield startup, database, root
    finally:
        assert database.graph_name.startswith('relay_test_')
        database.graph.delete()


def test_missing_mount_never_creates_graph_or_data(tmp_path):
    startup = script_module('startup')
    database = GraphDatabase('relay_test_missing_' + uuid4().hex)
    root = tmp_path / 'missing'
    with pytest.raises(RuntimeError, match='marker'):
        startup.check_storage(database, root)
    with pytest.raises(RuntimeError, match='missing'):
        startup.prepare_storage(database, root, quiesced=True, upgrade=True)
    assert not root.exists()
    assert database.graph_name not in database.db.list_graphs()


def test_initialization_refuses_orphaned_checkpoint_without_creating_graph(tmp_path):
    startup = script_module('startup')
    database = GraphDatabase('relay_test_orphaned_' + uuid4().hex)
    (tmp_path / 'checkpoints.sqlite').write_bytes(b'existing checkpoint')
    with pytest.raises(RuntimeError, match='existing checkpoint'):
        startup.prepare_storage(database, tmp_path, initialize=True, quiesced=True)
    assert database.graph_name not in database.db.list_graphs()


def test_first_install_is_versioned_and_repeated_startup_preserves_edits(prepared):
    startup, database, root = prepared
    ensure_schema(database)
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[False]]
    database.query("MATCH (s:Source {id:'src-launch-brief'}) SET s.payload=$payload",
                   {'payload': json.dumps({'id':'src-launch-brief','title':'Edited','excerpt':'User edit'})})
    before = database.read('MATCH (n) RETURN id(n),properties(n) ORDER BY id(n)')
    startup.check_storage(database, root)
    startup.prepare_storage(database, root, initialize=True, quiesced=True)
    assert database.read('MATCH (n) RETURN id(n),properties(n) ORDER BY id(n)') == before
    assert len(list((root / 'backups').iterdir())) == 1


@pytest.mark.parametrize('damage', ['marker', 'uploads', 'checkpoint', 'newer', 'incomplete', 'identity'])
def test_invalid_or_incomplete_storage_blocks_readiness(prepared, damage):
    startup, database, root = prepared
    if damage == 'marker':
        (root / 'storage.json').unlink()
    elif damage == 'uploads':
        shutil.rmtree(root / 'uploads')
    elif damage == 'checkpoint':
        (root / 'checkpoints.sqlite').unlink()
    elif damage == 'newer':
        database.query('MATCH (w:Workspace) SET w.schema_version=999')
    elif damage == 'incomplete':
        database.query("MATCH (m:SchemaMigration) SET m.status='running'")
    else:
        database.query("MATCH (w:Workspace) SET w.storage_id='different'")
    with pytest.raises(RuntimeError):
        startup.check_storage(database, root)


def test_initialization_never_seeds_an_unmarked_existing_graph(tmp_path):
    database = GraphDatabase('relay_test_existing_' + uuid4().hex)
    database.query("CREATE (:UserData {id:'keep'})")
    try:
        startup = script_module('startup')
        with pytest.raises(RuntimeError, match='existing data'):
            startup.prepare_storage(database, tmp_path, initialize=True, quiesced=True)
        assert database.read('MATCH (n) RETURN labels(n),n.id') == [[['UserData'], 'keep']]
    finally:
        database.graph.delete()


def test_executor_requires_explicit_post_upgrade_opt_in(prepared):
    startup, database, root = prepared
    startup.prepare_storage(database, root, adopt=True, quiesced=True, enable_execution=True)
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[True]]
    startup.check_storage(database, root)
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[True]]


def test_current_schema_upgrade_refuses_missing_checkpoint(prepared):
    startup, database, root = prepared
    (root / 'checkpoints.sqlite').unlink()
    with pytest.raises(RuntimeError, match='Checkpoint storage is missing'):
        startup.prepare_storage(database, root, upgrade=True, quiesced=True)
    assert not (root / 'checkpoints.sqlite').exists()


def test_external_checkpoint_is_supported_by_explicit_adoption(prepared, monkeypatch, tmp_path):
    startup, database, root = prepared
    checkpoint = tmp_path / 'external.sqlite'
    shutil.copy2(root / 'checkpoints.sqlite', checkpoint)
    monkeypatch.setenv('RELAY_CHECKPOINT_PATH', str(checkpoint))
    with pytest.raises(RuntimeError, match='changed'):
        startup.check_storage(database, root)
    startup.prepare_storage(database, root, adopt=True, quiesced=True)
    startup.check_storage(database, root)
    with pytest.raises(RuntimeError, match='checkpoint inside'):
        startup.prepare_storage(database, root, upgrade=True, quiesced=True)


def test_backup_pause_requires_verified_explicit_resume(prepared):
    from relay.migrations import create_backup
    startup, database, root = prepared
    manifest = create_backup(database, root, quiesced=True)
    with pytest.raises(RuntimeError, match='maintenance'):
        startup.check_storage(database, root)
    startup.resume_backup(database, root, manifest, quiesced=True)
    startup.check_storage(database, root)
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[False]]
