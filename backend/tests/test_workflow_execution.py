"""Bounded tools operate on authorized exact inputs and record actual outcomes."""
import importlib
from decimal import Decimal
from pathlib import Path

import pytest

from relay.parsers import ParsedDocument, ParsedRow, ParsedTable
from relay.workflow_models import StepLease

# These use actual FalkorDB leases/receipts and the isolated parser process.
from test_workflow_plans import setup_workflow as setup_workflow
from io import BytesIO
from uuid import uuid4
from relay.storage import BlobStore
from relay.source_store import SourceStore
from relay.sources import SourceService
from relay.workflow_models import ApprovalDecision


def tool_module():
    assert importlib.util.find_spec('relay.workflow_tools'), 'bounded workflow tools missing'
    return importlib.import_module('relay.workflow_tools')


def lease():
    return StepLease(step_id='step',run_id='run',plan_id='plan',generation=1,fence=1,
                     worker_id='worker',lease_until='2099-01-01T00:00:00+00:00')


def context(tool, prerequisites=None, existing_case=None):
    return {'run':{'id':'run','requester_id':'operator','project_id':'atlas'},
            'plan':{'automation':'auto_permitted','output_audience':['operator']},
            'step':{'id':'step','logical_key':tool,'tool':tool,'tool_version':'1','input_hash':'input',
                    'arguments':{'invoice':{'source_id':'invoice','version_id':'iv'},
                                 'purchase_order':{'source_id':'order','version_id':'ov'}}},
            'prerequisites':prerequisites or [],'case':existing_case}


class Sources:
    def __init__(self):
        self.calls = []
    def parsed_document(self, access, ref):
        self.calls.append((access,ref))
        price = '110' if ref.source_id == 'invoice' else '100'
        return ParsedDocument([],ParsedTable('USD',[ParsedRow('gateway-seat',2,Decimal(price),2)]))
    def detail(self, access, source_id, version_id=None):
        return {'title':source_id,'chunks':[{'id':source_id+'-row','text':'row',
                 'locator':{'row_start':2,'row_end':2}}]}


class Company:
    def get_graph(self, *, access):
        assert access.purpose == 'agent'
        return {'nodes':[{'id':'atlas','label':'Atlas','kind':'project'},
                         {'id':'owner','label':'Taylor','kind':'person'}],
                'edges':[{'source':'atlas','target':'owner','relation':'OWNED_BY'}], 'sources':[]}


@pytest.mark.asyncio
async def test_tools_compare_real_decimal_tables_and_preserve_row_evidence(tmp_path):
    module = tool_module()
    tools = module.WorkflowTools(Sources(), tmp_path, company=Company())
    finance = await tools.execute(lease(), context('finance_parse'))
    assert len(finance.evidence_refs) == 2
    assert all(ref.locator.row_start == 2 for ref in finance.evidence_refs)
    assert all(call[0].run_id == 'run' and call[0].purpose == 'agent' for call in tools.sources.calls)
    compare_context = context('invoice_compare', [{'logical_key':'finance_parse','result':finance.result}])
    compared = await tools.execute(lease(), compare_context)
    assert compared.result['comparison']['invoice_total'] == '220.00'
    assert compared.result['comparison']['order_total'] == '200.00'
    assert compared.result['comparison']['difference'] == '20.00'
    assert len(compared.result['comparison']['findings']) == 1
    assert compared.result['comparison']['findings'][0]['invoice_row'] == 2
    company = await tools.execute(lease(), context('company_context'))
    assert company.result['owner_entity_id'] == 'owner'
    report_context = context('publish_report', [
        {'logical_key':'invoice_compare','result':compared.result},
        {'logical_key':'company_context','result':company.result}])
    report = await tools.execute(lease(), report_context)
    assert len(report.artifacts) == 2
    assert report.result['narrative_mode'] == 'guided'
    case_context = context('upsert_case', [{'logical_key':'invoice_compare','result':compared.result},
                                         {'logical_key':'publish_report','result':report.result}])
    case = await tools.execute(lease(),case_context)
    assert case.case_revision['owner_entity_id'] == 'owner'
    assert case.case_revision['case_id'] == 'case:run'
    assert case.case_revision['launch_blocker'] is False


@pytest.mark.asyncio
async def test_matching_invoice_skips_new_case_but_resolves_existing_case(tmp_path):
    module = tool_module()
    tools = module.WorkflowTools(Sources(), tmp_path)
    comparison = {'currency':'USD','invoice_total':'200.00','order_total':'200.00',
                  'difference':'0.00','findings':[]}
    prerequisites = [{'logical_key':'invoice_compare','result':{'comparison':comparison}}]
    skipped = await tools.execute(lease(),context('upsert_case',prerequisites))
    assert skipped.case_revision is None and skipped.result['outcome'] == 'skipped'
    corrected = await tools.execute(lease(),context('upsert_case',prerequisites,{'id':'case:run'}))
    assert corrected.case_revision['case_id'] == 'case:run'
    assert corrected.case_revision['status'] == 'resolved'


