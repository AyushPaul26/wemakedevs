"""Real persisted identity, session and direct HTTP boundary checks."""

import hashlib

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from relay.auth import AuthError, AuthService
from relay.auth_routes import create_auth_router, session_dependency


PASSWORD = "a long test-only password"
pytest_plugins = ["identity_helpers"]


@pytest.fixture
def auth(identity_db):
    return AuthService(identity_db)


def create_operator(auth, login="operator"):
    return auth.create_member(login, PASSWORD, "Operator", "operator")


def test_passwords_tokens_and_private_fields_are_never_returned(auth, identity_db):
    member = create_operator(auth)
    stored = identity_db.query("MATCH (m:Member {id:$id}) RETURN m.password_hash",
                               {"id": member.id})[0][0]
    assert stored.startswith("$argon2id$") and PASSWORD not in stored
    credentials = auth.login(" OPERATOR ", PASSWORD)
    assert auth.resolve(credentials.raw_token).member.id == member.id
    session = identity_db.query("MATCH (s:Session) RETURN s.id, s.expires_at, s.created_at")[0]
    assert session[0] == hashlib.sha256(credentials.raw_token.encode()).hexdigest()
    assert session[1] - session[2] == 8 * 60 * 60
    rendered = credentials.view.model_dump_json()
    assert PASSWORD not in rendered and stored not in rendered
    assert credentials.raw_token not in rendered and "auth_revision" not in rendered


def test_wrong_credentials_and_unknown_account_are_indistinguishable(auth):
    create_operator(auth)
    errors = []
    for login in ("operator", "missing"):
        with pytest.raises(AuthError) as raised:
            auth.login(login, "incorrect")
        errors.append((raised.value.status_code, str(raised.value)))
    assert errors == [(401, "Invalid login or password")] * 2


def test_unique_normalized_logins(auth):
    create_operator(auth, " Alice ")
    with pytest.raises(ValueError, match="exists"):
        create_operator(auth, "ALICE")


@pytest.mark.parametrize("mutation", ["m.active=false", "m.auth_revision=2"])
def test_current_member_revocation_is_checked_on_every_resolve(auth, identity_db, mutation):
    member = create_operator(auth)
    token = auth.login("operator", PASSWORD).raw_token
    identity_db.query(f"MATCH (m:Member {{id:$id}}) SET {mutation}", {"id": member.id})
    with pytest.raises(AuthError) as raised:
        auth.resolve(token)
    assert raised.value.status_code == 401


def test_expired_and_logged_out_sessions_are_rejected(auth, identity_db):
    create_operator(auth)
    token = auth.login("operator", PASSWORD).raw_token
    identity_db.query("MATCH (s:Session) SET s.expires_at=0")
    with pytest.raises(AuthError):
        auth.resolve(token)
    token = auth.login("operator", PASSWORD).raw_token
    auth.logout(token)
    auth.logout(token)
    with pytest.raises(AuthError):
        auth.resolve(token)


def test_bootstrap_creates_first_admin_only_and_never_resets_password(auth):
    assert auth.bootstrap_admin("Owner", PASSWORD)
    assert not auth.bootstrap_admin("Owner", "replacement password")
    assert auth.resolve(auth.login("owner", PASSWORD).raw_token).member.role == "admin"
    with pytest.raises(AuthError):
        auth.login("owner", "replacement password")


def test_missing_bootstrap_secret_does_not_create_any_account(auth):
    assert not auth.bootstrap_admin("owner", None)
    with pytest.raises(AuthError):
        auth.login("owner", "")


def test_failed_login_throttle_is_bounded(auth):
    create_operator(auth)
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.login("operator", "bad")
    with pytest.raises(AuthError) as raised:
        auth.login("operator", PASSWORD)
    assert raised.value.status_code == 429
    for number in range(1100):
        # An already throttled shared client must not grow the account cache.
        with pytest.raises(AuthError):
            auth.login(f"unknown-{number}", "bad", client_key="same-client")
    assert auth.throttle_size <= 1024


def test_direct_requests_require_session_csrf_and_secure_cookie(auth):
    create_operator(auth)
    app = FastAPI()
    app.include_router(create_auth_router(auth, secure_cookie=True))

    @app.get("/api/bootstrap")
    def bootstrap(view=Depends(session_dependency(auth))):
        return {"member": view.member.id}

    @app.post("/api/protected")
    def mutate(view=Depends(session_dependency(auth))):
        return {"member": view.member.id}

    client = TestClient(app, base_url="https://testserver")
    assert client.get("/api/bootstrap").status_code == 401
    assert client.post("/api/auth/login", json={"username": "operator", "password": "bad"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert client.get("/api/bootstrap").status_code == 200
    assert client.post("/api/protected").status_code == 403
    csrf = response.json()["csrf_token"]
    assert client.post("/api/protected", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/session").status_code == 401


def test_finance_reviewer_assignment_requires_explicit_active_auditor(auth, identity_db):
    operator = create_operator(auth)
    with pytest.raises(ValueError):
        auth.assign_finance_reviewer(operator.id)
    unassigned = auth.create_member("unassigned", PASSWORD, "Unassigned", "finance_auditor")
    with pytest.raises(ValueError):
        auth.assign_finance_reviewer(unassigned.id)
    auditor = auth.create_member("auditor", PASSWORD, "Auditor", "finance_auditor", ["finance"])
    policy_id = auth.assign_finance_reviewer(auditor.id)
    row = identity_db.query("MATCH (d:Department {id:'finance'})-[:GOVERNED_BY]->(p:Policy) "
                            "WHERE p.id=d.current_policy_id RETURN p.id,p.reviewer_id")[0]
    assert row == [policy_id, auditor.id]


def test_role_change_and_disable_revoke_sessions_and_cli_can_reenable(auth):
    member = create_operator(auth)
    token = auth.login("operator", PASSWORD).raw_token
    auth.update_member(member.id, role="finance_auditor", department_ids=["finance"])
    with pytest.raises(AuthError):
        auth.resolve(token)
    assert auth.resolve(auth.login("operator", PASSWORD).raw_token).member.role == "finance_auditor"
    auth.update_member(member.id, active=False)
    with pytest.raises(AuthError):
        auth.login("operator", PASSWORD)
    auth.update_member(member.id, active=True)
    assert auth.resolve(auth.login("operator", PASSWORD).raw_token).member.id == member.id


def test_first_admin_bootstrap_race_creates_one_account(auth, identity_db):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(AuthService(identity_db).bootstrap_admin, login, PASSWORD)
                   for login in ("owner-one", "owner-two")]
        results = [future.result() for future in futures]
    assert sorted(results) == [False, True]
    assert identity_db.query("MATCH (m:Member) RETURN count(m)")[0][0] == 1


def test_cli_uses_hidden_confirmed_password_and_assigns_finance_policy(identity_db, monkeypatch):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "manage_members.py"
    spec = importlib.util.spec_from_file_location("manage_members", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    prompts = []

    def hidden(prompt):
        prompts.append(prompt)
        return PASSWORD

    monkeypatch.setattr(cli.getpass, "getpass", hidden)
    assert cli.main(["create", "auditor", "--display-name", "Finance Auditor", "--role",
                     "finance_auditor", "--department", "finance"], database=identity_db) == 0
    member = AuthService(identity_db).resolve(AuthService(identity_db).login("auditor", PASSWORD).raw_token).member
    assert len(prompts) == 2
    assert cli.main(["assign-finance-reviewer", member.id], database=identity_db) == 0
    assert identity_db.query("MATCH (d:Department {id:'finance'}) RETURN d.current_policy_id")[0][0]
