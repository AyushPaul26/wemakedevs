"""Authenticated deployment entry point; local development stays in relay.api."""

import base64
import binascii
import os
from pathlib import Path
from secrets import compare_digest

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relay.api import create_app


_PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class _AccessBoundary:
    """Authenticate before routing or reading request bodies."""

    def __init__(self, app: ASGIApp, password: str):
        self.app = app
        self._password = password.encode("utf-8")

    def _authenticated(self, scope: Scope) -> bool:
        authorization = Headers(scope=scope).getlist("authorization")
        if len(authorization) != 1:
            return False
        scheme, _, encoded = authorization[0].partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return False
        username, separator, password = decoded.partition(b":")
        valid_username = compare_digest(username, b"relay")
        valid_password = compare_digest(password, self._password)
        return bool(separator) and valid_username and valid_password

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_private(message: Message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(_PRIVATE_HEADERS)
            await send(message)

        public_health = (
            scope["method"] == "GET"
            and scope["path"] == "/api/health"
            and scope.get("raw_path", b"/api/health") == b"/api/health"
        )
        if not public_health and not self._authenticated(scope):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": 'Basic realm="Relay", charset="UTF-8"'},
            )
            await response(scope, receive, send_private)
            return
        await self.app(scope, receive, send_private)


class _FrontendFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        # Reserve the API namespace even if the build contains an api directory.
        # Inspect the original path too: StaticFiles normalizes dot segments.
        original_path = scope["path"]
        if (path == "api" or path.startswith("api/")
                or original_path == "/api" or original_path.startswith("/api/")):
            raise HTTPException(status_code=404, detail="Not Found")
        return await super().get_response(path, scope)


def create_hosted_app(store=None, checkpoint_path: str | Path | None = None) -> FastAPI:
    """Use with ``uvicorn relay.hosting:create_hosted_app --factory``."""
    password = os.environ.get("RELAY_ACCESS_PASSWORD", "")
    if len(password) < 16:
        raise RuntimeError("RELAY_ACCESS_PASSWORD must contain at least 16 characters.")

    app = create_app(store=store, checkpoint_path=checkpoint_path)
    app.add_middleware(_AccessBoundary, password=password)

    @app.exception_handler(Exception)
    async def private_server_error(request, exc):
        # Starlette's server-error handler sits outside application middleware.
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
            headers=_PRIVATE_HEADERS,
        )

    app.mount(
        "/",
        _FrontendFiles(
            directory=os.environ.get("RELAY_STATIC_DIR", "/app/frontend/dist"),
            html=True,
            follow_symlink=False,
        ),
        name="frontend",
    )
    return app
