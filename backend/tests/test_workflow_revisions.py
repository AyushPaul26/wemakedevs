from uuid import uuid4

import pytest

from relay.workflow_models import RunRevision, StepEffects
from test_workflow_plans import setup_workflow as _setup_workflow, create, by_key

from test_approvals import decision

setup_workflow = _setup_workflow


def replace(db, source):
    version = source+':2'
    db.query('MATCH (s:Source {id:$source}) CREATE (v:SourceVersion {id:$version,source_id:$source,workspace_id:\'meridian\',classification:s.classification,department_id:s.department_id,uploader_id:s.uploader_id}), (s)-[:HAS_VERSION]->(v) SET s.current_version_id=$version,s.revision=s.revision+1',{'source':source,'version':version})
    return {'source_id':source,'version_id':version}


def test_invoice_revision_reuses_company_result_and_blocks_old_lease(setup_workflow):
    db, service, operator, auditor, request = setup_workflow
    run = create(setup_workflow)
    lease = service.store.claim_step('worker',run.id)
    assert service.store.commit_step(lease,StepEffects(effect_key='company:1',result={'summary':'company complete'},evidence_refs=[],artifacts=[]))
    run = service.get_run(operator,run.id)
    run = service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    old_lease = service.store.claim_step('finance',run.id)
    invoice = replace(db,'invoice')
    data = request.model_dump(exclude={'template','project_id'}) | {'invoice':invoice,'expected_revision':service.get_run(operator,run.id).revision}
    revised = service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert revised.generation == 2
    assert by_key(revised)['company_context']['id'] == by_key(run)['company_context']['id']
    assert by_key(revised)['company_context']['result'] == {'summary':'company complete'}
    assert by_key(revised)['finance_parse']['id'] != by_key(run)['finance_parse']['id']
    assert by_key(revised)['finance_parse']['status'] == 'waiting_approval'
    assert not service.store.commit_step(old_lease,StepEffects(effect_key='late',result={},evidence_refs=[],artifacts=[]))


def test_changed_company_input_creates_fresh_company_step(setup_workflow):
    db, service, operator, _, request = setup_workflow
    run = create(setup_workflow)
    brief = replace(db,'brief')
    data = request.model_dump(exclude={'template','project_id'}) | {'context':[brief],'expected_revision':run.revision}
    revised = service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert by_key(revised)['company_context']['id'] != by_key(run)['company_context']['id']


def test_commit_rechecks_current_sources_before_invalidation(setup_workflow):
    db, service, operator, auditor, _ = setup_workflow
    run = create(setup_workflow)
    run = service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    company = service.store.claim_step('company',run.id)
    finance = service.store.claim_step('finance',run.id)
    replace(db,'invoice')
    assert not service.store.commit_step(finance,StepEffects(effect_key='late',result={},evidence_refs=[],artifacts=[]))
    assert service.store.commit_step(company,StepEffects(effect_key='safe',result={},evidence_refs=[],artifacts=[])) is False


def test_invalidation_marks_only_affected_steps_and_outputs_historical(setup_workflow):
    db,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    lease=service.store.claim_step('worker',run.id)
    assert service.store.commit_step(lease,StepEffects(effect_key='company',result={'safe':True},evidence_refs=[],artifacts=[]))
    replace(db,'invoice')
    assert service.store.invalidate_source('invoice','invoice:2')==[run.id]
    changed=service.get_run(operator,run.id)
    assert changed.status=='stale'
    assert by_key(changed)['company_context']['status']=='completed'
    assert by_key(changed)['finance_parse']['status']=='stale'
    assert changed.approvals[0]['status']=='stale'


def test_recovery_requeues_only_expired_running_step(setup_workflow):
    db,service,_,_,_=setup_workflow
    run=create(setup_workflow)
    lease=service.store.claim_step('worker',run.id)
    assert service.store.recover().requeued==[]
    db.query('MATCH (s:WorkflowStep {id:$id}) SET s.lease_until=0',{'id':lease.step_id})
    report=service.store.recover()
    assert report.requeued==[lease.step_id]
    assert not service.store.heartbeat(lease)
    new=service.store.claim_step('new-worker',run.id)
    assert new.fence>lease.fence


def test_claim_and_commit_require_current_reviewer_membership(setup_workflow):
    db,service,_,auditor,_=setup_workflow
    run=create(setup_workflow)
    run=service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    company=service.store.claim_step('company',run.id)
    finance=service.store.claim_step('finance',run.id)
    db.query("MATCH (:Member {id:'auditor'})-[membership:MEMBER_OF]->(:Department {id:'finance'}) DELETE membership")
    assert not service.store.commit_step(finance,StepEffects(effect_key='late',result={},evidence_refs=[],artifacts=[]))
    assert service.store.heartbeat(company)


