"""Access never turns human finance visibility into agent permission."""

import time

import pytest

from relay.access import AccessContext, AccessError, AccessService
from relay.auth import AuthService

pytest_plugins = ["identity_helpers"]


@pytest.fixture
def access(identity_db):
    auth = AuthService(identity_db)
    members = {role: auth.create_member(role, "test-only long password", role, role,
                                       ["finance"] if role == "finance_auditor" else [])
               for role in ("admin", "operator", "finance_auditor")}
    identity_db.query("CREATE (:Source {id:'public'}), "
                      "(:Source {id:'private',workspace_id:'meridian',classification:'finance',"
                      "department_id:'finance',uploader_id:$uploader,current_version_id:'private-v1'}), "
                      "(:SourceVersion {id:'private-v1',source_id:'private',workspace_id:'meridian',"
                      "classification:'finance',department_id:'finance',uploader_id:$uploader})",
                      {"uploader": members["operator"].id})
    return AccessService(identity_db), members


def test_legacy_public_sources_visible_but_private_sources_require_human_permission(access):
    service, members = access
    uploader = AccessContext(members["operator"].id)
    service.require(uploader, "read", "public")
    service.require(uploader, "read", "private")
    for role in ("admin", "finance_auditor"):
        service.require(AccessContext(members[role].id), "read", "private")


def test_human_privileges_never_authorize_agent_finance_reads(access):
    service, members = access
    for member in members.values():
        with pytest.raises(AccessError) as raised:
            service.require(AccessContext(member.id, purpose="agent"), "read", "private-v1")
        assert raised.value.status_code == 404


def test_other_operator_private_content_hidden_in_all_derived_records(access, identity_db):
    service, _ = access
    other = AuthService(identity_db).create_member("other", "test-only long password", "Other", "operator")
    context = AccessContext(other.id)
    records = [{"id": "public"}, {"id": "private"}]
    assert service.filter_records(context, records) == [{"id": "public"}]
    assert not service.can_read_record(context, {"id": "memory", "source_ids": ["private"], "answer": "secret"})
    assert not service.can_read_record(context, {"id": "edge", "source_ids": ["private"]})
    assert not service.can_read_record(context, {"id": "unknown", "classification": "restricted"})
    assert not service.can_read_record(context, {"id": "missing-source", "source_ids": ["nonexistent"]})


def test_disabled_member_and_cross_workspace_are_rejected(access, identity_db):
    service, members = access
    member = members["admin"]
    with pytest.raises(AccessError):
        service.require(AccessContext(member.id, workspace_id="other"), "read", "public")
    identity_db.query("MATCH (m:Member {id:$id}) SET m.active=false", {"id": member.id})
    with pytest.raises(AccessError) as raised:
        service.require(AccessContext(member.id), "read", "public")
    assert raised.value.status_code == 401


def test_general_classification_is_workspace_visible_to_human_and_agent(access, identity_db):
    service, members = access
    identity_db.query("CREATE (:Source {id:'general',workspace_id:'meridian',classification:'general'})")
    for purpose in ("human", "agent"):
        service.require(AccessContext(members["operator"].id, purpose=purpose), "read", "general")


def test_new_member_owned_memories_do_not_become_workspace_public(access, identity_db):
    service, members = access
    owner = members["operator"].id
    identity_db.query("CREATE (:Investigation {id:'owned-memory',requester_id:$owner,"
                      "workspace_id:'meridian',classification:'general',audience:[$owner],"
                      "payload:'{\"source_ids\":[\"public\"]}'})", {"owner": owner})
    service.require(AccessContext(owner), "read", "owned-memory")
    service.require(AccessContext(members["admin"].id), "read", "owned-memory")
    with pytest.raises(AccessError):
        service.require(AccessContext(members["finance_auditor"].id), "read", "owned-memory")


def test_approved_output_memory_visibility_does_not_grant_originals(access, identity_db):
    service, members = access
    viewer = AuthService(identity_db).create_member("report-viewer", "test-only long password", "Viewer", "operator")
    identity_db.query("CREATE (:WorkflowRun {id:'completed-run',workspace_id:'meridian',"
                      "requester_id:$viewer,status:'completed',output_audience:[$viewer]}), "
                      "(:Artifact {id:'report',workspace_id:'meridian',classification:'finance',"
                      "run_id:'completed-run',audience:[$viewer],execution_id:'receipt'}), "
                      "(:Investigation {id:'report-memory',workspace_id:'meridian',classification:'finance',"
                      "requester_id:$viewer,audience:[$viewer],run_id:'completed-run',"
                      "payload:'{\"output_ids\":[\"report\"]}'})", {"viewer": viewer.id})
    context = AccessContext(viewer.id)
    service.require(context, "read", "report-memory")
    with pytest.raises(AccessError):
        service.require(context, "read", "private")
    with pytest.raises(AccessError):
        service.require(AccessContext(members["finance_auditor"].id), "read", "report-memory")
    identity_db.query("MATCH (r:WorkflowRun {id:'completed-run'}) SET r.requester_id='other',r.output_audience=[]")
    with pytest.raises(AccessError):
        service.require(context, "read", "report-memory")


def test_agent_can_read_explicitly_permitted_completed_output_for_that_run(access, identity_db):
    service, members = access
    owner = members["operator"].id
    identity_db.query("CREATE (:WorkflowRun {id:'output-run',workspace_id:'meridian',requester_id:$owner,"
                      "status:'completed',output_audience:[$owner]}), "
                      "(a:Artifact {id:'output-report',workspace_id:'meridian',classification:'finance',"
                      "run_id:'output-run',execution_id:'output-receipt',output_audience:[$owner]}), "
                      "(e:Execution {id:'output-receipt',run_id:'output-run',workspace_id:'meridian',status:'completed'}), "
                      "(e)-[:PRODUCED]->(a)", {"owner": owner})
    context = AccessContext(owner, purpose="agent", run_id="output-run")
    service.require(context, "read", "output-report")
    with pytest.raises(AccessError):
        service.require(AccessContext(owner, purpose="agent", run_id="another"), "read", "output-report")
    identity_db.query("MATCH (e:Execution {id:'output-receipt'}) SET e.status='failed'")
    with pytest.raises(AccessError):
        service.require(context, "read", "output-report")


