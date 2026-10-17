"""Bounded graph-authoritative execution with independent LangGraph checkpoints.

SQLite stores execution metadata only. It cannot authorize a tool or publish an
output: all work must acquire and retain the current graph fencing token.
"""
import asyncio
from contextlib import suppress
import os
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from relay.llm import ModelError
from relay.reports import ReportError
from relay.workflow_models import RecoveryReport, StepEffects


class _LaneState(TypedDict, total=False):
    run_id: str
    step_id: str
    branch: str
    input_hash: str
    fence: int
    outcome: str
    effect_key: str


class WorkflowEngine:
    def __init__(self, store, sources, tools, checkpoint_path, *, poll_interval=0.5):
        self.store, self.sources, self.tools = store, sources, tools
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.checkpoint_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(self.checkpoint_path, 0o600)
        self.worker_id = 'executor:'+uuid4().hex
        self.poll_interval = max(0.01, poll_interval)
        self._signal = asyncio.Event()
        self._dispatcher = None
        self._active = set()
        self._stopping = False
        self.last_error = None
        if getattr(self.tools, 'validate', None) is None:
            self.tools.validate = self.store.heartbeat

    async def recover(self):
        result = await asyncio.to_thread(self.store.recover)
        return result if isinstance(result, RecoveryReport) else RecoveryReport.model_validate(result)

    async def start(self):
        if self._dispatcher and not self._dispatcher.done():
            return
        await self.recover()
        self._stopping = False
        self._dispatcher = asyncio.create_task(self._dispatch(), name='relay-workflow-dispatcher')
        self.wake()

    async def stop(self):
        self._stopping = True
        self._signal.set()
        if self._dispatcher:
            self._dispatcher.cancel()
            with suppress(asyncio.CancelledError):
                await self._dispatcher
            self._dispatcher = None
        tasks = list(self._active)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()

    def wake(self, run_id=None):
        # A hint only: the authoritative ready set is always selected by the graph.
        self._signal.set()

    async def run_once(self, run_id=None):
        lease = await asyncio.to_thread(self.store.claim_step, self.worker_id, run_id=run_id)
        if lease is None:
            return False
        await self._execute(lease)
        return True

    async def _dispatch(self):
        while not self._stopping:
            self._signal.clear()
            try:
                while len(self._active) < 2 and not self._stopping:
                    lease = await asyncio.to_thread(self.store.claim_step, self.worker_id)
                    if lease is None:
                        break
                    task = asyncio.create_task(self._execute(lease), name='relay-step:'+lease.step_id)
                    self._active.add(task)
                    task.add_done_callback(self._finished)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = 'Workflow storage is unavailable; execution will resume after recovery.'
            try:
                await asyncio.wait_for(self._signal.wait(), timeout=self.poll_interval)
            except TimeoutError:
                pass

    def _finished(self, task):
        self._active.discard(task)
        if not task.cancelled():
            # Retrieve an unexpected failure to prevent detached-task exceptions.
            with suppress(Exception):
                task.result()
        self._signal.set()

    async def _heartbeat(self, lease, lost):
        while True:
            await asyncio.sleep(20)
            try:
                valid = await asyncio.to_thread(self.store.heartbeat, lease)
            except Exception:
                valid = False
            if not valid:
                lost.set()
                return

    async def _execute(self, lease):
        lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(lease,lost))
        try:
            if not await asyncio.to_thread(self.store.heartbeat, lease):
                return
            context = await asyncio.to_thread(self.store.step_context, lease)
            if not context:
                return
            logical_key = context['step']['logical_key']
            branch = 'company' if logical_key == 'company_context' else (
                'finance' if logical_key in {'finance_parse','invoice_compare'} else logical_key)

            async def execute_node(state):
                if lost.is_set() or not await asyncio.to_thread(self.store.heartbeat, lease):
                    return {'outcome':'discarded'}
                # Exact reviewed proposals are reused, including live narrative;
                # generating new prose would change what the requester approved.
                preview = context.get('effect_preview')
                effects = (StepEffects.model_validate(preview) if preview else
                           await self.tools.execute(lease, context))
                if effects.artifacts:
                    valid_files = await asyncio.to_thread(self.tools.reports.verify,
                                                          {'items':effects.artifacts})
                    if not valid_files:
                        raise ReportError('A staged output is missing or failed verification')
                if lost.is_set() or not await asyncio.to_thread(self.store.heartbeat, lease):
                    return {'outcome':'discarded'}
                gate = ('report_write' if effects.artifacts else
                        'case_write' if effects.case_revision else None)
                if gate and context['plan'].get('automation') == 'review_changes':
                    approval = await asyncio.to_thread(self.store.create_effect_approval, lease,
                                                       effects.model_dump(mode='json'), gate)
                    if not approval or approval.get('status') != 'approved':
                        return {'outcome':'waiting_approval','effect_key':effects.effect_key}
                committed = await asyncio.to_thread(self.store.commit_step, lease, effects)
                return {'outcome':'completed' if committed else 'discarded','effect_key':effects.effect_key}

            # Each branch/fingerprint has its own thread. An unapproved finance
            # branch is never claimed and therefore cannot suspend company work.
            async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                graph = StateGraph(_LaneState)
                graph.add_node('execute',execute_node)
                graph.add_edge(START,'execute')
                graph.add_edge('execute',END)
                compiled = graph.compile(checkpointer=saver)
                thread_id = f'{lease.run_id}/{branch}/{context["step"]["input_hash"]}'
                await compiled.ainvoke({'run_id':lease.run_id,'step_id':lease.step_id,
                    'branch':branch,'input_hash':context['step']['input_hash'],'fence':lease.fence,
                    'outcome':'claimed'}, {'configurable':{'thread_id':thread_id}})
        except asyncio.CancelledError:
            # A cancelled executor leaves its graph lease recoverable, and cannot
            # publish when a background parser thread eventually returns.
            raise
        except Exception as exc:
            error = ('Model execution failed; manual retry is available.' if isinstance(exc,ModelError)
                     else 'Tool execution failed; manual retry is available.')
            with suppress(Exception):
                await asyncio.to_thread(self.store.fail_step, lease, error)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
