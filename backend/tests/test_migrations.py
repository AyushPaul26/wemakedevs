"""Migration preservation/recovery against unique real graphs, never relay_demo."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from relay.graph_store import GraphStore


def foundation():
    assert importlib.util.find_spec("relay.database"), "Missing versioned database foundation"
    assert importlib.util.find_spec("relay.migrations"), "Missing migration service"
    from relay.database import GraphDatabase
    from relay.migrations import MigrationService, create_backup, ensure_schema
    return GraphDatabase, MigrationService, create_backup, ensure_schema


@pytest.fixture
def legacy():
    store = GraphStore(f"relay_test_migration_{uuid4().hex}")
    store.seed()
    source = store.add_source("User note", "Exact original excerpt.\nUnicode: ₹ café.")
    memory = {"id": "history", "question": "Old question", "answer": "Old answer",
              "source_ids": [source["id"]], "node_ids": [], "actions": [],
              "steps": [], "created_at": "2026-10-17T00:00:00Z", "mode": "demo"}
    for status in ("proposed", "approved", "done"):
        action = {"id": status, "title": status, "description": "manual",
                  "owner": "Existing owner", "status": "proposed", "source_ids": [source["id"]],
                  "investigation_id": memory["id"], "created_at": memory["created_at"]}
        memory["actions"].append(action)
    store.save_investigation(memory)
    store.transition_action("approved", "approved")
    store.transition_action("done", "approved")
    store.transition_action("done", "done")
    try:
        yield store
    finally:
        assert store.graph.name.startswith("relay_test_")
        store.graph.delete()


def originals(store):
    return {label: store._query(f"MATCH (n:{label}) RETURN n.id,n.payload,n.status,n.approved_at ORDER BY n.id")
            for label in ("Entity", "Source", "Investigation", "Action")} | {
        "edges": store._query("MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id,type(r),b.id,r.payload ORDER BY a.id,type(r),b.id")}


def test_upgrade_preserves_legacy_data_and_repeats_safely(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, ensure_schema = foundation()
    db = GraphDatabase(legacy.graph.name)
    before = originals(legacy)
    service = MigrationService(db, tmp_path)
    assert service.inspect().current_version == 0
    with pytest.raises(RuntimeError, match="schema"):
        ensure_schema(db)
    manifest = backup(db, tmp_path, quiesced=True)
    assert service.apply(manifest).phase == "complete"
    assert service.apply(manifest).current_version == 1
    ensure_schema(db)
    assert originals(legacy) == before
    assert legacy._query("MATCH (s:Source) RETURN count(s)") == legacy._query("MATCH (v:SourceVersion) RETURN count(v)")
    assert legacy._query("MATCH (v:SourceVersion) WHERE v.provenance <> 'migration_snapshot' RETURN count(v)") == [[0]]
    assert legacy._query("MATCH (i:Investigation)-[:CITES]->(:Source) RETURN count(i)") == [[1]]
    assert legacy._query("MATCH (:Investigation)-[:CITES_VERSION|CITES_CHUNK]->(n) RETURN count(n)") == [[0]]
    assert legacy._query("MATCH (e:Execution) RETURN count(e)") == [[0]]
    assert legacy._query("MATCH (a:Action) WHERE a.record_kind='legacy_manual' RETURN count(a)") == [[3]]


def test_interrupted_batch_resumes_without_duplicate_versions(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    service = MigrationService(db, tmp_path)
    original = service._snapshot_source
    completed = []

    def interrupt(source):
        if completed:
            raise RuntimeError("simulated process interruption")
        original(source)
        completed.append(source)

    service._snapshot_source = interrupt
    with pytest.raises(RuntimeError, match="simulated"):
        service.apply(manifest)
    assert legacy._query("MATCH (w:Workspace {id:'meridian'}) RETURN w.maintenance") == [[True]]
    assert MigrationService(db, tmp_path).apply(manifest).phase == "complete"
    assert legacy._query("MATCH (v:SourceVersion) WITH v.source_id AS id,count(v) AS n WHERE n<>1 RETURN id") == []


@pytest.mark.parametrize("corruption", ["payload", "duplicate", "missing_id", "status", "newer"])
def test_preflight_refuses_malformed_or_duplicate_records_without_writes(legacy, tmp_path, corruption):
    GraphDatabase, MigrationService, _, _ = foundation()
    statements = {"payload": "CREATE (:Source {id:'broken',payload:'bad json'})",
                  "duplicate": "CREATE (:Source {id:'duplicate',payload:'{}'}),(:Source {id:'duplicate',payload:'{}'})",
                  "missing_id": "CREATE (:Source {payload:'{}'})",
                  "status": "MATCH (a:Action {id:'done'}) SET a.status='executed'",
                  "newer": "MERGE (w:Workspace {id:'meridian'}) SET w.schema_version=999"}
    legacy._query(statements[corruption])
    before = originals(legacy)
    service = MigrationService(GraphDatabase(legacy.graph.name), tmp_path)
    assert service.inspect().violations
    with pytest.raises(RuntimeError):
        service.apply(tmp_path / "missing.json")
    assert originals(legacy) == before
    assert legacy._query("MATCH (m:SchemaMigration) RETURN count(m)") == [[0]]


def test_backup_is_private_restored_verified_and_tamper_refused(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "private").write_bytes(b"preserved bytes")
    import sqlite3
    with sqlite3.connect(tmp_path / "checkpoints.sqlite") as conn:
        conn.execute("CREATE TABLE checkpoint (id TEXT)")
        conn.execute("INSERT INTO checkpoint VALUES ('waiting')")
    with pytest.raises(RuntimeError, match="quiesc"):
        backup(db, tmp_path)
    manifest = backup(db, tmp_path, quiesced=True)
    data = json.loads(manifest.read_text())
    assert data["restore_verified"] is True
    assert manifest.stat().st_mode & 0o077 == 0
    graph_file = manifest.parent / "graph.dump"
    graph_file.write_bytes(graph_file.read_bytes() + b"tamper")
    with pytest.raises(RuntimeError, match="checksum"):
        MigrationService(db, tmp_path).apply(manifest)


def test_schema_checks_maintenance_and_seed_never_overwrites_user_edits(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, ensure_schema = foundation()
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    MigrationService(db, tmp_path).apply(manifest)
    legacy._query("MATCH (s:Source {id:'src-launch-brief'}) SET s.payload=$payload", payload=json.dumps({"id":"src-launch-brief","excerpt":"user edit"}))
    legacy.seed()
    assert legacy.get_source("src-launch-brief")["excerpt"] == "user edit"
    legacy._query("MATCH (w:Workspace) SET w.maintenance=true")
    with pytest.raises(RuntimeError, match="maintenance"):
        ensure_schema(db)


def test_shared_contracts_bound_inputs_and_require_decision_reasons():
    assert importlib.util.find_spec('relay.workflow_models'), 'Missing shared DTO contracts'
    from relay.workflow_models import RunCreate, ApprovalDecision, SourceRef
    from pydantic import ValidationError
    ref = {'source_id':'s','version_id':'v'}
    assert SourceRef(**ref).version_id == 'v'
    with pytest.raises(ValidationError):
        SourceRef(**ref, role='admin')
    with pytest.raises(ValidationError):
        RunCreate(template='invoice_review', invoice=ref, purchase_order=ref,
                  context=[ref] * 4, project_id='p', automation='auto_permitted',
                  output_audience=['member'])
    with pytest.raises(ValidationError):
        ApprovalDecision(decision='reject', expected_revision=1, scope_hash='abc')


def test_maintenance_blocks_legacy_writers(legacy, tmp_path):
    GraphDatabase, _, backup, _ = foundation()
    backup(GraphDatabase(legacy.graph.name), tmp_path, quiesced=True)
    before = originals(legacy)
    with pytest.raises(RuntimeError, match='maintenance'):
        legacy.add_source('must not write', 'maintenance barrier')
    with pytest.raises(RuntimeError, match='maintenance'):
        legacy.transition_action('proposed', 'approved')
    with pytest.raises(RuntimeError, match='maintenance'):
        legacy.simulate('payment-gateway')
    assert originals(legacy) == before


def test_snapshot_chunks_do_not_invent_historical_locators(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    source = legacy.add_source('Long note', 'A' * 4001 + '\nExact end.')
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    MigrationService(db, tmp_path).apply(manifest)
    rows = db.read('MATCH (:Source {id:$id})-[:HAS_VERSION]->(:SourceVersion)-[:HAS_CHUNK]->(c:SourceChunk) '
                   'RETURN c.text,c.locator_json ORDER BY c.ordinal', {'id':source['id']})
    assert ''.join(row[0] for row in rows) == source['excerpt']
    assert len(rows) == 2
    assert all(row[1] == '{}' for row in rows)


def test_backup_missing_and_changed_legacy_state_are_refused(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    with pytest.raises(RuntimeError, match='verified backup'):
        MigrationService(db, tmp_path).apply(tmp_path / 'missing.json')
    manifest = backup(db, tmp_path, quiesced=True)
    db.query("MATCH (s:Source {id:'src-launch-brief'}) SET s.payload=$payload",
             {'payload':json.dumps({'id':'src-launch-brief','title':'changed','excerpt':'new'})})
    with pytest.raises(RuntimeError, match='no longer matches'):
        MigrationService(db, tmp_path).apply(manifest)


def test_backup_checksums_cover_nested_manifest_named_file(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    (uploads / 'manifest.json').write_text('private user file')
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    (manifest.parent / 'files' / 'uploads' / 'manifest.json').write_text('tampered')
    with pytest.raises(RuntimeError, match='checksum'):
        MigrationService(db, tmp_path).apply(manifest)


def test_migration_cli_check_is_read_only_and_reports_schema(legacy, tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    script = root / 'scripts' / 'migrate.py'
    assert script.is_file(), 'Missing explicit migration CLI'
    before = originals(legacy)
    output = subprocess.run([sys.executable, str(script), '--graph', legacy.graph.name,
                             '--data-dir', str(tmp_path), '--check'], cwd=root,
                            capture_output=True, text=True)
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout)['current_version'] == 0
    assert originals(legacy) == before
    assert legacy._query('MATCH (m:SchemaMigration) RETURN count(m)') == [[0]]


def test_backup_cli_requires_explicit_quiescence_before_writes(legacy, tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[2]
    script = root / 'scripts' / 'backup.py'
    assert script.is_file(), 'Missing backup CLI'
    result = subprocess.run([sys.executable, str(script), '--graph', legacy.graph.name,
                             '--data-dir', str(tmp_path)], cwd=root, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'quiesc' in result.stderr.lower()
    assert legacy._query("MATCH (w:Workspace {id:'meridian'}) RETURN w.maintenance") == [[None]]


def test_interruption_after_indexes_resumes_without_rebuilding_data(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    service = MigrationService(db, tmp_path)

    def interrupt(_manifest):
        raise RuntimeError('interrupted validation')

    service._validate = interrupt
    with pytest.raises(RuntimeError, match='interrupted validation'):
        service.apply(manifest)
    versions = db.read('MATCH (v:SourceVersion) RETURN v.id,v.created_at ORDER BY v.id')
    assert MigrationService(db, tmp_path).apply(manifest).phase == 'complete'
    assert db.read('MATCH (v:SourceVersion) RETURN v.id,v.created_at ORDER BY v.id') == versions


def test_inspect_nonexistent_graph_never_creates_it(tmp_path):
    GraphDatabase, MigrationService, _, ensure_schema = foundation()
    db = GraphDatabase(f'relay_test_missing_{uuid4().hex}')
    report = MigrationService(db, tmp_path).inspect()
    assert report.current_version == 0
    assert not report.violations
    with pytest.raises(RuntimeError, match='schema'):
        ensure_schema(db)
    assert db.graph_name not in db.db.list_graphs()


def test_preflight_refuses_non_string_ids_without_crashing(legacy, tmp_path):
    GraphDatabase, MigrationService, _, _ = foundation()
    legacy._query("CREATE (:Scenario {id:['invalid']})")
    report = MigrationService(GraphDatabase(legacy.graph.name), tmp_path).inspect()
    assert 'Scenario: missing or duplicate ID' in report.violations


def test_resume_uses_last_verified_source_cursor(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    first = MigrationService(db, tmp_path)
    original = first._snapshot_source
    done = []

    def stop_after_one(source):
        if done:
            raise RuntimeError('after one')
        original(source)
        done.append(source[0])

    first._snapshot_source = stop_after_one
    with pytest.raises(RuntimeError, match='after one'):
        first.apply(manifest)
    second = MigrationService(db, tmp_path)
    resumed = []
    original = second._snapshot_source

    def record(source):
        resumed.append(source[0])
        original(source)

    second._snapshot_source = record
    second.apply(manifest)
    assert done[0] not in resumed
    assert resumed


def test_finance_policy_covers_the_bounded_archive_step(legacy, tmp_path):
    GraphDatabase, MigrationService, backup, _ = foundation()
    db = GraphDatabase(legacy.graph.name)
    manifest = backup(db, tmp_path, quiesced=True)
    MigrationService(db, tmp_path).apply(manifest)
    assert db.read("MATCH (p:Policy {id:'finance-v1'}) RETURN p.allowed_tools") == [[[
        'finance_parse','invoice_compare','publish_report','upsert_case','archive_run']]]


def test_backup_detects_changed_private_file_named_manifest(legacy, tmp_path, monkeypatch):
    from relay import migrations

    source = tmp_path / 'uploads'
    source.mkdir()
    original = source / 'manifest.json'
    original.write_text('original private bytes')
    copy = migrations.shutil.copytree

    def change_during_copy(src, dst, *args, **kwargs):
        result = copy(src, dst, *args, **kwargs)
        if Path(src) == source:
            original.write_text('changed while copying')
        return result

    monkeypatch.setattr(migrations.shutil, 'copytree', change_during_copy)
    with pytest.raises(RuntimeError, match='Private files changed'):
        migrations.create_backup(legacy.database, tmp_path, quiesced=True)
