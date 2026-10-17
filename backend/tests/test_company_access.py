"""Every legacy read must pass the same identity/evidence boundary as uploads."""

import json

import pytest

from relay.access import AccessContext, AccessService
from relay.auth import AuthService
from relay.company import CompanyService
from relay.graph_store import GraphStore

pytest_plugins = ["identity_helpers"]


@pytest.fixture
def company(identity_db):
    raw = GraphStore(graph_name=identity_db.graph_name)
    raw.seed()
    auth = AuthService(identity_db)
    owner = auth.create_member("owner", "test-only long password", "Owner", "operator")
    other = auth.create_member("other", "test-only long password", "Other", "operator")
    return CompanyService(raw, AccessService(identity_db)), AccessContext(owner.id), AccessContext(other.id)


def test_legacy_graph_bootstrap_contains_no_full_source_excerpts(company):
    service, owner, _ = company
    graph = service.get_graph(owner)
    assert len(graph["nodes"]) == 24
    assert all("excerpt" not in source for source in graph["sources"])


def test_new_memories_and_actions_visible_only_to_owner(company):
    service, owner, other = company
    action = {"id": "a-private", "title": "Review", "description": "Private request",
              "owner": "Isha Rao", "status": "proposed", "investigation_id": "i-private",
              "source_ids": ["src-payment-runbook"], "created_at": "2026-10-17T00:00:00Z"}
    memory = {"id": "i-private", "question": "Private request", "answer": "Private answer",
              "source_ids": ["src-payment-runbook"], "node_ids": [], "steps": [], "actions": [action],
              "created_at": "2026-10-17T00:00:00Z", "mode": "demo"}
    service.save_investigation(memory, access=owner)
    assert service.list_memories(owner)[0]["id"] == "i-private"
    assert service.list_actions(owner)[0]["id"] == "a-private"
    assert service.list_memories(other) == []
    assert service.list_actions(other) == []
    with pytest.raises(Exception):
        service.transition_action(other, "a-private", "approved")


def test_retrieval_filters_private_payload_and_bounds_total_text(company):
    service, owner, other = company
    database = service.store.database
    payload = {"id": "private", "title": "Launch secret", "excerpt": "secret finance launch",
               "author": "Owner", "type": "document", "updated_at": "today"}
    database.query("CREATE (:Source {id:'private',workspace_id:'meridian',classification:'finance',"
                   "uploader_id:$owner,search:'launch',payload:$payload})",
                   {"owner": owner.member_id, "payload": json.dumps(payload)})
    for member in (owner, other):
        context = service.retrieve("launch", access=member)
        assert "private" not in [source["id"] for source in context["sources"]]
        assert sum(len(s.get("excerpt", "")) for s in context["sources"]) <= 24000



def test_ripple_proposals_and_scenario_are_private_to_authenticated_requester(company):
    service, owner, other = company
    legacy = service.store.simulate('payment-gateway')
    result = service.simulate(owner,'payment-gateway')
    action_ids = {action['id'] for action in result['actions']}
    assert action_ids
    assert action_ids <= {action['id'] for action in service.list_actions(owner)}
    assert not action_ids & {action['id'] for action in service.list_actions(other)}
    assert result['scenario_id'] != legacy['scenario_id']
    database = service.store.database
    records = database.query('MATCH (n) WHERE n.id IN $ids RETURN properties(n)',
                             {'ids':[result['scenario_id'],*action_ids]})
    assert len(records) == len(action_ids)+1
    for (record,) in records:
        assert record['requester_id']==owner.member_id
        assert record['workspace_id']==owner.workspace_id
        assert record['audience']==[owner.member_id]
        assert record['record_kind']=='legacy_manual'
        assert not service.access.can_read(other,record['id'])
    for identifier in action_ids:
        with pytest.raises(Exception):
            service.transition_action(other,identifier,'approved')
    identifier = next(iter(action_ids))
    assert service.transition_action(owner,identifier,'approved')['status']=='approved'
    repeated = service.simulate(owner,'payment-gateway')
    assert next(action for action in repeated['actions'] if action['id']==identifier)['status']=='approved'
    others = service.simulate(other,'payment-gateway')
    assert not action_ids & {action['id'] for action in others['actions']}
    assert {action['id'] for action in service.store.simulate('payment-gateway')['actions']} == {
        action['id'] for action in legacy['actions']}
    assert service.store.database.query('MATCH (s:Scenario {id:$id}) RETURN s.requester_id',
                                         {'id':legacy['scenario_id']}) == [[None]]
