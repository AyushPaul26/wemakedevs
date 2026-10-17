"""Real graph tests for fixed branching plans; every graph is disposable."""
from uuid import uuid4

from falkordb import FalkorDB
import pytest

from relay.access import AccessContext, AccessError
from relay.workflow_models import RunCreate


class Database:
    def __init__(self):
        self.graph = FalkorDB(host='127.0.0.1', port=6379).select_graph('relay_test_' + uuid4().hex)

    def query(self, statement, params=None):
        return self.graph.query(statement, params=params).result_set


@pytest.fixture
def setup_workflow():
    from relay.workflow_service import WorkflowService
    db = Database()
    db.query("CREATE (:Workspace {id:'meridian',maintenance:false,execution_enabled:true}), (:Member {id:'operator',workspace_id:'meridian',role:'operator',active:true}), "
             "(:Member {id:'auditor',workspace_id:'meridian',role:'finance_auditor',active:true}), "
             "(:Member {id:'other',workspace_id:'meridian',role:'operator',active:true}), "
             "(:Entity {id:'atlas',workspace_id:'meridian',kind:'project',classification:'workspace'}), "
             "(d:Department {id:'finance',workspace_id:'meridian',current_policy_id:'finance:1'}), "
             "(p:Policy {id:'finance:1',department_id:'finance',version:1,reviewer_id:'auditor', "
             "allowed_tools:['company_context','finance_parse','invoice_compare','publish_report','upsert_case','archive_run'],approval_ttl_seconds:86400}), "
             "(d)-[:GOVERNED_BY]->(p)")
    db.query("MATCH (m:Member {id:'auditor'}),(d:Department {id:'finance'}) CREATE (m)-[:MEMBER_OF]->(d)")
    for source, classification, department in [('invoice', 'finance', 'finance'), ('po', 'finance', 'finance'), ('brief', 'workspace', 'general')]:
        db.query("CREATE (s:Source {id:$source,workspace_id:'meridian',current_version_id:$version, "
                 "classification:$classification,department_id:$department,uploader_id:'operator',revision:1}), "
                 "(v:SourceVersion {id:$version,source_id:$source,workspace_id:'meridian',classification:$classification, "
                 "department_id:$department,uploader_id:'operator',processing_status:'pending'}), (s)-[:HAS_VERSION]->(v)",
                 {'source':source,'version':source+':1','classification':classification,'department':department})
    service = WorkflowService(db)
    request = RunCreate(template='invoice_review', project_id='atlas', invoice={'source_id':'invoice','version_id':'invoice:1'},
                        purchase_order={'source_id':'po','version_id':'po:1'},context=[{'source_id':'brief','version_id':'brief:1'}],
                        automation='auto_permitted',output_audience=['operator','auditor'])
    try:
        yield db, service, AccessContext('operator'), AccessContext('auditor'), request
    finally:
        assert db.graph.name.startswith('relay_test_')
        db.graph.delete()


def create(setup):
    db, service, operator, auditor, request = setup
    return service.create_run(operator, request, str(uuid4()))


def by_key(run):
    return {s['logical_key']:s for s in run.steps}


def test_company_lane_is_runnable_while_finance_waits(setup_workflow):
    db, service, operator, _, _ = setup_workflow
    run = create(setup_workflow)
    steps = by_key(run)
    assert steps['company_context']['status'] == 'queued'
    assert steps['finance_parse']['status'] == 'waiting_approval'
    assert steps['company_context']['depends_on'] == []
    assert steps['finance_parse']['depends_on'] == []
    lease = service.store.claim_step('worker', run.id)
    assert lease.step_id == steps['company_context']['id']
    assert service.store.claim_step('worker-2', run.id) is None
    assert db.query('MATCH (v:SourceVersion) RETURN v.processing_status') == [['pending'],['pending'],['pending']]
    assert service.get_run(operator,run.id).id == run.id


def test_create_is_idempotent_per_member_and_input(setup_workflow):
    _, service, operator, _, request = setup_workflow
    key = str(uuid4())
    first = service.create_run(operator,request,key)
    assert service.create_run(operator,request,key).id == first.id
    changed = request.model_copy(update={'automation':'review_changes'})
    with pytest.raises(AccessError) as exc:
        service.create_run(operator,changed,key)
    assert exc.value.status_code == 409


def test_rejects_general_finance_inputs_and_unknown_project(setup_workflow):
    _, service, operator, _, request = setup_workflow
    for bad in [request.model_copy(update={'invoice':request.context[0]}),request.model_copy(update={'project_id':'missing'})]:
        with pytest.raises(AccessError):
            service.create_run(operator,bad,str(uuid4()))


def test_missing_reviewer_is_visible_and_finance_stays_blocked(setup_workflow):
    db, _, _, _, _ = setup_workflow
    db.query("MATCH (m:Member {id:'auditor'}) SET m.active=false")
    run = create(setup_workflow)
    assert run.approvals[0]['waiting_reason']
    assert by_key(run)['finance_parse']['status'] == 'waiting_approval'


