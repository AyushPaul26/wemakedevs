"""Exact evidence and session ownership at the investigation boundary."""

from copy import deepcopy

import pytest

from relay.access import AccessContext
from relay.agents import InvestigationService
from relay.llm import ModelResponseError, validate_plan
from relay.models import InvestigationRequest
from test_agents import EvidenceStore


REF = {"source_id": "selected", "version_id": "version-2", "chunk_id": "chunk-2",
       "locator": {"paragraph": 1}, "title": "Selected attachment"}


def evidence_context():
    return {"nodes": [], "edges": [], "sources": [{"id": "selected", "title": REF["title"],
            "excerpt": "A quoted fact."}], "evidence_refs": [REF], "prior_memories": []}


def test_exact_attachment_reference_is_accepted_but_forged_version_is_rejected():
    payload = {"answer": "A quoted fact [selected].", "source_ids": ["selected"],
               "node_ids": [], "actions": [], "evidence_refs": [REF]}
    result = validate_plan(payload, evidence_context())
    assert result["evidence_refs"][0]["chunk_id"] == "chunk-2"
    for field in ("version_id", "chunk_id", "source_id", "title"):
        forged = deepcopy(payload)
        forged["evidence_refs"][0][field] = "invented"
        with pytest.raises(ModelResponseError):
            validate_plan(forged, evidence_context())
    forged = deepcopy(payload)
    forged["evidence_refs"][0]["locator"] = {"page": 100}
    with pytest.raises(ModelResponseError):
        validate_plan(forged, evidence_context())


def test_request_has_bounded_exact_source_versions():
    request = InvestigationRequest(question="Read this", source_refs=[
        {"source_id": "selected", "version_id": "version-2"}])
    assert request.source_refs[0].version_id == "version-2"
    with pytest.raises(ValueError):
        InvestigationRequest(question="Read this", source_refs=[
            {"source_id": str(i), "version_id": str(i)} for i in range(6)])


class SelectedStore(EvidenceStore):
    def __init__(self):
        super().__init__()
        self.calls = []

    def retrieve(self, question, *, access=None, source_refs=(), run_id=None):
        self.calls.append((access, source_refs, run_id))
        return {**evidence_context(), "chunks": [{"id": "chunk-2", "text": "A quoted fact.",
                 "evidence_ref": REF}], "selected_sources": [REF["source_id"]],
                 "truncated": True}

    def save_actions(self, actions, *, access=None):
        return super().save_actions(actions)

    def save_investigation(self, result, *, access=None):
        return super().save_investigation(result)


@pytest.mark.asyncio
async def test_selected_evidence_and_two_members_never_share_checkpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    store = SelectedStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    ref = {"source_id": "selected", "version_id": "version-2"}
    results = []
    for member in ("alice", "bob", "alice"):
        results.append(await service.investigate("Read my attached note", "same-browser-thread",
            access=AccessContext(member), source_refs=[ref]))
    assert ["Session turn 2" in r["steps"][0]["detail"] for r in results] == [False, False, True]
    assert results[0]["evidence_refs"][0]["chunk_id"] == "chunk-2"
    assert "A quoted fact" in results[0]["answer"]
    assert "truncated" in results[0]["answer"].lower()
    assert results[0]["actions"] == []
    assert store.calls[0][0].member_id == "alice"
    assert store.calls[0][1] == [ref]


def test_output_citations_must_refer_to_permitted_actual_artifacts():
    context = evidence_context()
    context["permitted_run_outputs"] = {"outputs": [{"id": "report-real"}]}
    payload = {"answer": "The completed report records a difference.", "source_ids": [],
               "node_ids": [], "actions": [], "output_ids": ["report-real"]}
    assert validate_plan(payload, context)["output_ids"] == ["report-real"]
    payload["output_ids"] = ["report-invented"]
    with pytest.raises(ModelResponseError):
        validate_plan(payload, context)


@pytest.mark.asyncio
async def test_run_followup_remembers_outcome_without_reopening_finance_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    store = SelectedStore()
    store.retrieve = lambda *args, **kwargs: {"nodes": [], "edges": [], "sources": [],
        "prior_memories": [], "permitted_run_outputs": {"run_id": "run-real", "status": "completed",
        "outputs": [{"id": "report-real", "kind": "html_report"}], "decisions": [
            {"gate_kind": "finance_access", "status": "approved"}], "results": [
            {"tool": "publish_report", "status": "completed", "result": {
                "comparison": {"currency": "USD", "difference": "20.00"}}}]}}
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What happened in that review?", access=AccessContext("alice"),
                                       run_id="run-real")
    assert result["run_id"] == "run-real"
    assert "20.00" in result["answer"]
    assert result["output_ids"] == ["report-real"]
    assert result["source_ids"] == [] and result["actions"] == []
