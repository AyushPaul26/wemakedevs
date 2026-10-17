"""FalkorDB is the authority for workflow state and fenced execution.

Every permission-bearing transition is one conditional graph mutation. Read-side
preflights improve error messages; they never replace the guards in the mutation.
"""
from datetime import datetime, timezone
import hashlib
import json
import time

from .workflow_models import RecoveryReport, StepLease


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


class WorkflowStore:
    def __init__(self, database, *, clock=time.time):
        self.database = database
        self.clock = clock

    def node(self, label, node_id):
        assert label in {'WorkflowRun','WorkflowPlan','WorkflowStep','Approval','WorkflowMutation','ExceptionCase'}
        rows = self.database.query(f'MATCH (n:{label} {{id:$id}}) RETURN properties(n)', {'id':node_id})
        return rows[0][0] if rows else None

    def mutation(self, mutation_id):
        return self.node('WorkflowMutation',mutation_id)

    def steps(self, plan_id):
        return [row[0] for row in self.database.query(
            'MATCH (:WorkflowPlan {id:$id})-[:HAS_STEP]->(s:WorkflowStep) RETURN properties(s) ORDER BY s.ordinal', {'id':plan_id})]

    def approvals(self, run_id):
        return [row[0] for row in self.database.query(
            'MATCH (a:Approval {run_id:$id}) RETURN properties(a) ORDER BY a.created_at,a.id', {'id':run_id})]

    # A plan always has at least the invoice and purchase order. Compare each
    # immutable input to the source pointer inside every privileged mutation.
    @staticmethod
    def current_scope(variables='r,p'):
        return (' MATCH (p)-[:USES_SOURCE]->(v:SourceVersion)<-[:HAS_VERSION]-(source:Source) '
                f'WITH {variables}, collect(source.current_version_id=v.id AND source.workspace_id=r.workspace_id '
                'AND v.workspace_id=r.workspace_id) AS current_inputs '
                'WHERE size(current_inputs)=p.input_count AND all(valid IN current_inputs WHERE valid) ')

    def save_plan(self, bundle, *, revision=None):
        """Create an immutable plan; optionally atomically replace a prior generation."""
        params = dict(bundle)
        params['expected'] = revision
        params['audience'] = bundle['run_properties']['output_audience']
        params['now'] = self.clock()
        prefix = (
            'MATCH (actor:Member {id:$requester}), (project:Entity {id:$project}), '
            '(department:Department {id:$department})-[:GOVERNED_BY]->(policy:Policy {id:$policy}) '
            'WHERE actor.active=true AND actor.workspace_id=$workspace '
            'AND project.workspace_id=$workspace AND department.current_policy_id=policy.id '
            'OPTIONAL MATCH (op:WorkflowMutation {id:$mutation_id}) WITH actor,project,department,policy,op '
            'WHERE op IS NULL '
            'UNWIND $refs AS ref MATCH (source:Source {id:ref.source_id})-[:HAS_VERSION]->(version:SourceVersion {id:ref.version_id}) '
            'WITH actor,project,department,policy,collect(source) AS sources,collect(version) AS versions '
            'WHERE size(versions)=size($refs) AND all(s IN sources WHERE s.workspace_id=$workspace) '
            'AND all(v IN versions WHERE v.workspace_id=$workspace) '
            'AND all(s IN sources WHERE s.current_version_id IN $version_ids) '
        )
        if revision is None:
            prefix += (' CREATE (r:WorkflowRun) SET r=$run_properties '
                       'CREATE (r)-[:REQUESTED_BY]->(actor) ')
        else:
            prefix += (
                'MATCH (r:WorkflowRun {id:$run_id}) WHERE r.requester_id=$requester '
                'AND r.revision=$expected AND r.workspace_id=$workspace AND r.status<>\'cancelled\' '
                'SET r.current_plan_id=$plan_id,r.generation=r.generation+1,r.revision=r.revision+1, '
                'r.status=\'waiting_approval\',r.output_audience=$audience,r.updated_at=$timestamp '
            )
        statement = prefix + (
            'CREATE (p:WorkflowPlan) SET p=$plan_properties CREATE (r)-[:HAS_PLAN]->(p) '
            'FOREACH (v IN versions | CREATE (p)-[:USES_SOURCE]->(v)) '
            'CREATE (a:Approval) SET a=$approval_properties '
            'CREATE (op:WorkflowMutation {id:$mutation_id,member_id:$requester,request_hash:$request_hash,run_id:$run_id}) '
            'CREATE (e:RunEvent {id:$event_id,run_id:$run_id,sequence:r.revision,kind:$event_kind,actor_id:$requester,created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(e) '
            'WITH r,p,a,versions UNWIND $steps AS spec '
            'MERGE (s:WorkflowStep {id:spec.id}) ON CREATE SET s=spec '
            'CREATE (p)-[:HAS_STEP]->(s) '
            'FOREACH (v IN [v IN versions WHERE v.id IN spec.version_ids] | MERGE (s)-[:USES_SOURCE]->(v)) '
            'FOREACH (ignored IN CASE WHEN spec.logical_key<>\'company_context\' THEN [1] ELSE [] END | '
            'CREATE (s)-[:REQUIRES_APPROVAL]->(a) '
            'CREATE (a)-[:AUTHORIZES {tool:spec.tool,tool_version:spec.tool_version,input_hash:spec.input_hash,arguments_json:spec.arguments_json}]->(s)) '
            'WITH DISTINCT r,p,a,versions '
            'FOREACH (v IN versions | CREATE (a)-[:PERMITS_SOURCE]->(v)) '
            'WITH r,p,a OPTIONAL MATCH (reviewer:Member {id:$reviewer}) '
            'FOREACH (m IN CASE WHEN reviewer IS NULL THEN [] ELSE [reviewer] END | CREATE (a)-[:ASSIGNED_TO]->(m)) '
            'WITH DISTINCT r,p UNWIND $dependencies AS dependency '
            'MATCH (dependent:WorkflowStep {id:dependency.dependent}),(prerequisite:WorkflowStep {id:dependency.prerequisite}) '
            'MERGE (dependent)-[:DEPENDS_ON]->(prerequisite) RETURN DISTINCT r.id'
        )
        rows = self.database.query(statement,params)
        if rows and revision is not None:
            # No security depends on this cleanup: current plan and pointer guards
            # already made the superseded generation incapable of publication.
            self.database.query(
                'MATCH (a:Approval {run_id:$run}) WHERE a.plan_id<>$plan AND a.status IN [\'pending\',\'approved\'] '
                'SET a.status=\'stale\' RETURN a.id',{'run':bundle['run_id'],'plan':bundle['plan_id']})
            self.database.query(
                'MATCH (artifact:Artifact {run_id:$run}) SET artifact.stale=true RETURN artifact.id', {'run':bundle['run_id']})
            self.database.query(
                'MATCH (c:ExceptionCase {run_id:$run}) SET c.stale=true '
                'WITH c OPTIONAL MATCH (revision:CaseRevision)-[:VERSION_OF]->(c) SET revision.stale=true RETURN c.id',
                {'run':bundle['run_id']})
        return bool(rows)

    def decide(self, approval, access, decision, mutation_id, request_hash):
        now = self.clock()
        params = {'approval':approval['id'],'member':access.member_id,'workspace':access.workspace_id,
                  'expected':decision.expected_revision,'hash':decision.scope_hash,'now':now,'timestamp':stamp(now),
                  'status':{'approve':'approved','reject':'rejected','request_changes':'changes_requested'}[decision.decision],
                  'reason':decision.reason or '', 'mutation':mutation_id,'request_hash':request_hash,
                  'event':fingerprint([mutation_id,'event'])}
        query = (
            'MATCH (a:Approval {id:$approval}),(r:WorkflowRun {id:a.run_id})-[:HAS_PLAN]->(p:WorkflowPlan {id:a.plan_id}), '
            '(m:Member {id:$member}),(d:Department)-[:GOVERNED_BY]->(policy:Policy {id:a.policy_id}) '
            'WHERE r.current_plan_id=p.id AND r.revision=$expected AND r.workspace_id=$workspace '
            'AND r.status IN [\'queued\',\'running\',\'waiting_approval\'] AND r.cancelled_at IS NULL '
            'AND a.status=\'pending\' AND a.expires_at>$now AND a.scope_hash=$hash '
            'AND a.reviewer_id=m.id AND m.active=true AND m.workspace_id=$workspace '
            'AND d.current_policy_id=policy.id AND p.policy_id=policy.id '
            'AND ((a.gate_kind=\'finance_access\' AND m.role=\'finance_auditor\' AND policy.reviewer_id=m.id AND m.id<>r.requester_id '
            ') OR (a.gate_kind<>\'finance_access\' AND m.id=r.requester_id)) '
            'AND a.output_audience=p.output_audience '
            'AND (a.gate_kind<>\'finance_access\' OR a.scope_hash=p.scope_hash) '
        )
        query += ('OPTIONAL MATCH (m)-[membership:MEMBER_OF]->(d) WITH r,p,a,m,policy,membership '
                  'WHERE a.gate_kind<>\'finance_access\' OR membership IS NOT NULL ')
        query += self.current_scope('r,p,a,m,policy')
        query += (
            'OPTIONAL MATCH (prior:WorkflowMutation {id:$mutation}) WITH r,p,a,m,policy,prior WHERE prior IS NULL '
            'SET a.status=$status,a.reason=$reason,a.decision_at=$now,a.revision=a.revision+1, '
            'r.revision=r.revision+1,r.updated_at=$timestamp '
            'CREATE (a)-[:DECIDED_BY]->(m) '
            'CREATE (:WorkflowMutation {id:$mutation,member_id:$member,request_hash:$request_hash,run_id:r.id}) '
            'CREATE (event:RunEvent {id:$event,run_id:r.id,sequence:r.revision,kind:\'approval_\'+$status,actor_id:$member,approval_id:a.id,created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(event) '
            'WITH r,p,a MATCH (p)-[:HAS_STEP]->(s:WorkflowStep)-[:REQUIRES_APPROVAL]->(a) '
            'SET s.status=CASE WHEN $status=\'approved\' AND s.status=\'waiting_approval\' THEN \'queued\' '
            'WHEN $status=\'rejected\' AND s.status<>\'completed\' THEN \'rejected\' ELSE s.status END '
            'SET r.status=CASE WHEN $status=\'rejected\' THEN \'rejected\' ELSE \'waiting_approval\' END RETURN DISTINCT r.id'
        )
        return bool(self.database.query(query,params))

    def _execution_guard(self, *, lease=False):
        query = (
            'MATCH (r:WorkflowRun)-[:HAS_PLAN]->(p:WorkflowPlan)-[:HAS_STEP]->(s:WorkflowStep), '
            '(requester:Member {id:r.requester_id}),(workspace:Workspace {id:r.workspace_id}), '
            '(department:Department)-[:GOVERNED_BY]->(policy:Policy {id:p.policy_id}) '
            'WHERE r.current_plan_id=p.id AND r.workspace_id=\'meridian\' '
            'AND workspace.maintenance=false AND workspace.execution_enabled=true '
            'AND requester.active=true AND requester.workspace_id=r.workspace_id '
            'AND r.status IN [\'queued\',\'running\',\'waiting_approval\'] AND r.cancelled_at IS NULL '
            'AND department.current_policy_id=policy.id '
        )
        if lease:
            query += ('AND r.id=$run AND p.id=$plan AND r.generation=$generation AND s.id=$step '
                      'AND s.status=\'running\' AND s.fence=$fence AND s.lease_owner=$worker AND s.lease_until>$now ')
        else:
            query += ('AND ($run IS NULL OR r.id=$run) '
                      'AND (s.status=\'queued\' OR (s.status=\'running\' AND s.lease_until<=$now)) ')
        query += self.current_scope('r,p,s,policy')
        # On pinned FalkorDB, an indexed Member.id lookup using a nullable
        # optional approval alias crashes the planner. Follow its routing edge
        # and still validate the scalar reviewer identity below.
        query += (
            'OPTIONAL MATCH (s)-[:DEPENDS_ON]->(dependency:WorkflowStep) '
            'WITH r,p,s,policy,collect(dependency.status) AS prerequisites '
            'WHERE all(state IN prerequisites WHERE state IN [\'completed\',\'skipped\']) '
            'OPTIONAL MATCH (s)-[:REQUIRES_APPROVAL]->(a:Approval) '
            'OPTIONAL MATCH (a)-[:ASSIGNED_TO]->(reviewer:Member) '
            'OPTIONAL MATCH (reviewer)-[membership:MEMBER_OF]->(:Department {id:\'finance\'}) '
            'OPTIONAL MATCH (a)-[grant:AUTHORIZES]->(s) '
            'OPTIONAL MATCH (a)-[:PERMITS_SOURCE]->(permitted:SourceVersion) '
            'WITH r,p,s,policy,a,reviewer,membership,grant,collect(DISTINCT permitted.id) AS permits '
            'WITH r,p,s,policy,collect(CASE WHEN a IS NULL THEN true ELSE '
            'coalesce(a.status=\'approved\' AND a.expires_at>$now AND a.plan_id=p.id '
            'AND a.scope_hash=CASE WHEN a.gate_kind=\'finance_access\' THEN p.scope_hash ELSE a.scope_hash END '
            'AND a.policy_id=policy.id AND a.output_audience=p.output_audience '
            'AND reviewer.id=a.reviewer_id AND reviewer.active=true AND reviewer.workspace_id=r.workspace_id '
            'AND ((a.gate_kind=\'finance_access\' AND reviewer.role=\'finance_auditor\' AND reviewer.id=policy.reviewer_id AND reviewer.id<>r.requester_id AND membership IS NOT NULL) '
            'OR (a.gate_kind<>\'finance_access\' AND reviewer.id=r.requester_id)) '
            'AND grant.tool=s.tool AND grant.tool_version=s.tool_version '
            'AND grant.input_hash=s.input_hash AND grant.arguments_json=s.arguments_json '
            'AND s.tool IN policy.allowed_tools '
            'AND (a.gate_kind<>\'finance_access\' OR (size(permits)=p.input_count AND all(version IN s.version_ids WHERE version IN permits))) '
            ',false) END) AS grants,collect(a.id) AS approval_ids '
            'WHERE all(valid IN grants WHERE valid) '
        )
        return query

    def claim_step(self, worker_id, run_id=None, now=None):
        now = self.clock() if now is None else now
        query = self._execution_guard() + (
            'OPTIONAL MATCH (active:WorkflowStep {status:\'running\'}) WHERE active.lease_until>$now '
            'WITH r,p,s,count(active) AS active_count WHERE active_count<2 '
            'WITH r,p,s ORDER BY s.ordinal LIMIT 1 '
            'SET s.status=\'running\',s.fence=s.fence+1,s.attempt=s.attempt+1,s.lease_owner=$worker,s.lease_until=$until,s.started_at=$timestamp, '
            'r.status=\'running\',r.revision=r.revision+1,r.updated_at=$timestamp '
            'CREATE (event:RunEvent {id:s.id+\':started:\'+toString(s.fence),run_id:r.id,sequence:r.revision,kind:\'step_started\',step_id:s.id,actor_id:\'system\',created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(event) RETURN s.id,r.id,p.id,r.generation,s.fence,s.lease_until'
        )
        rows = self.database.query(query,{'run':run_id,'worker':worker_id,'now':now,'until':now+120,'timestamp':stamp(now)})
        if not rows:
            return None
        step, run, plan, generation, fence, until = rows[0]
        return StepLease(step_id=step,run_id=run,plan_id=plan,generation=generation,fence=fence,worker_id=worker_id,lease_until=stamp(until))

    @staticmethod
    def _lease_params(lease, now):
        return {'step':lease.step_id,'run':lease.run_id,'plan':lease.plan_id,'generation':lease.generation,
                'fence':lease.fence,'worker':lease.worker_id,'now':now,'timestamp':stamp(now)}

    def heartbeat(self, lease, now=None):
        now = self.clock() if now is None else now
        return bool(self.database.query(self._execution_guard(lease=True) +
            'SET s.lease_until=$until RETURN s.id',self._lease_params(lease,now)|{'until':now+120}))

    def step_context(self, lease):
        step = self.node('WorkflowStep',lease.step_id)
        run = self.node('WorkflowRun',lease.run_id)
        plan = self.node('WorkflowPlan',lease.plan_id)
        if not step or not run or run['current_plan_id'] != lease.plan_id or step.get('fence') != lease.fence:
            return None
        step['arguments'] = json.loads(step['arguments_json'])
        prerequisites = [row[0] for row in self.database.query(
            'MATCH (:WorkflowStep {id:$step})-[:DEPENDS_ON]->(p:WorkflowStep) RETURN properties(p)',{'step':lease.step_id})]
        for item in prerequisites:
            item['result'] = json.loads(item.get('result_json','{}'))
        sources = [row[0] for row in self.database.query(
            'MATCH (:WorkflowStep {id:$step})-[:USES_SOURCE]->(v:SourceVersion) RETURN properties(v)',{'step':lease.step_id})]
        approval = next((a for a in self.approvals(lease.run_id) if a['plan_id']==lease.plan_id and a['gate_kind']=='finance_access'),None)
        return {'run':run,'plan':plan,'step':step,'sources':sources,'prerequisites':prerequisites,'approval':approval,
                'case':self.node('ExceptionCase','case:'+lease.run_id),
                'effect_preview':json.loads(step['effect_preview_json']) if step.get('effect_preview_json') else None}

    def commit_step(self, lease, effects, now=None):
        now = self.clock() if now is None else now
        effects = effects.model_dump() if hasattr(effects,'model_dump') else effects
        params = self._lease_params(lease,now)|{
            'effect':effects['effect_key'],'result':canonical(effects['result']),
            'evidence':canonical(effects.get('evidence_refs',[])),
            'refs':[dict(ref,locator_json=canonical({k:v for k,v in ref['locator'].items() if v is not None})) for ref in effects.get('evidence_refs',[])],
            'artifacts':effects.get('artifacts',[]),'case_revision':effects.get('case_revision'),
            'skipped':effects['result'].get('outcome')=='skipped' and not effects.get('case_revision') and not effects.get('artifacts'),
            'event':fingerprint([effects['effect_key'],'completed']),
            'execution':fingerprint([effects['effect_key'],'execution'])}
        # The immutable effect key is checked under the same graph write lock.
        params['preview_hash'] = fingerprint(effects)
        query = self._execution_guard(lease=True) + (
            'OPTIONAL MATCH (s)-[:REQUIRES_APPROVAL]->(change:Approval) '
            'WHERE change.gate_kind=CASE WHEN s.logical_key=\'publish_report\' THEN \'report_write\' ELSE \'case_write\' END '
            'WITH r,p,s,change,approval_ids WHERE p.automation<>\'review_changes\' OR NOT (s.logical_key IN [\'publish_report\',\'upsert_case\']) '
            'OR (s.logical_key=\'upsert_case\' AND $skipped) OR (change.status=\'approved\' AND change.preview_hash=$preview_hash AND change.plan_id=p.id AND change.expires_at>$now) '
            'UNWIND CASE WHEN size($refs)=0 THEN [null] ELSE $refs END AS evidence '
            'OPTIONAL MATCH (version:SourceVersion {id:evidence.version_id})-[:HAS_CHUNK]->(chunk:SourceChunk {id:evidence.chunk_id}) '
            'WITH r,p,s,approval_ids,collect(version) AS cited_versions,collect(chunk) AS cited_chunks, '
            'collect(CASE WHEN evidence IS NULL THEN true ELSE chunk IS NOT NULL AND version.id IN s.version_ids '
            'AND version.source_id=evidence.source_id AND chunk.locator_json=evidence.locator_json END) AS valid_evidence '
            'WHERE all(valid IN valid_evidence WHERE valid) '
            'OPTIONAL MATCH (existing:Execution {effect_key:$effect}) '
            'WITH r,p,s,approval_ids,cited_versions,cited_chunks,existing WHERE existing IS NULL '
            'CREATE (execution:Execution {id:$execution,workspace_id:r.workspace_id,run_id:r.id,step_id:s.id,effect_key:$effect, '
            'attempt:s.attempt,fence:s.fence,tool:s.tool,input_hash:s.input_hash,approval_ids:approval_ids,status:\'completed\',started_at:s.started_at,ended_at:$timestamp,result_json:$result,evidence_refs_json:$evidence}) '
            'CREATE (s)-[:EXECUTED_AS]->(execution) '
            'FOREACH (version IN cited_versions | CREATE (execution)-[:CITES_VERSION]->(version)) '
            'FOREACH (chunk IN cited_chunks | CREATE (execution)-[:CITES_CHUNK]->(chunk)) '
            'SET s.status=CASE WHEN s.logical_key=\'upsert_case\' AND $skipped THEN \'skipped\' ELSE \'completed\' END,s.result_id=execution.id,s.result_json=$result,s.lease_until=0, '
            'r.revision=r.revision+1,r.updated_at=$timestamp '
            'FOREACH (spec IN $artifacts | '
            'CREATE (artifact:Artifact {id:spec.id,workspace_id:r.workspace_id,run_id:r.id,execution_id:execution.id,effect_key:$effect+\':\'+spec.kind, '
            'kind:spec.kind,blob_key:spec.blob_key,content_hash:spec.content_hash,mime:spec.mime,byte_size:spec.byte_size,classification:\'finance\',output_audience:p.output_audience,stale:false,created_at:$timestamp}) '
            'CREATE (execution)-[:PRODUCED]->(artifact) '
            'FOREACH (version IN cited_versions | CREATE (artifact)-[:CITES_VERSION]->(version)) '
            'FOREACH (chunk IN cited_chunks | CREATE (artifact)-[:CITES_CHUNK]->(chunk))) '
            'FOREACH (spec IN CASE WHEN $case_revision IS NULL THEN [] ELSE [$case_revision] END | '
            'MERGE (c:ExceptionCase {id:\'case:\'+r.id}) '
            'ON CREATE SET c.workspace_id=r.workspace_id,c.run_id=r.id,c.classification=\'finance\',c.output_audience=p.output_audience '
            'CREATE (cr:CaseRevision {id:spec.id,case_id:c.id,execution_id:execution.id,workspace_id:r.workspace_id, '
            'classification:\'finance\',output_audience:p.output_audience,payload_json:spec.payload_json,created_at:$timestamp}) '
            'SET c.current_revision_id=cr.id,c.status=spec.status,c.output_audience=p.output_audience,c.owner_entity_id=spec.owner_entity_id,c.stale=false,cr.stale=false '
            'CREATE (execution)-[:REVISED]->(cr)-[:VERSION_OF]->(c) '
            'FOREACH (version IN cited_versions | CREATE (cr)-[:CITES_VERSION]->(version)) '
            'FOREACH (chunk IN cited_chunks | CREATE (cr)-[:CITES_CHUNK]->(chunk))) '
            'CREATE (event:RunEvent {id:$event,run_id:r.id,sequence:r.revision,kind:\'step_completed\',step_id:s.id,actor_id:\'system\',created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(event) '
            'SET r.status=CASE WHEN s.logical_key=\'archive_run\' THEN \'completed\' ELSE \'running\' END '
            'RETURN s.id'
        )
        case_revision = params['case_revision']
        if case_revision:
            params['case_revision'] = {'id':case_revision.get('id',fingerprint([effects['effect_key'],'case'])),
                                     'status':case_revision.get('status','open'),'payload_json':canonical(case_revision),
                                     'owner_entity_id':case_revision.get('owner_entity_id')}
        return bool(self.database.query(query,params))

    def fail_step(self, lease, error, now=None):
        now = self.clock() if now is None else now
        # Errors are deliberately bounded and never contain provider/source bodies.
        params = self._lease_params(lease,now)|{'error':str(error)[:300]}
        return bool(self.database.query(self._execution_guard(lease=True) +
            'SET s.status=\'failed\',s.error=\'Tool execution failed; retry is available\',s.lease_until=0, '
            'r.status=\'failed\',r.revision=r.revision+1,r.updated_at=$timestamp RETURN s.id',params))

    def invalidate_source(self, source_id, new_version_id):
        """Idempotent recovery after the authoritative source pointer swap."""
        self.database.query(
            'MATCH (source:Source {id:$source})-[:HAS_VERSION]->(old:SourceVersion)<-[:USES_SOURCE]-(direct:WorkflowStep), '
            '(p:WorkflowPlan)-[:HAS_STEP]->(direct),(r:WorkflowRun {id:p.run_id}) '
            'WHERE old.id<>$version AND source.current_version_id=$version AND r.current_plan_id=p.id '
            'OPTIONAL MATCH (marker:RunEvent {id:r.id+\':source:\'+$version}) '
            'WITH r,p,direct,marker WHERE marker IS NULL '
            'MATCH (affected:WorkflowStep)-[:DEPENDS_ON*0..]->(direct) '
            'WITH DISTINCT r,p,affected SET affected.status=CASE WHEN affected.status=\'cancelled\' THEN affected.status ELSE \'stale\' END,affected.fence=affected.fence+1 '
            'WITH DISTINCT r,p SET r.status=CASE WHEN r.status=\'cancelled\' THEN r.status ELSE \'stale\' END, '
            'r.revision=r.revision+1,r.updated_at=$timestamp '
            'CREATE (marker:RunEvent {id:r.id+\':source:\'+$version,run_id:r.id,sequence:r.revision,kind:\'source_invalidated\', '
            'actor_id:\'system\',source_id:$source,version_id:$version,created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(marker) '
            'WITH r,p MATCH (a:Approval {plan_id:p.id}) SET a.status=\'stale\' '
            'WITH DISTINCT r OPTIONAL MATCH (c:ExceptionCase {run_id:r.id}) SET c.stale=true '
            'WITH DISTINCT r OPTIONAL MATCH (c:ExceptionCase {run_id:r.id})<-[:VERSION_OF]-(revision:CaseRevision) SET revision.stale=true '
            'WITH DISTINCT r OPTIONAL MATCH (artifact:Artifact {run_id:r.id}) SET artifact.stale=true RETURN DISTINCT r.id',
            {'source':source_id,'version':new_version_id,'timestamp':stamp(self.clock())})
        return [row[0] for row in self.database.query(
            'MATCH (event:RunEvent {source_id:$source,version_id:$version,kind:\'source_invalidated\'}) '
            'RETURN event.run_id ORDER BY event.run_id',{'source':source_id,'version':new_version_id})]

    def create_effect_approval(self, lease, preview, gate_kind):
        """Persist exact staged effects before the requester reviews a strict write."""
        step=self.node('WorkflowStep',lease.step_id)
        required={'publish_report':'report_write','upsert_case':'case_write'}
        if not step or required.get(step['logical_key'])!=gate_kind:
            raise ValueError('Effect approval does not match this tool')
        now=self.clock()
        scope=fingerprint({'plan':lease.plan_id,'step':lease.step_id,'preview':preview})
        approval_id=fingerprint([lease.plan_id,lease.step_id,gate_kind,scope])
        existing=self.node('Approval',approval_id)
        if existing:
            return existing
        params=self._lease_params(lease,now)|{'approval':approval_id,'kind':gate_kind,'scope':scope,
                'preview':canonical(preview),'preview_hash':fingerprint(preview),'event':fingerprint([approval_id,'requested'])}
        rows=self.database.query(self._execution_guard(lease=True)+
            'WITH r,p,s,policy WHERE p.automation=\'review_changes\' '
            'MATCH (requester:Member {id:r.requester_id}) '
            'OPTIONAL MATCH (existing:Approval {id:$approval}) WITH r,p,s,policy,requester,existing WHERE existing IS NULL '
            'CREATE (a:Approval {id:$approval,workspace_id:r.workspace_id,run_id:r.id,plan_id:p.id,scope_hash:$scope,gate_kind:$kind, '
            'requester_id:r.requester_id,reviewer_id:r.requester_id,policy_id:p.policy_id,status:\'pending\',expires_at:$now+policy.approval_ttl_seconds, '
            'output_audience:p.output_audience,revision:0,preview_hash:$preview_hash,preview_json:$preview,created_at:$timestamp}) '
            'CREATE (s)-[:REQUIRES_APPROVAL]->(a) CREATE (a)-[:ASSIGNED_TO]->(requester) '
            'CREATE (a)-[:AUTHORIZES {tool:s.tool,tool_version:s.tool_version,input_hash:s.input_hash,arguments_json:s.arguments_json}]->(s) '
            'SET s.status=\'waiting_approval\',s.lease_until=0,s.effect_preview_json=$preview, '
            'r.status=\'waiting_approval\',r.revision=r.revision+1,r.updated_at=$timestamp '
            'CREATE (event:RunEvent {id:$event,run_id:r.id,sequence:r.revision,kind:\'effect_approval_requested\',actor_id:\'system\',approval_id:a.id,created_at:$timestamp}) '
            'CREATE (r)-[:HAS_EVENT]->(event) RETURN properties(a)',params)
        return rows[0][0] if rows else None

    def recover(self):
        """Requeue expired valid claims, retaining committed immutable receipts."""
        now=self.clock()
        rows=self.database.query(self._execution_guard()+
            'WITH r,p,s WHERE s.status=\'running\' AND s.lease_until<=$now '
            'SET s.status=\'queued\',s.fence=s.fence+1,s.lease_until=0 RETURN s.id',{'run':None,'now':now})
        waiting=self.database.query(
            'MATCH (r:WorkflowRun)-[:HAS_PLAN]->(p:WorkflowPlan)-[:HAS_STEP]->(s:WorkflowStep) '
            'WHERE r.current_plan_id=p.id AND s.status=\'waiting_approval\' RETURN s.id')
        return RecoveryReport(requeued=[r[0] for r in rows],waiting=[r[0] for r in waiting],reconciled=[],failed=[])