@pytest.mark.asyncio
async def test_unknown_tool_has_no_execution_capability(tmp_path):
    tools = tool_module().WorkflowTools(Sources(),tmp_path)
    with pytest.raises(ValueError, match='Unsupported'):
        await tools.execute(lease(),context('shell'))
    assert not tools.sources.calls


@pytest.mark.asyncio
async def test_company_context_ingests_selected_general_brief_with_exact_citation(tmp_path):
    tools = tool_module().WorkflowTools(Sources(), tmp_path, company=Company())
    selected = context('company_context')
    selected['step']['arguments']['context'] = [{'source_id':'brief','version_id':'bv'}]
    effects = await tools.execute(lease(),selected)
    assert [call[1].source_id for call in tools.sources.calls] == ['brief']
    assert effects.evidence_refs[0].version_id == 'bv'
    assert effects.result['evidence_refs'][0]['chunk_id'] == 'brief-row'




def execution_services(setup_workflow, tmp_path):
    from relay.workflow_tools import WorkflowTools
    from relay.workflow_engine import WorkflowEngine
    db, service, operator, auditor, request = setup_workflow
    blobs = BlobStore(tmp_path)
    fixtures = Path(__file__).parent/'fixtures'/'invoices'
    for source, mime, data in [
        ('invoice','text/csv',(fixtures/'invoice.csv').read_bytes()),
        ('po','text/csv',(fixtures/'purchase-order.csv').read_bytes()),
        ('brief','text/plain',b'Atlas depends on gateway. No launch gating policy is recorded.')]:
        blob = blobs.put_stream(BytesIO(data),mime=mime)
        db.query('MATCH (s:Source {id:$source}),(v:SourceVersion {id:$version}) '
                 'SET s.title=$source,s.type=$mime,s.author="operator",s.updated_at="2026-10-17", '
                 'v.blob_key=$blob,v.byte_size=$size,v.mime=$mime,v.content_hash=$hash,v.storage_kind="blob",v.number=1',
                 {'source':source,'version':source+':1','mime':mime,'blob':blob.key,
                  'size':blob.byte_size,'hash':blob.sha256})
    sources = SourceService(SourceStore(db),blobs)
    tools = WorkflowTools(sources,tmp_path/'artifacts')
    return WorkflowEngine(service.store,sources,tools,tmp_path/'checkpoints.sqlite'), tools


def approve_current(service, access, operator, run_id, gate):
    snapshot = service.get_run(operator,run_id)
    approval = next(a for a in snapshot.approvals if a['gate_kind'] == gate and a['status'] == 'pending')
    return service.decide(access,approval['id'],ApprovalDecision(decision='approve',
        expected_revision=snapshot.revision,scope_hash=approval['scope_hash']),str(uuid4()))


@pytest.mark.asyncio
async def test_real_graph_gate_blocks_bytes_then_resumes_to_single_report_and_case(setup_workflow,tmp_path):
    db, service, operator, auditor, request = setup_workflow
    engine, tools = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request,str(uuid4()))
    assert await engine.run_once(run.id)
    assert not await engine.run_once(run.id)
    snapshot = service.get_run(operator,run.id)
    assert next(s for s in snapshot.steps if s['logical_key']=='company_context')['status']=='completed'
    finance_chunks = db.query('MATCH (v:SourceVersion)-[:HAS_CHUNK]->(c:SourceChunk) WHERE v.classification="finance" RETURN count(c)')[0][0]
    assert finance_chunks == 0
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(10):
        if not await engine.run_once(run.id):
            break
    snapshot = service.get_run(operator,run.id)
    assert snapshot.status == 'completed'
    assert len(snapshot.outputs) == 2 and len(snapshot.cases) == 1
    assert db.query('MATCH (e:Execution {run_id:$run}) RETURN count(e)',{'run':run.id})[0][0] == 6
    assert db.query('MATCH (c:ExceptionCase {run_id:$run}) RETURN c.status',{'run':run.id}) == [['open']]
    assert tools.reports.verify({'items':[service.artifact_metadata(operator,item['id']) for item in snapshot.outputs]})
    assert not await engine.run_once(run.id)


@pytest.mark.asyncio
async def test_real_graph_strict_report_and_case_each_wait_for_exact_requester_preview(setup_workflow,tmp_path):
    db, service, operator, auditor, request = setup_workflow
    engine, _ = execution_services(setup_workflow,tmp_path)
    request = request.model_copy(update={'automation':'review_changes'})
    run = service.create_run(operator,request,str(uuid4()))
    await engine.run_once(run.id)
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(6):
        if not await engine.run_once(run.id):
            break
    assert not service.get_run(operator,run.id).outputs
    approve_current(service,operator,operator,run.id,'report_write')
    for _ in range(6):
        if not await engine.run_once(run.id):
            break
    snapshot = service.get_run(operator,run.id)
    assert len(snapshot.outputs)==2 and not snapshot.cases
    approve_current(service,operator,operator,run.id,'case_write')
    for _ in range(6):
        if not await engine.run_once(run.id):
            break
    snapshot = service.get_run(operator,run.id)
    assert snapshot.status=='completed' and len(snapshot.cases)==1
    assert db.query('MATCH (e:Execution {run_id:$run}) RETURN count(e)',{'run':run.id})[0][0]==6


