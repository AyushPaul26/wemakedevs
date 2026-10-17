from identity_helpers import identity_db as identity_db
import importlib
from io import BytesIO
import json
from uuid import uuid4
import pytest
from relay.access import AccessContext, AccessError
from relay.storage import BlobStore


def modules():
    assert importlib.util.find_spec("relay.source_store"), "versioned source store missing"
    assert importlib.util.find_spec("relay.sources"), "authorized source service missing"
    return importlib.import_module("relay.source_store"), importlib.import_module("relay.sources")


@pytest.fixture
def setup_sources(identity_db, tmp_path):
    store_module, service_module = modules()
    for member, role in [
        ("operator", "operator"),
        ("other", "operator"),
        ("auditor", "finance_auditor"),
    ]:
        identity_db.query(
            'CREATE (:Member {id:$id,workspace_id:"meridian",role:$role,active:true,display_name:$id})',
            {"id": member, "role": role},
        )
    blobs = BlobStore(tmp_path)
    store = store_module.SourceStore(identity_db)
    return store, service_module.SourceService(store, blobs), blobs


def upload(
    setup_sources, classification="general", key=None, text=b"First paragraph.\n\nSecond paragraph."
):
    store, service, blobs = setup_sources
    blob = blobs.put_stream(BytesIO(text), mime="text/plain")
    ref = store.create_upload(
        AccessContext("operator"),
        {
            "title": "Evidence",
            "filename": "../evidence.txt",
            "classification": classification,
            "department_id": "finance" if classification == "finance" else "general",
        },
        blob,
        idempotency_key=key,
    )
    return ref


def test_finance_upload_does_not_parse_and_agent_cannot_inspect(setup_sources):
    store, service, blobs = setup_sources
    ref = upload(setup_sources, "finance")
    assert store.detail(AccessContext("operator"), ref).chunks == []
    with pytest.raises(AccessError):
        service.ingest(AccessContext("operator", purpose="agent"), ref)
    assert store.database.query("MATCH (c:SourceChunk) RETURN count(c)")[0][0] == 0
    with pytest.raises(AccessError):
        store.detail(AccessContext("other"), ref)
    assert service.ingest(AccessContext("auditor"), ref).chunks[0]["text"] == "First paragraph."
    with pytest.raises(AccessError):
        store.detail(AccessContext("operator", purpose="agent"), ref)


def test_ingestion_has_exact_locators_metadata_only_and_retry_identity(setup_sources):
    store, service, blobs = setup_sources
    key = str(uuid4())
    ref = upload(setup_sources, key=key)
    assert upload(setup_sources, key=key) == ref
    with pytest.raises(Exception) as exc:
        upload(setup_sources, key=key, text=b"different")
    assert exc.value.status_code == 409
    detail = service.ingest(AccessContext("operator", purpose="agent"), ref)
    assert [c["locator"] for c in detail.chunks] == [{"paragraph": 1}, {"paragraph": 2}]
    assert detail.chunks[0]["version_id"] == ref.version_id
    assert detail.chunks[0]["source_id"] == ref.source_id
    record = store.database.query(
        "MATCH (s:Source {id:$id}) RETURN properties(s)", {"id": ref.source_id}
    )[0][0]
    assert "First paragraph" not in record["payload"] + record["search"]
    assert "excerpt" not in json.loads(record["payload"])
    page = store.list_sources(AccessContext("operator"), query="evidence")
    assert len(page.items) == 1 and not hasattr(page.items[0], "chunks")


def test_replacement_preserves_old_bytes_and_checks_revision(setup_sources):
    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    replacement = blobs.put_stream(BytesIO(b"New evidence"), mime="text/plain")
    result = store.add_version(AccessContext("operator"), ref.source_id, 0, replacement)
    assert result.ref.version_id != ref.version_id
    payload = json.loads(
        store.database.query("MATCH (s:Source {id:$id}) RETURN s.payload", {"id": ref.source_id})[
            0
        ][0]
    )
    assert payload["current_version_id"] == result.ref.version_id
    assert store.version(AccessContext("operator"), ref)["content_hash"] != replacement.sha256
    with pytest.raises(Exception) as exc:
        store.add_version(AccessContext("operator"), ref.source_id, 0, replacement)
    assert exc.value.status_code == 409


