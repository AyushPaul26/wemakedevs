"""Protected multipart and evidence HTTP boundary, wired by the application."""

import hashlib
import json
from pathlib import PurePath
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from .access import AccessError
from .parsers import ParseError
from .source_store import SourceError, canonical
from .storage import StorageError, MAX_FILES, MAX_REQUEST_BYTES
from .workflow_models import SourceRef


class BoundedBodyRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            limit = MAX_REQUEST_BYTES + 64 * 1024
            declared = request.headers.get("content-length")
            if declared and (not declared.isdigit() or int(declared) > limit):
                raise HTTPException(413, "Attachment request exceeds 50 MiB.")
            receive = request._receive
            consumed = 0

            async def bounded_receive():
                nonlocal consumed
                message = await receive()
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise HTTPException(413, "Attachment request exceeds 50 MiB.")
                return message

            request._receive = bounded_receive
            try:
                return await handler(request)
            except (AccessError, SourceError, StorageError) as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
            except ParseError as exc:
                raise HTTPException(422, str(exc)) from exc

        return bounded


def _key(request):
    try:
        return UUID(request.headers.get("Idempotency-Key", ""))
    except ValueError as exc:
        raise SourceError("An Idempotency-Key UUID is required.") from exc


async def _form(request):
    try:
        return await request.form(max_files=MAX_FILES, max_fields=10, max_part_size=4096)
    except StarletteHTTPException as exc:
        if exc.status_code == 400:
            raise SourceError("Select at most five files with valid bounded metadata.") from exc
        raise


class LinkProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_entity_id: str | None = Field(default=None, max_length=200)
    target_entity_id: str = Field(min_length=1, max_length=200)
    relation: Literal["DOCUMENTS", "RELATED_TO", "DEPENDS_ON"]
    evidence_chunk_ids: list[str] = Field(min_length=1, max_length=20)


class LinkDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=200)
    decision: Literal["accept", "reject"]


class LinkReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    decisions: list[LinkDecision] = Field(min_length=1, max_length=20)


