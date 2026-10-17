"""Persisted workspace identities; bearer secrets never leave server credentials."""

from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import secrets
from threading import RLock
import time
import unicodedata
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict


ROLES = {"admin", "operator", "finance_auditor"}
SESSION_SECONDS = 8 * 60 * 60
_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))


class AuthError(Exception):
    def __init__(self, message="Authentication required", status_code=401):
        super().__init__(message)
        self.status_code = status_code


class MemberView(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    display_name: str
    role: str
    department_ids: list[str]


class SessionView(BaseModel):
    model_config = ConfigDict(frozen=True)
    member: MemberView
    csrf_token: str
    expires_at: str


@dataclass(frozen=True, repr=False)
class SessionCredentials:
    raw_token: str
    view: SessionView


def normalized_login(value):
    login = unicodedata.normalize("NFKC", value).strip().casefold()
    if not re.fullmatch(r"[a-z0-9_.@+\-]{1,128}", login):
        raise ValueError("Login must contain 1–128 letters, digits, or . _ @ + -")
    return login


def token_digest(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


class AuthService:
    """Use an injected GraphDatabase; all security fields are scalar properties."""

    def __init__(self, database, *, clock=time.time):
        self.database = database
        self.clock = clock
        self._failures = OrderedDict()
        self._lock = RLock()

    @property
    def throttle_size(self):
        return len(self._failures)

    def _member(self, member_id, *, require_active=True):
        rows = self.database.query(
            "MATCH (m:Member {id:$id}) RETURN m.id,m.display_name,m.role,m.active,"
            "m.auth_revision,m.workspace_id,m.department_ids", {"id": member_id})
        if not rows:
            raise AuthError()
        row = rows[0]
        if (require_active and not row[3]) or row[5] != "meridian" or row[2] not in ROLES:
            raise AuthError()
        return (MemberView(id=row[0], display_name=row[1], role=row[2],
                           department_ids=row[6] or []), row[4])

    @staticmethod
    def _validate_member(login, password, display_name, role, departments):
        login = normalized_login(login)
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError("Password must contain 12–1024 characters")
        if not display_name.strip() or len(display_name) > 160:
            raise ValueError("Display name must contain 1–160 characters")
        if role not in ROLES or any(d not in {"general", "finance"} for d in departments):
            raise ValueError("Unsupported role or department")
        return login

    def create_member(self, login, password, display_name, role, department_ids=()):
        """Local administrator provisioning only; never expose as a public route."""
        login = self._validate_member(login, password, display_name, role, department_ids)
        member_id = f"member_{uuid4().hex}"
        rows = self.database.query(
            "MERGE (m:Member {login:$login}) ON CREATE SET m.id=$id,"
            "m.password_hash=$password_hash,m.display_name=$display_name,m.role=$role,"
            "m.active=true,m.auth_revision=1,m.workspace_id='meridian',"
            "m.department_ids=$departments,m.created_at=$now RETURN m.id",
            {"login": login, "id": member_id, "password_hash": _HASHER.hash(password),
             "display_name": display_name.strip(), "role": role,
             "departments": sorted(set(department_ids)), "now": self.clock()})
        if not rows or rows[0][0] != member_id:
            raise ValueError("Login already exists")
        for department in set(department_ids):
            self.database.query(
                "MATCH (m:Member {id:$member}) MERGE (d:Department {id:$department}) "
                "MERGE (m)-[:MEMBER_OF]->(d)", {"member": member_id, "department": department})
        return self._member(member_id)[0]

    def bootstrap_admin(self, login, password):
        """The caller supplies its configured bootstrap secret; no hidden env reads."""
        if not password or self.database.query("MATCH (m:Member) RETURN count(m)")[0][0]:
            return False
        login = self._validate_member(login, password, "Workspace administrator", "admin", ())
        member_id = f"member_{uuid4().hex}"
        rows = self.database.query(
            "OPTIONAL MATCH (existing:Member) WITH count(existing) AS total WHERE total=0 "
            "MERGE (b:IdentityBootstrap {id:'meridian'}) ON CREATE SET b.member_id=$id "
            "WITH b WHERE b.member_id=$id CREATE (m:Member {id:$id,login:$login,"
            "display_name:'Workspace administrator',password_hash:$hash,role:'admin',"
            "workspace_id:'meridian',active:true,auth_revision:1,department_ids:[],created_at:$now}) "
            "RETURN m.id", {"id": member_id, "login": login,
                             "hash": _HASHER.hash(password), "now": self.clock()})
        return bool(rows)

    def _throttled(self, keys, now):
        for key in keys:
            attempts = self._failures.get(key)
            if attempts:
                while attempts and attempts[0] <= now - 300:
                    attempts.popleft()
                if len(attempts) >= (20 if key.startswith("client:") else 5):
                    return True
        return False

    def _failure(self, keys, now):
        for key in keys:
            self._failures.setdefault(key, deque(maxlen=20)).append(now)
            self._failures.move_to_end(key)
        while len(self._failures) > 1024:
            self._failures.popitem(last=False)

    def login(self, username, password, *, client_key=None):
        try:
            login = normalized_login(username)
        except (ValueError, TypeError):
            login = "!invalid"
        keys = ["login:" + login]
        if client_key:
            keys.append("client:" + str(client_key)[:128])
        now = self.clock()
        with self._lock:
            if self._throttled(keys, now):
                raise AuthError("Too many login attempts; retry later", 429)
            rows = self.database.query(
                "MATCH (m:Member {login:$login}) RETURN m.id,m.password_hash", {"login": login})
            password_hash = rows[0][1] if rows else _DUMMY_HASH
            try:
                valid = isinstance(password, str) and len(password) <= 1024 and _HASHER.verify(
                    password_hash, password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or not rows:
                self._failure(keys, now)
                raise AuthError("Invalid login or password")
            try:
                member, revision = self._member(rows[0][0])
            except AuthError:
                self._failure(keys, now)
                raise AuthError("Invalid login or password") from None
            self._failures.pop(keys[0], None)
            raw_token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            expires_at = now + SESSION_SECONDS
            self.database.query(
                "CREATE (:Session {id:$id,member_id:$member,auth_revision:$revision,"
                "csrf_token:$csrf,created_at:$now,expires_at:$expiry,revoked_at:0})",
                {"id": token_digest(raw_token), "member": member.id, "revision": revision,
                 "csrf": csrf, "now": now, "expiry": expires_at})
            return SessionCredentials(raw_token, self._session_view(member, csrf, expires_at))

    @staticmethod
    def _session_view(member, csrf, expiry):
        return SessionView(member=member, csrf_token=csrf,
                           expires_at=datetime.fromtimestamp(expiry, timezone.utc).isoformat())

    def resolve(self, raw_token):
        if not raw_token or not isinstance(raw_token, str) or len(raw_token) > 256:
            raise AuthError()
        rows = self.database.query(
            "MATCH (s:Session {id:$id}) RETURN s.member_id,s.auth_revision,s.expires_at,"
            "s.revoked_at,s.csrf_token", {"id": token_digest(raw_token)})
        if not rows or rows[0][3] or rows[0][2] <= self.clock():
            raise AuthError()
        member, revision = self._member(rows[0][0])
        if revision != rows[0][1]:
            raise AuthError()
        return self._session_view(member, rows[0][4], rows[0][2])

    def logout(self, raw_token):
        if raw_token and isinstance(raw_token, str) and len(raw_token) <= 256:
            self.database.query("MATCH (s:Session {id:$id}) SET s.revoked_at=$now",
                                {"id": token_digest(raw_token), "now": self.clock()})

    def update_member(self, member_id, *, role=None, active=None, department_ids=None):
        member, _ = self._member(member_id, require_active=False)
        role = role or member.role
        departments = member.department_ids if department_ids is None else department_ids
        if role not in ROLES or any(d not in {"general", "finance"} for d in departments):
            raise ValueError("Unsupported role or department")
        self.database.query(
            "MATCH (m:Member {id:$id}) SET m.role=$role,m.active=coalesce($active,m.active),"
            "m.department_ids=$departments,m.auth_revision=m.auth_revision+1",
            {"id": member_id, "role": role, "active": None if active is None else bool(active),
             "departments": sorted(set(departments))})
        self.database.query("MATCH (m:Member {id:$id})-[r:MEMBER_OF]->() DELETE r", {"id": member_id})
        for department in departments:
            self.database.query("MATCH (m:Member {id:$id}) MERGE (d:Department {id:$department}) "
                                "MERGE (m)-[:MEMBER_OF]->(d)",
                                {"id": member_id, "department": department})

    def assign_finance_reviewer(self, member_id):
        member, _ = self._member(member_id)
        membership = self.database.query(
            "MATCH (:Member {id:$id})-[:MEMBER_OF]->(:Department {id:'finance'}) RETURN 1",
            {"id": member_id})
        if member.role != "finance_auditor" or not membership:
            raise ValueError("Finance reviewer must be an active Finance auditor in Finance")
        policy_id = f"policy_finance_{uuid4().hex}"
        self.database.query(
            "MERGE (d:Department {id:'finance'}) WITH d "
            "OPTIONAL MATCH (old:Policy {id:d.current_policy_id}) WITH d,old "
            "CREATE (p:Policy {id:$id,workspace_id:'meridian',department_id:'finance',"
            "version:coalesce(old.version,0)+1,reviewer_id:$reviewer,"
            "allowed_tools:['finance_parse','invoice_compare','publish_report','upsert_case','archive_run'],"
            "approval_ttl_seconds:86400,created_at:$now}) "
            "SET d.current_policy_id=$id MERGE (d)-[:GOVERNED_BY]->(p)",
            {"id": policy_id, "reviewer": member_id, "now": self.clock()})
        return policy_id
