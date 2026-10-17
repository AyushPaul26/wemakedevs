"""Hosted login assets with the same session-authenticated API as development."""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from relay.api import PRIVATE_HEADERS, create_app


class _FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        original_path = scope["path"]
        if (path == "api" or path.startswith("api/") or original_path == "/api"
                or original_path.startswith("/api/")):
            raise HTTPException(status_code=404, detail="Not Found")
        return await super().get_response(path, scope)


def create_hosted_app(store=None, checkpoint_path: str | Path | None = None) -> FastAPI:
    """Use with uvicorn relay.hosting:create_hosted_app --factory."""
    password = os.environ.get("RELAY_ACCESS_PASSWORD", "")
    if password and len(password) < 16:
        raise RuntimeError("RELAY_ACCESS_PASSWORD must contain at least 16 characters.")
    app = create_app(store=store, checkpoint_path=checkpoint_path, secure_cookie=True,
                     public_origin=os.getenv("RELAY_PUBLIC_ORIGIN"))

    @app.exception_handler(Exception)
    async def private_server_error(request, exc):
        return JSONResponse(status_code=500, content={"detail": "Internal server error."}, headers=PRIVATE_HEADERS)

    app.mount("/", _FrontendFiles(directory=os.environ.get("RELAY_STATIC_DIR", "/app/frontend/dist"),
                                  html=True, follow_symlink=False), name="frontend")
    return app
