"""HTTP boundary for Relay. All company state is stored in FalkorDB."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from relay.agents import InvestigationService
from relay.graph_store import GraphStore
from relay.llm import ModelError
from relay.models import InvestigationRequest, RippleRequest, SourceRequest

logger = logging.getLogger(__name__)


def create_app(store=None, checkpoint_path: str | Path | None = None) -> FastAPI:
    seed_lock = Lock()

    def ensure_seeded():
        if not app.state.seeded:
            with seed_lock:
                if not app.state.seeded:
                    app.state.store.seed()
                    app.state.seeded = True

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store if store is not None else GraphStore()
        app.state.seeded = False
        try:
            ensure_seeded()
        except RedisError:
            logger.warning("FalkorDB unavailable during startup; health will report unavailable.")
        app.state.service = InvestigationService(
            app.state.store,
            checkpoint_path=checkpoint_path or os.getenv(
                "RELAY_CHECKPOINT_PATH", ".data/checkpoints.sqlite"
            ),
        )
        try:
            yield
        finally:
            await app.state.service.aclose()

    app = FastAPI(title="Relay · Company Brain", version="0.1.0", lifespan=lifespan,
                  dependencies=[Depends(ensure_seeded)])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RedisError)
    async def graph_error(request: Request, exc: RedisError):
        return JSONResponse(status_code=503, content={
            "detail": "FalkorDB is unavailable. Start the database and retry."
        })

    @app.exception_handler(ModelError)
    async def model_error(request: Request, exc: ModelError):
        # Never return raw provider response bodies, which can include request metadata.
        return JSONResponse(status_code=502, content={
            "detail": "The model could not complete this investigation. Check the provider "
                      "settings and quota, then retry. Your previous memory is unchanged."
        })

    @app.get("/api/health")
    def health():
        if not app.state.store.health():
            raise HTTPException(503, "FalkorDB is unavailable. Start the database and retry.")
        return {"status": "ok", "graph": "connected", "mode": app.state.service.mode}

    @app.get("/api/bootstrap")
    def bootstrap():
        graph = app.state.store.get_graph()
        return {
            "workspace": {"name": "Meridian", "project": "Atlas launch", "is_demo": True},
            **graph,
            "stats": app.state.store.stats(),
            "capabilities": {"mode": app.state.service.mode,
                             "provider": app.state.service.provider,
                             "document_ingestion": False},
            "recent_memory": app.state.store.list_memories(),
            "actions": app.state.store.list_actions(),
        }

    @app.post("/api/investigate")
    async def investigate(body: InvestigationRequest):
        return await app.state.service.investigate(body.question, body.session_id)

    @app.post("/api/ripple")
    def ripple(body: RippleRequest):
        nodes = app.state.store.get_graph()["nodes"]
        origin = next((node for node in nodes if node["id"] == body.origin_id), None)
        if origin is None:
            raise HTTPException(404, "This graph node does not exist.")
        if origin["kind"] != "service":
            raise HTTPException(422, "Choose a service as the Ripple origin.")
        try:
            return app.state.store.simulate(body.origin_id, body.mitigation)
        except ValueError as exc:
            raise HTTPException(422, "This service cannot be simulated.") from exc

    @app.get("/api/memory")
    def memory():
        return {"items": app.state.store.list_memories()}

    @app.get("/api/actions")
    def actions():
        return {"items": app.state.store.list_actions()}

    def transition(action_id, target_status):
        try:
            return app.state.store.transition_action(action_id, target_status)
        except KeyError as exc:
            raise HTTPException(404, "This action does not exist.") from exc
        except ValueError as exc:
            raise HTTPException(409, "Approve a proposed action before completing it. "
                                "Completed actions cannot be reopened.") from exc

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: str):
        return transition(action_id, "approved")

    @app.post("/api/actions/{action_id}/complete")
    def complete(action_id: str):
        return transition(action_id, "done")

    @app.get("/api/sources/{source_id}")
    def source(source_id: str):
        result = app.state.store.get_source(source_id)
        if result is None:
            raise HTTPException(404, "This source does not exist.")
        return result

    @app.post("/api/sources", status_code=201)
    def add_source(body: SourceRequest):
        return app.state.store.add_source(body.title, body.content)

    return app


app = create_app()