def test_link_confirmation_only_writes_allowed_company_facts_with_exact_evidence(setup_sources):
    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    detail = service.ingest(AccessContext("operator"), ref)
    for identifier in ("project", "supplier"):
        store.database.query(
            'CREATE (:Entity {id:$id,workspace_id:"meridian",classification:"general",name:$id})',
            {"id": identifier},
        )
    assert service.suggest_links(AccessContext("operator"), ref) == []
    proposal = service.propose_link(
        AccessContext("operator"),
        ref,
        {
            "source_entity_id": "project",
            "target_entity_id": "supplier",
            "relation": "DEPENDS_ON",
            "evidence_chunk_ids": [detail.chunks[0]["id"]],
        },
    )
    assert (
        store.database.query("MATCH (:Entity)-[r:DEPENDS_ON]->(:Entity) RETURN count(r)")[0][0] == 0
    )
    result = service.review_links(
        AccessContext("operator"), ref, [{"proposal_id": proposal["id"], "decision": "accept"}], 0
    )
    assert result.provenance["source_revision"] == 1
    edge = store.database.query(
        'MATCH (:Entity {id:"project"})-[r:DEPENDS_ON]->(:Entity {id:"supplier"}) RETURN properties(r)'
    )[0][0]
    assert json.loads(edge["evidence_refs_json"])[0]["chunk_id"] == detail.chunks[0]["id"]
    assert edge["source_ids"] == [ref.source_id]
    assert json.loads(edge["payload"])["evidence_refs"][0]["version_id"] == ref.version_id
    with pytest.raises(Exception):
        service.propose_link(
            AccessContext("operator"),
            ref,
            {
                "source_entity_id": "project",
                "target_entity_id": "supplier",
                "relation": "AUTHORIZES",
                "evidence_chunk_ids": [detail.chunks[0]["id"]],
            },
        )
    with pytest.raises(Exception):
        service.propose_link(
            AccessContext("operator"),
            ref,
            {
                "source_entity_id": "project",
                "target_entity_id": "supplier",
                "relation": "RELATED_TO",
                "evidence_chunk_ids": ["forged"],
            },
        )
    with pytest.raises(AccessError):
        service.review_links(AccessContext("other"), ref, [], 1)


def test_detail_exposes_authorized_controls_and_immutable_history(setup_sources):
    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    detail = service.detail(AccessContext("operator"), ref)
    assert detail.provenance["can_replace"] is True
    assert detail.provenance["versions"][0]["version_id"] == ref.version_id
    assert service.detail(AccessContext("other"), ref).provenance["can_replace"] is False


