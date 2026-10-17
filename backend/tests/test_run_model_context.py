"""Live run questions send bounded derived facts without broadening evidence access."""

from copy import deepcopy
import json

import httpx
import pytest

from relay.agents import InvestigationService, _demo_plan
from relay.llm import ModelConfig, ModelError, ModelResponseError, OpenAICompatibleClient
from test_agents import EvidenceStore


RAW_REF = {"source_id": "private-finance-source", "version_id": "private-version",
           "chunk_id": "private-chunk", "locator": {"row_start": 2, "row_end": 2},
           "title": "Private original"}
FINDING = {"item_id": "gateway-seat", "kind": "unit_price_mismatch",
           "invoice_row": 2, "order_row": 2, "expected": "100.00", "actual": "110.00"}
TOTALS = {"currency": "USD", "invoice_total": "220.00", "order_total": "200.00",
          "difference": "20.00"}


def run_context():
    company = {"project_id": "atlas", "project_label": "Atlas launch",
               "owner_entity_id": "mara", "owner_status": "assigned",
               "launch_blocker": False, "impact": "Connections do not establish a launch blocker.",
               "nodes": [{"id": "nested-graph-only", "description": "duplicate graph " * 100}],
               "edges": [], "evidence_refs": []}
    report = {"comparison": {**TOTALS, "findings": [deepcopy(FINDING)]},
              "company": company, "evidence_refs": [deepcopy(RAW_REF)],
              "artifact_ids": ["report-html", "report-csv"], "narrative_mode": "live",
              "narrative": "DUPLICATE_NARRATIVE " * 100}
    return {"nodes": [], "edges": [], "sources": [], "prior_memories": [],
            "chunks": [], "evidence_refs": [], "truncated": False, "missing": [],
            "permitted_run_outputs": {"run_id": "run-real", "status": "completed",
                "generation": 2, "outputs": [
                    {"id": "report-html", "kind": "report_html", "stale": False,
                     "content_hash": "HASH_METADATA", "output_audience": ["PRIVATE_AUDIENCE"]},
                    {"id": "report-csv", "kind": "report_csv", "stale": True}],
                "decisions": [{"gate_kind": "finance_access", "status": "approved",
                               "reviewer_id": "PRIVATE_REVIEWER"}],
                "results": [
                    {"tool": "company_context", "status": "completed", "result": company},
                    {"tool": "publish_report", "status": "completed", "result": report},
                    {"tool": "upsert_case", "status": "completed",
                     "result": {"outcome": "open", "case_id": "case-real"}},
                    {"tool": "archive_run", "status": "completed",
                     "result": {"outcome": "archived", "outcomes": [
                         {"result": deepcopy(report)}]}}]}}


def answer(**overrides):
    return {"answer": "The recorded report has a 20.00 USD difference.", "source_ids": [],
            "node_ids": [], "actions": [], "evidence_refs": [],
            "output_ids": ["report-html"], **overrides}


async def capture(context, response=None):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps(response or answer())}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http:
        client = OpenAICompatibleClient(ModelConfig(api_key="unit-test-only"), http_client=http)
        result = await client.generate("What did this review find?", context)
    return json.loads(requests[0]["messages"][1]["content"])["evidence"], result


@pytest.mark.asyncio
async def test_live_followup_projects_derived_facts_without_mutating_run_or_demo():
    context = run_context()
    original = deepcopy(context)
    demo_before = _demo_plan("What did this review find?", context)
    sent, result = await capture(context)
    projected = sent["permitted_run_outputs"]
    serialized = json.dumps(projected)
    for forbidden in ("private-finance-source", "private-version", "private-chunk",
                      "nested-graph-only", "DUPLICATE_NARRATIVE", "HASH_METADATA",
                      "PRIVATE_AUDIENCE", "PRIVATE_REVIEWER", '"outcomes"'):
        assert forbidden not in serialized
    assert projected["run_id"] == "run-real"
    assert projected["status"] == "completed" and projected["generation"] == 2
    assert projected["outputs"] == [
        {"id": "report-html", "kind": "report_html", "stale": False},
        {"id": "report-csv", "kind": "report_csv", "stale": True}]
    assert projected["decisions"] == [{"gate_kind": "finance_access", "status": "approved"}]
    results = {step["tool"]: step["result"] for step in projected["results"]}
    comparison = results["publish_report"]["comparison"]
    assert {key: comparison[key] for key in TOTALS} == TOTALS
    assert comparison["findings"] == [FINDING]
    assert comparison["findings_total"] == 1 and comparison["findings_truncated"] is False
    assert results["company_context"]["launch_blocker"] is False
    assert results["company_context"]["owner_entity_id"] == "mara"
    assert results["upsert_case"] == {"outcome": "open", "case_id": "case-real"}
    assert results["archive_run"] == {"outcome": "archived"}
    assert result["output_ids"] == ["report-html"]
    assert context == original
    assert _demo_plan("What did this review find?", context) == demo_before


