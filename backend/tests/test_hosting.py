"""Hosted assets are public; company API and private files require real sessions."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from api_helpers import TEST_PASSWORD, login, prepare
from relay.graph_store import GraphStore


def assert_private_headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.fixture
def hosted_workspace(tmp_path, monkeypatch):
    from relay.hosting import create_hosted_app
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", TEST_PASSWORD)
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>Relay test frontend</html>")
    (static_dir / "assets").mkdir()
    (static_dir / "assets/app.js").write_text("document.title = 'Relay';")
    (static_dir / "api").mkdir()
    (static_dir / "api/index.html").write_text("This is not an API response")
    (tmp_path / "outside.txt").write_text("outside the static root")
    (static_dir / "outside-link.txt").symlink_to(tmp_path / "outside.txt")
    (tmp_path / "dist-neighbor").mkdir()
    (tmp_path / "dist-neighbor/private.txt").write_text("outside the static root")
    monkeypatch.setenv("RELAY_STATIC_DIR", str(static_dir))
    store = GraphStore(graph_name=f"relay_test_hosting_{uuid4().hex}")
    prepare(store, tmp_path)
    app = create_hosted_app(store=store, checkpoint_path=tmp_path / "checkpoints.sqlite")
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, store, app
    finally:
        store.graph.delete()


def test_login_assets_and_exact_health_are_public_but_api_is_private(hosted_workspace):
    client, store, _ = hosted_workspace
    for path in ("/", "/assets/app.js", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert_private_headers(response)
    before = store.get_graph()
    for method, path in [
        ("GET", "/api/bootstrap"), ("GET", "/api/missing"), ("GET", "/api/health/"),
        ("GET", "/api/%68ealth"), ("HEAD", "/api/health"), ("POST", "/api/health"),
        ("POST", "/api/investigate"), ("POST", "/api/sources"), ("POST", "/api/ripple"),
    ]:
        response = client.request(method, path, content=b"{", follow_redirects=False)
        assert response.status_code == 401, (method, path, response.text)
        assert "www-authenticate" not in response.headers
        assert_private_headers(response)
    assert store.get_graph() == before


def test_basic_auth_cannot_bypass_session_and_hosted_cookie_is_secure(hosted_workspace):
    client, _, _ = hosted_workspace
    assert client.get("/api/bootstrap", auth=("relay", TEST_PASSWORD)).status_code == 401
    result = client.post("/api/auth/login", json={"username": "owner", "password": TEST_PASSWORD})
    assert result.status_code == 200
    assert "secure" in result.headers["set-cookie"].lower()
    assert "httponly" in result.headers["set-cookie"].lower()
    assert client.get("/api/bootstrap").status_code == 200


def test_authenticated_frontend_api_and_ripple_work(hosted_workspace):
    client, store, _ = hosted_workspace
    login(client)
    bootstrap = client.get("/api/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["stats"]["entities"] == 24
    before = store.get_graph()
    ripple = client.post("/api/ripple", json={"origin_id": "payment-gateway"})
    assert ripple.status_code == 200
    assert ripple.json()["risk_after"] == 3
    assert store.get_graph() == before
    for response in (bootstrap, ripple):
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
    client, store, app = hosted_workspace
    login(client)
    def unexpected_failure():
        raise RuntimeError("private internal failure")
    monkeypatch.setattr(store, "get_graph", unexpected_failure)
    with TestClient(app, raise_server_exceptions=False, base_url="https://testserver") as second:
        second.cookies.update(client.cookies)
        response = second.get("/api/bootstrap")
    assert response.status_code == 500
    assert "private internal failure" not in response.text
    assert_private_headers(response)


def test_static_files_cannot_escape_root_or_capture_unknown_api(hosted_workspace):
    client, _, _ = hosted_workspace
    login(client)
    for path in [
        "/api", "/api/", "/api/missing", "/api/index.html", "/api/%2e%2e/index.html",
        "/missing-page", "/%2e%2e/outside.txt", "/%2e%2e/dist-neighbor/private.txt", "/outside-link.txt",
    ]:
        response = client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert "Relay test frontend" not in response.text
        assert "outside the static root" not in response.text
        assert "This is not an API response" not in response.text
        assert_private_headers(response)
