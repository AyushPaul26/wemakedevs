"""The normal and hosted API share one real identity boundary."""
from uuid import uuid4
import asyncio

import pytest
from fastapi.testclient import TestClient

from relay.api import create_app
from relay.access import AccessContext
from relay.graph_store import GraphStore
from relay.migrations import MigrationService, create_backup


@pytest.fixture
def session_app(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", "test-only long password")
    store = GraphStore(f"relay_test_session_api_{uuid4().hex}")
    store.seed()
    MigrationService(store.database, tmp_path).apply(create_backup(store.database, tmp_path, quiesced=True))
    app = create_app(store, tmp_path / "checkpoints.sqlite")
    try:
        with TestClient(app) as client:
            yield client, app, store
    finally:
        store.graph.delete()


def test_login_session_and_csrf_protect_existing_endpoints(session_app):
    client, _, _ = session_app
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/bootstrap").status_code == 401
    assert client.post("/api/investigate", content=b"{").status_code == 401
    login = client.post("/api/auth/login", json={"username": "owner", "password": "test-only long password"})
    assert login.status_code == 200
    assert "httponly" in login.headers["set-cookie"].lower()
    session = login.json()
    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert all("excerpt" not in source for source in bootstrap.json()["sources"])
    assert client.post("/api/investigate", json={"question": "Who owns payments?"}).status_code == 403
    client.headers["X-CSRF-Token"] = session["csrf_token"]
    result = client.post("/api/investigate", json={"question": "Who owns payments?"})
    assert result.status_code == 200, result.text
    assert result.json()["source_ids"]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/memory").status_code == 401


def test_unmigrated_health_never_seeds_or_upgrades(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    store = GraphStore(f"relay_test_unmigrated_{uuid4().hex}")
    store.database.query("CREATE (:Source {id:'untouched',payload:'{}'})")
    try:
        with TestClient(create_app(store, tmp_path / "checkpoints.sqlite")) as client:
            assert client.get("/api/health").status_code == 503
            assert client.get("/api/health").status_code == 503
        assert store.database.query("MATCH (n) RETURN labels(n),n.id") == [[["Source"], "untouched"]]
    finally:
        store.graph.delete()


def test_http_invoice_review_approval_download_and_followup(session_app):
    client, app, store = session_app
    auditor = app.state.auth.create_member("auditor", "test-only auditor password",
                                           "Finance auditor", "finance_auditor", ("finance",))
    app.state.auth.assign_finance_reviewer(auditor.id)
    store.database.query("MATCH (w:Workspace {id:'meridian'}) SET w.execution_enabled=true")
    client.portal.call(app.state.engine.start)

    def sign_in(username, password):
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response.json()["member"]

    def post(path, **kwargs):
        return client.post(path, headers={"Idempotency-Key": str(uuid4())}, **kwargs)

    owner = sign_in("owner", "test-only long password")
    refs = []
    for title, price in (("Invoice", "110.00"), ("Purchase order", "100.00")):
        response = post("/api/attachments", data={"title": title, "classification": "finance",
            "department_id": "finance"}, files=[("files", (title + ".csv",
            f"item_id,quantity,unit_price,currency\ngateway-seat,2,{price},USD\n".encode(), "text/csv"))])
        assert response.status_code == 201, response.text
        refs.append(response.json()["items"][0]["ref"])
    response = post("/api/workflow-runs", json={"template": "invoice_review", "invoice": refs[0],
        "purchase_order": refs[1], "context": [], "project_id": "atlas-launch",
        "automation": "auto_permitted", "output_audience": [owner["id"]]})
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    async def wait_for(predicate):
        for _ in range(200):
            run = await asyncio.to_thread(app.state.workflows.get_run, AccessContext(owner["id"]), run_id)
            if predicate(run):
                return run
            if run.status == "failed" or any(step['status'] == 'failed' for step in run.steps):
                raise AssertionError(str(run.model_dump()))
            await asyncio.sleep(.1)
        raise AssertionError(f"Workflow did not reach expected state: {run.model_dump()}, dispatcher={app.state.engine.last_error}")

    run = client.portal.call(wait_for, lambda run: next(s for s in run.steps if s["logical_key"] == "company_context")["status"] == "completed")
    assert store.database.query("MATCH (c:SourceChunk) WHERE c.version_id IN $ids RETURN count(c)",
        {"ids": [ref["version_id"] for ref in refs]}) == [[0]]
    assert client.post("/api/investigate", json={"question": "Read the invoice", "source_refs": refs}).status_code == 404
    sign_in("auditor", "test-only auditor password")
    inbox = client.get("/api/approvals").json()["items"]
    approval = next(a for a in inbox if a["run_id"] == run_id)
    response = post(f"/api/approvals/{approval['id']}/decision", json={"decision": "approve",
        "expected_revision": approval["expected_revision"], "scope_hash": approval["scope_hash"]})
    assert response.status_code == 200, response.text
    sign_in("owner", "test-only long password")
    run = client.portal.call(wait_for, lambda run: run.status == "completed")
    assert len(run.outputs) == 2 and len(run.cases) == 1
    assert all(step.get("execution", {}).get("id") for step in run.steps)
    for artifact in run.outputs:
        download = client.get(f"/api/artifacts/{artifact['id']}/download")
        assert download.status_code == 200
        assert "20.00" in download.text if artifact["kind"] == "report_html" else "gateway-seat" in download.text
    answer = client.post("/api/investigate", json={"question": "What happened in that review?", "run_id": run_id})
    assert answer.status_code == 200, answer.text
    assert answer.json()["output_ids"]
    assert "20.00" in answer.json()["answer"]
