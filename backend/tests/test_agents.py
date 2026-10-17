"""Workflow checks use real LangGraph/SQLite with a small isolated evidence store."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from relay.agents import InvestigationService
from relay.llm import (
    ModelError,
    ModelResponseError,
    OpenAICompatibleClient,
    get_model_config,
)


class EvidenceStore:
    def __init__(self):
        self.memories = []
        self.actions = {}
        self.context = {
            "nodes": [
                node("payment-gateway", "Payment gateway", "service", "at_risk", "Isha Rao", "src-runbook"),
                node("checkout", "Checkout", "service", "healthy", "Mara Chen", "src-launch"),
                node("atlas-launch", "Atlas launch", "project", "at_risk", "Mara Chen", "src-launch"),
                node("backup-provider", "Backup provider", "service", "healthy", "Isha Rao", "src-runbook"),
                node("payment-incident", "September payment incident", "incident", "resolved", "Isha Rao", "src-incident"),
            ],
            "edges": [
                edge("checkout", "payment-gateway", "DEPENDS_ON", "src-launch"),
                edge("atlas-launch", "checkout", "DEPENDS_ON", "src-launch"),
                edge("backup-provider", "payment-gateway", "BACKUP_FOR", "src-runbook"),
                edge("checkout", "backup-provider", "CAN_USE", "src-runbook"),
            ],
            "sources": [
                source("src-launch", "Atlas readiness", "Atlas launch depends on Checkout; Checkout depends on Payment gateway."),
                source("src-runbook", "Payment recovery", "Isha Rao owns Payment gateway. Checkout can use Backup provider after a reviewed failover."),
                source("src-incident", "Incident review", "In September, checkout recovered with Backup provider in 18 minutes; billing stayed delayed."),
            ],
        }

    def retrieve(self, question):
        return deepcopy({**self.context, "prior_memories": self.memories[-5:]})

    def save_investigation(self, result):
        self.memories.append(deepcopy(result))
        return result

    def save_actions(self, actions):
        self.actions.update({action["id"]: deepcopy(action) for action in actions})


def node(node_id, label, kind, status, owner, source_id):
    return {"id": node_id, "label": label, "kind": kind, "status": status,
            "owner": owner, "description": label, "source_ids": [source_id], "x": 0, "y": 0}


def edge(source_id, target, relation, evidence):
    return {"id": f"{source_id}-{relation}-{target}", "source": source_id, "target": target,
            "relation": relation, "label": relation, "source_ids": [evidence]}


def source(source_id, title, excerpt):
    return {"id": source_id, "title": title, "excerpt": excerpt, "type": "document",
            "author": "Meridian", "updated_at": "2026-10-01T00:00:00+00:00"}


@pytest.fixture(autouse=True)
def no_paid_provider(monkeypatch):
    monkeypatch.delenv("RELAY_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("RELAY_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("RELAY_MODEL", raising=False)


@pytest.mark.asyncio
async def test_demo_runs_three_agents_and_saves_only_proposals(tmp_path):
    store = EvidenceStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What happens if payments fail?", "demo-session")
    assert result["mode"] == service.mode == "demo"
    assert "Payment gateway" in result["answer"]
    assert "Checkout" in result["answer"] and "Atlas launch" in result["answer"]
    assert "Backup provider" in result["answer"]
    assert [step["agent"] for step in result["steps"]] == ["Researcher", "Planner", "Archivist"]
    assert all(step["status"] == "complete" for step in result["steps"])
    assert result["actions"] and set(store.actions) == {a["id"] for a in result["actions"]}
    assert all(a["status"] == "proposed" and "approved_at" not in a for a in store.actions.values())
    assert all(a["owner"] in {"Mara Chen", "Isha Rao"} for a in result["actions"])
    assert set(result["source_ids"]) <= {s["id"] for s in store.context["sources"]}
    assert result["source_ids"] and store.memories == [result]
    await service.aclose()


@pytest.mark.asyncio
async def test_demo_uses_graph_data_instead_of_fixed_company_answer(tmp_path):
    store = EvidenceStore()
    for item in store.context["nodes"]:
        if item["id"] == "atlas-launch":
            item["label"] = "Aurora release"
            item["owner"] = "Ana Lima"
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What are the launch blockers?")
    assert "Aurora release" in result["answer"]
    assert "Atlas launch" not in result["answer"]
    owners = await service.investigate("Who owns the launch?")
    assert "Ana Lima" in owners["answer"]


@pytest.mark.asyncio
async def test_unknown_question_is_honest_and_proposes_no_actions(tmp_path):
    store = EvidenceStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What is the capital of France?")
    assert "guided demo" in result["answer"].lower()
    assert "launch" in result["answer"].lower()
    assert not result["source_ids"] and not result["actions"] and not result["node_ids"]
    assert not store.actions


@pytest.mark.asyncio
async def test_prior_incident_uses_real_excerpt_without_future_guarantee(tmp_path):
    service = InvestigationService(EvidenceStore(), tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What happened in the previous payment incident?")
    assert "18 minutes" in result["answer"] and "billing stayed delayed" in result["answer"]
    assert "src-incident" in result["source_ids"]
    assert not result["actions"]


@pytest.mark.asyncio
async def test_healthy_launch_explains_required_signoffs_without_inventing_outage(tmp_path):
    store = EvidenceStore()
    for item in store.context["nodes"]:
        if item["kind"] == "service":
            item["status"] = "healthy"
        elif item["kind"] == "project":
            item["status"] = "active"
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What blocks the launch?")
    assert "no service is currently marked blocked" in result["answer"].lower()
    assert "Checkout" in result["answer"]
    assert result["actions"] and result["actions"][0]["owner"] == "Mara Chen"
    assert "recorded as at risk" not in result["answer"].lower()


@pytest.mark.asyncio
async def test_dependency_direction_does_not_invent_reverse_impact(tmp_path):
    store = EvidenceStore()
    store.context["edges"][0].update(source="payment-gateway", target="checkout")
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite")
    result = await service.investigate("What happens if payments fail?")
    assert "Payment gateway → Checkout" not in result["answer"]


@pytest.mark.asyncio
async def test_independent_sessions_share_sqlite_without_losing_turns(tmp_path):
    service = InvestigationService(EvidenceStore(), tmp_path / "checkpoints.sqlite")
    results = await asyncio.gather(*[
        service.investigate("Who owns payments?", f"session-{index}") for index in range(6)
    ])
    assert len({result["id"] for result in results}) == 6
    assert all("Session turn 1" in result["steps"][0]["detail"] for result in results)


@pytest.mark.asyncio
async def test_checkpoint_survives_service_restart_and_serializes_same_session(tmp_path):
    path = tmp_path / "checkpoints.sqlite"
    store = EvidenceStore()
    service = InvestigationService(store, path)
    first, second = await asyncio.gather(
        service.investigate("What blocks launch?", "persistent-thread"),
        service.investigate("Who owns payments?", "persistent-thread"),
    )
    await service.aclose()
    reopened = InvestigationService(store, path)
    third = await reopened.investigate("What happened previously?", "persistent-thread")
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": "persistent-thread"}})
    state = checkpoint.checkpoint["channel_values"]
    assert state["turn"] == 3
    assert state["investigation_ids"] == [first["id"], second["id"], third["id"]]
    assert "previous" in third["steps"][0]["detail"].lower()
    assert len({a["id"] for a in first["actions"]}) == len(first["actions"])


def live_client(monkeypatch, handler):
    monkeypatch.setenv("RELAY_MODEL_API_KEY", "unit-test-not-a-real-key")
    return OpenAICompatibleClient(
        get_model_config(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_live_provider_failure_never_silently_falls_back(monkeypatch, tmp_path):
    client = live_client(monkeypatch, lambda request: httpx.Response(503, text="provider down"))
    store = EvidenceStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite", client)
    with pytest.raises(ModelError, match="unavailable"):
        await service.investigate("What blocks launch?")
    assert service.mode == "live" and not store.memories and not store.actions
    await client.aclose()


@pytest.mark.parametrize("payload", [
    {"answer": "A launch fact.", "source_ids": ["invented"], "node_ids": [], "actions": []},
    {"answer": "A launch fact [invented].", "source_ids": ["src-launch"], "node_ids": [], "actions": []},
    {"answer": "A launch fact.", "source_ids": ["src-launch"], "node_ids": ["invented"], "actions": []},
    {"answer": "A launch fact.", "source_ids": ["src-launch"], "node_ids": [], "actions": [
        {"title": "Investigate", "description": "Look at evidence.", "owner": "Invented Person", "source_ids": ["src-launch"]}
    ]},
    {"answer": "A launch fact.", "source_ids": ["src-launch"], "node_ids": [], "actions": [
        {"title": "Investigate", "description": "Look at evidence.", "owner": "Mara Chen",
         "source_ids": ["src-launch"], "status": "approved"}
    ]},
])
@pytest.mark.asyncio
async def test_live_fabricated_evidence_and_owners_are_rejected(monkeypatch, tmp_path, payload):
    client = live_client(monkeypatch, lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
    ))
    store = EvidenceStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite", client)
    with pytest.raises(ModelResponseError):
        await service.investigate("What blocks launch?")
    assert not store.memories and not store.actions
    await client.aclose()


@pytest.mark.asyncio
async def test_live_success_uses_configured_groq_and_preserves_approval_gate(monkeypatch, tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "answer": "Checkout depends on Payment gateway [src-launch].",
            "source_ids": ["src-launch"], "node_ids": ["checkout", "payment-gateway"],
            "actions": [{"title": "Review checkout recovery", "description": "Review payment dependencies.",
                         "owner": "Mara Chen", "source_ids": ["src-launch"]}],
        })}}]})

    client = live_client(monkeypatch, handler)
    store = EvidenceStore()
    service = InvestigationService(store, tmp_path / "checkpoints.sqlite", client)
    result = await service.investigate("What blocks launch?")
    assert result["mode"] == "live" and result["actions"][0]["status"] == "proposed"
    assert requests[0].url == "https://api.groq.com/openai/v1/chat/completions"
    assert json.loads(requests[0].content)["model"] == "openai/gpt-oss-20b"
    assert max(requests[0].extensions["timeout"].values()) <= 30
    assert "unit-test-not-a-real-key" not in repr(client.config)
    await client.aclose()