def test_public_snapshot_omits_worker_and_private_arguments(setup_workflow):
    _, service, operator, _, _ = setup_workflow
    run = create(setup_workflow)
    service.store.claim_step('secret-worker',run.id)
    rendered = service.get_run(operator,run.id).model_dump_json()
    assert 'secret-worker' not in rendered
    assert 'arguments_json' not in rendered
    assert 'lease_owner' not in rendered


def test_claim_advances_snapshot_revision_and_started_event(setup_workflow):
    _,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    service.store.claim_step('worker',run.id)
    updated=service.get_run(operator,run.id)
    assert updated.revision>run.revision
    assert service.timeline(operator,run.id).items[-1]['kind']=='step_started'


def test_artifact_and_case_metadata_require_run_audience(setup_workflow):
    db,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    db.query("CREATE (:Artifact {id:'report',run_id:$run,workspace_id:'meridian',classification:'finance',output_audience:['operator'],blob_key:'private-key',kind:'report'}), "
             "(:ExceptionCase {id:'case',run_id:$run,workspace_id:'meridian',classification:'finance',output_audience:['operator'],current_revision_id:'revision'}), "
             "(:CaseRevision {id:'revision',case_id:'case',payload_json:'{\"findings\":[]}'})",{'run':run.id})
    assert service.artifact_metadata(operator,'report')['blob_key']=='private-key'
    assert service.get_case(operator,'case')['current_revision']['findings']==[]
    assert service.list_cases(operator)['items'][0]['id']=='case'
    with pytest.raises(AccessError):
        service.artifact_metadata(AccessContext('other'),'report')
    with pytest.raises(AccessError):
        service.get_case(AccessContext('other'),'case')


def test_cancel_key_replay_is_idempotent(setup_workflow):
    _,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    key=str(uuid4())
    first=service.cancel(operator,run.id,run.revision,key)
    assert service.cancel(operator,run.id,run.revision,key).revision==first.revision


def test_commit_rejects_fabricated_or_out_of_scope_evidence(setup_workflow):
    from relay.workflow_models import StepEffects
    db,service,_,_,_=setup_workflow
    run=create(setup_workflow)
    lease=service.store.claim_step('worker',run.id)
    forged={'source_id':'brief','version_id':'brief:1','chunk_id':'fabricated','locator':{'paragraph':1},'title':'Brief'}
    assert not service.store.commit_step(lease,StepEffects(effect_key='forged',result={},evidence_refs=[forged],artifacts=[]))
    db.query("MATCH (v:SourceVersion {id:'brief:1'}) CREATE (c:SourceChunk {id:'real',version_id:v.id,text:'General company context',locator_json:'{\"paragraph\":1}'}), (v)-[:HAS_CHUNK]->(c)")
    actual={**forged,'chunk_id':'real'}
    assert service.store.commit_step(lease,StepEffects(effect_key='actual',result={},evidence_refs=[actual],artifacts=[]))
    snapshot=service.get_run(setup_workflow[2],run.id)
    assert by_key(snapshot)['company_context']['evidence_refs'][0]['chunk_id']=='real'


@pytest.mark.parametrize('flag',['maintenance','execution_enabled'])
def test_workspace_gate_blocks_claim_heartbeat_and_commit(setup_workflow,flag):
    from relay.workflow_models import StepEffects
    db,service,_,_,_=setup_workflow
    run=create(setup_workflow)
    db.query("MERGE (w:Workspace {id:'meridian'}) SET w.maintenance=false,w.execution_enabled=true")
    lease=service.store.claim_step('worker',run.id)
    db.query('MATCH (w:Workspace {id:\'meridian\'}) SET w.'+flag+'=$value',{'value':flag=='maintenance'})
    assert not service.store.heartbeat(lease)
    assert not service.store.commit_step(lease,StepEffects(effect_key='late',result={},evidence_refs=[],artifacts=[]))
    assert service.store.claim_step('other',run.id) is None


def test_snapshot_exposes_actual_sanitized_execution_receipt(setup_workflow):
    from relay.workflow_models import StepEffects
    db,service,operator,_,_=setup_workflow
    run=create(setup_workflow)
    lease=service.store.claim_step('secret-worker',run.id)
    assert service.store.commit_step(lease,StepEffects(effect_key='real-effect',result={'summary':'Real work'},evidence_refs=[],artifacts=[]))
    snapshot=service.get_run(operator,run.id)
    receipt=by_key(snapshot)['company_context']['execution']
    assert receipt['id']==db.query("MATCH (e:Execution {effect_key:'real-effect'}) RETURN e.id")[0][0]
    assert receipt['tool']=='company_context' and receipt['status']=='completed'
    assert receipt['completed_at']
    assert receipt['approval_ids']==[]
    assert 'secret-worker' not in str(receipt)
