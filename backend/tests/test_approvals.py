from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from relay.access import AccessContext, AccessError, AccessService
from relay.workflow_models import ApprovalDecision
from test_workflow_plans import setup_workflow as _setup_workflow, create, by_key

setup_workflow = _setup_workflow


def decision(run, **changes):
    return ApprovalDecision(decision='approve',expected_revision=run.revision,scope_hash=run.approvals[0]['scope_hash'],**changes)


def test_only_assigned_auditor_can_grant_exact_scope(setup_workflow):
    db, service, operator, auditor, _ = setup_workflow
    run = create(setup_workflow)
    with pytest.raises(AccessError) as exc:
        service.decide(operator,run.approvals[0]['id'],decision(run),str(uuid4()))
    assert exc.value.status_code == 403
    updated = service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    assert by_key(updated)['finance_parse']['status'] == 'queued'
    context = AccessContext('operator',purpose='agent',run_id=run.id,step_id=by_key(updated)['finance_parse']['id'])
    assert AccessService(db).can_read(context,'invoice:1')
    assert not AccessService(db).can_read(AccessContext('operator',purpose='agent'),'invoice:1')


def test_two_client_approval_race_has_one_decision_and_one_event(setup_workflow):
    db, service, _, auditor, _ = setup_workflow
    run = create(setup_workflow)
    def attempt(_):
        try:
            return service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4())).id
        except AccessError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt,range(2)))
    assert results.count(run.id) == 1
    assert db.query("MATCH (e:RunEvent {run_id:$id,kind:'approval_approved'}) RETURN count(e)",{'id':run.id}) == [[1]]


@pytest.mark.parametrize('mutation',[
    "MATCH (a:Approval) SET a.expires_at=0",
    "MATCH (s:Source {id:'invoice'}) SET s.current_version_id='invoice:2'",
    "MATCH (d:Department {id:'finance'}) SET d.current_policy_id='finance:2'",
    "MATCH (m:Member {id:'auditor'}) SET m.active=false",
])
def test_stale_scope_never_grants(setup_workflow,mutation):
    db, service, _, auditor, _ = setup_workflow
    run = create(setup_workflow)
    db.query(mutation)
    with pytest.raises(AccessError):
        service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    assert by_key(service.get_run(setup_workflow[2],run.id))['finance_parse']['status'] == 'waiting_approval'


def test_decision_replay_does_not_add_event(setup_workflow):
    db, service, _, auditor, _ = setup_workflow
    run = create(setup_workflow)
    key = str(uuid4())
    first = service.decide(auditor,run.approvals[0]['id'],decision(run),key)
    assert service.decide(auditor,run.approvals[0]['id'],decision(run),key).revision == first.revision
    assert db.query("MATCH (e:RunEvent {kind:'approval_approved'}) RETURN count(e)") == [[1]]


def test_reject_blocks_finance_and_records_reason(setup_workflow):
    _, service, operator, auditor, _ = setup_workflow
    run = create(setup_workflow)
    body=ApprovalDecision(decision='reject',expected_revision=run.revision,scope_hash=run.approvals[0]['scope_hash'],reason='Wrong order')
    updated=service.decide(auditor,run.approvals[0]['id'],body,str(uuid4()))
    assert updated.status=='rejected'
    assert by_key(updated)['finance_parse']['status']=='rejected'
    assert updated.approvals[0]['reason']=='Wrong order'
    assert service.store.claim_step('worker',run.id) is None


def test_cancel_fences_worker_and_preserves_completed_work(setup_workflow):
    from relay.workflow_models import StepEffects
    _, service, operator, _, _=setup_workflow
    run=create(setup_workflow)
    lease=service.store.claim_step('worker',run.id)
    updated=service.cancel(operator,run.id,service.get_run(operator,run.id).revision)
    assert updated.status=='cancelled'
    assert not service.store.heartbeat(lease)
    assert not service.store.commit_step(lease,StepEffects(effect_key='late',result={},evidence_refs=[],artifacts=[]))
    assert service.timeline(operator,run.id).items[-1]['kind']=='run_cancelled'