def test_parser_worker_imports_package_without_parent_pythonpath(setup_sources, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    ref = upload(setup_sources)
    assert setup_sources[1].ingest(AccessContext("operator"), ref).processing_status == "completed"


def test_invalid_extraction_publishes_no_chunks_and_source_summary_is_failed(setup_sources):
    from relay.parsers import ParseError

    store, service, blobs = setup_sources
    ref = upload(setup_sources, text=b"x" * 200001)
    with pytest.raises(ParseError):
        service.ingest(AccessContext("operator"), ref)
    assert store.detail(AccessContext("operator"), ref).chunks == []
    assert store.list_sources(AccessContext("operator")).items[0].processing_status == "failed"


def test_csv_table_is_cached_with_decimal_values_and_exact_row_refs(setup_sources):
    from decimal import Decimal

    store, service, blobs = setup_sources
    blob = blobs.put_stream(
        BytesIO(b"item_id,quantity,unit_price,currency\nwidget,2,10.50,USD\n"), mime="text/csv"
    )
    ref = store.create_upload(
        AccessContext("operator"), {"title": "Order", "filename": "order.csv"}, blob
    )
    first = service.parse(AccessContext("operator"), ref)
    assert first.table.rows[0].unit_price == Decimal("10.50")
    assert first.chunks[0].locator == {"row_start": 2, "row_end": 2}
    # Immutable cached table remains usable without opening the private bytes again.
    blobs.path(blob.key).unlink()
    assert service.parsed_document(AccessContext("operator"), ref) == first


def test_replacement_retry_reconciles_crash_after_pointer_swap(setup_sources):
    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    replacement = blobs.put_stream(BytesIO(b"Revised notes."), mime="text/plain")
    key = str(uuid4())

    def interrupted(source_id, version_id):
        raise RuntimeError("Simulated crash after source pointer swap")

    store.invalidate = interrupted
    with pytest.raises(RuntimeError):
        store.add_version(
            AccessContext("operator"), ref.source_id, 0, replacement, idempotency_key=key
        )
    store.invalidate = lambda source_id, version_id: ["affected-run"]
    result = store.add_version(
        AccessContext("operator"), ref.source_id, 0, replacement, idempotency_key=key
    )
    assert result.invalidated_run_ids == ["affected-run"]
    assert (
        store.database.query("MATCH (s:Source {id:$id}) RETURN s.revision", {"id": ref.source_id})[
            0
        ][0]
        == 1
    )


def finance_agent(setup_sources, ref):
    from types import SimpleNamespace
    from test_access import grant
    from relay.workflow_models import SourceRef

    store, service, blobs = setup_sources
    store.database.query(
        'MATCH (v:SourceVersion {id:$version}),(s:Source {id:$source}) SET v.id="private-v1",s.current_version_id="private-v1"',
        {"version": ref.version_id, "source": ref.source_id},
    )
    store.database.query(
        'MATCH (m:Member {id:"auditor"}) CREATE (d:Department {id:"finance"}), (m)-[:MEMBER_OF]->(d)'
    )
    grant(
        store.database,
        {
            "operator": SimpleNamespace(id="operator"),
            "finance_auditor": SimpleNamespace(id="auditor"),
        },
    )
    context = AccessContext("operator", purpose="agent", run_id="run", step_id="step")
    return context, SourceRef(source_id=ref.source_id, version_id="private-v1")


def test_finance_grant_is_rechecked_after_waiting_for_parser_slot(setup_sources, monkeypatch):
    import fcntl
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import relay.sources as module

    store, service, blobs = setup_sources
    access, ref = finance_agent(setup_sources, upload(setup_sources, "finance"))
    store.version(access, ref)
    attempted = Event()
    parser_calls = []
    original_flock = fcntl.flock
    original_run = module.subprocess.run

    def observe_lock(fd, operation):
        if operation == fcntl.LOCK_EX:
            attempted.set()
        return original_flock(fd, operation)

    def observe_parser(*args, **kwargs):
        parser_calls.append(True)
        return original_run(*args, **kwargs)

    with (blobs.root / ".parser.lock").open("a+b") as held:
        original_flock(held, fcntl.LOCK_EX)
        monkeypatch.setattr(module.fcntl, "flock", observe_lock)
        monkeypatch.setattr(module.subprocess, "run", observe_parser)
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(service.parse, access, ref)
            try:
                assert attempted.wait(10), "parser worker did not reach semaphore"
                store.database.query('MATCH (a:Approval {id:"approval"}) SET a.status="revoked"')
            finally:
                original_flock(held, fcntl.LOCK_UN)
            with pytest.raises(AccessError):
                future.result(timeout=10)
    assert parser_calls == [], "revoked grant must prevent every parser invocation"


def test_finance_cache_return_rechecks_grant_after_hydration(setup_sources, monkeypatch):
    store, service, blobs = setup_sources
    access, ref = finance_agent(setup_sources, upload(setup_sources, "finance"))
    service.ingest(AccessContext("auditor"), ref)
    original_detail = store.detail

    def revoke_after_hydration(context, source_ref):
        detail = original_detail(context, source_ref)
        store.database.query('MATCH (a:Approval {id:"approval"}) SET a.status="revoked"')
        return detail

    monkeypatch.setattr(store, "detail", revoke_after_hydration)
    with pytest.raises(AccessError):
        service.parse(access, ref)


def synchronize_initial_reads(database, statement, monkeypatch):
    from threading import Barrier, Lock

    barrier, lock = Barrier(2), Lock()
    original = database.query
    reads = 0

    def query(query_text, params=None):
        nonlocal reads
        if query_text == statement:
            with lock:
                reads += 1
                initial = reads <= 2
            result = original(query_text, params)
            if initial:
                barrier.wait(timeout=10)
            return result
        return original(query_text, params)

    monkeypatch.setattr(database, "query", query)


def test_racing_replacements_replay_original_filename_and_same_result(setup_sources, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    blob = blobs.put_stream(BytesIO(b"Replaced"), mime="text/plain")
    store.invalidate = lambda source, version: []
    synchronize_initial_reads(
        store.database, "MATCH (i:IdempotencyRecord {id:$id}) RETURN properties(i)", monkeypatch
    )
    key = str(uuid4())

    def replace():
        return store.add_version(
            AccessContext("operator"),
            ref.source_id,
            0,
            blob,
            idempotency_key=key,
            original_filename="new.txt",
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: replace(), range(2)))
    assert results[0] == results[1]
    assert store.database.query("MATCH (v:SourceVersion) RETURN count(v)")[0][0] == 2


def test_racing_link_reviews_return_same_atomic_receipt(setup_sources, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    store, service, blobs = setup_sources
    ref = upload(setup_sources)
    detail = service.ingest(AccessContext("operator"), ref)
    store.database.query(
        'CREATE (:Entity {id:"project",workspace_id:"meridian",classification:"general"})'
    )
    proposal = service.propose_link(
        AccessContext("operator"),
        ref,
        {
            "target_entity_id": "project",
            "relation": "DOCUMENTS",
            "evidence_chunk_ids": [detail.chunks[0]["id"]],
        },
    )
    synchronize_initial_reads(
        store.database,
        "MATCH (i:IdempotencyRecord {id:$id}) RETURN i.request_hash,i.response_json",
        monkeypatch,
    )
    key = str(uuid4())

    def review():
        return service.review_links(
            AccessContext("operator"),
            ref,
            [{"proposal_id": proposal["id"], "decision": "accept"}],
            0,
            key,
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: review(), range(2)))
    assert results[0] == results[1]
    assert (
        store.database.query("MATCH (:Source)-[r:DOCUMENTS]->(:Entity) RETURN count(r)")[0][0] == 1
    )


def test_revocation_after_chunk_commit_does_not_corrupt_completed_cache(setup_sources, monkeypatch):
    store, service, blobs = setup_sources
    access, ref = finance_agent(setup_sources, upload(setup_sources, "finance"))
    original_save = store.save_parsed

    def revoke_after_commit(*args, **kwargs):
        original_save(*args, **kwargs)
        store.database.query('MATCH (a:Approval {id:"approval"}) SET a.status="revoked"')

    monkeypatch.setattr(store, "save_parsed", revoke_after_commit)
    with pytest.raises(AccessError):
        service.parse(access, ref)
    detail = store.detail(AccessContext("auditor"), ref)
    assert detail.processing_status == "completed"
    assert len(detail.chunks) == 2


def test_migrated_ready_inline_version_remains_retrievable_without_original_blob(setup_sources):
    from relay.workflow_models import SourceRef

    store, service, blobs = setup_sources
    store.database.query(
        'CREATE (s:Source {id:"legacy",workspace_id:"meridian",classification:"general",current_version_id:"legacy-v",revision:1,payload:$payload}), (v:SourceVersion {id:"legacy-v",source_id:"legacy",workspace_id:"meridian",classification:"general",processing_status:"ready",storage_kind:"legacy_inline",provenance:"migration_snapshot",number:1}), (c:SourceChunk {id:"legacy-c",version_id:"legacy-v",ordinal:0,text:"Migrated source context.",locator_json:"{}"}), (s)-[:HAS_VERSION]->(v),(v)-[:HAS_CHUNK]->(c)',
        {
            "payload": json.dumps(
                {
                    "id": "legacy",
                    "title": "Migrated source",
                    "type": "document",
                    "author": "Legacy",
                    "updated_at": "2026-10-17",
                }
            )
        },
    )
    ref = SourceRef(source_id="legacy", version_id="legacy-v")
    assert (
        service.ingest(AccessContext("operator", purpose="agent"), ref).chunks[0]["text"]
        == "Migrated source context."
    )
    with pytest.raises(AccessError) as exc:
        service.download(AccessContext("operator"), ref)
    assert exc.value.status_code == 404
    assert service.detail(AccessContext("operator"), ref).provenance["can_download"] is False
