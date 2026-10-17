"""One session boundary used by development and hosted FastAPI applications."""

import secrets
import ipaddress
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, SESSION_SECONDS, SessionView


COOKIE_NAME = "relay_session"


def validate_public_origin(value: str | None) -> str | None:
    """Accept a single canonical HTTPS origin, never a path or proxy header."""
    if value is None:
        return None
    message = "RELAY_PUBLIC_ORIGIN must be a canonical HTTPS origin without a path, query or credentials"
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
            authority = f"[{address.compressed}]" if address.version == 6 else str(address)
        except ValueError:
            if len(host) > 253 or not all(re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
                raise ValueError() from None
            authority = host
        port = parsed.port
        if port == 0:
            raise ValueError()
        if port is not None and port != 443:
            authority += f":{port}"
        canonical = f"https://{authority}"
        if value != canonical:
            raise ValueError()
        return canonical
    except ValueError:
        raise RuntimeError(message) from None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


def session_dependency(auth_service):
    """Attach to every protected request; unsafe methods require session CSRF."""
    def require_session(request: Request):
        try:
            view = auth_service.resolve(request.cookies.get(COOKIE_NAME))
        except AuthError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(supplied, view.csrf_token):
                raise HTTPException(403, "Invalid CSRF token")
        request.state.session = view
        return view
    return require_session


def create_auth_router(auth_service, *, secure_cookie=False, public_origin=None):
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    current_session = session_dependency(auth_service)

    @router.post("/login", response_model=SessionView)
    def login(body: LoginRequest, request: Request, response: Response):
        # Reject explicit cross-site credential submissions even before a session exists.
        origin = request.headers.get("origin")
        if public_origin is not None:
            mismatch = origin is not None and origin != public_origin
        else:
            mismatch = bool(origin) and origin.rstrip("/") != str(request.base_url).rstrip("/")
        if mismatch:
            raise HTTPException(403, "Cross-origin login is not allowed")
        try:
            credentials = auth_service.login(
                body.username, body.password,
                client_key=request.client.host if request.client else "unknown")
        except AuthError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        old_token = request.cookies.get(COOKIE_NAME)
        if old_token:
            auth_service.logout(old_token)
        response.set_cookie(COOKIE_NAME, credentials.raw_token, max_age=SESSION_SECONDS,
                            httponly=True, secure=secure_cookie, samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"
        return credentials.view

    @router.get("/session", response_model=SessionView)
    def session(response: Response, view=Depends(current_session)):
        response.headers["Cache-Control"] = "no-store"
        return view

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response, view=Depends(current_session)):
        auth_service.logout(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, httponly=True, secure=secure_cookie,
                               samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"

    return router
