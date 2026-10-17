"""Selected immutable evidence is represented before supplementary company text."""

import re

from .workflow_models import SourceRef, EvidenceRef
from .source_store import SourceError

MAX_CONTEXT_CHARACTERS = 24_000


class EvidenceService:
    def __init__(self, sources):
        self.sources = sources

    def retrieve(self, access, source_refs, question=""):
        refs = list(
            dict.fromkeys(
                (SourceRef.model_validate(r).source_id, SourceRef.model_validate(r).version_id)
                for r in source_refs
            )
        )
        if len(refs) > 5:
            raise SourceError("Select at most five source versions.")
        chunks, missing, truncated, summaries = [], [], [], []
        terms = set(re.findall(r"\w+", question.lower()))
        budget = MAX_CONTEXT_CHARACTERS // max(1, len(refs))
        for source_id, version_id in refs:
            ref = SourceRef(source_id=source_id, version_id=version_id)
            detail = self.sources.ingest(access, ref)
            summaries.append(detail.model_dump(exclude={"chunks", "provenance"}))
            if not detail.chunks:
                missing.append(ref.model_dump())
                continue
            ranked = sorted(
                detail.chunks,
                key=lambda c: (-sum(t in c["text"].lower() for t in terms), c["ordinal"]),
            )
            remaining = budget
            represented = 0
            for chunk in ranked:
                if not remaining:
                    break
                text = chunk["text"][:remaining]
                chunks.append({**chunk, "text": text, "partial": len(text) < len(chunk["text"])})
                remaining -= len(text)
                represented += len(text)
            if represented < sum(len(c["text"]) for c in detail.chunks):
                truncated.append(ref.model_dump())
        evidence_refs = [
            EvidenceRef(
                source_id=c["source_id"],
                version_id=c["version_id"],
                chunk_id=c["id"],
                locator=c["locator"],
                title=c["title"],
            ).model_dump(exclude_none=True)
            for c in chunks
        ]
        return {
            "chunks": chunks,
            "evidence_refs": evidence_refs,
            "sources": summaries,
            "missing": missing,
            "truncated": truncated,
            "coverage": "partial" if truncated or missing else "complete",
            "notice": "Selected passages only; larger documents were not read exhaustively."
            if truncated
            else "Some selected evidence is unavailable."
            if missing
            else "",
            "remaining_characters": MAX_CONTEXT_CHARACTERS - sum(len(c["text"]) for c in chunks),
        }

    def validate_refs(self, access, refs):
        validated = []
        for value in refs:
            ref = EvidenceRef.model_validate(value)
            chunk = self.sources.evidence(access, ref.chunk_id)
            expected = EvidenceRef(
                source_id=chunk["source_id"],
                version_id=chunk["version_id"],
                chunk_id=chunk["id"],
                locator=chunk["locator"],
                title=chunk["title"],
            )
            if ref != expected:
                raise ValueError("Citation does not match stored evidence.")
            validated.append(expected.model_dump(exclude_none=True))
        return validated
