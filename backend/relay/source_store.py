"""Authoritative graph metadata and version/chunk provenance."""

import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import time
from uuid import UUID, uuid4

from .access import AccessService, AccessError
from .workflow_models import SourceRef, SourceSummary, SourceDetail, SourcePage, VersionResult


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def now():
    return datetime.now(timezone.utc).isoformat()


class SourceError(ValueError):
    def __init__(self, message, status_code=422):
        super().__init__(message)
        self.status_code = status_code


class SourceStore:
    def __init__(self, database, access_service=None, invalidate=None):
        self.database = database
        self.access = access_service or AccessService(database)
        self.invalidate = invalidate

    @staticmethod
    def validate_metadata(metadata):
        if set(metadata) - {"title", "filename", "classification", "department_id"}:
            raise SourceError("Invalid attachment metadata.")
        title = metadata.get("title", "")
        filename = metadata.get("filename", "attachment")
        classification = metadata.get("classification", "general")
        department = metadata.get("department_id", "general")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 300
            or not isinstance(filename, str)
            or not filename
            or len(filename) > 255
            or classification not in {"general", "finance"}
            or department not in {"general", "finance"}
        ):
            raise SourceError("Invalid attachment metadata.")

    def create_upload(self, access, metadata, blob, idempotency_key=None):
        member = self.access.require_member(access)
        if access.purpose != "human":
            raise AccessError("Operation is not permitted", 403)
        self.validate_metadata(metadata)
        title = metadata.get("title", "").strip()
        classification = metadata.get("classification", "general")
        department = metadata.get("department_id", "general")
        filename = metadata.get("filename", "attachment")
        if (
            not title
            or len(title) > 300
            or classification not in {"general", "finance"}
            or department not in {"general", "finance"}
            or len(filename) > 255
        ):
            raise SourceError("Invalid attachment metadata.")
        # Finance department always receives Finance handling regardless of client label.
        if department == "finance" or classification == "finance":
            classification, department = "finance", "finance"
        key = str(UUID(idempotency_key)) if idempotency_key else str(uuid4())
        identifier = "source-" + uuid4().hex
        version = "version-" + uuid4().hex
        timestamp = now()
        payload = dict(
            id=identifier,
            title=title,
            type="attachment",
            author=member.get("display_name", access.member_id),
            updated_at=timestamp,
            current_version_id=version,
            classification=classification,
            department_id=department,
            processing_status="waiting_approval" if classification == "finance" else "pending",
        )
        digest = hashlib.sha256(
            canonical({"metadata": metadata, "blob": blob.model_dump()}).encode()
        ).hexdigest()
        identity = hashlib.sha256(f"{access.member_id}:source_upload:{key}".encode()).hexdigest()
        props = dict(
            payload,
            workspace_id=access.workspace_id,
            uploader_id=access.member_id,
            revision=0,
            payload=canonical(payload),
            search=f"{title} {filename}".lower(),
        )
        vprops = dict(
            id=version,
            workspace_id=access.workspace_id,
            source_id=identifier,
            number=1,
            content_hash=blob.sha256,
            mime=blob.mime,
            storage_kind="blob",
            blob_key=blob.key,
            byte_size=blob.byte_size,
            original_filename=filename,
            classification=classification,
            department_id=department,
            uploader_id=access.member_id,
            processing_status=payload["processing_status"],
            created_at=timestamp,
        )
        rows = self.database.query(
            "MERGE (i:IdempotencyRecord {id:$key}) ON CREATE SET i.request_hash=$hash, "
            'i.actor_id=$actor,i.operation="source_upload",i.source_id=$source,i.version_id=$version '
            "WITH i WHERE i.request_hash=$hash "
            "MERGE (s:Source {id:i.source_id}) ON CREATE SET s += $props "
            "MERGE (v:SourceVersion {id:i.version_id}) ON CREATE SET v += $version_props "
            "MERGE (s)-[:HAS_VERSION]->(v) RETURN s.id,v.id",
            {
                "key": identity,
                "hash": digest,
                "actor": access.member_id,
                "source": identifier,
                "version": version,
                "props": props,
                "version_props": vprops,
            },
        )
        if not rows:
            raise SourceError("Idempotency key was already used with different content.", 409)
        return SourceRef(source_id=rows[0][0], version_id=rows[0][1])

    def version(self, access, ref):
        self.access.require(access, "source_read", ref.version_id)
        rows = self.database.query(
            "MATCH (s:Source {id:$source})-[:HAS_VERSION]->(v:SourceVersion {id:$version}) RETURN properties(v)",
            {"source": ref.source_id, "version": ref.version_id},
        )
        if not rows:
            raise AccessError()
        return rows[0][0]

    def current_ref(self, access, source_id):
        self.access.require(access, "source_read", source_id)
        rows = self.database.query(
            "MATCH (s:Source {id:$id}) RETURN s.current_version_id", {"id": source_id}
        )
        if not rows or not rows[0][0]:
            raise AccessError()
        return SourceRef(source_id=source_id, version_id=rows[0][0])

    def summary(self, record):
        payload = json.loads(record.get("payload") or "{}")
        return SourceSummary(
            id=record["id"],
            title=record.get("title") or payload.get("title", "Attachment"),
            type=record.get("type") or payload.get("type", "attachment"),
            author=record.get("author") or payload.get("author", ""),
            updated_at=record.get("updated_at") or payload.get("updated_at", ""),
            current_version_id=record.get("current_version_id"),
            classification="finance" if record.get("classification") == "finance" else "general",
            department_id=record.get("department_id", "general"),
            processing_status=record.get("processing_status", "completed"),
        )

    def detail(self, access, ref):
        version = self.version(access, ref)
        source = self.database.query(
            "MATCH (s:Source {id:$id}) RETURN properties(s)", {"id": ref.source_id}
        )[0][0]
        chunks = self.database.query(
            "MATCH (v:SourceVersion {id:$id})-[:HAS_CHUNK]->(c:SourceChunk) RETURN properties(c) ORDER BY c.ordinal",
            {"id": ref.version_id},
        )
        values = []
        for row in chunks:
            chunk = row[0]
            values.append(
                {
                    "id": chunk["id"],
                    "chunk_id": chunk["id"],
                    "source_id": ref.source_id,
                    "version_id": ref.version_id,
                    "text": chunk["text"],
                    "ordinal": chunk["ordinal"],
                    "locator": json.loads(chunk["locator_json"]),
                    "title": self.summary(source).title,
                }
            )
        try:
            self.access.require(access, "source_replace", ref.source_id)
            can_replace = True
        except AccessError:
            can_replace = False
        versions = self.database.query(
            "MATCH (s:Source {id:$id})-[:HAS_VERSION]->(v:SourceVersion) RETURN v.id,v.number,v.created_at,v.processing_status ORDER BY v.number DESC",
            {"id": ref.source_id},
        )
        history = [
            {"version_id": v[0], "number": v[1], "created_at": v[2], "processing_status": v[3]}
            for v in versions
            if self.access.can_read(access, v[0])
        ]
        return SourceDetail(
            **self.summary(source).model_dump(exclude={"processing_status"}),
            processing_status=version.get("processing_status", "pending"),
            chunks=values,
            provenance={
                k: version[k]
                for k in (
                    "id",
                    "number",
                    "content_hash",
                    "mime",
                    "byte_size",
                    "original_filename",
                    "created_at",
                )
                if k in version
            }
            | {
                "source_revision": source.get("revision", 0),
                "can_replace": can_replace,
                "can_download": version.get("storage_kind") == "blob",
                "storage_kind": version.get("storage_kind"),
                "citation_provenance": version.get("provenance", "original_upload"),
                "can_review_links": can_replace,
                "versions": history,
            },
        )

    def list_sources(self, access, query="", cursor=None):
        self.access.require_member(access)
        if len(query) > 300:
            raise SourceError("Search is too long.")
        try:
            after = base64.urlsafe_b64decode(cursor.encode()).decode() if cursor else ""
        except (ValueError, UnicodeError):
            raise SourceError("Invalid source cursor.")
        rows = self.database.query(
            "MATCH (s:Source) WHERE s.id>$after AND "
            '($query="" OR toLower(coalesce(s.title,s.search,"")) CONTAINS $query) '
            "RETURN properties(s) ORDER BY s.id",
            {"after": after, "query": query.lower()},
        )
        visible = [r[0] for r in rows if self.access.can_read(access, r[0]["id"])]
        page = visible[:20]
        return SourcePage(
            items=[self.summary(s) for s in page],
            next_cursor=base64.urlsafe_b64encode(page[-1]["id"].encode()).decode()
            if len(visible) > 20
            else None,
        )

    def add_version(
        self,
        access,
        source_id,
        expected_revision,
        blob,
        idempotency_key=None,
        original_filename=None,
    ):
        self.access.require(access, "source_replace", source_id)
        filename = original_filename or "attachment"
        if not isinstance(filename, str) or len(filename) > 255:
            raise SourceError("Invalid original filename.")
        source = self.database.query(
            "MATCH (s:Source {id:$id}) RETURN properties(s)", {"id": source_id}
        )[0][0]
        key = str(UUID(idempotency_key)) if idempotency_key else str(uuid4())
        request_hash = hashlib.sha256(
            canonical(
                {
                    "source": source_id,
                    "revision": expected_revision,
                    "blob": blob.model_dump(),
                    "original_filename": filename,
                }
            ).encode()
        ).hexdigest()
        identity = hashlib.sha256(f"{access.member_id}:source_replace:{key}".encode()).hexdigest()
        replay = self.database.query(
            "MATCH (i:IdempotencyRecord {id:$id}) RETURN properties(i)", {"id": identity}
        )
        if replay:
            if replay[0][0]["request_hash"] != request_hash:
                raise SourceError("Idempotency key was already used with different content.", 409)
            record = replay[0][0]
            if "invalidated_run_ids" not in record:
                invalidated = self._invalidate_version(source_id, record["version_id"])
                self.database.query(
                    "MATCH (i:IdempotencyRecord {id:$id}) SET i.invalidated_run_ids=$runs",
                    {"id": identity, "runs": canonical(invalidated)},
                )
                record["invalidated_run_ids"] = canonical(invalidated)
            return VersionResult(
                ref=SourceRef(source_id=source_id, version_id=record["version_id"]),
                source_revision=record["source_revision"],
                invalidated_run_ids=json.loads(record.get("invalidated_run_ids", "[]")),
            )
        version = "version-" + uuid4().hex
        prior = self.database.query(
            "MATCH (s:Source {id:$id})-[:HAS_VERSION]->(v:SourceVersion) RETURN max(v.number)",
            {"id": source_id},
        )[0][0]
        props = dict(
            id=version,
            source_id=source_id,
            workspace_id=access.workspace_id,
            number=(prior or 0) + 1,
            content_hash=blob.sha256,
            mime=blob.mime,
            storage_kind="blob",
            original_filename=filename,
            blob_key=blob.key,
            byte_size=blob.byte_size,
            classification=source.get("classification", "general"),
            department_id=source.get("department_id", "general"),
            uploader_id=access.member_id,
            processing_status="waiting_approval"
            if source.get("classification") == "finance"
            else "pending",
            created_at=now(),
        )
        payload = self.summary(source).model_dump()
        payload.update(
            current_version_id=version,
            updated_at=now(),
            processing_status=props["processing_status"],
        )
        rows = self.database.query(
            "MATCH (s:Source {id:$id}) WHERE s.revision=$revision "
            "SET s.revision=s.revision+1,s.current_version_id=$version,s.updated_at=$now,s.processing_status=$status,s.payload=$payload "
            "CREATE (v:SourceVersion) SET v += $props CREATE (s)-[:HAS_VERSION]->(v) "
            'CREATE (i:IdempotencyRecord {id:$key,request_hash:$hash,actor_id:$actor,operation:"source_replace",version_id:$version,source_revision:$next}) '
            "RETURN s.revision",
            {
                "id": source_id,
                "revision": expected_revision,
                "version": version,
                "props": props,
                "now": now(),
                "status": props["processing_status"],
                "payload": canonical(payload),
                "key": identity,
                "hash": request_hash,
                "actor": access.member_id,
                "next": expected_revision + 1,
            },
        )
        if not rows:
            replay = self.database.query(
                "MATCH (i:IdempotencyRecord {id:$id}) RETURN i.id", {"id": identity}
            )
            if replay:
                return self.add_version(
                    access,
                    source_id,
                    expected_revision,
                    blob,
                    idempotency_key=key,
                    original_filename=filename,
                )
            raise SourceError("Source revision changed. Reload and retry.", 409)
        invalidated = self._invalidate_version(source_id, version)
        self.database.query(
            "MATCH (i:IdempotencyRecord {id:$id}) SET i.invalidated_run_ids=$runs",
            {"id": identity, "runs": canonical(invalidated)},
        )
        return VersionResult(
            ref=SourceRef(source_id=source_id, version_id=version),
            source_revision=rows[0][0],
            invalidated_run_ids=invalidated,
        )

    def _invalidate_version(self, source_id, version_id):
        if self.invalidate:
            return self.invalidate(source_id, version_id)
        from .workflow_store import WorkflowStore

        return WorkflowStore(self.database).invalidate_source(source_id, version_id)

    def claim_processing(self, access, ref):
        self.version(access, ref)
        token = uuid4().hex
        rows = self.database.query(
            'MATCH (v:SourceVersion {id:$id}) WHERE v.processing_status<>"completed" '
            "AND (v.processing_until IS NULL OR v.processing_until<$now) "
            'SET v.processing_status="processing",v.processing_token=$token,v.processing_until=$until RETURN v.id',
            {"id": ref.version_id, "now": time.time(), "until": time.time() + 35, "token": token},
        )
        if not rows:
            raise SourceError("Attachment is already being processed.", 409)
        return token

    def save_parsed(self, access, ref, parsed, token):
        self.version(access, ref)  # Revalidate gate before publishing any extracted text.
        chunks = []
        for chunk in parsed.chunks:
            chunks.append(
                dict(
                    id=f"{ref.version_id}-chunk-{chunk.ordinal}",
                    version_id=ref.version_id,
                    workspace_id=access.workspace_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    locator_json=canonical(chunk.locator),
                    content_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                )
            )
        table = canonical(asdict(parsed.table)) if parsed.table else ""
        rows = self.database.query(
            "MATCH (v:SourceVersion {id:$id}) WHERE v.processing_token=$token "
            "AND v.processing_until>$now WITH v UNWIND $chunks AS chunk "
            "CREATE (c:SourceChunk) SET c += chunk CREATE (v)-[:HAS_CHUNK]->(c) "
            'WITH DISTINCT v SET v.processing_status="completed",v.table_json=$table,v.processing_until=0 '
            "WITH v MATCH (s:Source {id:v.source_id}) "
            'FOREACH (_ IN CASE WHEN s.current_version_id=v.id THEN [1] ELSE [] END | SET s.processing_status="completed") RETURN v.id',
            {
                "id": ref.version_id,
                "token": token,
                "now": time.time(),
                "chunks": chunks,
                "table": table,
            },
        )
        if not rows:
            raise SourceError("Attachment processing lease expired.", 409)

    def fail_processing(self, ref, token, message):
        self.database.query(
            'MATCH (v:SourceVersion {id:$id}) WHERE v.processing_token=$token AND v.processing_status="processing" '
            'SET v.processing_status="failed",v.processing_error=$message,v.processing_until=0 '
            "WITH v MATCH (s:Source {id:v.source_id}) "
            'FOREACH (_ IN CASE WHEN s.current_version_id=v.id THEN [1] ELSE [] END | SET s.processing_status="failed")',
            {"id": ref.version_id, "token": token, "message": message},
        )
