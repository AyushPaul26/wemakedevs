"""The public hosting boundary protects the real API and built frontend."""

import base64
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from relay.graph_store import GraphStore


PASSWORD = "test-password-16"


def assert_private_headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.fixture
def hosted_workspace(tmp_path, monkeypatch):
    from relay.hosting import create_hosted_app

    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", PASSWORD)
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>Relay test frontend</html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets/app.js").write_text("document.title = 'Relay';")
    # Even a frontend build with an api directory cannot capture unknown API routes.
    (static_dir / "api").mkdir()
    (static_dir / "api/index.html").write_text("This is not an API response")
    (tmp_path / "outside.txt").write_text("outside the static root")
    (static_dir / "outside-link.txt").symlink_to(tmp_path / "outside.txt")
    (tmp_path / "dist-neighbor").mkdir()
    (tmp_path / "dist-neighbor/private.txt").write_text("outside the static root")
    monkeypatch.setenv("RELAY_STATIC_DIR", str(static_dir))
    store = GraphStore(graph_name=f"relay_test_hosting_{uuid4().hex}")
    app = create_hosted_app(store=store, checkpoint_path=tmp_path / "checkpoints.sqlite")
    try:
        with TestClient(app) as client:
            yield client, store, app
    finally:
        store.graph.delete()


@pytest.mark.parametrize("password", [None, "", "short", "x" * 15])
def test_hosting_requires_a_strong_configured_password(password, monkeypatch):
    from relay.hosting import create_hosted_app

    if password is None:
        monkeypatch.delenv("RELAY_ACCESS_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("RELAY_ACCESS_PASSWORD", password)
    with pytest.raises(RuntimeError, match="RELAY_ACCESS_PASSWORD.*16"):
        create_hosted_app()


def test_only_exact_get_health_is_public(hosted_workspace):
    client, store, _ = hosted_workspace
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "graph": "connected", "mode": "demo"}
    assert_private_headers(health)
    before = store.get_graph()
    for method, path in [
        ("GET", "/"), ("GET", "/assets/app.js"), ("GET", "/api/bootstrap"),
        ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/api/missing"),
        ("GET", "/api/health/"), ("GET", "/api/%68ealth"), ("HEAD", "/api/health"),
        ("POST", "/api/health"), ("OPTIONS", "/api/bootstrap"),
        ("POST", "/api/investigate"), ("POST", "/api/sources"), ("POST", "/api/ripple"),
        ("POST", "/api/actions/example/approve"),
    ]:
        response = client.request(method, path, content=b"{", follow_redirects=False)
        assert response.status_code == 401, (method, path, response.text)
        assert response.headers["www-authenticate"].startswith("Basic ")
        assert_private_headers(response)
    assert store.get_graph() == before
    assert store.list_memories() == []


def test_wrong_and_malformed_basic_credentials_are_rejected(hosted_workspace):
    client, _, _ = hosted_workspace
    for credentials in [("relay", "wrong"), ("other", PASSWORD), ("", PASSWORD)]:
        response = client.get("/api/bootstrap", auth=credentials)
        assert response.status_code == 401
        assert "Basic" in response.headers["www-authenticate"]
        assert PASSWORD not in response.text
        assert_private_headers(response)
    for authorization in [
        "", "Basic", "Basic ", "Bearer abc", "Basic !!!", "Basic a",
        "Basic " + base64.b64encode(b"relay-without-colon").decode(),
        "Basic " + base64.b64encode(b"relay:\xff").decode(),
    ]:
        response = client.get("/api/bootstrap", headers={"Authorization": authorization})
        assert response.status_code == 401, authorization
        assert "Basic" in response.headers["www-authenticate"]
        assert_private_headers(response)


def test_authenticated_frontend_api_and_ripple_work(hosted_workspace):
    client, store, _ = hosted_workspace
    client.auth = ("relay", PASSWORD)
    index = client.get("/")
    assert index.status_code == 200
    assert index.text == "<html>Relay test frontend</html>"
    assert index.headers["content-type"].startswith("text/html")
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "document.title = 'Relay';"
    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["stats"]["entities"] == 24
    assert bootstrap.json()["capabilities"]["mode"] == "demo"
    before = store.get_graph()
    ripple = client.post("/api/ripple", json={"origin_id": "payment-gateway"})
    assert ripple.status_code == 200
    assert ripple.json()["risk_after"] == 3
    assert store.get_graph() == before
    for response in (index, asset, bootstrap, ripple):
        assert_private_headers(response)


def test_public_health_checks_graph_availability(hosted_workspace, monkeypatch):
    client, store, _ = hosted_workspace

    def disconnected(*args, **kwargs):
        raise ConnectionError("private graph connection details")

    monkeypatch.setattr(store, "_query", disconnected)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert "FalkorDB" in response.json()["detail"]
    assert "private" not in response.text
    assert_private_headers(response)


def test_unexpected_errors_keep_private_headers(hosted_workspace, monkeypatch):
    _, store, app = hosted_workspace

    def unexpected_failure():
        raise RuntimeError("private internal failure")

    monkeypatch.setattr(store, "get_graph", unexpected_failure)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/bootstrap", auth=("relay", PASSWORD))
        assert response.status_code == 500
        assert "private internal failure" not in response.text
        assert_private_headers(response)
    finally:
        client.close()


def test_static_files_cannot_escape_root_or_capture_unknown_api(hosted_workspace):
    client, _, _ = hosted_workspace
    client.auth = ("relay", PASSWORD)
    for path in [
        "/api", "/api/", "/api/missing", "/api/index.html", "/api/%2e%2e/index.html",
        "/missing-page",
        "/%2e%2e/outside.txt", "/%2e%2e/dist-neighbor/private.txt", "/outside-link.txt",
    ]:
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert "Relay test frontend" not in response.text
        assert "outside the static root" not in response.text
        assert "This is not an API response" not in response.text
        assert_private_headers(response)