def test_revised_audience_does_not_retain_old_financial_result_access(setup_workflow):
    _,service,operator,auditor,request=setup_workflow
    run=create(setup_workflow)
    data=request.model_dump(exclude={'template','project_id'})|{'output_audience':['operator'],'expected_revision':run.revision}
    revised=service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    current=service.store.node('WorkflowRun',run.id)
    assert current['output_audience']==['operator']
    auditor_view=service.get_run(auditor,revised.id)
    assert all('result' not in s for s in auditor_view.steps)


def test_revoked_source_permission_fences_finance_commit(setup_workflow):
    db,service,_,auditor,_=setup_workflow
    run=create(setup_workflow)
    run=service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    service.store.claim_step('company',run.id)
    lease=service.store.claim_step('finance',run.id)
    db.query("MATCH (:Approval)-[permit:PERMITS_SOURCE]->(:SourceVersion {id:'invoice:1'}) DELETE permit")
    assert not service.store.heartbeat(lease)
    assert not service.store.commit_step(lease,StepEffects(effect_key='revoked-source',result={},evidence_refs=[],artifacts=[]))


def test_source_invalidation_replay_does_not_refence_or_duplicate_event(setup_workflow):
    db,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    replace(db,'invoice')
    first=service.store.invalidate_source('invoice','invoice:2')
    snapshot=service.get_run(operator,run.id)
    fences=db.query('MATCH (s:WorkflowStep {run_id:$id}) RETURN s.id,s.fence ORDER BY s.id',{'id':run.id})
    assert service.store.invalidate_source('invoice','invoice:2')==first==[run.id]
    assert service.get_run(operator,run.id).revision==snapshot.revision
    assert db.query('MATCH (s:WorkflowStep {run_id:$id}) RETURN s.id,s.fence ORDER BY s.id',{'id':run.id})==fences
    assert db.query("MATCH (e:RunEvent {run_id:$id,kind:'source_invalidated'}) RETURN count(e)",{'id':run.id})==[[1]]


def test_invalidation_marks_existing_case_revision_historical(setup_workflow):
    db,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    db.query("CREATE (c:ExceptionCase {id:'case',run_id:$run,current_revision_id:'case-rev',classification:'finance',workspace_id:'meridian',output_audience:['operator']}), "
             "(revision:CaseRevision {id:'case-rev',case_id:'case',payload_json:'{}'}), (revision)-[:VERSION_OF]->(c)",{'run':run.id})
    replace(db,'invoice')
    service.store.invalidate_source('invoice','invoice:2')
    assert service.get_case(operator,'case')['stale'] is True
    assert db.query("MATCH (c:CaseRevision {id:'case-rev'}) RETURN c.stale")==[[True]]


def test_completed_company_work_from_second_generation_is_reused_in_third(setup_workflow):
    db,service,operator,_,request=setup_workflow
    run=create(setup_workflow)
    brief=replace(db,'brief')
    data=request.model_dump(exclude={'template','project_id'})|{'context':[brief],'expected_revision':run.revision}
    second=service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    lease=service.store.claim_step('company',run.id)
    assert service.store.commit_step(lease,StepEffects(effect_key='second-company',result={'summary':'Corrected company brief'},evidence_refs=[],artifacts=[]))
    invoice=replace(db,'invoice')
    third_data=data|{'invoice':invoice,'expected_revision':service.get_run(operator,run.id).revision}
    third=service.revise(operator,run.id,RunRevision(**third_data),str(uuid4()))
    assert by_key(third)['company_context']['id']==by_key(second)['company_context']['id']
    assert by_key(third)['company_context']['result']=={'summary':'Corrected company brief'}


@pytest.mark.parametrize('completed',[False,True])
def test_no_op_revision_preserves_current_plan_approvals_and_outputs(setup_workflow,completed):
    from relay.access import AccessError
    db,service,operator,auditor,request=setup_workflow
    run=create(setup_workflow)
    if completed:
        run=service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
        for index in range(6):
            lease=service.store.claim_step('worker',run.id)
            assert lease is not None
            assert service.store.commit_step(lease,StepEffects(effect_key='complete:'+str(index),result={},evidence_refs=[],artifacts=[]))
        run=service.get_run(operator,run.id)
        assert run.status=='completed'
    db.query("CREATE (:Artifact {id:'preserved-output',run_id:$id,workspace_id:'meridian',classification:'finance',output_audience:['operator'],stale:false})",{'id':run.id})
    before=db.query('MATCH (p:WorkflowPlan),(a:Approval),(e:RunEvent) RETURN count(DISTINCT p),count(DISTINCT a),count(DISTINCT e)')
    # Audience order has no authorization meaning; the stored plan is canonical.
    data=request.model_dump(exclude={'template','project_id'})|{'expected_revision':run.revision,'output_audience':list(reversed(request.output_audience))}
    with pytest.raises(AccessError,match='No changes') as exc:
        service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert exc.value.status_code==409
    after=service.get_run(operator,run.id)
    assert (after.current_plan_id,after.generation,after.revision,after.status)==(run.current_plan_id,run.generation,run.revision,run.status)
    assert db.query('MATCH (p:WorkflowPlan),(a:Approval),(e:RunEvent) RETURN count(DISTINCT p),count(DISTINCT a),count(DISTINCT e)')==before
    assert db.query("MATCH (a:Artifact {id:'preserved-output'}) RETURN a.stale")==[[False]]


