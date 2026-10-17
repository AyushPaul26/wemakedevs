from test_sources import setup_sources as setup_sources
from identity_helpers import identity_db as identity_db
import importlib
from io import BytesIO
import pytest
from test_sources import upload
from relay.access import AccessContext, AccessError


def evidence_service(setup_sources):
    assert importlib.util.find_spec("relay.evidence"), (
        "bounded selected-version evidence service missing"
    )
    from relay.evidence import EvidenceService

    return EvidenceService(setup_sources[1])


def test_selected_sources_each_represented_with_exact_citations_in_bounded_context(setup_sources):
    refs = [
        upload(setup_sources, text=(f"Document{i} " + ("x" * 50000)).encode()) for i in range(5)
    ]
    evidence = evidence_service(setup_sources)
    result = evidence.retrieve(AccessContext("operator", purpose="agent"), refs)
    assert sum(len(c["text"]) for c in result["chunks"]) <= 24000
    assert {c["source_id"] for c in result["chunks"]} == {r.source_id for r in refs}
    assert result["truncated"] and result["coverage"] == "partial"
    for ref in result["evidence_refs"]:
        assert evidence.validate_refs(AccessContext("operator", purpose="agent"), [ref]) == [ref]
    forged = dict(result["evidence_refs"][0], version_id=refs[1].version_id)
    with pytest.raises(ValueError):
        evidence.validate_refs(AccessContext("operator", purpose="agent"), [forged])


def test_human_finance_inspection_does_not_authorize_agent_retrieval(setup_sources):
    ref = upload(setup_sources, "finance")
    setup_sources[1].ingest(AccessContext("auditor"), ref)
    with pytest.raises(AccessError):
        evidence_service(setup_sources).retrieve(AccessContext("operator", purpose="agent"), [ref])


def test_selected_version_stays_exact_after_replacement(setup_sources):
    ref = upload(setup_sources, text=b"Historic evidence.")
    service = evidence_service(setup_sources)
    setup_sources[0].add_version(
        AccessContext("operator"),
        ref.source_id,
        0,
        setup_sources[2].put_stream(BytesIO(b"New evidence."), mime="text/plain"),
    )
    result = service.retrieve(AccessContext("operator", purpose="agent"), [ref])
    assert result["chunks"][0]["text"] == "Historic evidence."
    assert result["evidence_refs"][0]["version_id"] == ref.version_id
