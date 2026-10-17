"""Authorized source processing; protected bytes are never opened before a gate."""

from dataclasses import asdict
from decimal import Decimal
import fcntl
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile

from .access import AccessError
from .parsers import ParsedDocument, ParsedChunk, ParsedTable, ParsedRow, ParseError
from .source_store import SourceError, canonical, now
from .workflow_models import SourceRef, EvidenceRef, SourceDetail
from uuid import uuid4


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _deserialize(document):
    chunks = [ParsedChunk(c["ordinal"], c["text"], c["locator"]) for c in document["chunks"]]
    value = document.get("table")
    table = (
        ParsedTable(
            value["currency"],
            [
                ParsedRow(r["item_id"], r["quantity"], Decimal(r["unit_price"]), r["row_number"])
                for r in value["rows"]
            ],
        )
        if value
        else None
    )
    return ParsedDocument(chunks, table)


class SourceService:
    def __init__(self, store, blobs, parser=None):
        self.store, self.blobs, self.parser = store, blobs, parser

    def _parse_isolated(self, path, mime):
        # The caller holds the shared parser slot and has just rechecked access.
        with tempfile.TemporaryFile(dir=self.blobs.root) as output:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "relay.sources", "--parse", str(path), mime],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    preexec_fn=_limits,
                    check=False,
                    env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "LANG": "C.UTF-8"},
                )
            except subprocess.TimeoutExpired as exc:
                raise ParseError("Attachment processing timed out.") from exc
            output.seek(0)
            data = output.read(8 * 1024 * 1024 + 1)
            if result.returncode or len(data) > 8 * 1024 * 1024:
                raise ParseError("Attachment could not be processed within resource limits.")
            payload = json.loads(data)
            if "error" in payload:
                raise ParseError(payload["error"])
            return _deserialize(payload)

    def _cached_document(self, access, ref, version):
        detail = self.store.detail(access, ref)
        parsed = _deserialize(
            {
                "chunks": [
                    {"ordinal": c["ordinal"], "text": c["text"], "locator": c["locator"]}
                    for c in detail.chunks
                ],
                "table": json.loads(version["table_json"]) if version.get("table_json") else None,
            }
        )
        self.store.version(access, ref)
        return parsed

    def parse(self, access, ref):
        version = self.store.version(access, ref)
        if version.get("processing_status") in {"completed", "ready"}:
            return self._cached_document(access, ref, version)
        # Acquire the slot before a lease or content read. Waiting never extends
        # permission and never consumes the bounded parser processing lease.
        with (self.blobs.root / ".parser.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            version = self.store.version(access, ref)
            if version.get("processing_status") in {"completed", "ready"}:
                return self._cached_document(access, ref, version)
            token = self.store.claim_processing(access, ref)
            try:
                path = self.blobs.path(version["blob_key"])
                if not path.is_file() or path.stat().st_size != version["byte_size"]:
                    raise ParseError("Original attachment is unavailable.")
                self.store.version(access, ref)
                if hashlib.sha256(path.read_bytes()).hexdigest() != version["content_hash"]:
                    raise ParseError("Original attachment integrity check failed.")
                self.store.version(access, ref)
                parsed = (self.parser or self._parse_isolated)(path, version["mime"])
                self.store.save_parsed(access, ref, parsed, token)
                self.store.version(access, ref)
                return parsed
            except (AccessError, SourceError):
                self.store.fail_processing(ref, token, "Processing permission or state changed.")
                raise
            except (ParseError, OSError, ValueError) as exc:
                message = (
                    str(exc) if isinstance(exc, ParseError) else "Attachment processing failed."
                )
                self.store.fail_processing(ref, token, message)
                if isinstance(exc, ParseError):
                    raise
                raise ParseError(message) from exc

    parsed_document = parse

    def ingest(self, access, ref):
        self.parse(access, ref)
        return self.store.detail(access, ref)

    def detail(self, access, source_id, version_id=None):
        ref = (
            source_id
            if isinstance(source_id, SourceRef)
            else SourceRef(source_id=source_id, version_id=version_id)
            if version_id
            else self.store.current_ref(access, source_id)
        )
        return self.store.detail(access, ref)

    def evidence(self, access, chunk_id):
        self.store.access.require(access, "evidence_read", chunk_id)
        rows = self.store.database.query(
            "MATCH (v:SourceVersion)-[:HAS_CHUNK]->(c:SourceChunk {id:$id}) RETURN v.source_id,v.id",
            {"id": chunk_id},
        )
        if not rows:
            raise AccessError()
        detail = self.store.detail(access, SourceRef(source_id=rows[0][0], version_id=rows[0][1]))
        return next(c for c in detail.chunks if c["id"] == chunk_id)

    def download(self, access, ref):
        self.store.access.require(access, "source_download", ref.version_id)
        version = self.store.version(access, ref)
        if version.get("storage_kind") != "blob" or not version.get("blob_key"):
            raise AccessError("Original attachment is unavailable", 404)
        path = self.blobs.path(version["blob_key"])
        if not path.is_file():
            raise AccessError()
        return path, version

    def suggest_links(self, access, ref):
        # No semantic extraction is claimed when no live extractor is configured.
        self.store.version(access, ref)
        rows = self.store.database.query(
            "MATCH (p:LinkProposal {version_id:$version}) RETURN properties(p) ORDER BY p.id",
            {"version": ref.version_id},
        )
        return [
            dict(row[0], evidence_chunk_ids=json.loads(row[0]["evidence_chunk_ids_json"]))
            for row in rows
        ]

    def _mutation(self, access, key, operation, payload):
        identity = hashlib.sha256(
            f"{access.member_id}:{operation}:{key or uuid4().hex}".encode()
        ).hexdigest()
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        rows = self.store.database.query(
            "MATCH (i:IdempotencyRecord {id:$id}) RETURN i.request_hash,i.response_json",
            {"id": identity},
        )
        if rows and rows[0][0] != digest:
            raise SourceError("Idempotency key was already used with different content.", 409)
        return identity, digest, json.loads(rows[0][1]) if rows else None

    def propose_link(self, access, ref, proposal, idempotency_key=None):
        self.store.access.require(access, "links_review", ref.source_id)
        self.store.version(access, ref)
        mutation, digest, replay = self._mutation(
            access, idempotency_key, "link_propose", {"ref": ref.model_dump(), "proposal": proposal}
        )
        if replay is not None:
            return replay
        if set(proposal) - {
            "source_entity_id",
            "target_entity_id",
            "relation",
            "evidence_chunk_ids",
        }:
            raise SourceError("Unknown link proposal fields.")
        relation = proposal.get("relation")
        origin = proposal.get("source_entity_id")
        target = proposal.get("target_entity_id")
        if (
            relation not in {"DOCUMENTS", "RELATED_TO", "DEPENDS_ON"}
            or not target
            or origin == target
        ):
            raise SourceError("Unsupported company relationship.")
        if not origin and relation != "DOCUMENTS":
            raise SourceError("Company relationship requires two existing entities.")
        for identifier in [value for value in (origin, target) if value]:
            self.store.access.require(access, "read", identifier)
            rows = self.store.database.query(
                "MATCH (e:Entity {id:$id}) RETURN e.id", {"id": identifier}
            )
            if not rows:
                raise SourceError("Company links require existing entities.")
        chunk_ids = proposal.get("evidence_chunk_ids", [])
        if (
            not isinstance(chunk_ids, list)
            or not 1 <= len(chunk_ids) <= 20
            or len(set(chunk_ids)) != len(chunk_ids)
        ):
            raise SourceError("Select one to twenty exact evidence passages.")
        for chunk_id in chunk_ids:
            chunk = self.evidence(access, chunk_id)
            if chunk["source_id"] != ref.source_id or chunk["version_id"] != ref.version_id:
                raise SourceError("Link evidence must belong to the selected source version.")
        record = dict(
            id="link-" + uuid4().hex,
            workspace_id=access.workspace_id,
            source_id=ref.source_id,
            version_id=ref.version_id,
            source_entity_id=origin or "",
            target_entity_id=target,
            relation=relation,
            evidence_chunk_ids_json=canonical(chunk_ids),
            status="pending",
            revision=0,
            created_at=now(),
        )
        response = dict(record, evidence_chunk_ids=chunk_ids)
        rows = self.store.database.query(
            "MATCH (v:SourceVersion {id:$version}) OPTIONAL MATCH (op:IdempotencyRecord {id:$mutation}) WITH v,op WHERE op IS NULL "
            'CREATE (i:IdempotencyRecord {id:$mutation,actor_id:$actor,operation:"link_propose",request_hash:$hash,response_json:$response}) '
            "CREATE (p:LinkProposal) SET p += $record "
            "CREATE (p)-[:USES_SOURCE]->(v) WITH p UNWIND $chunks AS chunk "
            "MATCH (c:SourceChunk {id:chunk}) CREATE (p)-[:SUPPORTED_BY]->(c) RETURN p.id",
            {
                "version": ref.version_id,
                "record": record,
                "chunks": chunk_ids,
                "mutation": mutation,
                "actor": access.member_id,
                "hash": digest,
                "response": canonical(response),
            },
        )
        if not rows:
            _, _, replay = self._mutation(
                access,
                idempotency_key,
                "link_propose",
                {"ref": ref.model_dump(), "proposal": proposal},
            )
            if replay is None:
                raise SourceError("Proposal changed. Retry.", 409)
            return replay
        return response

    def review_links(self, access, ref, decisions, expected_revision, idempotency_key=None):
        self.store.access.require(access, "links_review", ref.source_id)
        self.store.version(access, ref)
        payload = {
            "ref": ref.model_dump(),
            "decisions": decisions,
            "expected_revision": expected_revision,
        }
        mutation, digest, replay = self._mutation(access, idempotency_key, "link_review", payload)
        if replay is not None:
            return SourceDetail.model_validate(replay)
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 20:
            raise SourceError("Select one to twenty exact proposals.")
        if len({d.get("proposal_id") for d in decisions}) != len(decisions):
            raise SourceError("Duplicate link decisions.")
        proposals = {p["id"]: p for p in self.suggest_links(access, ref)}
        statements = []
        params = {
            "source": ref.source_id,
            "version": ref.version_id,
            "revision": expected_revision,
            "reviewer": access.member_id,
            "now": now(),
        }
        for index, decision in enumerate(decisions):
            if set(decision) - {"proposal_id", "decision"} or decision.get("decision") not in {
                "accept",
                "reject",
            }:
                raise SourceError("Invalid link decision.")
            proposal = proposals.get(decision.get("proposal_id"))
            if not proposal or proposal["status"] != "pending":
                _, _, replay = self._mutation(access, idempotency_key, "link_review", payload)
                if replay is not None:
                    return SourceDetail.model_validate(replay)
                raise SourceError("Proposal is missing or already reviewed.", 409)
            evidence = []
            for chunk_id in proposal["evidence_chunk_ids"]:
                chunk = self.evidence(access, chunk_id)
                evidence.append(
                    EvidenceRef(
                        source_id=ref.source_id,
                        version_id=ref.version_id,
                        chunk_id=chunk_id,
                        locator=chunk["locator"],
                        title=chunk["title"],
                    ).model_dump(exclude_none=True)
                )
            params[f"proposal{index}"] = proposal["id"]
            params[f"decision{index}"] = decision["decision"]
            statements.append(
                f'MATCH (p{index}:LinkProposal {{id:$proposal{index},version_id:$version,status:"pending"}})'
            )
            if decision["decision"] == "accept":
                origin = proposal["source_entity_id"]
                target = proposal["target_entity_id"]
                for identifier in [v for v in (origin, target) if v]:
                    self.store.access.require(access, "read", identifier)
                params[f"origin{index}"] = origin or ref.source_id
                params[f"target{index}"] = target
                params[f"evidence{index}"] = canonical(evidence)
                params[f"edge{index}"] = canonical(
                    {
                        "id": proposal["id"],
                        "source": origin or ref.source_id,
                        "target": target,
                        "relation": proposal["relation"],
                        "label": proposal["relation"].lower().replace("_", " "),
                        "source_ids": [ref.source_id],
                        "evidence_refs": evidence,
                    }
                )
                relation = proposal["relation"]
                if relation not in {"DOCUMENTS", "RELATED_TO", "DEPENDS_ON"}:
                    raise SourceError("Unsupported company relationship.")
                label = "Entity" if origin else "Source"
                statements.append(
                    f"MATCH (from{index}:{label} {{id:$origin{index}}}),(to{index}:Entity {{id:$target{index}}})"
                )
        for index, decision in enumerate(decisions):
            statements.append(
                f"SET p{index}.status=$decision{index},p{index}.reviewer_id=$reviewer,p{index}.reviewed_at=$now,p{index}.revision=p{index}.revision+1"
            )
            if decision["decision"] == "accept":
                proposal = proposals[decision["proposal_id"]]
                relation = proposal["relation"]
                statements.append(
                    f"MERGE (from{index})-[e{index}:{relation} {{id:$proposal{index}}}]->(to{index}) "
                    f"SET e{index}.source_ids=[$source],e{index}.evidence_refs_json=$evidence{index},e{index}.payload=$edge{index},e{index}.confirmed_by=$reviewer,e{index}.version_id=$version"
                )
        response = self.store.detail(access, ref)
        response.provenance["source_revision"] = expected_revision + 1
        params.update(
            {"mutation": mutation, "hash": digest, "response": canonical(response.model_dump())}
        )
        query = "MATCH (s:Source {id:$source}) WHERE s.revision=$revision AND s.current_version_id=$version "
        query += " ".join(statements) + " SET s.revision=s.revision+1 "
        query += 'CREATE (i:IdempotencyRecord {id:$mutation,actor_id:$reviewer,operation:"link_review",request_hash:$hash,response_json:$response}) RETURN s.id'
        if not self.store.database.query(query, params):
            _, _, replay = self._mutation(access, idempotency_key, "link_review", payload)
            if replay is not None:
                return SourceDetail.model_validate(replay)
            raise SourceError("Source or proposal revision changed. Reload and retry.", 409)
        return response


if __name__ == "__main__":
    from .parsers import parse_file

    try:
        result = parse_file(Path(sys.argv[2]), sys.argv[3])
        print(json.dumps(asdict(result), default=str))
    except ParseError as exc:
        print(json.dumps({"error": str(exc)}))
