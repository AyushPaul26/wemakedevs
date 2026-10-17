"""Authenticated HTTP boundary for persisted workflows and approval decisions."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from .access import AccessContext, AccessError
from .auth_routes import session_dependency
from .workflow_models import ApprovalDecision, RunCreate, RunRevision


class RunControl(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)


def create_workflow_router(service, auth_service):
    router = APIRouter(prefix='/api',tags=['workflows'])
    current_session = session_dependency(auth_service)

    def invoke(call):
        try:
            return call()
        except AccessError as exc:
            raise HTTPException(exc.status_code,str(exc)) from None
        except RedisError:
            raise HTTPException(503,'Workflow storage is unavailable') from None

    def context(session):
        return AccessContext(session.member.id)

    @router.post('/workflow-runs',status_code=202)
    def create_run(body:RunCreate,session=Depends(current_session),key:str=Header(alias='Idempotency-Key')):
        return invoke(lambda:service.create_run(context(session),body,key))

    @router.get('/workflow-runs')
    def list_runs(cursor:str|None=None,session=Depends(current_session)):
        return invoke(lambda:service.list_runs(context(session),cursor))

    @router.get('/workflow-runs/{run_id}')
    def get_run(run_id:str,session=Depends(current_session)):
        return invoke(lambda:service.get_run(context(session),run_id))

    @router.post('/workflow-runs/{run_id}/revise')
    def revise(run_id:str,body:RunRevision,session=Depends(current_session),key:str=Header(alias='Idempotency-Key')):
        return invoke(lambda:service.revise(context(session),run_id,body,key))

    @router.post('/workflow-runs/{run_id}/cancel')
    def cancel(run_id:str,body:RunControl,session=Depends(current_session),key:str=Header(alias='Idempotency-Key')):
        return invoke(lambda:service.cancel(context(session),run_id,body.expected_revision,key))

    @router.post('/workflow-runs/{run_id}/retry')
    def retry(run_id:str,body:RunControl,session=Depends(current_session),key:str=Header(alias='Idempotency-Key')):
        return invoke(lambda:service.retry(context(session),run_id,body.expected_revision,key))

    @router.get('/workflow-runs/{run_id}/timeline')
    def timeline(run_id:str,cursor:str|None=None,session=Depends(current_session)):
        return invoke(lambda:service.timeline(context(session),run_id,cursor))

    @router.get('/approvals')
    def approvals(cursor:str|None=None,session=Depends(current_session)):
        return invoke(lambda:service.list_approvals(context(session),cursor))

    @router.post('/approvals/{approval_id}/decision')
    def decide(approval_id:str,body:ApprovalDecision,session=Depends(current_session),key:str=Header(alias='Idempotency-Key')):
        return invoke(lambda:service.decide(context(session),approval_id,body,key))

    return router
