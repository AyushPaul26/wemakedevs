"""Authenticated HTTP boundary for company knowledge and durable workflows."""
import asyncio
from contextlib import asynccontextmanager
import io
import logging
import os
from pathlib import Path
import secrets
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from redis.exceptions import RedisError

from relay.access import AccessContext, AccessError, AccessService
from relay.agents import InvestigationService
from relay.auth import AuthError, AuthService
from relay.auth_routes import COOKIE_NAME, create_auth_router, session_dependency, validate_public_origin
from relay.company import CompanyService
from relay.evidence import EvidenceService
from relay.graph_store import GraphStore
from relay.llm import ModelError, ModelResponseError
from relay.migrations import ensure_schema
from relay.models import InvestigationRequest, RippleRequest, SourceRequest
from relay.parsers import ParseError
from relay.reports import ReportService
from relay.sources import SourceService
from relay.source_store import SourceError, SourceStore
from relay.source_routes import build_source_router
from relay.storage import BlobStore, StorageError
from relay.workflow_engine import WorkflowEngine
from relay.workflow_routes import create_workflow_router
from relay.workflow_service import WorkflowService
from relay.workflow_tools import WorkflowTools

logger = logging.getLogger(__name__)
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                   "X-Content-Type-Options": "nosniff"}
# Match only fixed application messages. Never log an exception's arbitrary text,
# its cause, a provider response, request data, or generated output.
_MODEL_ERROR_REASONS = {
    "Live model access needs RELAY_MODEL_API_KEY in environment settings.": "missing_model_key",
    "RELAY_MODEL_BASE_URL must be an absolute HTTP(S) API URL.": "invalid_model_url",
    "The model provider is unavailable or timed out. Please retry.": "provider_transport",
    "Model authentication failed. Check RELAY_MODEL_API_KEY in environment settings.": "provider_authentication",
    "The model provider is rate-limited. Please retry shortly.": "provider_rate_limited",
    "The model provider is unavailable. Please retry or check the model configuration.": "provider_http_error",
    "The model returned unreadable JSON. Please retry.": "response_json",
    "The model returned an invalid response. Please retry.": "response_schema",
    "The model cited evidence outside the retrieved graph. Please retry.": "citation_scope",
    "The model proposed a task without valid evidence or owner. Please retry.": "action_scope",
    "The model omitted evidence for its proposed answer. Please retry.": "citation_missing",
    "The model cited an unavailable evidence version. Please retry.": "citation_version",
    "The model omitted exact attachment citations. Please retry.": "citation_exact_missing",
    "The model cited an unavailable report. Please retry.": "report_scope",
    "The model returned an invalid reconciliation narrative": "report_narrative",
    "The model provider is unavailable; retry is available": "provider_unavailable",
}
_MODEL_VALIDATION_REASONS = frozenset({
    "answer_empty", "source_outside_context", "node_outside_context", "inline_not_declared",
})


