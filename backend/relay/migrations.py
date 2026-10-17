"""Explicit, backup-gated schema upgrade; never invoked by ordinary reads.

Operators must quiesce API/executor writers before backup/apply. The maintenance
flag gates the upgraded application; it cannot stop an older process ignoring it.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

from redis import ConnectionPool, Redis
from redis.exceptions import ResponseError

from .database import GraphDatabase
from .workflow_models import MigrationReport

SCHEMA_VERSION = 1
WORKSPACE = 'meridian'
MIGRATION_ID = '001_workflows'
MIGRATION_CHECKSUM = hashlib.sha256(b'relay-workflows-schema-1:legacy-snapshot-v1:finance-archive-v1').hexdigest()
LEGACY_LABELS = ('Entity', 'Source', 'Investigation', 'Action', 'Scenario')
LABELS = LEGACY_LABELS + ('SchemaMigration', 'Workspace', 'Member', 'Session', 'Department',
    'Policy', 'SourceVersion', 'SourceChunk', 'LinkProposal', 'WorkflowRun', 'WorkflowPlan',
    'WorkflowStep', 'Approval', 'Execution', 'Artifact', 'ExceptionCase', 'CaseRevision', 'RunEvent')
INDEXES = {'Member': ('login',), 'Source': ('workspace_id', 'department_id'),
    'SourceVersion': ('source_id',), 'SourceChunk': ('version_id',),
    'WorkflowRun': ('requester_id', 'status'), 'WorkflowStep': ('run_id', 'status', 'lease_until'),
    'Approval': ('reviewer_id', 'status', 'run_id'), 'ExceptionCase': ('run_id',),
    'Execution': ('effect_key',), 'Artifact': ('effect_key',)}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _legacy_state(database):
    # The legacy scalars are authoritative; serialized display payload is untouched.
    nodes = {label: database.read(
        f'MATCH (n:{label}) RETURN n.id,n.payload,n.status,n.approved_at,n.kind,'
        'n.source_ids,n.search,n.created_at,n.investigation_id,n.origin_id,n.mitigation '
        'ORDER BY n.id') for label in LEGACY_LABELS}
    nodes['edges'] = database.read('MATCH (a:Entity)-[r]->(b:Entity) '
        'RETURN a.id,type(r),b.id,r.id,r.payload,r.source_ids ORDER BY a.id,type(r),b.id,r.id')
    nodes['citations'] = database.read('MATCH (a)-[:CITES]->(b:Source) '
        'RETURN labels(a),a.id,b.id ORDER BY a.id,b.id')
    return nodes


def _graph_state(database):
    return {'nodes': database.read('MATCH (n) RETURN id(n),labels(n),properties(n) ORDER BY id(n)'),
            'edges': database.read('MATCH (a)-[r]->(b) RETURN id(r),id(a),type(r),id(b),properties(r) ORDER BY id(r)')}


def _binary_client(database):
    options = dict(database.db.connection.connection_pool.connection_kwargs)
    options['decode_responses'] = False
    return Redis.from_pool(ConnectionPool(
        connection_class=database.db.connection.connection_pool.connection_class, **options))


def _private_write(path, content):
    with path.open('xb') as handle:
        os.chmod(path, 0o600)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _check_tree(directory):
    if directory.is_symlink():
        raise RuntimeError('Private storage must not contain symlinks')
    for path in directory.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise RuntimeError('Private storage must contain only regular files/directories')


def _file_hashes(directory, *, exclude_manifest=False):
    _check_tree(directory)
    return {str(path.relative_to(directory)): _hash(path.read_bytes())
            for path in sorted(directory.rglob('*')) if path.is_file()
            and not (exclude_manifest and path == directory / 'manifest.json')}


def _restore_rehearsal(database, directory, manifest):
    """Restore a graph and copied private files without replacing any live target."""
    name = f'relay_test_restore_{uuid4().hex}'
    restored = GraphDatabase(name)
    client = _binary_client(database)
    try:
        client.restore(name, 0, (directory / 'graph.dump').read_bytes())
        if _hash(_json(_graph_state(restored)).encode()) != manifest['graph_fingerprint']:
            raise RuntimeError('Backup graph restoration fingerprint mismatch')
        if _hash(_json(_legacy_state(restored)).encode()) != manifest['legacy_fingerprint']:
            raise RuntimeError('Backup legacy ID/status restoration mismatch')
        files = directory / 'files'
        if files.exists():
            import tempfile
            with tempfile.TemporaryDirectory(prefix='relay_restore_') as temp:
                target = Path(temp) / 'files'
                shutil.copytree(files, target)
                if _file_hashes(target) != _file_hashes(files):
                    raise RuntimeError('Backup private file restoration mismatch')
                checkpoint = target / 'checkpoints.sqlite'
                if checkpoint.exists():
                    with sqlite3.connect(f'file:{checkpoint}?mode=ro', uri=True) as conn:
                        if conn.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                            raise RuntimeError('Checkpoint backup integrity failure')
        return True
    finally:
        if client.exists(name):
            restored.graph.delete()
        client.close()


def create_backup(database, data_dir, *, quiesced=False):
    """Private graph DUMP plus SQLite online snapshot and immutable-file copies.

    A required operator assertion is deliberate: a flag in the new application
    cannot quiesce a still-running old binary. No live services are stopped here.
    """
    if not quiesced:
        raise RuntimeError('Backup requires quiesced API and executor writers')
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    for directory in ('uploads', 'artifacts'):
        if (data_dir / directory).exists():
            _check_tree(data_dir / directory)
    # Mark before the snapshot so upgraded writers and startup checks remain closed.
    database.query("MERGE (w:Workspace {id:$id}) SET w.maintenance=true", {'id': WORKSPACE})
    baseline = _graph_state(database)
    legacy = _legacy_state(database)
    directory = data_dir / 'backups' / f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}-{uuid4().hex}'
    directory.mkdir(parents=True, mode=0o700)
    os.chmod(directory.parent, 0o700)
    client = _binary_client(database)
    try:
        dump = client.dump(database.graph_name)
    finally:
        client.close()
    if dump is None:
        raise RuntimeError('Graph snapshot is missing')
    _private_write(directory / 'graph.dump', dump)
    files = directory / 'files'
    files.mkdir(mode=0o700)
    before_files = {}
    for name in ('uploads', 'artifacts'):
        source = data_dir / name
        if source.exists():
            before_files[name] = _file_hashes(source)
            shutil.copytree(source, files / name)
    checkpoint = data_dir / 'checkpoints.sqlite'
    if checkpoint.exists():
        if checkpoint.is_symlink():
            raise RuntimeError('Checkpoint symlinks are not supported')
        with sqlite3.connect(f'file:{checkpoint}?mode=ro', uri=True) as source:
            with sqlite3.connect(files / 'checkpoints.sqlite') as target:
                source.backup(target)
    for name, expected in before_files.items():
        if _file_hashes(data_dir / name) != expected or _file_hashes(files / name) != expected:
            raise RuntimeError('Private files changed during quiesced backup')
    if _graph_state(database) != baseline:
        raise RuntimeError('Graph changed during quiesced backup')
    for path in directory.rglob('*'):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    manifest = {'format': 1, 'graph_name': database.graph_name, 'created_at': _now(),
        'quiesced': True, 'graph_fingerprint': _hash(_json(baseline).encode()),
        'legacy_fingerprint': _hash(_json(legacy).encode()), 'legacy_state': legacy,
        'checksums': _file_hashes(directory), 'restore_verified': False}
    manifest['restore_verified'] = _restore_rehearsal(database, directory, manifest)
    path = directory / 'manifest.json'
    _private_write(path, _json(manifest).encode())
    return path


def verify_backup(database, path):
    path = Path(path).resolve()
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('Migration requires a verified backup manifest')
    try:
        manifest = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise RuntimeError('Invalid backup manifest') from exc
    if manifest.get('format') != 1 or manifest.get('graph_name') != database.graph_name or not manifest.get('quiesced') or not manifest.get('restore_verified'):
        raise RuntimeError('Migration requires a verified backup for this graph')
    if manifest.get('checksums') != _file_hashes(path.parent, exclude_manifest=True):
        raise RuntimeError('Backup checksum mismatch')
    _restore_rehearsal(database, path.parent, manifest)
    return manifest


def _wait_constraints(graph):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        constraints = graph.list_constraints()
        if all(item['status'] == 'OPERATIONAL' for item in constraints):
            return
        if any(item['status'] == 'FAILED' for item in constraints):
            raise RuntimeError('Database uniqueness constraint failed')
        sleep(0.01)
    raise RuntimeError('Database uniqueness constraint readiness timed out')


def probe_capabilities(database):
    """Prove the exact required behavior using independent disposable clients."""
    probe = GraphDatabase(f'relay_test_probe_{uuid4().hex}')
    # Reuse target endpoint, never silently probe a different configured server.
    probe.host, probe.port = database.host, database.port
    try:
        probe.query('CREATE (:Receipt {id:"unique"}),(:WorkflowStep {id:"s",status:"queued",fence:0})')
        probe.graph.create_node_range_index('Receipt', 'id')
        probe.graph.create_node_unique_constraint('Receipt', 'id')
        _wait_constraints(probe.graph)
        barrier = Barrier(8)

        def claim(index):
            client = GraphDatabase(probe.graph_name)
            client.host, client.port = probe.host, probe.port
            barrier.wait()
            return client.query("MATCH (s:WorkflowStep {id:'s'}) WHERE s.status='queued' "
                "SET s.status='running',s.fence=s.fence+1,s.lease_owner=$owner RETURN s.fence", {'owner': str(index)})

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(claim, range(8)))
        if sum(bool(row) for row in claims) != 1:
            raise RuntimeError('Conditional claims are not exclusive')
        failed = False
        try:
            probe.query("MATCH (s:WorkflowStep {id:'s'}) SET s.status='completed' "
                "CREATE (:Artifact {id:'rollback'}),(:Receipt {id:'unique'})")
        except ResponseError:
            failed = True
        if not failed or probe.query('MATCH (s:WorkflowStep) RETURN s.status') != [['running']] or probe.query('MATCH (a:Artifact) RETURN count(a)') != [[0]]:
            raise RuntimeError('Database does not provide required mutation rollback')
        probe.query("CREATE (:WorkflowStep {id:'report'})-[:DEPENDS_ON]->(:WorkflowStep {id:'parse'}),"
                    "(:Entity {id:'launch'})-[:DEPENDS_ON]->(:Entity {id:'gateway'})")
        if probe.query("MATCH (s:WorkflowStep)-[:DEPENDS_ON*1..]->(:WorkflowStep {id:'parse'}) RETURN s.id") != [['report']]:
            raise RuntimeError('Directed dependency traversal failed')
        probe.query("CREATE (:WorkflowRun {id:'run',generation:1,revision:1,cancelled:false}),"
                    "(:Approval {id:'grant',status:'approved',scope:'v1'})")
        commit = ("MATCH (r:WorkflowRun {id:'run'}),(s:WorkflowStep {id:'s'}),"
            "(a:Approval {id:'grant'}) WHERE r.generation=$generation AND r.revision=1 "
            "AND r.cancelled=false AND s.status='running' AND s.fence=$fence "
            "AND a.status='approved' AND a.scope=$scope "
            "CREATE (e:Receipt {id:'committed'}),(o:Artifact {id:'committed-artifact'}) "
            "SET s.status='completed',r.revision=r.revision+1 "
            "CREATE (s)-[:EXECUTED_AS]->(e)-[:PRODUCED]->(o) RETURN e.id")
        for invalid in ({'generation': 1, 'fence': 0, 'scope': 'v1'},
                        {'generation': 2, 'fence': 1, 'scope': 'v1'},
                        {'generation': 1, 'fence': 1, 'scope': 'replaced'}):
            if probe.query(commit, invalid):
                raise RuntimeError('Stale scope/fence/generation committed effects')
        probe.query("MATCH (r:WorkflowRun {id:'run'}) SET r.cancelled=true")
        valid = {'generation': 1, 'fence': 1, 'scope': 'v1'}
        if probe.query(commit, valid):
            raise RuntimeError('Cancelled run committed effects')
        probe.query("MATCH (r:WorkflowRun {id:'run'}) SET r.cancelled=false")
        if probe.query(commit, valid) != [['committed']] or probe.query(commit, valid):
            raise RuntimeError('Fenced effects are not a conditional single commit')
        return {'unique_ids': True, 'conditional_claims': True, 'mutation_rollback': True,
                'dependency_traversal': True, 'fenced_effects': True}
    finally:
        probe.graph.delete()


def ensure_schema(database):
    if database.graph_name not in database.db.list_graphs():
        raise RuntimeError('Database schema is missing; run scripts/migrate.py explicitly')
    rows = database.read("MATCH (w:Workspace {id:$id}) RETURN w.schema_version,w.maintenance", {'id': WORKSPACE})
    if not rows or rows[0][0] != SCHEMA_VERSION:
        raise RuntimeError('Database schema is not supported; run scripts/migrate.py explicitly')
    if rows[0][1]:
        raise RuntimeError('Database is in maintenance')
    migrations = database.read('MATCH (m:SchemaMigration {id:$id}) RETURN m.status,m.checksum', {'id': MIGRATION_ID})
    if migrations != [['complete', MIGRATION_CHECKSUM]]:
        raise RuntimeError('Database schema migration is incomplete or unsupported')


class MigrationService:
    def __init__(self, database, data_dir):
        self.database = database
        self.data_dir = Path(data_dir)

    def inspect(self) -> MigrationReport:
        db = self.database
        violations = []
        if db.graph_name not in db.db.list_graphs():
            return MigrationReport(current_version=0, target_version=SCHEMA_VERSION,
                                   phase='preflight', counts={label: 0 for label in LABELS}, violations=[])
        workspace = db.read("MATCH (w:Workspace {id:'meridian'}) RETURN w.schema_version")
        version = workspace[0][0] or 0 if workspace else 0
        if not isinstance(version, int) or version not in (0, SCHEMA_VERSION):
            violations.append('Unsupported database schema version')
        migrations = db.read('MATCH (m:SchemaMigration) RETURN m.id,m.checksum,m.phase,m.status')
        for mid, checksum, _, _ in migrations:
            if mid != MIGRATION_ID or checksum != MIGRATION_CHECKSUM:
                violations.append('Unsupported migration or checksum')
        counts = {}
        for label in LABELS:
            rows = db.read(f'MATCH (n:{label}) RETURN n.id,n.payload,n.status')
            counts[label] = len(rows)
            ids = [row[0] for row in rows]
            if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
                violations.append(f'{label}: missing or duplicate ID')
            if label in ('Entity', 'Source', 'Investigation', 'Action'):
                for identifier, payload, status in rows:
                    try:
                        value = json.loads(payload)
                        if not isinstance(value, dict) or value.get('id') != identifier:
                            raise ValueError('payload ID mismatch')
                        required = {'Entity': ('label', 'kind', 'source_ids'),
                            'Source': ('title', 'excerpt') if version == 0 else ('title',),
                            'Investigation': ('question', 'answer', 'source_ids'),
                            'Action': ('title', 'source_ids')}[label]
                        if any(key not in value for key in required):
                            raise ValueError('missing payload fields')
                        if label == 'Source' and version == 0 and not isinstance(value['excerpt'], str):
                            raise ValueError('source excerpt must be text')
                    except (ValueError, TypeError):
                        violations.append(f'{label}: invalid legacy payload ({identifier})')
                    if label == 'Action' and status not in ('proposed', 'approved', 'done'):
                        violations.append(f'Action: invalid manual status ({identifier})')
        if not self.data_dir.exists():
            ancestor = self.data_dir.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
        else:
            ancestor = self.data_dir
        if shutil.disk_usage(ancestor).free < 10 * 1024 * 1024:
            violations.append('Insufficient free storage for migration')
        phase = migrations[0][2] if migrations else 'preflight'
        return MigrationReport(current_version=version, target_version=SCHEMA_VERSION,
                               phase=phase, counts=counts, violations=violations)

    def _phase(self, phase, last_id=''):
        self.database.query('MATCH (m:SchemaMigration {id:$id}) SET m.phase=$phase,m.last_id=$last,m.updated_at=$now',
            {'id': MIGRATION_ID, 'phase': phase, 'last': last_id, 'now': _now()})

    def _snapshot_source(self, source):
        identifier, payload = source
        excerpt = json.loads(payload)['excerpt']
        digest = _hash(excerpt.encode())
        version_id = 'legacy-version-' + _hash(identifier.encode())
        now = _now()
        # Chunk boundaries describe migration-time snapshots, never historical views.
        chunks = [{'id': 'legacy-chunk-' + _hash(f'{version_id}:{ordinal}'.encode()),
                   'ordinal': ordinal, 'text': excerpt[start:start + 4000],
                   'hash': _hash(excerpt[start:start + 4000].encode())}
                  for ordinal, start in enumerate(range(0, len(excerpt), 4000))]
        self.database.query(
            'MATCH (s:Source {id:$source}) '
            'MERGE (v:SourceVersion {id:$version}) ON CREATE SET '
            "v.workspace_id=$workspace,v.source_id=$source,v.number=1,v.content_hash=$hash,"
            "v.mime='text/plain',v.storage_kind='legacy_inline',v.byte_size=$size,"
            "v.classification='general',v.department_id='general',v.uploader_id='legacy_unknown',"
            "v.processing_status='ready',v.provenance='migration_snapshot',v.created_at=$now "
            "SET s.workspace_id=$workspace,s.current_version_id=$version,s.department_id='general',"
            "s.classification='general',s.uploader_id='legacy_unknown',s.revision=1 "
            'MERGE (s)-[:HAS_VERSION]->(v)',
            {'source': identifier, 'version': version_id, 'workspace': WORKSPACE,
             'hash': digest, 'size': len(excerpt.encode()), 'now': now})
        if chunks:
            self.database.query('MATCH (v:SourceVersion {id:$version}) UNWIND $chunks AS chunk '
                'MERGE (c:SourceChunk {id:chunk.id}) ON CREATE SET c.workspace_id=$workspace,'
                'c.version_id=$version,c.ordinal=chunk.ordinal,c.text=chunk.text,'
                "c.locator_json='{}',c.content_hash=chunk.hash,c.created_at=$now "
                'MERGE (v)-[:HAS_CHUNK]->(c)',
                {'version': version_id, 'workspace': WORKSPACE, 'chunks': chunks, 'now': now})

    def _indexes(self):
        graph = self.database.graph
        existing = {(item['label'], tuple(item['properties'])) for item in graph.list_constraints()}
        for label in LABELS:
            for prop in ('id',) + INDEXES.get(label, ()):
                try:
                    graph.create_node_range_index(label, prop)
                except ResponseError as exc:
                    if 'already indexed' not in str(exc).lower() and 'already exists' not in str(exc).lower():
                        raise
                if prop == 'id' or (label, prop) in (('Member', 'login'), ('Execution', 'effect_key'), ('Artifact', 'effect_key')):
                    if (label, (prop,)) not in existing:
                        graph.create_node_unique_constraint(label, prop)
        _wait_constraints(graph)

    def _validate(self, manifest):
        if _legacy_state(self.database) != manifest['legacy_state']:
            raise RuntimeError('Legacy IDs, payloads, statuses or company edges changed; maintenance retained')
        for source_id, payload in self.database.read('MATCH (s:Source) RETURN s.id,s.payload'):
            rows = self.database.read('MATCH (s:Source {id:$id})-[:HAS_VERSION]->(v:SourceVersion) '
                'RETURN v.id,v.content_hash,v.provenance,s.current_version_id', {'id': source_id})
            if len(rows) != 1 or rows[0][1] != _hash(json.loads(payload)['excerpt'].encode()) or rows[0][2] != 'migration_snapshot' or rows[0][0] != rows[0][3]:
                raise RuntimeError('Source snapshot integrity violation')
            chunks = self.database.read('MATCH (:SourceVersion {id:$id})-[:HAS_CHUNK]->(c:SourceChunk) '
                'RETURN c.text,c.content_hash ORDER BY c.ordinal', {'id': rows[0][0]})
            if ''.join(chunk[0] for chunk in chunks) != json.loads(payload)['excerpt'] or any(_hash(text.encode()) != digest for text, digest in chunks):
                raise RuntimeError('Source chunk integrity violation')
        if self.database.read('MATCH (e:Execution) RETURN count(e)') != [[0]]:
            raise RuntimeError('Legacy migration must not fabricate execution receipts')

    def apply(self, backup_manifest: Path) -> MigrationReport:
        report = self.inspect()
        if report.violations:
            raise RuntimeError('; '.join(report.violations))
        if report.current_version == SCHEMA_VERSION and report.phase == 'complete':
            ensure_schema(self.database)
            return report
        manifest = verify_backup(self.database, backup_manifest)
        db = self.database
        if _legacy_state(db) != manifest['legacy_state']:
            raise RuntimeError('Backup no longer matches legacy graph; quiesce and back up again')
        probe_capabilities(db)
        db.query('MERGE (w:Workspace {id:$workspace}) SET w.maintenance=true '
                 'MERGE (m:SchemaMigration {id:$id}) ON CREATE SET m.version=1,m.status="running",'
                 'm.phase="mark",m.last_id="",m.checksum=$checksum,m.backup_manifest=$backup,m.created_at=$now',
                 {'workspace': WORKSPACE, 'id': MIGRATION_ID, 'checksum': MIGRATION_CHECKSUM,
                  'backup': str(Path(backup_manifest).resolve()), 'now': _now()})
        progress = db.read('MATCH (m:SchemaMigration {id:$id}) RETURN m.phase,m.last_id',
                           {'id': MIGRATION_ID})[0]
        if progress[0] == 'mark':
            self._phase('backfill')
        for label in ('Entity', 'Investigation', 'Action', 'Scenario'):
            db.query(f'MATCH (n:{label}) SET n.workspace_id=$workspace,n.classification="general",n.department_id="general"',
                     {'workspace': WORKSPACE})
        db.query("MATCH (a:Action) SET a.record_kind='legacy_manual'")
        # Deterministic upserts replay safely even after a crash before cursor commit.
        if progress[0] in ('mark', 'backfill'):
            cursor = progress[1] or ''
            for source in db.read('MATCH (s:Source) WHERE s.id > $cursor RETURN s.id,s.payload ORDER BY s.id',
                                  {'cursor': cursor}):
                self._snapshot_source(source)
                self._phase('backfill', source[0])
        self._phase('policies_indexes')
        self._indexes()
        for department, title in (('general', 'General'), ('finance', 'Finance')):
            db.query('MERGE (d:Department {id:$id}) ON CREATE SET d.name=$name,d.workspace_id=$workspace,d.current_policy_id=$policy,d.created_at=$now '
                'MERGE (p:Policy {id:$policy}) ON CREATE SET p.workspace_id=$workspace,p.department_id=$id,p.version=1,'
                'p.allowed_tools=$tools,p.approval_ttl_seconds=86400,p.created_at=$now '
                'MERGE (d)-[:GOVERNED_BY]->(p)',
                {'id': department, 'name': title, 'workspace': WORKSPACE, 'policy': f'{department}-v1',
                 'tools': ['finance_parse', 'invoice_compare', 'publish_report', 'upsert_case', 'archive_run'] if department == 'finance' else ['company_context', 'archive_run'], 'now': _now()})
        self._phase('validate')
        self._validate(manifest)
        from .seed import SEED_VERSION
        db.query('MATCH (w:Workspace {id:$workspace}),(m:SchemaMigration {id:$id}) '
            'SET w.schema_version=$version,w.seed_version=$seed,w.maintenance=false,w.execution_enabled=false,'
            'm.status="complete",m.phase="complete",m.completed_at=$now',
            {'workspace': WORKSPACE, 'id': MIGRATION_ID, 'version': SCHEMA_VERSION,
             'seed': SEED_VERSION, 'now': _now()})
        return self.inspect()