def advance_to_report(setup, automation='review_changes'):
    from relay.workflow_models import StepEffects
    db,service,operator,auditor,request=setup
    request=request.model_copy(update={'automation':automation})
    run=service.create_run(operator,request,str(uuid4()))
    run=service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    for expected in ['company_context','finance_parse','invoice_compare']:
        lease=service.store.claim_step('worker',run.id)
        assert service.store.node('WorkflowStep',lease.step_id)['logical_key']==expected
        assert service.store.commit_step(lease,StepEffects(effect_key=lease.step_id,result={},evidence_refs=[],artifacts=[]))
    return service.store.claim_step('worker',run.id)


def test_strict_effect_preview_waits_for_requester_and_cannot_change(setup_workflow):
    from relay.workflow_models import StepEffects
    _,service,operator,_,_=setup_workflow
    lease=advance_to_report(setup_workflow)
    effects=StepEffects(effect_key='report',result={'summary':'Exact approved preview'},evidence_refs=[],artifacts=[])
    assert not service.store.commit_step(lease,effects)
    approval=service.store.create_effect_approval(lease,effects.model_dump(),'report_write')
    assert approval['status']=='pending'
    assert service.store.step_context(lease)['effect_preview']==effects.model_dump()
    assert service.store.claim_step('worker',lease.run_id) is None
    run=service.get_run(operator,lease.run_id)
    body=ApprovalDecision(decision='approve',expected_revision=run.revision,scope_hash=approval['scope_hash'])
    service.decide(operator,approval['id'],body,str(uuid4()))
    fresh=service.store.claim_step('worker',lease.run_id)
    changed=effects.model_copy(update={'result':{'summary':'Unreviewed change'}})
    assert not service.store.commit_step(fresh,changed)
    assert service.store.commit_step(fresh,effects)


def test_effect_preview_only_for_matching_tool(setup_workflow):
    _,service,_,_,_=setup_workflow
    lease=advance_to_report(setup_workflow)
    with pytest.raises(ValueError):
        service.store.create_effect_approval(lease,{'result':{}},'case_write')


def test_approval_view_binds_current_run_revision_and_reviewable_scope(setup_workflow):
    _,service,operator,auditor,_=setup_workflow
    run=create(setup_workflow)
    service.store.claim_step('worker',run.id)
    run=service.get_run(operator,run.id)
    approval=run.approvals[0]
    assert approval['expected_revision']==run.revision
    assert approval['scope']['invoice']=={'source_id':'invoice','version_id':'invoice:1'}
    assert approval['scope']['purchase_order']=={'source_id':'po','version_id':'po:1'}
    assert approval['scope']['tools'][0]['tool']
    assert approval['reviewer_name']=='auditor'
    inbox=service.list_approvals(auditor)['items'][0]
    assert inbox['scope']==approval['scope']
    assert inbox['expected_revision']==run.revision


def test_changes_requested_run_can_be_cancelled_with_an_event(setup_workflow):
    _,service,operator,auditor,_=setup_workflow
    run=create(setup_workflow)
    body=ApprovalDecision(decision='request_changes',expected_revision=run.revision,scope_hash=run.approvals[0]['scope_hash'],reason='Correct the selected invoice')
    changed=service.decide(auditor,run.approvals[0]['id'],body,str(uuid4()))
    cancelled=service.cancel(operator,run.id,changed.revision,str(uuid4()))
    assert cancelled.status=='cancelled'
    assert service.timeline(operator,run.id).items[-1]['kind']=='run_cancelled'


def test_strict_mode_requires_requester_to_receive_exact_preview(setup_workflow):
    _,service,operator,_,request=setup_workflow
    request=request.model_copy(update={'automation':'review_changes','output_audience':['auditor']})
    with pytest.raises(AccessError) as exc:
        service.create_run(operator,request,str(uuid4()))
    assert exc.value.status_code==422


def test_finance_auditor_requester_cannot_approve_own_run(setup_workflow):
    db,service,operator,_,request=setup_workflow
    db.query("MATCH (m:Member {id:'operator'}),(d:Department {id:'finance'}),(p:Policy {id:'finance:1'}) SET m.role='finance_auditor',p.reviewer_id=m.id CREATE (m)-[:MEMBER_OF]->(d)")
    run=service.create_run(operator,request.model_copy(update={'output_audience':['operator']}),str(uuid4()))
    with pytest.raises(AccessError):
        service.decide(operator,run.approvals[0]['id'],decision(run),str(uuid4()))
    assert by_key(service.get_run(operator,run.id))['finance_parse']['status']=='waiting_approval'