@pytest.mark.asyncio
async def test_corrected_source_reuses_company_and_resolves_existing_case(setup_workflow,tmp_path):
    from relay.workflow_models import RunRevision
    db, service, operator, auditor, request = setup_workflow
    engine, tools = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request,str(uuid4()))
    await engine.run_once(run.id)
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(8):
        if not await engine.run_once(run.id):
            break
    original = service.get_run(operator,run.id)
    original_company = next(s['id'] for s in original.steps if s['logical_key']=='company_context')
    corrected = tools.sources.blobs.put_stream(BytesIO((Path(__file__).parent/'fixtures'/'invoices'/'purchase-order.csv').read_bytes()),mime='text/csv')
    version = tools.sources.store.add_version(operator,'invoice',1,corrected)
    current = service.get_run(operator,run.id)
    revision = RunRevision(expected_revision=current.revision,invoice=version.ref,
                           purchase_order=request.purchase_order,context=request.context,
                           automation=request.automation,output_audience=request.output_audience)
    revised = service.revise(operator,run.id,revision,str(uuid4()))
    assert next(s['id'] for s in revised.steps if s['logical_key']=='company_context') == original_company
    assert not await engine.run_once(run.id)
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(8):
        if not await engine.run_once(run.id):
            break
    completed = service.get_run(operator,run.id)
    assert completed.status=='completed'
    assert db.query('MATCH (c:ExceptionCase {run_id:$run}) RETURN c.id,c.status',{'run':run.id}) == [['case:'+run.id,'resolved']]
    assert db.query('MATCH (cr:CaseRevision {case_id:$case}) RETURN count(cr)',{'case':'case:'+run.id})[0][0] == 2
    assert len(completed.outputs) == 4
    assert sum(bool(item['stale']) for item in completed.outputs) == 2


@pytest.mark.asyncio
async def test_live_model_transient_failure_has_two_retries_and_never_guided_fallback(tmp_path):
    from relay.llm import ModelError
    class UnavailableModel:
        def __init__(self):
            self.calls=0
        async def generate(self,question,context):
            self.calls+=1
            raise ModelError('The model provider is unavailable or timed out. Please retry.')
    model = UnavailableModel()
    tools = tool_module().WorkflowTools(Sources(),tmp_path,model_client=model)
    with pytest.raises(ModelError):
        await tools._narrative(lease(),{'findings':[]},{},[])
    assert model.calls==3
    assert not list(tmp_path.glob('*.html'))


@pytest.mark.asyncio
async def test_indexed_graph_background_dispatch_completes_company_while_finance_waits(setup_workflow,tmp_path):
    import asyncio
    db, service, operator, auditor, request = setup_workflow
    # Migration installs this index. Indexless fixtures hid an optional-null
    # reviewer lookup bug in the pinned FalkorDB query planner.
    db.query('CREATE INDEX FOR (member:Member) ON (member.id)')
    engine, _ = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request,str(uuid4()))
    await engine.start()
    try:
        for _ in range(30):
            snapshot = await asyncio.to_thread(service.get_run,operator,run.id)
            company = next(step for step in snapshot.steps if step['logical_key']=='company_context')
            if company['status'] in {'completed','failed'}:
                break
            await asyncio.sleep(.05)
        assert company['status']=='completed', engine.last_error
        assert next(step for step in snapshot.steps if step['logical_key']=='finance_parse')['status']=='waiting_approval'
        assert db.query('MATCH(v:SourceVersion)-[:HAS_CHUNK]->(c:SourceChunk) WHERE v.classification="finance" RETURN count(c)') == [[0]]
    finally:
        await engine.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('reviewer_route',['missing','forged'])
async def test_indexed_strict_preview_missing_or_forged_reviewer_route_cannot_claim(setup_workflow,tmp_path,reviewer_route):
    db, service, operator, auditor, request = setup_workflow
    db.query('CREATE INDEX FOR (member:Member) ON (member.id)')
    engine, _ = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request.model_copy(update={'automation':'review_changes'}),str(uuid4()))
    await engine.run_once(run.id)
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(5):
        if not await engine.run_once(run.id):
            break
    approve_current(service,operator,operator,run.id,'report_write')
    db.query('MATCH (a:Approval {run_id:$run,gate_kind:"report_write"})-[edge:ASSIGNED_TO]->() DELETE edge',{'run':run.id})
    if reviewer_route=='forged':
        db.query('MATCH (a:Approval {run_id:$run,gate_kind:"report_write"}),(other:Member {id:"other"}) CREATE (a)-[:ASSIGNED_TO]->(other)',{'run':run.id})
    assert service.store.claim_step('late-worker',run.id) is None
    assert not service.get_run(operator,run.id).outputs