@pytest.mark.asyncio
async def test_large_run_projection_has_hard_bound_and_explicit_omissions():
    context = run_context()
    run = context["permitted_run_outputs"]
    findings = [{**FINDING, "item_id": str(index).zfill(80)} for index in range(2000)]
    run["results"][1]["result"]["comparison"]["findings"] = findings
    run["outputs"].extend({"id": f"old-report-{i:064d}", "kind": "report_html", "stale": True}
                          for i in range(100))
    sent, _ = await capture(context)
    projected = sent["permitted_run_outputs"]
    assert len(json.dumps(projected)) <= 8000
    assert projected["truncated"] is True
    assert projected["outputs_total"] == 102
    assert 1 <= len(projected["outputs"]) <= 20
    assert projected["outputs"][0]["id"] == "report-html"
    report = next(s["result"] for s in projected["results"] if s["tool"] == "publish_report")
    comparison = report["comparison"]
    assert {key: comparison[key] for key in TOTALS} == TOTALS
    assert comparison["findings_total"] == 2000 and comparison["findings_truncated"] is True
    assert 0 < len(comparison["findings"]) <= 20
    assert comparison["findings"] == findings[:len(comparison["findings"])]


@pytest.mark.asyncio
async def test_projection_does_not_restore_outputs_or_results_removed_by_access_filter():
    context = run_context()
    run = context["permitted_run_outputs"]
    run["outputs"] = []
    run["results"] = run["results"][:1]
    sent, _ = await capture(context, answer(output_ids=[]))
    projected = sent["permitted_run_outputs"]
    assert projected["outputs"] == []
    assert [s["tool"] for s in projected["results"]] == ["company_context"]
    assert "comparison" not in json.dumps(projected)


@pytest.mark.parametrize("kind", ["company", "attachment", "report_narrative"])
@pytest.mark.asyncio
async def test_non_run_model_context_keeps_existing_evidence_contract(kind):
    context = EvidenceStore().retrieve("launch")
    if kind == "attachment":
        context["sources"] = [{"id": RAW_REF["source_id"], "title": "Authorized selected file",
                               "excerpt": "Explicitly authorized quoted text."}]
        context["evidence_refs"] = [deepcopy(RAW_REF)]
        context["chunks"] = [{"text": "Explicitly authorized quoted text.", "evidence_ref": RAW_REF}]
    if kind == "report_narrative":
        context["sources"] = [{"id": "authorized-invoice", "title": "Authorized reconciliation",
                               "excerpt": json.dumps({**TOTALS, "findings": [FINDING]})}]
    original = deepcopy(context)
    sent, _ = await capture(context, answer(output_ids=[]))
    assert "permitted_run_outputs" not in sent
    for key in ("nodes", "edges", "sources", "prior_memories"):
        assert sent[key] == context[key]
    if kind == "attachment":
        assert sent["evidence_refs"] == [RAW_REF]
        assert sent["chunks"] == [{"evidence_ref": RAW_REF}]
    assert context == original


@pytest.mark.parametrize("payload", [
    answer(answer="Raw evidence [private-finance-source].", source_ids=[RAW_REF["source_id"]]),
    answer(evidence_refs=[RAW_REF]),
    answer(output_ids=["invented-report"]),
])
@pytest.mark.asyncio
async def test_live_followup_invalid_citations_still_fail_without_saving_memory(tmp_path, payload):
    store = EvidenceStore()
    store.context = run_context()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}))) as http:
        client = OpenAICompatibleClient(ModelConfig(api_key="unit-test-only"), http_client=http)
        service = InvestigationService(store, tmp_path / "checkpoints.sqlite", client)
        with pytest.raises(ModelResponseError):
            await service.investigate("What did the run find?", run_id="run-real")
        assert not store.memories and not store.actions
        await service.aclose()


@pytest.mark.parametrize("status", [400, 401, 403, 413, 429, 500, 503])
@pytest.mark.asyncio
async def test_provider_failure_keeps_only_safe_http_status(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        status, text="PRIVATE_PROVIDER_BODY"))) as http:
        client = OpenAICompatibleClient(ModelConfig(api_key="unit-test-only"), http_client=http)
        with pytest.raises(ModelError) as raised:
            await client.generate("Question", {"nodes": [], "edges": [], "sources": []})
    assert raised.value.provider_status == status
    assert "PRIVATE_PROVIDER_BODY" not in str(raised.value)
    assert "PRIVATE_PROVIDER_BODY" not in repr(raised.value)


def test_model_error_preserves_runtime_error_args_and_ignores_unsafe_status_values():
    assert ModelError("first", "second").args == ("first", "second")
    for invalid in (True, "413", {"body": "private"}, 200, 600, None):
        assert ModelError("safe", provider_status=invalid).provider_status is None
