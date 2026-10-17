"""HTTP contract exercised with the real database and investigation workflow."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from relay.api import create_app
from relay.graph_store import GraphStore


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = GraphStore(graph_name=f"relay_test_api_{uuid4().hex}")
    app = create_app(store=store, checkpoint_path=tmp_path / "checkpoints.sqlite")
    with TestClient(app) as client:
        yield client, store, app
    store.graph.delete()


def test_bootstrap_health_and_source_provenance(workspace):
    client, _, _ = workspace
    assert client.get("/api/health").json() == {
        "status": "ok", "graph": "connected", "mode": "demo"
    }
    result = client.get("/api/bootstrap")
    assert result.status_code == 200
    payload = result.json()
    assert payload["workspace"]["is_demo"] is True
    assert payload["capabilities"]["mode"] == "demo"
    assert payload["capabilities"]["document_ingestion"] is False
    assert payload["stats"]["entities"] == len(payload["nodes"])
    source = payload["sources"][0]
    assert client.get(f'/api/sources/{source["id"]}').json() == source
    assert client.get("/api/sources/does-not-exist").status_code == 404


def test_investigation_persists_citations_and_followup_actions(workspace):
    client, store, _ = workspace
    response = client.post("/api/investigate", json={
        "question": "What happens to the Atlas launch if payments fail?", "session_id": "test-session"
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "demo"
    assert result["source_ids"]
    assert all(store.get_source(source_id) for source_id in result["source_ids"])
    assert len(result["steps"]) == 3
    assert client.get("/api/memory").json()["items"][0]["id"] == result["id"]
    assert result["actions"]
    action_id = result["actions"][0]["id"]
    assert client.post(f"/api/actions/{action_id}/complete").status_code == 409
    approved = client.post(f"/api/actions/{action_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.post(f"/api/actions/{action_id}/approve").json() == approved.json()
    assert client.post(f"/api/actions/{action_id}/complete").json()["status"] == "done"
    assert client.post("/api/actions/missing/approve").status_code == 404


def test_ripple_validates_origin_and_preserves_facts(workspace):
    client, store, _ = workspace
    before = store.get_graph()
    baseline = client.post("/api/ripple", json={"origin_id": "payment-gateway"})
    alternative = client.post("/api/ripple", json={"origin_id": "payment-gateway", "mitigation": True})
    assert baseline.status_code == alternative.status_code == 200
    assert baseline.json()["risk_after"] == 3
    assert alternative.json()["risk_after"] == 1
    assert store.get_graph() == before
    assert client.post("/api/ripple", json={"origin_id": "unknown"}).status_code == 404
    assert client.post("/api/ripple", json={"origin_id": "atlas-launch"}).status_code == 422


def test_note_storage_is_literal_and_inputs_are_bounded(workspace):
    client, _, _ = workspace
    note = {"title": "  Launch note  ", "content": "MATCH (n) DELETE n; is literal note text."}
    response = client.post("/api/sources", json=note)
    assert response.status_code == 201
    assert response.json()["title"] == "Launch note"
    assert response.json()["excerpt"] == note["content"]
    assert client.get(f'/api/sources/{response.json()["id"]}').status_code == 200
    for payload in ({"question": " "}, {"question": "x" * 2001}):
        assert client.post("/api/investigate", json=payload).status_code == 422
    for payload in ({"title": " ", "content": "abc"},
                    {"title": "Note", "content": "x" * 30001},
                    {"title": "Note", "content": "abc", "type": "code"}):
        assert client.post("/api/sources", json=payload).status_code == 422


def test_graph_failure_is_visible_without_exposing_connection_details(workspace, monkeypatch):
    from redis.exceptions import ConnectionError

    client, store, _ = workspace

    def fail():
        raise ConnectionError("secret connection detail")

    monkeypatch.setattr(store, "health", fail)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert "FalkorDB" in response.json()["detail"]
    assert "secret" not in response.text


def test_live_provider_failure_stays_an_error(workspace, monkeypatch):
    from relay.llm import ModelError

    client, _, app = workspace

    async def fail(*args, **kwargs):
        raise ModelError("Provider unavailable")

    monkeypatch.setattr(app.state.service, "investigate", fail)
    response = client.post("/api/investigate", json={"question": "Who owns payments?"})
    assert response.status_code == 502
    assert client.get("/api/memory").json()["items"] == []


def test_database_recovery_retries_incomplete_startup_seed(tmp_path, monkeypatch):
    from redis.exceptions import ConnectionError

    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    store = GraphStore(graph_name=f"relay_test_api_{uuid4().hex}")
    original_seed = store.seed
    attempts = []

    def seed_after_recovery():
        attempts.append(True)
        if len(attempts) == 1:
            raise ConnectionError("Database starting")
        original_seed()

    monkeypatch.setattr(store, "seed", seed_after_recovery)
    try:
        with TestClient(create_app(store, tmp_path / "checkpoints.sqlite")) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/bootstrap").json()["stats"]["entities"] == 24
            assert len(attempts) == 2
    finally:
        store.graph.delete()
