"""Hosted login trusts one configured origin, independently of proxy headers."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api_helpers import TEST_PASSWORD, prepare
from relay.graph_store import GraphStore
from relay.hosting import create_hosted_app


PUBLIC_ORIGIN = "https://relay-example.onrender.com"


@pytest.fixture
def origin_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("RELAY_PUBLIC_ORIGIN", PUBLIC_ORIGIN)
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("Relay")
    monkeypatch.setenv("RELAY_STATIC_DIR", str(static))
    store = GraphStore(f"relay_test_origin_{uuid4().hex}")
    try:
        prepare(store, tmp_path)
        yield store, tmp_path / "checkpoints.sqlite"
    finally:
        store.graph.delete()


def test_canonical_https_login_works_behind_internal_http_ingress(origin_workspace):
    store, checkpoint = origin_workspace
    with TestClient(create_hosted_app(store, checkpoint), base_url="http://internal:10000") as client:
        response = client.post("/api/auth/login", headers={"Origin": PUBLIC_ORIGIN},
                               json={"username": "owner", "password": TEST_PASSWORD})
        assert response.status_code == 200, response.text
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", PUBLIC_ORIGIN + "/path"])
def test_untrusted_origin_cannot_match_spoofed_host_or_forwarded_headers(origin_workspace, origin):
    store, checkpoint = origin_workspace
    with TestClient(create_hosted_app(store, checkpoint), base_url="https://attacker.example") as client:
        response = client.post("/api/auth/login", headers={
            "Origin": origin, "Host": "attacker.example",
            "X-Forwarded-Host": "attacker.example", "X-Forwarded-Proto": "https",
            "Forwarded": 'host="attacker.example";proto=https',
        }, json={"username": "owner", "password": TEST_PASSWORD})
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert store.database.query("MATCH (s:Session) RETURN count(s)") == [[0]]


@pytest.mark.parametrize("configured", [
    "", " ", "http://relay-example.onrender.com", "https://", "//relay-example.onrender.com",
    "https://*.onrender.com", "https://user:password@relay-example.onrender.com",
    PUBLIC_ORIGIN + "/", PUBLIC_ORIGIN + "/path", PUBLIC_ORIGIN + "?query=1",
    PUBLIC_ORIGIN + "#fragment", PUBLIC_ORIGIN + ":bad", PUBLIC_ORIGIN + ":65536",
    "https://relay-example.onrender.com\n", "https://relay-example.onrender.com\\attacker.example",
])
def test_malformed_public_origin_refuses_hosted_construction(tmp_path, monkeypatch, configured):
    monkeypatch.setenv("RELAY_PUBLIC_ORIGIN", configured)
    monkeypatch.delenv("RELAY_ACCESS_PASSWORD", raising=False)
    monkeypatch.setenv("RELAY_STATIC_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="RELAY_PUBLIC_ORIGIN"):
        create_hosted_app(checkpoint_path=tmp_path / "checkpoints.sqlite")


def test_unset_origin_preserves_same_origin_login(origin_workspace, monkeypatch):
    store, checkpoint = origin_workspace
    monkeypatch.delenv("RELAY_PUBLIC_ORIGIN")
    with TestClient(create_hosted_app(store, checkpoint), base_url="https://testserver") as client:
        body = {"username": "owner", "password": TEST_PASSWORD}
        assert client.post("/api/auth/login", headers={"Origin": "https://other.example"},
                           json=body).status_code == 403
        assert client.post("/api/auth/login", headers={"Origin": "https://testserver"},
                           json=body).status_code == 200


def test_missing_origin_retains_nonbrowser_login_support(origin_workspace):
    store, checkpoint = origin_workspace
    with TestClient(create_hosted_app(store, checkpoint), base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={
            "username": "owner", "password": TEST_PASSWORD}).status_code == 200
