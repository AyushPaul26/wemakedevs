"""Integration behavior checks against a disposable, real FalkorDB graph."""

from datetime import datetime, timezone
import socket
from uuid import uuid4

import pytest

from relay.graph_store import GraphStore


@pytest.fixture
def store():
    graph_name = f"relay_test_{uuid4().hex}"
    result = GraphStore(graph_name=graph_name)
    result.seed()
    try:
        yield result
    finally:
        # Never clear a user's configured workspace graph.
        assert graph_name.startswith("relay_test_")
        result.graph.delete()


def test_seed_is_idempotent_and_retains_notes_memories_and_actions(store):
    before = store.stats()
    source = store.add_source("My launch note", "Review the rollout before Friday.")
    investigation = memory(source["id"])
    store.save_investigation(investigation)
    store.save_actions([action(investigation["id"], source["id"])])
    store.seed()
    after = store.stats()
    assert after["entities"] == before["entities"]
    assert after["relationships"] == before["relationships"]
    assert after["memories"] == before["memories"] + 1
    assert after["actions"] == before["actions"] + 1
    assert store.get_source(source["id"])["excerpt"] == "Review the rollout before Friday."
    assert store.list_memories()[0]["id"] == investigation["id"]


def test_real_graph_has_truthful_sources_owners_and_edge_direction(store):
    graph = store.get_graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    source_ids = {source["id"] for source in graph["sources"]}
    assert 20 <= len(nodes) <= 30
    assert 25 <= len(graph["edges"]) <= 40
    assert nodes["checkout"]["owner"]
    for item in graph["nodes"] + graph["edges"]:
        assert item["source_ids"]
        assert set(item["source_ids"]) <= source_ids
    dependencies = {(edge["source"], edge["target"]) for edge in graph["edges"]
                    if edge["relation"] == "DEPENDS_ON"}
    assert ("checkout", "payment-gateway") in dependencies
    assert ("atlas-launch", "checkout") in dependencies
    assert ("payment-gateway", "checkout") not in dependencies


def test_ripple_uses_directed_multi_hop_dependencies(store):
    ripple = store.simulate("payment-gateway")
    assert set(ripple["affected_ids"]) == {"checkout", "atlas-launch", "billing-reconciliation"}
    assert ["payment-gateway", "checkout", "atlas-launch"] in ripple["paths"]
    assert ripple["risk_before"] == ripple["risk_after"] == 3
    assert "backup-provider" not in ripple["affected_ids"]
    assert "payment-gateway" not in store.simulate("checkout")["affected_ids"]
    assert all(store.get_source(source_id) for source_id in ripple["source_ids"])
    with pytest.raises(ValueError):
        store.simulate("atlas-launch")
    with pytest.raises(ValueError):
        store.simulate("not-a-service")


def test_mitigation_only_removes_supported_path_without_changing_facts(store):
    baseline_graph = store.get_graph()
    baseline = store.simulate("payment-gateway")
    alternative = store.simulate("payment-gateway", mitigation=True)
    assert alternative["risk_before"] == 3
    assert alternative["risk_after"] == 1
    assert alternative["affected_ids"] == ["billing-reconciliation"]
    assert alternative["assumptions"]
    assert store.get_graph() == baseline_graph
    assert store.simulate("payment-gateway")["affected_ids"] == baseline["affected_ids"]
    assert store.simulate("identity-service", True)["risk_after"] == store.simulate(
        "identity-service", False
    )["risk_after"]


