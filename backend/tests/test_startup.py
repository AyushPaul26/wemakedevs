"""Real disposable graph checks for explicit startup and persisted storage identity."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
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


def hosted(startup, database, root, environ, *, quiesced=True):
    operation = getattr(startup, 'hosted_startup', None)
    assert callable(operation), 'Hosted startup must apply explicit environment opt-in before HTTP'
    return operation(database, root, environ=environ, quiesced=quiesced)


def graph_snapshot(database):
    return database.read('MATCH (n) RETURN id(n),labels(n),properties(n) ORDER BY id(n)')


def test_hosted_opt_in_enables_ready_existing_storage_without_reseeding(prepared):
    startup, database, root = prepared
    database.query("CREATE (:UserData {id:'preserved',value:'not a fixture'})")
    versions = database.read('MATCH (v:SourceVersion) RETURN v.id,v.content_hash ORDER BY v.id')
    marker = (root / 'storage.json').read_bytes()
    backups = list((root / 'backups').iterdir())
    hosted(startup, database, root, {'RELAY_STORAGE_MODE':'persistent',
                                  'RELAY_ENABLE_EXECUTION':'1'})
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[True]]
    assert database.read("MATCH (n:UserData {id:'preserved'}) RETURN n.value") == [['not a fixture']]
    assert database.read('MATCH (v:SourceVersion) RETURN v.id,v.content_hash ORDER BY v.id') == versions
    assert (root / 'storage.json').read_bytes() == marker
    assert list((root / 'backups').iterdir()) == backups


@pytest.mark.parametrize('flag', [None, '0'])
@pytest.mark.parametrize('existing_enabled', [False, True])
def test_hosted_missing_or_zero_opt_in_is_read_only(prepared, flag, existing_enabled):
    startup, database, root = prepared
    database.query('MATCH (w:Workspace) SET w.execution_enabled=$enabled',
                   {'enabled':existing_enabled})
    before = graph_snapshot(database)
    environment = {'RELAY_STORAGE_MODE':'persistent'}
    if flag is not None:
        environment['RELAY_ENABLE_EXECUTION'] = flag
    hosted(startup, database, root, environment)
    assert graph_snapshot(database) == before


@pytest.mark.parametrize('invalid', [
    {'RELAY_ENABLE_EXECUTION':'true'}, {'RELAY_ENABLE_EXECUTION':''},
    {'RELAY_INITIALIZE_DATA':'yes'}, {'RELAY_UPGRADE_DATA':'01'},
    {'RELAY_PROVISION_DEMO_ACCOUNTS':'True'}, {'RELAY_STORAGE_MODE':'unknown'},
    {'RELAY_INITIALIZE_DATA':'1','RELAY_UPGRADE_DATA':'1'},
])
def test_hosted_invalid_flags_refuse_without_changing_existing_data(prepared, invalid):
    startup, database, root = prepared
    before = graph_snapshot(database)
    environment = {'RELAY_STORAGE_MODE':'persistent','RELAY_ENABLE_EXECUTION':'1', **invalid}
    with pytest.raises(RuntimeError, match='flag|exactly|mode|together'):
        hosted(startup, database, root, environment)
    assert graph_snapshot(database) == before


def test_hosted_invalid_flags_do_not_initialize_absent_graph(tmp_path):
    startup = script_module('startup')
    database = GraphDatabase('relay_test_hosted_invalid_' + uuid4().hex)
    with pytest.raises(RuntimeError, match='exactly|flag'):
        hosted(startup, database, tmp_path / 'data', {'RELAY_ENABLE_EXECUTION':'yes'})
    assert database.graph_name not in database.db.list_graphs()
    assert not (tmp_path / 'data').exists()


def test_hosted_new_install_can_opt_in_before_api(tmp_path, monkeypatch):
    monkeypatch.delenv('RELAY_CHECKPOINT_PATH', raising=False)
    startup = script_module('startup')
    database = GraphDatabase('relay_test_hosted_new_' + uuid4().hex)
    root = tmp_path / 'data'
    try:
        hosted(startup, database, root, {'RELAY_STORAGE_MODE':'ephemeral',
                                      'RELAY_ENABLE_EXECUTION':'1'})
        startup.check_storage(database, root)
        assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[True]]
    finally:
        if database.graph_name in database.db.list_graphs():
            database.graph.delete()


def test_hosted_opt_in_requires_quiescence_and_ready_storage(prepared):
    startup, database, root = prepared
    environment = {'RELAY_STORAGE_MODE':'persistent','RELAY_ENABLE_EXECUTION':'1'}
    before = graph_snapshot(database)
    with pytest.raises(RuntimeError, match='quiesc'):
        hosted(startup, database, root, environment, quiesced=False)
    assert graph_snapshot(database) == before
    database.query('MATCH (w:Workspace) SET w.maintenance=true')
    before = graph_snapshot(database)
    with pytest.raises(RuntimeError, match='maintenance'):
        hosted(startup, database, root, environment)
    assert graph_snapshot(database) == before


def test_hosted_failed_provisioning_never_enables_execution(prepared):
    startup, database, root = prepared
    before = graph_snapshot(database)
    environment = {'RELAY_STORAGE_MODE':'persistent','RELAY_ENABLE_EXECUTION':'1',
                   'RELAY_PROVISION_DEMO_ACCOUNTS':'1'}
    with pytest.raises(RuntimeError, match='password|provision'):
        hosted(startup, database, root, environment)
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[False]]
    assert graph_snapshot(database) == before


def test_hosted_cli_opt_in_works_on_repeated_ephemeral_start(prepared, monkeypatch):
    startup, database, root = prepared
    monkeypatch.setenv('RELAY_STORAGE_MODE','ephemeral')
    monkeypatch.setenv('RELAY_ENABLE_EXECUTION','1')
    monkeypatch.setenv('RELAY_PROVISION_DEMO_ACCOUNTS','0')
    monkeypatch.delenv('RELAY_INITIALIZE_DATA',raising=False)
    monkeypatch.delenv('RELAY_UPGRADE_DATA',raising=False)
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'startup.py'
    result = subprocess.run([sys.executable,str(script),'--graph',database.graph_name,
                             '--data-dir',str(root),'--hosted','--quiesced'],
                            capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert database.read('MATCH (w:Workspace) RETURN w.execution_enabled') == [[True]]
    startup.check_storage(database, root)
