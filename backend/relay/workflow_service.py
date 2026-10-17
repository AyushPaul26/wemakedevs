"""Validated fixed-template proposals and filtered member-facing workflow views."""
import base64
import json
import time
from uuid import UUID

from .access import AccessError, AccessService
from .workflow_models import EventPage, RunSnapshot
from .workflow_store import WorkflowStore, canonical, fingerprint, stamp


KEYS = ['company_context','finance_parse','invoice_compare','publish_report','upsert_case','archive_run']
DEPENDENCIES = {'company_context':[],'finance_parse':[],'invoice_compare':['finance_parse'],
                'publish_report':['company_context','invoice_compare'],
                'upsert_case':['invoice_compare','publish_report'],'archive_run':['publish_report','upsert_case']}


class WorkflowService:
    def __init__(self, database, access_service=None, *, clock=time.time):
        self.database = database
        self.access = access_service or AccessService(database,clock=clock)
        self.store = WorkflowStore(database,clock=clock)
        self.clock = clock

    def _human(self, access):
        member = self.access.require_member(access)
        if access.purpose!='human':
            raise AccessError('Human session required',403)
        return member

    def _mutation(self, access, operation, key, body):
        self._human(access)
        try:
            normalized = str(UUID(key))
        except (ValueError,TypeError,AttributeError):
            raise AccessError('Idempotency-Key must be a UUID',422) from None
        mutation_id = fingerprint([access.member_id,operation,normalized])
        request_hash = fingerprint(body)
        existing = self.store.mutation(mutation_id)
        if existing and existing['request_hash']!=request_hash:
            raise AccessError('Idempotency key has different input',409)
        return mutation_id,request_hash,existing

    def _validate_inputs(self, access, request, project_id):
        if request.automation=='review_changes' and access.member_id not in request.output_audience:
            raise AccessError('Review each change requires the requester in the output audience',422)
        self.access.require(access,'read',project_id)
        project = self.database.query('MATCH (e:Entity {id:$id}) WHERE e.workspace_id=$workspace RETURN e.kind',
                                      {'id':project_id,'workspace':access.workspace_id})
        if not project or project[0][0]!='project':
            raise AccessError('Project not found',404)
        refs = [request.invoice,request.purchase_order,*request.context]
        if len({ref.source_id for ref in refs})!=len(refs):
            raise AccessError('Select each file once',422)
        for index,ref in enumerate(refs):
            self.access.require(access,'read',ref.source_id)
            rows = self.database.query(
                'MATCH (s:Source {id:$source})-[:HAS_VERSION]->(v:SourceVersion {id:$version}) '
                'WHERE s.workspace_id=$workspace AND v.workspace_id=$workspace RETURN properties(s),properties(v)',
                {'source':ref.source_id,'version':ref.version_id,'workspace':access.workspace_id})
            if not rows:
                raise AccessError()
            source,version=rows[0]
            if source.get('current_version_id')!=ref.version_id:
                raise AccessError('Selected version is no longer current',409)
            if index<2 and (source.get('classification')!='finance' or version.get('classification')!='finance'
                            or source.get('department_id')!='finance' or version.get('department_id')!='finance'):
                raise AccessError('Invoice and purchase order must be Finance files',422)
            if index>=2 and source.get('classification') not in {'workspace','general','public'}:
                raise AccessError('Company context must be general workspace evidence',422)
        policies = self.database.query(
            'MATCH (d:Department {id:\'finance\'})-[:GOVERNED_BY]->(p:Policy) '
            'WHERE d.current_policy_id=p.id RETURN properties(p)')
        if not policies:
            raise AccessError('Finance policy is unavailable',503)
        policy = policies[0][0]
        if any(key not in policy.get('allowed_tools',[]) for key in KEYS[1:]):
            raise AccessError('Finance policy does not permit this template',403)
        reviewers = self.database.query(
            'MATCH (m:Member {id:$id})-[:MEMBER_OF]->(:Department {id:\'finance\'}) '
            'WHERE m.active=true AND m.role=\'finance_auditor\' AND m.workspace_id=$workspace RETURN m.id',
            {'id':policy.get('reviewer_id',''),'workspace':access.workspace_id})
        reviewer_id = reviewers[0][0] if reviewers and reviewers[0][0]!=access.member_id else ''
        # The initial Finance policy permits only requester and assigned reviewer.
        permitted = {access.member_id,policy.get('reviewer_id','')}
        if any(audience not in permitted for audience in request.output_audience):
            raise AccessError('Output audience is outside Finance policy',403)
        for audience in request.output_audience:
            if audience == policy.get('reviewer_id') and not reviewer_id:
                continue
            members=self.database.query('MATCH (m:Member {id:$id}) WHERE m.active=true AND m.workspace_id=$workspace RETURN m.id',
                                        {'id':audience,'workspace':access.workspace_id})
            if not members:
                raise AccessError('Output audience is unavailable',422)
        return policy,reviewer_id

    def _bundle(self,access,request,run_id,project_id,mutation_id,request_hash,*,generation=1,revision=0,old_steps=None):
        policy,reviewer = self._validate_inputs(access,request,project_id)
        now=self.clock()
        timestamp=stamp(now)
        refs=[request.invoice.model_dump(),request.purchase_order.model_dump(),*[r.model_dump() for r in request.context]]
        args={'invoice':request.invoice.model_dump(),'purchase_order':request.purchase_order.model_dump(),
              'context':[r.model_dump() for r in request.context],'project_id':project_id,
              'output_audience':sorted(set(request.output_audience)),'automation':request.automation}
        steps=[]
        ids={}
        for ordinal,key in enumerate(KEYS):
            selected = refs[2:] if key=='company_context' else refs[:2] if key in {'finance_parse','invoice_compare'} else refs
            step_args = {'project_id':project_id,'context':args['context']} if key=='company_context' else args
            signature=fingerprint({'tool':key,'version':'1','arguments':step_args,'dependencies':[ids[k] for k in DEPENDENCIES[key]],
                                   'policy':None if key=='company_context' else policy['id']})
            step_id=fingerprint([run_id,key,signature])
            ids[key]=step_id
            compatible=next((s for s in (old_steps or []) if s['logical_key']==key and s['input_hash']==signature and s['status'] in {'completed','skipped'}),None)
            if compatible:
                step_id=compatible['id']
                ids[key]=step_id
            if old_steps and not compatible:
                # Only completed unaffected work can be shared across generations.
                step_id=fingerprint([step_id,generation])
                ids[key]=step_id
            steps.append(compatible or {'id':step_id,'workspace_id':access.workspace_id,'run_id':run_id,'logical_key':key,
                         'tool':key,'tool_version':'1','input_hash':signature,'arguments_json':canonical(step_args),
                         'version_ids':[r['version_id'] for r in selected], 'ordinal':ordinal,
                         'status':'queued' if key=='company_context' else 'waiting_approval',
                         'attempt':0,'fence':0,'lease_until':0,'created_at':timestamp})
        scope=fingerprint({'run':run_id,'generation':generation,'inputs':refs,'policy':policy['id'],
                           'audience':args['output_audience'],'steps':[(s['id'],s['input_hash']) for s in steps]})
        plan_id=fingerprint([run_id,generation,scope])
        approval={'id':fingerprint([plan_id,'finance_access']),'workspace_id':access.workspace_id,'run_id':run_id,
                  'plan_id':plan_id,'scope_hash':scope,'gate_kind':'finance_access','requester_id':access.member_id,
                  'reviewer_id':reviewer,'policy_id':policy['id'],'status':'pending','expires_at':now+policy.get('approval_ttl_seconds',86400),
                  'output_audience':args['output_audience'],'revision':0,'created_at':timestamp,
                  'waiting_reason':'' if reviewer else ('Finance approval requires a different assigned auditor' if policy.get('reviewer_id')==access.member_id else 'Finance policy has no active assigned auditor')}
        run={'id':run_id,'workspace_id':access.workspace_id,'requester_id':access.member_id,'template':'invoice_review','template_version':'1',
             'project_id':project_id,'current_plan_id':plan_id,'generation':generation,'revision':revision,
             'status':'waiting_approval','output_audience':args['output_audience'],'created_at':timestamp,'updated_at':timestamp}
        plan={'id':plan_id,'workspace_id':access.workspace_id,'run_id':run_id,'number':generation,'scope_hash':scope,
              'automation':request.automation,'policy_id':policy['id'],'output_audience':args['output_audience'],'input_count':len(refs),
              'inputs_json':canonical(args),'created_at':timestamp}
        return {'requester':access.member_id,'project':project_id,'workspace':access.workspace_id,'department':'finance',
                'policy':policy['id'],'reviewer':reviewer,'refs':refs,'version_ids':[r['version_id'] for r in refs],
                'mutation_id':mutation_id,'request_hash':request_hash,'run_id':run_id,'plan_id':plan_id,
                'run_properties':run,'plan_properties':plan,'approval_properties':approval,'timestamp':timestamp,
                'steps':steps,'event_id':fingerprint([mutation_id,'event']),'event_kind':'run_created' if generation==1 else 'plan_revised',
                'dependencies':[{'dependent':ids[key],'prerequisite':ids[dependency]} for key in KEYS for dependency in DEPENDENCIES[key]]}

    def create_run(self,access,request,idempotency_key):
        mutation,request_hash,existing=self._mutation(access,'create',idempotency_key,request.model_dump())
        if existing:
            return self.get_run(access,existing['run_id'])
        run_id='run:'+fingerprint([access.member_id,mutation])
        bundle=self._bundle(access,request,run_id,request.project_id,mutation,request_hash)
        if not self.store.save_plan(bundle):
            prior=self.store.mutation(mutation)
            if not prior or prior['request_hash']!=request_hash:
                raise AccessError('Inputs or policy changed; refresh and try again',409)
        return self.get_run(access,run_id)

    def get_run(self,access,run_id):
        self._human(access)
        self.access.require(access,'read',run_id)
        run=self.store.node('WorkflowRun',run_id)
        plan=self.store.node('WorkflowPlan',run['current_plan_id'])
        steps=[]
        for step in self.store.steps(plan['id']):
            item={key:step[key] for key in ('id','logical_key','tool','tool_version','status','attempt','error') if key in step}
            receipt=None
            if step.get('result_id'):
                receipts=self.database.query('MATCH (e:Execution {id:$id,step_id:$step}) RETURN properties(e)',{'id':step['result_id'],'step':step['id']})
                if receipts:
                    receipt=receipts[0][0]
                    item['execution']={key:receipt[key] for key in ('id','tool','input_hash','approval_ids','status','attempt','fence','started_at') if key in receipt}
                    item['execution']['completed_at']=receipt.get('ended_at')
            item['reused']=self.database.query('MATCH (p:WorkflowPlan)-[:HAS_STEP]->(:WorkflowStep {id:$id}) RETURN count(p)',{'id':step['id']})[0][0]>1
            item['depends_on']=[row[0] for row in self.database.query(
                'MATCH (:WorkflowStep {id:$id})-[:DEPENDS_ON]->(s:WorkflowStep) RETURN s.id',{'id':step['id']})]
            # Derived financial text follows the run's explicit audience.
            if access.member_id in run.get('output_audience',[]) or self.access.require_member(access)['role']=='admin':
                item['result']=json.loads(step.get('result_json','{}'))
                if receipt:
                    item['evidence_refs']=json.loads(receipt.get('evidence_refs_json','[]'))
            steps.append(item)
        approvals=[]
        for a in self.store.approvals(run_id):
            if a['plan_id']!=plan['id']:
                continue
            if access.member_id not in {a['requester_id'],a['reviewer_id']}:
                continue
            approvals.append(self._approval_view(access,a,run['revision'],plan))
        outputs=[row[0] for row in self.database.query('MATCH (a:Artifact {run_id:$id}) RETURN properties(a)',{'id':run_id})]
        outputs=[{k:v for k,v in a.items() if k not in {'blob_key','execution_id'}} for a in outputs if self.access.can_read(access,a['id'])]
        cases=[row[0] for row in self.database.query('MATCH (c:ExceptionCase {run_id:$id}) RETURN properties(c)',{'id':run_id})]
        cases=[c for c in cases if self.access.can_read(access,c['id'])]
        controls=[]
        if access.member_id==run['requester_id']:
            controls=['revise'] if run['status']!='cancelled' else []
            if run['status'] in {'queued','running','waiting_approval','failed'}:
                controls.append('cancel')
            if run['status']=='failed':
                controls.append('retry')
        return RunSnapshot(**{k:run[k] for k in ('id','template','current_plan_id','generation','revision','status','created_at','updated_at')},
                           steps=steps,approvals=approvals,outputs=outputs,cases=cases,allowed_controls=controls)

    def decide(self,access,approval_id,decision,idempotency_key):
        mutation,request_hash,existing=self._mutation(access,'decision:'+approval_id,idempotency_key,decision.model_dump())
        if existing:
            return self.get_run(access,existing['run_id'])
        self.access.require(access,'read',approval_id)
        approval=self.store.node('Approval',approval_id)
        if approval['reviewer_id']!=access.member_id:
            raise AccessError('Only the assigned reviewer can decide',403)
        if not self.store.decide(approval,access,decision,mutation,request_hash):
            existing=self.store.mutation(mutation)
            if not existing or existing['request_hash']!=request_hash:
                raise AccessError('Approval scope or revision changed; refresh the request',409)
        return self.get_run(access,approval['run_id'])

    def revise(self,access,run_id,request,idempotency_key):
        mutation,request_hash,existing=self._mutation(access,'revise:'+run_id,idempotency_key,request.model_dump())
        if existing:
            return self.get_run(access,run_id)
        self.access.require(access,'run_revise',run_id)
        run=self.store.node('WorkflowRun',run_id)
        if run['requester_id']!=access.member_id:
            raise AccessError('Only the requester can revise',403)
        if run['revision']!=request.expected_revision:
            raise AccessError('Run changed; refresh before revising',409)
        current_plan=self.store.node('WorkflowPlan',run['current_plan_id'])
        # Only the independent company lane crosses an authority renewal.
        # Completed protected outputs must be republished under the new grant.
        reusable=[s for s in self.store.steps(run['current_plan_id']) if s['logical_key']=='company_context']
        bundle=self._bundle(access,request,run_id,run['project_id'],mutation,request_hash,generation=run['generation']+1,
                            revision=run['revision']+1,old_steps=reusable)
        candidate=bundle['plan_properties']
        approvals=[a for a in self.store.approvals(run_id) if a['plan_id']==current_plan['id']]
        renewal=(run['status'] not in {'completed','cancelled'} and any(
            a['status'] in {'expired','rejected','changes_requested','revoked','stale'}
            or a['expires_at']<=self.clock()
            or (a['gate_kind']=='finance_access'
                and a['reviewer_id']!=bundle['approval_properties']['reviewer_id'])
            for a in approvals))
        # Generations alone are not a change. Renew unusable authority only for
        # unfinished work, while retaining the existing completed run as history.
        if (not renewal and current_plan['policy_id']==candidate['policy_id']
                and canonical(json.loads(current_plan['inputs_json']))==candidate['inputs_json']):
            raise AccessError('No changes to input versions or workflow settings',409)
        if not self.store.save_plan(bundle,revision=request.expected_revision):
            raise AccessError('Run changed; refresh before revising',409)
        return self.get_run(access,run_id)

    def _control(self,access,run_id,expected_revision,operation,idempotency_key=None):
        self._human(access)
        mutation_id=request_hash=None
        if idempotency_key:
            mutation_id,request_hash,existing=self._mutation(access,operation+':'+run_id,idempotency_key,{'expected_revision':expected_revision})
            if existing:
                return self.get_run(access,run_id)
        self.access.require(access,'run_'+operation,run_id)
        now=self.clock()
        params={'id':run_id,'expected':expected_revision,'member':access.member_id,'workspace':access.workspace_id,'timestamp':stamp(now)}
        guard='MATCH (r:WorkflowRun {id:$id}),(m:Member {id:$member}) WHERE r.revision=$expected AND r.requester_id=$member AND m.active=true AND r.workspace_id=$workspace '
        if operation=='cancel':
            mutation=(guard+'AND r.status IN [\'queued\',\'running\',\'waiting_approval\',\'failed\'] '
                      'SET r.status=\'cancelled\',r.cancelled_at=$timestamp,r.revision=r.revision+1,r.updated_at=$timestamp '
                      'WITH r MATCH (r)-[:HAS_PLAN]->(p:WorkflowPlan {id:r.current_plan_id})-[:HAS_STEP]->(s:WorkflowStep) '
                      'SET s.status=CASE WHEN s.status IN [\'completed\',\'skipped\'] THEN s.status ELSE \'cancelled\' END,s.fence=s.fence+1 '
                      'WITH DISTINCT r OPTIONAL MATCH (a:Approval {run_id:r.id}) WHERE a.status IN [\'pending\',\'approved\'] SET a.status=\'revoked\' '
                      'WITH DISTINCT r CREATE (e:RunEvent {id:$event,run_id:r.id,sequence:r.revision,kind:\'run_cancelled\',actor_id:$member,created_at:$timestamp}) '
                      'CREATE (r)-[:HAS_EVENT]->(e) RETURN r.id')
        else:
            mutation=(guard+'AND r.status=\'failed\' MATCH (r)-[:HAS_PLAN]->(p:WorkflowPlan {id:r.current_plan_id}) '
                      +self.store.current_scope('r,p')+
                      'SET r.status=\'queued\',r.revision=r.revision+1,r.updated_at=$timestamp '
                      'WITH r,p MATCH (p)-[:HAS_STEP]->(s:WorkflowStep) WHERE s.status=\'failed\' SET s.status=\'queued\' '
                      'WITH DISTINCT r CREATE (e:RunEvent {id:$event,run_id:r.id,sequence:r.revision,kind:\'run_retried\',actor_id:$member,created_at:$timestamp}) '
                      'CREATE (r)-[:HAS_EVENT]->(e) RETURN r.id')
        params['event']=fingerprint([run_id,operation,expected_revision])
        if mutation_id:
            mutation=mutation.replace('RETURN r.id','CREATE (:WorkflowMutation {id:$mutation,member_id:$member,request_hash:$request_hash,run_id:r.id}) RETURN r.id')
            params.update({'mutation':mutation_id,'request_hash':request_hash})
        if not self.database.query(mutation,params):
            existing=self.store.mutation(mutation_id) if mutation_id else None
            if not existing or existing['request_hash']!=request_hash:
                raise AccessError('Run changed; refresh before continuing',409)
        return self.get_run(access,run_id)

    def cancel(self,access,run_id,expected_revision,idempotency_key=None):
        return self._control(access,run_id,expected_revision,'cancel',idempotency_key)

    def retry(self,access,run_id,expected_revision,idempotency_key=None):
        return self._control(access,run_id,expected_revision,'retry',idempotency_key)

    @staticmethod
    def _cursor(cursor):
        if not cursor:
            return ''
        try:
            result=base64.urlsafe_b64decode(cursor.encode()).decode()
            if len(result)>200:
                raise ValueError()
            return result
        except (ValueError,UnicodeError):
            raise AccessError('Invalid cursor',422) from None

    @staticmethod
    def _page(items):
        more=len(items)>20
        selected=items[:20]
        return {'items':selected,'next_cursor':base64.urlsafe_b64encode(selected[-1]['id'].encode()).decode() if more else None}

    def list_runs(self,access,cursor=None):
        member=self._human(access)
        rows=self.database.query(
            'MATCH (r:WorkflowRun) WHERE r.workspace_id=$workspace AND r.id>$after '
            'AND (r.requester_id=$member OR $member IN r.output_audience OR $admin) RETURN r.id ORDER BY r.id LIMIT 21',
            {'workspace':access.workspace_id,'after':self._cursor(cursor),'member':access.member_id,'admin':member['role']=='admin'})
        return self._page([self.get_run(access,row[0]).model_dump() for row in rows])

    def list_approvals(self,access,cursor=None):
        self._human(access)
        rows=self.database.query(
            'MATCH (a:Approval),(r:WorkflowRun {id:a.run_id}) WHERE a.workspace_id=$workspace AND a.id>$after '
            'AND a.plan_id=r.current_plan_id AND (a.reviewer_id=$member OR a.requester_id=$member) '
            'RETURN properties(a),r.revision ORDER BY a.id LIMIT 21',
            {'workspace':access.workspace_id,'after':self._cursor(cursor),'member':access.member_id})
        items=[]
        for approval,revision in rows:
            items.append(self._approval_view(access,approval,revision))
        return self._page(items)

    def timeline(self,access,run_id,cursor=None):
        self.get_run(access,run_id)
        rows=self.database.query(
            'MATCH (:WorkflowRun {id:$id})-[:HAS_EVENT]->(e:RunEvent) WHERE e.sequence>$after '
            'RETURN properties(e) ORDER BY e.sequence LIMIT 21',{'id':run_id,'after':int(self._cursor(cursor) or '-1')})
        events=[row[0] for row in rows]
        selected=events[:20]
        return EventPage(items=selected,next_cursor=base64.urlsafe_b64encode(str(selected[-1]['sequence']).encode()).decode() if len(events)>20 else None)

    def artifact_metadata(self,access,artifact_id):
        """Internal download metadata; callers must never serialize blob keys."""
        self._human(access)
        self.access.require(access,'artifact_read',artifact_id)
        rows=self.database.query('MATCH (a:Artifact {id:$id}) RETURN properties(a)',{'id':artifact_id})
        if not rows:
            raise AccessError()
        return rows[0][0]

    def get_case(self,access,case_id):
        self._human(access)
        self.access.require(access,'read',case_id)
        case=self.store.node('ExceptionCase',case_id)
        if not case:
            raise AccessError()
        rows=self.database.query('MATCH (cr:CaseRevision {id:$id}) RETURN properties(cr)',{'id':case.get('current_revision_id','')})
        current=rows[0][0] if rows else {}
        return {**case,'current_revision':json.loads(current.get('payload_json','{}'))}

    def list_cases(self,access,cursor=None):
        member=self._human(access)
        rows=self.database.query(
            'MATCH (c:ExceptionCase) WHERE c.workspace_id=$workspace AND c.id>$after '
            'AND ($member IN c.output_audience OR $admin) RETURN c.id ORDER BY c.id LIMIT 21',
            {'workspace':access.workspace_id,'after':self._cursor(cursor),'member':access.member_id,'admin':member['role']=='admin'})
        return self._page([self.get_case(access,row[0]) for row in rows])

    def permitted_run_context(self,access,run_id):
        """Follow-up context is derived output, never a recycled raw-file grant."""
        snapshot=self.get_run(access,run_id)
        run=self.store.node('WorkflowRun',run_id)
        member=self.access.require_member(access)
        if access.member_id not in run.get('output_audience',[]) and member['role']!='admin':
            return {'run_id':run_id,'status':snapshot.status,'outputs':[],'decisions':[]}
        permitted=[]
        for step in snapshot.steps:
            if step['logical_key'] in {'company_context','publish_report','upsert_case','archive_run'} and step['status'] in {'completed','skipped','stale'}:
                permitted.append({'step_id':step['id'],'tool':step['tool'],'status':step['status'],'result':step.get('result',{})})
        return {'run_id':run_id,'status':snapshot.status,'generation':snapshot.generation,
                'outputs':snapshot.outputs,'results':permitted,
                'decisions':[{k:a[k] for k in ('id','gate_kind','reviewer_id','status','reason','decision_at') if k in a}
                             for a in snapshot.approvals]}

    def _approval_view(self,access,approval,revision,plan=None):
        plan=plan or self.store.node('WorkflowPlan',approval['plan_id'])
        item={k:v for k,v in approval.items() if k not in {'workspace_id','preview_json'}}
        item['expected_revision']=revision
        if item['status']=='pending' and item['expires_at']<=self.clock():
            item['status']='expired'
        reviewer=self.database.query('MATCH (m:Member {id:$id}) RETURN m.display_name',{'id':approval['reviewer_id']})
        item['reviewer_name']=(reviewer[0][0] if reviewer else '') or approval['reviewer_id'] or 'Unassigned'
        inputs=json.loads(plan['inputs_json'])
        tools=self.database.query(
            'MATCH (a:Approval {id:$id})-[:AUTHORIZES]->(s:WorkflowStep) '
            'RETURN s.id,s.tool,s.tool_version,s.input_hash ORDER BY s.ordinal',{'id':approval['id']})
        preview=None
        if approval.get('preview_json') and access.member_id in approval['output_audience']:
            raw=json.loads(approval['preview_json'])
            preview={'result':raw.get('result',{}),'evidence_refs':raw.get('evidence_refs',[]),
                     'artifacts':[{k:v for k,v in a.items() if k!='blob_key'} for a in raw.get('artifacts',[])],
                     'case_revision':raw.get('case_revision')}
        item['scope']={'plan_id':plan['id'],'policy_id':plan['policy_id'],'automation':plan['automation'],
                       'invoice':inputs['invoice'],'purchase_order':inputs['purchase_order'],
                       'context':inputs.get('context',[]),'output_audience':plan['output_audience'],
                       'tools':[{'step_id':row[0],'tool':row[1],'tool_version':row[2],'input_hash':row[3]} for row in tools],
                       'preview':preview}
        return item