def test_scenario_actions_have_durable_ids_and_idempotent_approval(store):
    first = store.simulate("payment-gateway")
    second = store.simulate("payment-gateway")
    assert first["actions"]
    assert [item["id"] for item in first["actions"]] == [item["id"] for item in second["actions"]]
    selected = first["actions"][0]
    with pytest.raises(ValueError):
        store.transition_action(selected["id"], "done")
    approved = store.transition_action(selected["id"], "approved")
    assert approved == store.transition_action(selected["id"], "approved")
    assert store.simulate("payment-gateway")["actions"][0]["status"] == "approved"
    completed = store.transition_action(selected["id"], "done")
    assert completed == store.transition_action(selected["id"], "done")
    with pytest.raises(ValueError):
        store.transition_action(selected["id"], "approved")
    with pytest.raises(KeyError):
        store.transition_action("missing", "approved")
    assert len(store.list_actions()) == len(first["actions"])
    assert store.stats()["actions"] == len(first["actions"])


def test_memory_sources_and_actions_survive_a_new_store_instance(store):
    source = store.add_source("Robert's note", "MATCH (n) DELETE n; is text, not Cypher.")
    investigation = memory(source["id"])
    investigation["actions"] = [action(investigation["id"], source["id"])]
    store.save_investigation(investigation)
    store.save_investigation(investigation)
    reopened = GraphStore(graph_name=store.graph.name)
    assert reopened.health()
    assert reopened.list_memories() == [investigation]
    assert reopened.get_source(source["id"])["title"] == "Robert's note"
    assert len(reopened.list_actions()) == 1
    assert reopened.get_source("unknown") is None
    approved = reopened.transition_action(investigation["actions"][0]["id"], "approved")
    assert reopened.list_memories()[0]["actions"][0] == approved


def test_retrieval_is_evidence_backed_and_bounded(store):
    context = store.retrieve("Who owns payments, and what happened in the previous incident?")
    assert context["nodes"]
    ids = {node["id"] for node in context["nodes"]}
    assert "payment-gateway" in ids
    assert "payment-incident" in ids
    assert context["sources"]
    assert len(context["nodes"]) <= 30
    assert len(context["prior_memories"]) <= 5
    assert all(store.get_source(source["id"]) for source in context["sources"])


def test_graphify_import_is_provenanced_idempotent_and_rejects_untrusted_types(store):
    data = {
        "nodes": [{"id": "module-a", "label": "Module A", "kind": "service"},
                  {"id": "module-b", "label": "Module B", "kind": "service"}],
        "edges": [{"source": "module-a", "target": "module-b", "relation": "DEPENDS_ON"}],
    }
    assert store.import_graphify(data, "Repository architecture") == {"nodes": 2, "edges": 1}
    count = store.stats()
    store.import_graphify(data, "Repository architecture")
    assert store.stats() == count
    imported = [node for node in store.get_graph()["nodes"] if node["label"] == "Module A"]
    assert len(imported) == 1
    assert store.get_source(imported[0]["source_ids"][0])["title"] == "Repository architecture"
    bad = {"nodes": data["nodes"], "edges": [{"source": "module-a", "target": "module-b",
                                               "relation": "X]->(n) DELETE n //"}]}
    with pytest.raises(ValueError):
        store.import_graphify(bad, "Rejected")
    with pytest.raises(ValueError):
        store.import_graphify({"nodes": [{"id": "unsafe", "kind": "UntrustedLabel"}],
                               "edges": []}, "Rejected")
    with pytest.raises(ValueError):
        store.import_graphify({"nodes": [{"id": str(i)} for i in range(501)], "edges": []}, "Too large")
    assert store.stats() == count


def test_backup_does_not_hide_an_alternate_unmitigated_path(store):
    # A new authoritative dependency creates another payment-to-launch route.
    # Removing the checkout edge must not clear launch exposure through billing.
    store.graph.query(
        "MATCH (a:Entity {id:'atlas-launch'}), (b:Entity {id:'billing-reconciliation'}) "
        "CREATE (a)-[:DEPENDS_ON {id:'test-second-launch-route', "
        "source_ids:['src-billing-policy']}]->(b)"
    )
    alternative = store.simulate("payment-gateway", True)
    assert set(alternative["affected_ids"]) == {"billing-reconciliation", "atlas-launch"}
    assert ["payment-gateway", "billing-reconciliation", "atlas-launch"] in alternative["paths"]
    assert alternative["risk_after"] == 2