def test_operator_cannot_decide_finance_approval_even_if_assigned(access, identity_db):
    service, members = access
    member = members["operator"]
    identity_db.query("CREATE (:Approval {id:'approval', workspace_id:'meridian',"
                      "reviewer_id:$id,gate_kind:'finance_access',status:'pending',expires_at:$expiry})",
                      {"id": member.id, "expiry": time.time() + 1000})
    with pytest.raises(AccessError) as raised:
        service.require(AccessContext(member.id), "approval_decide", "approval")
    assert raised.value.status_code == 403


def test_assigned_finance_auditor_can_inspect_current_plan_without_output_audience(access, identity_db):
    service, members = access
    identity_db.query("CREATE (:WorkflowRun {id:'pending-run',workspace_id:'meridian',"
                      "requester_id:$requester,current_plan_id:'current-plan',output_audience:[$requester]}), "
                      "(:Approval {id:'review',run_id:'pending-run',plan_id:'current-plan',"
                      "reviewer_id:$reviewer,gate_kind:'finance_access',status:'pending'})",
                      {"requester": members["operator"].id, "reviewer": members["finance_auditor"].id})
    context = AccessContext(members["finance_auditor"].id)
    service.require(context, "read", "pending-run")
    identity_db.query("MATCH (r:WorkflowRun {id:'pending-run'}) SET r.current_plan_id='replacement'")
    with pytest.raises(AccessError):
        service.require(context, "read", "pending-run")


def grant(identity_db, members):
    identity_db.query(
        "CREATE (r:WorkflowRun {id:'run',workspace_id:'meridian',requester_id:$requester,"
        "current_plan_id:'plan',generation:1,status:'running'}), "
        "(p:WorkflowPlan {id:'plan',run_id:'run',scope_hash:'scope',policy_id:'policy',"
        "output_audience:[$requester],generation:1,input_count:1}), "
        "(s:WorkflowStep {id:'step',run_id:'run',tool:'finance_parse',tool_version:'1',"
        "input_hash:'input',arguments_json:'{}',status:'running'}), "
        "(a:Approval {id:'approval',run_id:'run',plan_id:'plan',scope_hash:'scope',"
        "policy_id:'policy',reviewer_id:$reviewer,status:'approved',gate_kind:'finance_access',"
        "expires_at:$expiry,output_audience:[$requester]}), "
        "(policy:Policy {id:'policy',department_id:'finance',reviewer_id:$reviewer,"
        "allowed_tools:['finance_parse'],version:1}), "
        "(r)-[:HAS_PLAN]->(p), (p)-[:HAS_STEP]->(s), "
        "(s)-[:REQUIRES_APPROVAL]->(a), (a)-[:AUTHORIZES {tool:'finance_parse',"
        "tool_version:'1',input_hash:'input',arguments_json:'{}'}]->(s) "
        "WITH s,a,p,policy MATCH (v:SourceVersion {id:'private-v1'}),(d:Department {id:'finance'}) "
        "SET d.current_policy_id='policy' CREATE (d)-[:GOVERNED_BY]->(policy), "
        "(s)-[:USES_SOURCE]->(v), (a)-[:PERMITS_SOURCE]->(v), (p)-[:USES_SOURCE]->(v)",
        {"requester": members["operator"].id, "reviewer": members["finance_auditor"].id,
         "expiry": time.time() + 1000})


def test_agent_finance_read_is_exact_run_step_source_and_current_scope(access, identity_db):
    service, members = access
    grant(identity_db, members)
    context = AccessContext(members["operator"].id, purpose="agent", run_id="run", step_id="step")
    service.require(context, "read", "private-v1")
    with pytest.raises(AccessError):
        service.require(AccessContext(context.member_id, purpose="agent", run_id="unrelated", step_id="step"), "read", "private-v1")
    identity_db.query("MATCH (a:Approval) SET a.expires_at=0")
    with pytest.raises(AccessError):
        service.require(context, "read", "private-v1")


@pytest.mark.parametrize("mutation", [
    "MATCH (s:Source {id:'private'}) SET s.current_version_id='replacement'",
    "MATCH (d:Department {id:'finance'}) SET d.current_policy_id='replacement'",
    "MATCH (r:WorkflowRun) SET r.status='cancelled'",
    "MATCH (p:WorkflowPlan) SET p.scope_hash='changed'",
    "MATCH (s:WorkflowStep) SET s.arguments_json='changed'",
    "MATCH (a:Approval) SET a.output_audience=['another']",
    "MATCH (m:Member {role:'finance_auditor'}) SET m.active=false",
    "MATCH (m:Member {role:'finance_auditor'})-[r:MEMBER_OF]->(:Department {id:'finance'}) DELETE r",
    "MATCH (p:WorkflowPlan) SET p.input_count=2",
])
def test_agent_grant_rechecked_after_every_scope_change(access, identity_db, mutation):
    service, members = access
    grant(identity_db, members)
    context = AccessContext(members["operator"].id, purpose="agent", run_id="run", step_id="step")
    service.require(context, "read", "private-v1")
    identity_db.query(mutation)
    with pytest.raises(AccessError):
        service.require(context, "read", "private-v1")