def create_app(store=None, checkpoint_path: str | Path | None = None, *, secure_cookie=False,
               data_dir: str | Path | None = None, public_origin: str | None = None) -> FastAPI:
    public_origin = validate_public_origin(public_origin)
    store = store if store is not None else GraphStore()
    root = Path(data_dir or (Path(checkpoint_path).parent if checkpoint_path else
                            os.getenv("RELAY_DATA_DIR", ".data")))
    checkpoint = Path(checkpoint_path or os.getenv("RELAY_CHECKPOINT_PATH") or root / "checkpoints.sqlite")
    auth = AuthService(store.database)
    access_service = AccessService(store.database)
    source_store = SourceStore(store.database, access_service)
    sources = SourceService(source_store, BlobStore(root))
    workflows = WorkflowService(store.database, access_service)
    source_store.invalidate = workflows.store.invalidate_source
    company = CompanyService(store, access_service, EvidenceService(sources),
                             workflows.permitted_run_context)
    reports = ReportService(root / "artifacts")
    session = session_dependency(auth)

    def ready():
        try:
            ensure_schema(store.database)
        except RuntimeError:
            raise HTTPException(503, "Database migration is required or maintenance is in progress.") from None

    def context(view=Depends(session), _=Depends(ready)):
        return AccessContext(view.member.id)

    @asynccontextmanager
    async def lifespan(app):
        app.state.store, app.state.auth = store, auth
        app.state.company, app.state.sources = company, sources
        app.state.workflows, app.state.reports = workflows, reports
        app.state.service = InvestigationService(company, checkpoint_path=checkpoint)
        tools = WorkflowTools(sources, reports, company=company,
                              model_client=app.state.service.model_client)
        app.state.engine = WorkflowEngine(workflows.store, sources, tools, checkpoint)
        app.state.execution_enabled = False
        try:
            ready()
            auth.bootstrap_admin(os.getenv("RELAY_BOOTSTRAP_ADMIN_LOGIN", "owner"),
                                 os.getenv("RELAY_ACCESS_PASSWORD") or None)
            enabled = store.database.read("MATCH (w:Workspace {id:'meridian'}) RETURN w.execution_enabled")
            app.state.execution_enabled = bool(enabled and enabled[0][0])
            if app.state.execution_enabled:
                await app.state.engine.start()
        except (RedisError, HTTPException):
            logger.warning("Database is not ready; health remains unavailable until migration/restart.")
        try:
            yield
        finally:
            await app.state.engine.stop()
            await app.state.service.aclose()

    app = FastAPI(title="Relay · Company Brain", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def session_boundary(request: Request, call_next):
        path = request.url.path
        public_health = (request.method == "GET" and path == "/api/health"
                         and request.scope.get("raw_path") == b"/api/health")
        public_login = request.method == "POST" and path == "/api/auth/login"
        try:
            if path == "/api" or path.startswith("/api/"):
                if not public_health:
                    await asyncio.to_thread(ready)
                if not public_health and not public_login:
                    view = await asyncio.to_thread(auth.resolve, request.cookies.get(COOKIE_NAME))
                    if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(
                            request.headers.get("X-CSRF-Token", ""), view.csrf_token):
                        raise HTTPException(403, "Invalid CSRF token")
                    request.state.session = view
            response = await call_next(request)
        except (AuthError, AccessError, HTTPException) as exc:
            response = JSONResponse(status_code=exc.status_code,
                                    content={"detail": getattr(exc, "detail", str(exc))})
        except RedisError:
            response = JSONResponse(status_code=503, content={"detail": "FalkorDB is unavailable. Retry shortly."})
        response.headers.update(PRIVATE_HEADERS)
        return response

    @app.exception_handler(RedisError)
    async def graph_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "FalkorDB is unavailable. Retry shortly."})

    for error_type in (AccessError, AuthError, SourceError, StorageError):
        async def boundary_error(request, exc):
            return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})
        app.add_exception_handler(error_type, boundary_error)

    @app.exception_handler(ParseError)
    async def parse_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ModelError)
    async def model_error(request, exc):
        category = "response_validation" if isinstance(exc, ModelResponseError) else "provider"
        message = exc.args[0] if len(exc.args) == 1 and type(exc.args[0]) is str else None
        reason = _MODEL_ERROR_REASONS.get(message, "unknown")
        diagnostic = "Model investigation failed category=%s reason=%s"
        values = [category, reason]
        provider_status = getattr(exc, "provider_status", None)
        if type(provider_status) is int and 400 <= provider_status <= 599:
            diagnostic += " provider_status=%d"
            values.append(provider_status)
        validation_reason = getattr(exc, "validation_reason", None)
        if (isinstance(exc, ModelResponseError) and type(validation_reason) is str
                and validation_reason in _MODEL_VALIDATION_REASONS):
            diagnostic += " validation_reason=%s"
            values.append(validation_reason)
        logger.warning(diagnostic, *values)
        return JSONResponse(status_code=502, content={"detail": "The model could not complete this investigation. "
            "Check provider settings and quota, then retry. Your previous memory is unchanged."})

    @app.get("/api/health")
    def health():
        ready()
        if not store.health():
            raise HTTPException(503, "FalkorDB is unavailable. Retry shortly.")
        return {"status": "ok", "graph": "connected", "mode": app.state.service.mode}

    app.include_router(create_auth_router(auth, secure_cookie=secure_cookie, public_origin=public_origin))
    app.include_router(build_source_router(sources, context, context))
    app.include_router(create_workflow_router(workflows, auth))

    @app.get("/api/bootstrap")
    def bootstrap(access=Depends(context)):
        graph = company.get_graph(access)
        graph["sources"] = [source_store.summary(row[0]).model_dump() for row in store.database.read(
            "MATCH (s:Source) RETURN properties(s) ORDER BY s.id") if access_service.can_read(access, row[0]["id"])]
        return {"workspace": {"name": "Meridian", "project": "Atlas launch", "is_demo": True},
            **graph, "stats": company.stats(access), "recent_memory": company.list_memories(access),
            "actions": company.list_actions(access), "capabilities": {
                "mode": app.state.service.mode, "provider": app.state.service.provider,
                "document_ingestion": True, "attachment_types": ["pdf", "txt", "md", "csv"],
                "workflow_templates": ["invoice_review"], "execution_enabled": app.state.execution_enabled,
                "storage_mode": os.getenv("RELAY_STORAGE_MODE", "persistent")}}

    @app.post("/api/investigate")
    async def investigate(body: InvestigationRequest, access=Depends(context)):
        return await app.state.service.investigate(body.question, body.session_id, access=access,
                                                   source_refs=body.source_refs, run_id=body.run_id)

    @app.post("/api/ripple")
    def ripple(body: RippleRequest, access=Depends(context)):
        origin = next((node for node in company.get_graph(access)["nodes"] if node["id"] == body.origin_id), None)
        if origin is None:
            raise HTTPException(404, "This graph node does not exist.")
        if origin["kind"] != "service":
            raise HTTPException(422, "Choose a service as the Ripple origin.")
        return company.simulate(access, body.origin_id, body.mitigation)

    @app.get("/api/memory")
    def memory(access=Depends(context)):
        return {"items": company.list_memories(access)}

    @app.get("/api/actions")
    def actions(access=Depends(context)):
        return {"items": company.list_actions(access)}

    def transition(access, action_id, status):
        try:
            return company.transition_action(access, action_id, status)
        except KeyError:
            raise HTTPException(404, "This action does not exist.") from None
        except ValueError:
            raise HTTPException(409, "Approve a proposed action before completing it. Completed actions cannot be reopened.") from None

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: str, access=Depends(context)):
        return transition(access, action_id, "approved")

    @app.post("/api/actions/{action_id}/complete")
    def complete(action_id: str, access=Depends(context)):
        return transition(access, action_id, "done")

    @app.post("/api/sources", status_code=201)
    def add_note(body: SourceRequest, request: Request, access=Depends(context)):
        try:
            key = str(UUID(request.headers.get("Idempotency-Key", "")))
        except ValueError:
            raise HTTPException(422, "An Idempotency-Key UUID is required.") from None
        blob = sources.blobs.put_stream(io.BytesIO(body.content.encode()), mime="text/plain")
        ref = source_store.create_upload(access, {"title": body.title, "filename": "note.txt",
            "classification": "general", "department_id": "general"}, blob, key)
        detail = sources.ingest(access, ref)
        return {**detail.model_dump(), "excerpt": body.content}

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str, access=Depends(context)):
        artifact = workflows.artifact_metadata(access, artifact_id)
        path = reports.path(artifact["blob_key"])
        if not path.is_file() or not reports.verify({"items": [artifact]}):
            raise HTTPException(503, "The stored report is unavailable. Restore its private files.")
        suffix = path.suffix
        return FileResponse(path, media_type="text/csv" if suffix == ".csv" else "text/html",
                            filename=f"relay-report{suffix}")

    @app.get("/api/cases")
    def cases(cursor: str | None = None, access=Depends(context)):
        return workflows.list_cases(access, cursor)

    @app.get("/api/cases/{case_id}")
    def case(case_id: str, access=Depends(context)):
        return workflows.get_case(access, case_id)

    return app


app = create_app()