@pytest.mark.parametrize("transitive", [False, True])
def test_backup_exposed_to_same_outage_cannot_mitigate_consumer(store, transitive):
    node_ids = ["origin", "consumer", "backup"] + (["intermediate"] if transitive else [])
    data = {
        "nodes": [{"id": node_id, "label": f"Outage test {node_id}", "kind": "service",
                   "status": "healthy"} for node_id in node_ids],
        "edges": [
            {"source": "consumer", "target": "origin", "relation": "DEPENDS_ON"},
            {"source": "consumer", "target": "backup", "relation": "CAN_USE"},
            {"source": "backup", "target": "origin", "relation": "BACKUP_FOR"},
            {"source": "backup", "target": "intermediate" if transitive else "origin",
             "relation": "DEPENDS_ON"},
        ],
    }
    if transitive:
        data["edges"].append({"source": "intermediate", "target": "origin", "relation": "DEPENDS_ON"})
    store.import_graphify(data, "Backup exposure regression")
    nodes = {node["label"]: node["id"] for node in store.get_graph()["nodes"]}
    origin = nodes["Outage test origin"]
    baseline = store.simulate(origin)
    alternative = store.simulate(origin, mitigation=True)
    assert len(baseline["affected_ids"]) == (3 if transitive else 2)
    assert alternative["affected_ids"] == baseline["affected_ids"]
    assert nodes["Outage test consumer"] in alternative["affected_ids"]
    assert alternative["risk_after"] == baseline["risk_after"]
    assert all(store.get_source(source_id) for source_id in alternative["source_ids"])


def test_imported_dependency_chain_is_not_silently_cut_off(store):
    # No artificial depth limit may turn a reachable dependency into a safe node.
    data = {
        "nodes": [{"id": f"service-{i}", "label": f"Imported service {i}", "kind": "service"}
                  for i in range(36)],
        "edges": [{"source": f"service-{i}", "target": f"service-{i - 1}", "relation": "DEPENDS_ON"}
                  for i in range(1, 36)],
    }
    store.import_graphify(data, "Deep dependency graph")
    origin = next(node["id"] for node in store.get_graph()["nodes"]
                  if node["label"] == "Imported service 0")
    assert store.simulate(origin)["risk_after"] == 35


@pytest.mark.parametrize("bad", [
    {"nodes": [{"id": "x", "kind": []}], "edges": []},
    {"nodes": [{"id": "x", "status": {}}], "edges": []},
    {"nodes": [{"id": "x"}], "edges": [{"source": [], "target": "x"}]},
])
def test_malformed_import_types_fail_validation_before_writes(store, bad):
    before = store.stats()
    with pytest.raises(ValueError):
        store.import_graphify(bad, "Invalid input")
    assert store.stats() == before


def test_store_construction_defers_connection_failure_until_query(monkeypatch):
    from redis.exceptions import ConnectionError

    # Reserve an unused loopback port without listening; no running service is stopped.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        monkeypatch.setenv("RELAY_FALKORDB_HOST", "127.0.0.1")
        monkeypatch.setenv("RELAY_FALKORDB_PORT", str(reserved.getsockname()[1]))
        unavailable = GraphStore(graph_name="relay_test_unavailable")
        with pytest.raises(ConnectionError):
            unavailable.health()


def memory(source_id):
    return {"id": "investigation-test", "question": "What is our rollout note?",
            "answer": "Review before Friday.", "source_ids": [source_id], "node_ids": [],
            "steps": [], "actions": [], "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "demo"}


def action(investigation_id, source_id):
    return {"id": "action-test", "title": "Review rollout", "description": "Read the note.",
            "owner": "Mara Chen", "status": "proposed", "investigation_id": investigation_id,
            "source_ids": [source_id], "created_at": datetime.now(timezone.utc).isoformat()}