def test_same_inputs_can_be_reapproved_after_policy_replacement(setup_workflow):
    db,service,operator,_,request=setup_workflow
    run=create(setup_workflow)
    db.query("MATCH (d:Department {id:'finance'}) CREATE (p:Policy {id:'finance:2',department_id:'finance',version:2,reviewer_id:'auditor',allowed_tools:['finance_parse','invoice_compare','publish_report','upsert_case','archive_run'],approval_ttl_seconds:86400}), (d)-[:GOVERNED_BY]->(p) SET d.current_policy_id=p.id")
    data=request.model_dump(exclude={'template','project_id'})|{'expected_revision':run.revision}
    revised=service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert revised.generation==run.generation+1
    assert revised.approvals[0]['policy_id']=='finance:2'
    assert revised.approvals[0]['status']=='pending'


def test_revision_scope_preserves_existing_automation_preference(setup_workflow):
    _,service,operator,_,request=setup_workflow
    run=create(setup_workflow)
    assert service.get_run(operator,run.id).approvals[0]['scope']['automation']==request.automation


@pytest.mark.parametrize('state',['expired','rejected','changes_requested','unassigned'])
def test_unfinished_same_input_revision_can_renew_unusable_authority(setup_workflow,state):
    db,service,operator,_,request=setup_workflow
    run=create(setup_workflow)
    company=service.store.claim_step('company',run.id)
    assert service.store.commit_step(company,StepEffects(effect_key='safe-company',result={'summary':'Company complete'},evidence_refs=[],artifacts=[]))
    if state=='expired':
        db.query("MATCH (a:Approval {run_id:$run}) SET a.expires_at=0",{'run':run.id})
    elif state=='unassigned':
        db.query("MATCH (a:Approval {run_id:$run}) SET a.reviewer_id=''",{'run':run.id})
    else:
        db.query('MATCH (a:Approval {run_id:$run}) SET a.status=$status',{'run':run.id,'status':state})
    current=service.get_run(operator,run.id)
    data=request.model_dump(exclude={'template','project_id'})|{'expected_revision':current.revision}
    revised=service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert revised.generation==current.generation+1
    assert by_key(revised)['company_context']['id']==company.step_id
    assert by_key(revised)['company_context']['status']=='completed'
    assert by_key(revised)['finance_parse']['id']!=by_key(current)['finance_parse']['id']
    assert revised.approvals[0]['status']=='pending'
    assert revised.approvals[0]['reviewer_id']=='auditor'


def test_expired_authority_renewal_reexecutes_previously_published_outputs(setup_workflow):
    db,service,operator,auditor,request=setup_workflow
    run=create(setup_workflow)
    run=service.decide(auditor,run.approvals[0]['id'],decision(run),str(uuid4()))
    for index in range(4):
        lease=service.store.claim_step('worker',run.id)
        assert service.store.commit_step(lease,StepEffects(effect_key='before-renewal:'+str(index),result={},evidence_refs=[],artifacts=[]))
    current=service.get_run(operator,run.id)
    assert by_key(current)['publish_report']['status']=='completed'
    db.query("MATCH (a:Approval {run_id:$run,gate_kind:'finance_access'}) SET a.expires_at=0",{'run':run.id})
    data=request.model_dump(exclude={'template','project_id'})|{'expected_revision':current.revision}
    revised=service.revise(operator,run.id,RunRevision(**data),str(uuid4()))
    assert by_key(revised)['publish_report']['id']!=by_key(current)['publish_report']['id']
    assert by_key(revised)['publish_report']['status']=='waiting_approval'
    assert by_key(revised)['company_context']['id']==by_key(current)['company_context']['id']


def test_plan_review_routing_only_targets_real_assigned_member(setup_workflow):
    db,_,_,_,_=setup_workflow
    run=create(setup_workflow)
    assert db.query('MATCH (a:Approval {run_id:$run})-[:ASSIGNED_TO]->(reviewer) RETURN reviewer.id',{'run':run.id})==[['auditor']]
    assert db.query('MATCH (n) WHERE size(labels(n))=0 RETURN count(n)')==[[0]]
