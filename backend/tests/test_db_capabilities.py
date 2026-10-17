"""Persistence prerequisites, exercised on isolated real FalkorDB graphs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from relay.graph_store import GraphStore


@pytest.fixture
def database():
    store = GraphStore(f"relay_test_capability_{uuid4().hex}")
    store._query("RETURN 1")
    try:
        yield store
    finally:
        assert store.graph.name.startswith("relay_test_")
        store.graph.delete()


def unique_ids(database):
    database.graph.create_node_range_index("Receipt", "id")
    database.graph.create_node_unique_constraint("Receipt", "id")
    deadline = monotonic() + 5
    while monotonic() < deadline:
        constraints = database.graph.list_constraints()
        if constraints and all(c["status"] == "OPERATIONAL" for c in constraints):
            return
        sleep(0.01)
    pytest.fail(f"Unique ID constraint did not become operational: {constraints}")


def test_scalar_index_and_unique_constraint_reject_duplicate_id(database):
    unique_ids(database)
    database._query("CREATE (:Receipt {id:'effect'})")
    with pytest.raises(ResponseError):
        database._query("CREATE (:Receipt {id:'effect'})")
    assert database._query("MATCH (r:Receipt) RETURN count(r)") == [[1]]


def test_competing_conditional_claims_have_one_winner(database):
    database._query("CREATE (:WorkflowStep {id:'s', status:'queued', fence:0})")
    barrier = Barrier(8)

    def claim(index):
        client = GraphStore(database.graph.name)
        barrier.wait()
        return client._query(
            "MATCH (s:WorkflowStep {id:'s'}) WHERE s.status='queued' "
            "SET s.status='running', s.fence=s.fence+1, s.lease_owner=$owner RETURN s.fence",
            owner=str(index),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))
    assert sum(bool(result) for result in results) == 1
    assert database._query("MATCH (s:WorkflowStep) RETURN s.fence") == [[1]]


def test_multi_record_constraint_failure_rolls_back_all_effects(database):
    unique_ids(database)
    database._query("CREATE (:Receipt {id:'existing'}), (:WorkflowStep {id:'s', status:'running', fence:1})")
    with pytest.raises(ResponseError):
        database._query(
            "MATCH (s:WorkflowStep {id:'s'}) WHERE s.fence=1 "
            "SET s.status='completed' CREATE (:Artifact {id:'should-rollback'}) "
            "CREATE (:Receipt {id:'existing'})"
        )
    assert database._query("MATCH (s:WorkflowStep) RETURN s.status") == [["running"]]
    assert database._query("MATCH (a:Artifact) RETURN count(a)") == [[0]]


def test_dependency_traversal_keeps_company_and_workflow_labels_separate(database):
    database._query(
        "CREATE (a:WorkflowStep {id:'report'})-[:DEPENDS_ON]->(b:WorkflowStep {id:'compare'}), "
        "(b)-[:DEPENDS_ON]->(c:WorkflowStep {id:'parse'}), "
        "(:Entity {id:'launch'})-[:DEPENDS_ON]->(:Entity {id:'gateway'})"
    )
    assert database._query(
        "MATCH (s:WorkflowStep)-[:DEPENDS_ON*1..]->(:WorkflowStep {id:'parse'}) "
        "RETURN s.id ORDER BY s.id"
    ) == [["compare"], ["report"]]


def test_atomic_fenced_effect_commit_rejects_cancelled_or_replaced_scope(database):
    database._query("CREATE (:WorkflowRun {id:'run',generation:1,revision:1,cancelled:false}),"
                    "(:WorkflowStep {id:'step',status:'running',fence:1}),"
                    "(:Approval {id:'approval',status:'approved',scope:'v1'})")
    statement = (
        "MATCH (r:WorkflowRun {id:'run'}),(s:WorkflowStep {id:'step'}),"
        "(a:Approval {id:'approval'}) WHERE r.generation=$generation AND r.revision=$revision "
        "AND r.cancelled=false AND s.status='running' AND s.fence=$fence "
        "AND a.status='approved' AND a.scope=$scope "
        "CREATE (e:Execution {id:$effect}),(o:Artifact {id:$artifact}) "
        "SET s.status='completed',r.revision=r.revision+1 "
        "CREATE (s)-[:EXECUTED_AS]->(e)-[:PRODUCED]->(o) RETURN e.id"
    )
    args = dict(generation=1, revision=1, fence=1, scope='v1', effect='effect', artifact='artifact')
    database._query("MATCH (s:WorkflowStep {id:'step'}) SET s.fence=2")
    assert database._query(statement, **args) == []
    args['fence'] = 2
    database._query("MATCH (a:Approval) SET a.scope='v2'")
    assert database._query(statement, **args) == []
    args['scope'] = 'v2'
    database._query("MATCH (r:WorkflowRun) SET r.cancelled=true")
    assert database._query(statement, **args) == []
    assert database._query('MATCH (e:Execution) RETURN count(e)') == [[0]]
    database._query("MATCH (r:WorkflowRun) SET r.cancelled=false")
    assert database._query(statement, **args) == [['effect']]
    assert database._query(statement, **args) == []
    assert database._query('MATCH (e:Execution)-[:PRODUCED]->(a:Artifact) RETURN e.id,a.id') == [['effect','artifact']]


def test_runtime_capability_gate_proves_fenced_effects(database):
    from relay.migrations import probe_capabilities
    result = probe_capabilities(database.database)
    assert result.get('fenced_effects') is True
