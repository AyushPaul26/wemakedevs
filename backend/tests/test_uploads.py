from test_sources import setup_sources as setup_sources
from identity_helpers import identity_db as identity_db
import importlib
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from relay.access import AccessContext


def client_for(setup_sources, member="operator"):
    assert importlib.util.find_spec("relay.source_routes"), "bounded upload routes missing"
    from relay.source_routes import build_source_router

    app = FastAPI()

    def access():
        return AccessContext(member)

    app.include_router(build_source_router(setup_sources[1], access, access))
    return TestClient(app)


def test_upload_retry_is_stable_and_finance_stays_unparsed(setup_sources):
    client = client_for(setup_sources)
    key = {"Idempotency-Key": str(uuid4())}
    files = [("files", ("../private.txt", b"Private invoice notes.", "text/plain"))]
    result = client.post(
        "/api/attachments",
        headers=key,
        data={"classification": "finance", "department_id": "finance"},
        files=files,
    )
    assert result.status_code == 201, result.text
    item = result.json()["items"][0]
    assert item["processing_status"] == "waiting_approval"
    repeat = client.post(
        "/api/attachments",
        headers=key,
        data={"classification": "finance", "department_id": "finance"},
        files=files,
    )
    assert repeat.json()["items"][0]["ref"] == item["ref"]
    changed = client.post(
        "/api/attachments",
        headers=key,
        data={"classification": "finance", "department_id": "finance"},
        files=[("files", ("private.txt", b"changed", "text/plain"))],
    )
    assert changed.status_code == 409
    assert setup_sources[0].database.query("MATCH (c:SourceChunk) RETURN count(c)")[0][0] == 0
    other = client_for(setup_sources, "other")
    source = item["ref"]["source_id"]
    version = item["ref"]["version_id"]
    assert other.get(f"/api/sources/{source}").status_code == 404
    assert other.get(f"/api/sources/{source}/versions/{version}/download").status_code == 404


def test_batch_validation_and_failed_parser_are_explicit(setup_sources):
    client = client_for(setup_sources)
    headers = {"Idempotency-Key": str(uuid4())}
    assert (
        client.post(
            "/api/attachments",
            headers=headers,
            files=[("files", ("a.txt", b"x", "text/plain"))] * 6,
        ).status_code
        == 422
    )
    result = client.post(
        "/api/attachments",
        headers=headers,
        files=[
            ("files", ("a.csv", b"bad schema", "text/csv")),
            ("files", ("b.txt", b"Valid note.", "text/plain")),
        ],
    )
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["status"] == "partial_failure"
    assert [i["processing_status"] for i in body["items"]] == ["failed", "completed"]
    assert body["items"][0]["error"] and body["items"][0]["ref"]
    assert (
        client.post(
            "/api/attachments", files=[("files", ("a.txt", b"x", "text/plain"))]
        ).status_code
        == 422
    )


def test_manual_link_association_requires_review_and_retry_is_idempotent(setup_sources):
    client = client_for(setup_sources)
    headers = {"Idempotency-Key": str(uuid4())}
    result = client.post(
        "/api/attachments",
        headers=headers,
        files=[("files", ("a.txt", b"Project notes.", "text/plain"))],
    ).json()
    ref = result["items"][0]["ref"]
    source = ref["source_id"]
    version = ref["version_id"]
    chunk = client.get(f"/api/sources/{source}").json()["chunks"][0]["id"]
    setup_sources[0].database.query(
        'CREATE (:Entity {id:"project",workspace_id:"meridian",classification:"general",name:"Project"})'
    )
    base = f"/api/sources/{source}/versions/{version}/links"
    assert client.get(base).status_code == 200
    assert client.get(base).json()["extraction_status"] == "unavailable"
    proposal = client.post(
        base + "/proposals",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "target_entity_id": "project",
            "relation": "DOCUMENTS",
            "evidence_chunk_ids": [chunk],
        },
    )
    assert proposal.status_code == 201, proposal.text
    decision = {
        "expected_revision": 0,
        "decisions": [{"proposal_id": proposal.json()["id"], "decision": "accept"}],
    }
    review_headers = {"Idempotency-Key": str(uuid4())}
    accepted = client.post(base + "/review", headers=review_headers, json=decision)
    assert accepted.status_code == 200, accepted.text
    assert (
        client.post(base + "/review", headers=review_headers, json=decision).json()
        == accepted.json()
    )
    assert (
        setup_sources[0].database.query("MATCH (:Source)-[r:DOCUMENTS]->(:Entity) RETURN count(r)")[
            0
        ][0]
        == 1
    )


def test_upload_rejects_large_declared_and_streamed_body_before_parsing(setup_sources, monkeypatch):
    import relay.source_routes as routes

    monkeypatch.setattr(routes, "MAX_REQUEST_BYTES", 16)
    client = client_for(setup_sources)
    headers = {"Idempotency-Key": str(uuid4()), "Content-Type": "application/octet-stream"}
    result = client.post("/api/attachments", headers=headers, content=b"x" * (64 * 1024 + 17))
    assert result.status_code == 413
    assert setup_sources[0].database.query("MATCH (s:Source) RETURN count(s)")[0][0] == 0


def test_invalid_metadata_can_be_corrected_without_poisoning_retry_key(setup_sources):
    client = client_for(setup_sources)
    headers = {"Idempotency-Key": str(uuid4())}
    files = [("files", ("a.txt", b"Valid note.", "text/plain"))]
    rejected = client.post(
        "/api/attachments", headers=headers, data={"classification": "invalid"}, files=files
    )
    assert rejected.status_code == 422
    corrected = client.post(
        "/api/attachments", headers=headers, data={"classification": "general"}, files=files
    )
    assert corrected.status_code == 201, corrected.text


def test_replacement_retains_new_original_filename_and_retry_ref(setup_sources):
    client = client_for(setup_sources)
    uploaded = client.post(
        "/api/attachments",
        headers={"Idempotency-Key": str(uuid4())},
        files=[("files", ("old.txt", b"Old text.", "text/plain"))],
    ).json()
    source = uploaded["items"][0]["ref"]["source_id"]
    headers = {"Idempotency-Key": str(uuid4())}
    response = client.post(
        f"/api/sources/{source}/versions",
        headers=headers,
        data={"expected_revision": "0"},
        files={"file": ("../new.txt", b"New text.", "text/plain")},
    )
    assert response.status_code == 200, response.text
    version = response.json()["ref"]["version_id"]
    detail = client.get(f"/api/sources/{source}/versions/{version}").json()
    assert detail["provenance"]["original_filename"] == "new.txt"
    retry = client.post(
        f"/api/sources/{source}/versions",
        headers=headers,
        data={"expected_revision": "0"},
        files={"file": ("../new.txt", b"New text.", "text/plain")},
    )
    assert retry.json() == response.json()