def build_source_router(service, access_dependency, mutation_dependency):
    router = APIRouter(prefix="/api", route_class=BoundedBodyRoute)

    @router.get("/sources")
    def list_sources(query: str = "", cursor: str | None = None, access=Depends(access_dependency)):
        return service.store.list_sources(access, query, cursor)

    @router.post("/attachments", status_code=201)
    async def upload(request: Request, access=Depends(mutation_dependency)):
        key = _key(request)
        form = await _form(request)
        files = form.getlist("files")
        if not 1 <= len(files) <= MAX_FILES or any(not isinstance(f, UploadFile) for f in files):
            raise SourceError("Select one to five files.")
        allowed = {"files", "title", "department_id", "classification"}
        if set(form.keys()) - allowed:
            raise SourceError("Unknown attachment metadata.")
        staged = []
        total = 0
        try:
            for file in files:
                blob = await run_in_threadpool(
                    service.blobs.put_stream, file.file, mime=file.content_type
                )
                total += blob.byte_size
                if total > MAX_REQUEST_BYTES:
                    raise StorageError("Attachment request exceeds 50 MiB.", 413)
                filename = PurePath((file.filename or "attachment").replace("\\", "/")).name
                metadata = {
                    "filename": filename,
                    "title": form.get("title") or filename,
                    "classification": form.get("classification", "general"),
                    "department_id": form.get("department_id", "general"),
                }
                service.store.validate_metadata(metadata)
                staged.append((metadata, blob))
            identity = hashlib.sha256(f"{access.member_id}:attachments:{key}".encode()).hexdigest()
            digest = hashlib.sha256(
                canonical([{"metadata": m, "blob": b.model_dump()} for m, b in staged]).encode()
            ).hexdigest()
            rows = service.store.database.query(
                "MERGE (i:IdempotencyRecord {id:$id}) "
                'ON CREATE SET i.actor_id=$actor,i.operation="attachments",i.request_hash=$hash '
                "RETURN i.request_hash",
                {"id": identity, "actor": access.member_id, "hash": digest},
            )
            if rows[0][0] != digest:
                raise SourceError("Idempotency key was already used with different content.", 409)
            items = []
            for index, (metadata, blob) in enumerate(staged):
                ref = await run_in_threadpool(
                    service.store.create_upload,
                    access,
                    metadata,
                    blob,
                    idempotency_key=str(uuid5(key, str(index))),
                )
                error = None
                if (
                    metadata["classification"] == "finance"
                    or metadata["department_id"] == "finance"
                ):
                    detail = service.store.detail(access, ref)
                else:
                    try:
                        detail = await run_in_threadpool(service.ingest, access, ref)
                    except ParseError as exc:
                        detail = service.store.detail(access, ref)
                        error = str(exc)
                item = {
                    "ref": ref.model_dump(),
                    "processing_status": detail.processing_status,
                    "filename": metadata["filename"],
                }
                if error:
                    item["error"] = error
                items.append(item)
            return {
                "items": items,
                "status": "partial_failure" if any(i.get("error") for i in items) else "accepted",
            }
        finally:
            for file in files:
                await file.close()

    @router.post("/sources/{source_id}/versions")
    async def replace(source_id: str, request: Request, access=Depends(mutation_dependency)):
        key = _key(request)
        form = await _form(request)
        file = form.get("file")
        if not isinstance(file, UploadFile) or set(form.keys()) - {"file", "expected_revision"}:
            raise SourceError("A file and expected source revision are required.")
        try:
            revision = int(form.get("expected_revision", ""))
            if revision < 0:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise SourceError("Expected source revision must be nonnegative.") from exc
        # Authorize before reading the request's bytes into private storage.
        service.store.access.require(access, "source_replace", source_id)
        try:
            blob = await run_in_threadpool(
                service.blobs.put_stream, file.file, mime=file.content_type
            )
            result = await run_in_threadpool(
                service.store.add_version,
                access,
                source_id,
                revision,
                blob,
                idempotency_key=str(key),
                original_filename=PurePath((file.filename or "attachment").replace("\\", "/")).name,
            )
            return result
        finally:
            await file.close()

    @router.get("/sources/{source_id}")
    def detail(source_id: str, version_id: str | None = None, access=Depends(access_dependency)):
        return service.detail(access, source_id, version_id)

    @router.get("/sources/{source_id}/versions/{version_id}")
    def version(source_id: str, version_id: str, access=Depends(access_dependency)):
        return service.detail(access, source_id, version_id)

    @router.get("/sources/{source_id}/versions/{version_id}/download")
    def download(source_id: str, version_id: str, access=Depends(access_dependency)):
        path, version = service.download(
            access, SourceRef(source_id=source_id, version_id=version_id)
        )
        filename = PurePath(version.get("original_filename", "attachment").replace("\\", "/")).name
        return FileResponse(
            path,
            media_type=version["mime"],
            filename=filename,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/evidence/{chunk_id}")
    def evidence(chunk_id: str, access=Depends(access_dependency)):
        return service.evidence(access, chunk_id)

    @router.get("/sources/{source_id}/versions/{version_id}/links")
    def links(source_id: str, version_id: str, access=Depends(access_dependency)):
        ref = SourceRef(source_id=source_id, version_id=version_id)
        proposals = service.suggest_links(access, ref)
        entities = service.store.database.query(
            "MATCH (e:Entity) RETURN properties(e) ORDER BY e.id"
        )
        options = []
        for row in entities:
            record = row[0]
            if service.store.access.can_read(access, record["id"]):
                payload = json.loads(record.get("payload") or "{}")
                options.append(
                    {
                        "id": record["id"],
                        "name": record.get("name") or payload.get("label") or record["id"],
                    }
                )
        return {
            "proposals": proposals,
            "extraction_status": "unavailable",
            "manual_association": True,
            "entity_options": options,
        }

    @router.post("/sources/{source_id}/versions/{version_id}/links/proposals", status_code=201)
    def propose_link(
        source_id: str,
        version_id: str,
        body: LinkProposalRequest,
        request: Request,
        access=Depends(mutation_dependency),
    ):
        return service.propose_link(
            access,
            SourceRef(source_id=source_id, version_id=version_id),
            body.model_dump(exclude_none=True),
            str(_key(request)),
        )

    @router.post("/sources/{source_id}/versions/{version_id}/links/review")
    def review_links(
        source_id: str,
        version_id: str,
        body: LinkReviewRequest,
        request: Request,
        access=Depends(mutation_dependency),
    ):
        return service.review_links(
            access,
            SourceRef(source_id=source_id, version_id=version_id),
            [d.model_dump() for d in body.decisions],
            body.expected_revision,
            str(_key(request)),
        )

    return router
