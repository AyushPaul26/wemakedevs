"""Dispatcher boundary failures must never turn a stale lease into publication."""
import asyncio
import importlib

import pytest

from relay.workflow_models import RecoveryReport, StepEffects, StepLease

from test_workflow_plans import setup_workflow as setup_workflow
from test_workflow_execution import execution_services, approve_current
from uuid import uuid4

def engine_module():
    assert importlib.util.find_spec('relay.workflow_engine'), 'durable dispatcher missing'
    return importlib.import_module('relay.workflow_engine')


class FencedStore:
    """Small authority double; real atomic database guards are tested by store tests."""
    def __init__(self):
        self.valid = True
        self.claimed = False
        self.commits = []
        self.failures = []
        self.heartbeat_calls = 0
        self.context = {'run':{'id':'run','requester_id':'operator'},
                        'plan':{'automation':'auto_permitted'},
                        'step':{'logical_key':'company_context','tool':'company_context','input_hash':'hash'},
                        'prerequisites':[]}
    def claim_step(self, worker_id, run_id=None, now=None):
        if self.claimed or not self.valid:
            return None
        self.claimed = True
        return StepLease(step_id='step',run_id='run',plan_id='plan',generation=1,fence=1,
                         worker_id=worker_id,lease_until='2099-01-01T00:00:00+00:00')
    def step_context(self, lease):
        return self.context if self.valid else None
    def heartbeat(self, lease, now=None):
        self.heartbeat_calls += 1
        return self.valid
    def commit_step(self, lease, effects, now=None):
        if not self.valid:
            return False
        self.commits.append(effects)
        return True
    def fail_step(self, lease, error, now=None):
        self.failures.append(str(error))
        return self.valid
    def recover(self):
        return RecoveryReport(requeued=['step'],waiting=[],reconciled=[],failed=[])


class Tools:
    validate = None
    def __init__(self, store, invalidate=False, fail=False):
        self.store, self.invalidate, self.fail = store,invalidate,fail
        self.calls = 0
    async def execute(self, lease, context):
        self.calls += 1
        if self.invalidate:
            self.store.valid = False
        if self.fail:
            raise RuntimeError('secret-provider-body')
        return StepEffects(effect_key='effect',result={'outcome':'completed'},evidence_refs=[],artifacts=[])


@pytest.mark.asyncio
async def test_successful_execution_has_metadata_checkpoint_and_one_authoritative_commit(tmp_path):
    store = FencedStore()
    tools = Tools(store)
    engine = engine_module().WorkflowEngine(store,None,tools,tmp_path/'checkpoints.sqlite')
    assert await engine.run_once()
    assert not await engine.run_once()
    assert len(store.commits) == 1 and tools.calls == 1
    assert store.heartbeat_calls >= 2
    assert (tmp_path/'checkpoints.sqlite').exists()


@pytest.mark.asyncio
async def test_cancellation_during_tool_discards_late_effects(tmp_path):
    store = FencedStore()
    engine = engine_module().WorkflowEngine(store,None,Tools(store,invalidate=True),tmp_path/'c.sqlite')
    assert await engine.run_once()
    assert not store.commits


@pytest.mark.asyncio
async def test_tool_failure_is_visible_and_does_not_fake_success(tmp_path):
    store = FencedStore()
    engine = engine_module().WorkflowEngine(store,None,Tools(store,fail=True),tmp_path/'c.sqlite')
    await engine.run_once()
    assert not store.commits and store.failures
    assert 'secret-provider-body' not in store.failures[0]


@pytest.mark.asyncio
async def test_start_recovers_graph_work_and_stop_is_idempotent(tmp_path):
    store = FencedStore()
    engine = engine_module().WorkflowEngine(store,None,Tools(store),tmp_path/'c.sqlite',poll_interval=0.01)
    recovery = await engine.recover()
    assert recovery.requeued == ['step']
    await engine.start()
    for _ in range(100):
        if store.commits:
            break
        await asyncio.sleep(0.01)
    await engine.stop()
    await engine.stop()
    assert len(store.commits) == 1





@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',['finance_parse','invoice_compare','publish_report'])
async def test_real_graph_restart_after_tool_before_commit_reuses_one_logical_effect(setup_workflow,tmp_path,boundary):
    module = engine_module()
    db, service, operator, auditor, request = setup_workflow
    engine, tools = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request,str(uuid4()))
    await engine.run_once(run.id)
    approve_current(service,auditor,operator,run.id,'finance_access')
    actual_execute = tools.execute
    interrupted = []
    async def crashing_execute(lease, context):
        effects = await actual_execute(lease,context)
        if context['step']['logical_key'] == boundary and not interrupted:
            interrupted.append(lease)
            execution_task.cancel()
            await asyncio.sleep(0)
        return effects
    tools.execute = crashing_execute
    with pytest.raises(asyncio.CancelledError):
        for _ in range(6):
            execution_task = asyncio.create_task(engine.run_once(run.id))
            await execution_task
    assert interrupted
    assert db.query('MATCH (s:WorkflowStep {id:$id}) RETURN s.status',{'id':interrupted[0].step_id}) == [['running']]
    # Simulate process death followed by lease expiry without waiting 120 seconds.
    db.query('MATCH (s:WorkflowStep {id:$id}) SET s.lease_until=0',{'id':interrupted[0].step_id})
    replacement = module.WorkflowEngine(service.store,engine.sources,tools,tmp_path/'checkpoints.sqlite')
    recovered = await replacement.recover()
    assert interrupted[0].step_id in recovered.requeued
    for _ in range(8):
        if not await replacement.run_once(run.id):
            break
    assert service.get_run(operator,run.id).status == 'completed'
    assert db.query('MATCH (e:Execution {run_id:$run}) RETURN count(e)',{'run':run.id})[0][0] == 6
    assert db.query('MATCH (a:Artifact {run_id:$run}) RETURN count(a)',{'run':run.id})[0][0] == 2
    assert db.query('MATCH (c:ExceptionCase {run_id:$run}) RETURN count(c)',{'run':run.id})[0][0] == 1
    assert len(list((tmp_path/'artifacts').glob('*.html'))) == 1
    assert len(list((tmp_path/'artifacts').glob('*.csv'))) == 1


@pytest.mark.asyncio
async def test_real_graph_uncertain_commit_acknowledgement_does_not_repeat_receipt(setup_workflow,tmp_path):
    db, service, operator, auditor, request = setup_workflow
    engine, _ = execution_services(setup_workflow,tmp_path)
    run = service.create_run(operator,request,str(uuid4()))
    actual_commit = service.store.commit_step
    interrupted = []
    def uncertain_commit(lease,effects,now=None):
        result = actual_commit(lease,effects,now)
        if not interrupted:
            interrupted.append(lease.step_id)
            raise ConnectionError('Commit acknowledgement lost')
        return result
    service.store.commit_step = uncertain_commit
    await engine.run_once(run.id)
    assert service.store.node('WorkflowStep',interrupted[0])['status']=='completed'
    await engine.recover()
    approve_current(service,auditor,operator,run.id,'finance_access')
    for _ in range(8):
        if not await engine.run_once(run.id):
            break
    assert service.get_run(operator,run.id).status=='completed'
    assert db.query('MATCH (e:Execution {run_id:$run}) RETURN count(e)',{'run':run.id})[0][0]==6
