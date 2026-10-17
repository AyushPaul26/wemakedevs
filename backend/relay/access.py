"""Current graph-backed permissions for human and narrowly scoped agent reads."""

from dataclasses import dataclass
from datetime import datetime
import json
import time
from typing import Literal


@dataclass(frozen=True)
class AccessContext:
    member_id: str
    workspace_id: str = "meridian"
    purpose: Literal["human", "agent"] = "human"
    run_id: str | None = None
    step_id: str | None = None

    def __post_init__(self):
        if self.purpose not in {"human", "agent"}:
            raise ValueError("Unsupported access purpose")


class AccessError(Exception):
    def __init__(self, message="Resource not found", status_code=404):
        super().__init__(message)
        self.status_code = status_code


_LEGACY_LABELS = {"Source", "Entity", "Investigation", "Action", "Scenario"}
_READ_OPERATIONS = {"read", "source_read", "source_download", "evidence_read", "memory_read",
                    "graph_read", "run_read", "artifact_read"}
_WRITE_OPERATIONS = {"write", "source_replace", "links_review", "run_cancel", "run_retry",
                     "run_revise", "action_update"}


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


class AccessService:
    def __init__(self, database, *, clock=time.time):
        self.database = database
        self.clock = clock

    def require_member(self, context):
        if context.workspace_id != "meridian":
            raise AccessError()
        rows = self.database.query(
            "MATCH (m:Member {id:$id}) RETURN properties(m)", {"id": context.member_id})
        if not rows or rows[0][0].get("active") is not True:
            raise AccessError("Authentication required", 401)
        member = rows[0][0]
        if member.get("workspace_id") != context.workspace_id or member.get("role") not in {
                "admin", "operator", "finance_auditor"}:
            raise AccessError("Authentication required", 401)
        return member

    def _resource(self, resource_id):
        rows = self.database.query(
            "MATCH (n {id:$id}) RETURN labels(n),properties(n)", {"id": resource_id})
        return rows[0] if len(rows) == 1 else None

    def require(self, context, operation: str, resource_id: str):
        member = self.require_member(context)
        resource = self._resource(resource_id)
        if not resource:
            raise AccessError()
        labels, record = resource
        if record.get("workspace_id", "meridian") != context.workspace_id:
            raise AccessError()
        if operation == "approval_decide":
            if "Approval" not in labels:
                raise AccessError()
            if (context.purpose != "human" or record.get("reviewer_id") != context.member_id
                    or (record.get("gate_kind") == "finance_access"
                        and member.get("role") != "finance_auditor")):
                raise AccessError("Operation is not permitted", 403)
            if record.get("status") != "pending" or _epoch(record.get("expires_at")) <= self.clock():
                raise AccessError("Approval is no longer current", 409)
            return
        if operation not in _READ_OPERATIONS | _WRITE_OPERATIONS:
            raise AccessError("Operation is not permitted", 403)
        if not self._readable(context, member, labels, record, set()):
            raise AccessError()
        if operation in _WRITE_OPERATIONS:
            owner = record.get("uploader_id") or record.get("requester_id") or record.get("member_id")
            if context.purpose != "human" or (owner and owner != context.member_id
                                              and member["role"] != "admin"):
                raise AccessError("Operation is not permitted", 403)

    def can_read(self, context, resource_id):
        try:
            self.require(context, "read", resource_id)
            return True
        except AccessError:
            return False

    def can_read_record(self, context, record):
        """Filter hydrated graph edges, source summaries, and memory payloads safely.

        Existing node security metadata always wins over caller-supplied DTO fields.
        Derived text is excluded wholesale if any citation is inaccessible.
        """
        member = self.require_member(context)
        resource = self._resource(record.get("id", ""))
        if resource:
            return self._readable(context, member, resource[0], resource[1], set())
        # Graph relationship DTOs have no node record. Their access is inherited
        # from every cited source and both endpoints (filtered separately by caller).
        if record.get("classification", "workspace") not in {"workspace", "public", "general"}:
            return False
        if record.get("workspace_id", "meridian") != context.workspace_id:
            return False
        refs = self._references(record)
        if not refs:
            return False
        return all(self._reference_readable(context, member, ref, set()) for ref in refs)

    def filter_records(self, context, records):
        return [record for record in records if self.can_read_record(context, record)]

    def filter_graph(self, context, graph):
        nodes = self.filter_records(context, graph.get("nodes", []))
        ids = {node["id"] for node in nodes}
        edges = [edge for edge in self.filter_records(context, graph.get("edges", []))
                 if edge.get("source") in ids and edge.get("target") in ids]
        return {**graph, "nodes": nodes, "edges": edges,
                "sources": self.filter_records(context, graph.get("sources", []))}

    @staticmethod
    def _references(record):
        refs = list(record.get("source_ids") or [])
        refs.extend(record.get("output_ids") or [])
        refs.extend(record.get("artifact_ids") or [])
        for ref in record.get("evidence_refs") or []:
            refs.append(ref.get("chunk_id") or ref.get("version_id") or ref.get("source_id"))
        for ref in record.get("source_refs") or []:
            refs.append(ref.get("version_id") or ref.get("source_id"))
        return [ref for ref in refs if isinstance(ref, str) and ref]

    def _reference_readable(self, context, member, ref, seen):
        if ref in seen:
            return False
        resource = self._resource(ref)
        return bool(resource and self._readable(context, member, resource[0], resource[1], seen))

    def _readable(self, context, member, labels, record, seen):
        resource_id = record.get("id")
        if resource_id in seen or record.get("workspace_id", "meridian") != context.workspace_id:
            return False
        seen = seen | {resource_id}
        if "SourceChunk" in labels:
            return self._reference_readable(context, member, record.get("version_id"), seen)
        if "SourceVersion" in labels:
            source = self._resource(record.get("source_id"))
            if not source:
                return False
            # Source and selected immutable version both constrain access.
            if not self._readable(context, member, source[0], source[1], seen):
                return False
        if "Approval" in labels:
            return context.purpose == "human" and context.member_id in {
                record.get("requester_id"), record.get("reviewer_id")}
        if "WorkflowRun" in labels:
            if member["role"] == "admin" or context.member_id in {
                    record.get("requester_id"), *(record.get("output_audience") or [])}:
                return True
            assigned = self.database.query(
                "MATCH (a:Approval {run_id:$run,plan_id:$plan,reviewer_id:$member}) "
                "WHERE a.gate_kind<>'finance_access' OR $role='finance_auditor' RETURN a.id",
                {"run": record["id"], "plan": record.get("current_plan_id"),
                 "member": context.member_id, "role": member["role"]})
            return context.purpose == "human" and bool(assigned)
        if "WorkflowStep" in labels or "RunEvent" in labels:
            return self._reference_readable(context, member, record.get("run_id"), seen)
        if "Member" in labels or "Session" in labels or "IdentityBootstrap" in labels:
            return False
        payload = record.get("payload")
        try:
            display = json.loads(payload) if payload else {}
            if not isinstance(display, dict):
                return False
        except (ValueError, TypeError):
            return False
        owner = record.get("requester_id") or record.get("member_id")
        audience = record.get("audience")
        if member["role"] != "admin":
            if audience is not None and context.member_id not in audience:
                return False
            if owner and owner != context.member_id and audience is None:
                return False
        run_id = record.get("run_id") or display.get("run_id")
        if run_id and not self._reference_readable(context, member, run_id, seen):
            return False
        classification = record.get("classification")
        if classification is None:
            if set(labels) & _LEGACY_LABELS:
                classification = "workspace"
            else:
                return False
        if classification in {"finance", "restricted", "private"}:
            if context.purpose == "agent":
                if set(labels) & {"Source", "SourceVersion"}:
                    if not self._agent_grant(context, resource_id):
                        return False
                else:
                    if not self._agent_output(context, labels, record, display):
                        return False
            elif member["role"] != "admin":
                audience = record.get("audience") or record.get("output_audience")
                if audience is not None:
                    if context.member_id not in audience:
                        return False
                elif not (context.member_id == record.get("uploader_id") or (
                        member["role"] == "finance_auditor"
                        and (record.get("department_id") == "finance" or classification == "finance"))):
                    return False
        elif classification not in {"workspace", "public", "general"}:
            return False
        # JSON may add citations that further restrict access, never grant it.
        refs = set(self._references(record) + self._references(display))
        return all(self._reference_readable(context, member, ref, seen) for ref in refs)

    def _agent_output(self, context, labels, record, display):
        """Published report access is independent of permission to its raw inputs."""
        audience = record.get("output_audience") or record.get("audience") or []
        if (not context.run_id or record.get("run_id") != context.run_id
                or context.member_id not in audience):
            return False
        if "Artifact" in labels:
            receipt = self.database.query(
                "MATCH (e:Execution {id:$execution})-[:PRODUCED]->(a:Artifact {id:$artifact}) "
                "WHERE e.status='completed' AND e.run_id=$run AND e.workspace_id=$workspace "
                "RETURN e.id", {"execution": record.get("execution_id"), "artifact": record["id"],
                                 "run": context.run_id, "workspace": context.workspace_id})
            return bool(receipt)
        if "Investigation" in labels:
            return bool(display.get("output_ids") or display.get("artifact_ids")
                        or record.get("output_ids") or record.get("artifact_ids"))
        return False

    def _agent_grant(self, context, resource_id):
        if not context.run_id or not context.step_id:
            return False
        rows = self.database.query(
            "MATCH (r:WorkflowRun {id:$run})-[:HAS_PLAN]->(p:WorkflowPlan)"
            "-[:HAS_STEP]->(s:WorkflowStep {id:$step}), "
            "(s)-[:REQUIRES_APPROVAL]->(a:Approval)-[grant:AUTHORIZES]->(s), "
            "(a)-[:PERMITS_SOURCE]->(v:SourceVersion), (s)-[:USES_SOURCE]->(v), "
            "(source:Source {id:v.source_id}), "
            "(d:Department {id:v.department_id})-[:GOVERNED_BY]->(policy:Policy {id:a.policy_id}), "
            "(reviewer:Member {id:a.reviewer_id})-[:MEMBER_OF]->(d) "
            "WHERE (v.id=$resource OR source.id=$resource) AND r.current_plan_id=p.id "
            "AND d.current_policy_id=policy.id AND source.current_version_id=v.id "
            "RETURN properties(r),properties(p),properties(s),properties(a),properties(policy),"
            "properties(reviewer),properties(grant)",
            {"run": context.run_id, "step": context.step_id, "resource": resource_id})
        for run, plan, step, approval, policy, reviewer, grant in rows:
            if (run.get("workspace_id") != context.workspace_id
                    or run.get("requester_id") != context.member_id
                    or run.get("status") not in {"queued", "running", "waiting_approval"}
                    or run.get("cancelled_at")
                    or plan.get("run_id") != run["id"] or step.get("run_id") != run["id"]
                    or step.get("status") not in {"queued", "running"}
                    or approval.get("run_id") != run["id"]
                    or approval.get("plan_id") != plan["id"]
                    or approval.get("gate_kind") != "finance_access"
                    or approval.get("status") != "approved"
                    or _epoch(approval.get("expires_at")) <= self.clock()
                    or not approval.get("scope_hash")
                    or approval["scope_hash"] != plan.get("scope_hash")
                    or approval.get("policy_id") != plan.get("policy_id")
                    or approval.get("reviewer_id") != policy.get("reviewer_id")
                    or approval.get("output_audience") != plan.get("output_audience")
                    or not reviewer.get("active") or reviewer.get("role") != "finance_auditor"
                    or reviewer.get("workspace_id") != context.workspace_id
                    or step.get("tool") not in (policy.get("allowed_tools") or [])
                    or any(not step.get(key) or grant.get(key) != step.get(key)
                           for key in ("tool", "tool_version", "input_hash", "arguments_json"))):
                continue
            # Every input, not only this requested version, must remain current and
            # inside the same exact approval. A partial invalidation is fail-closed.
            invalid = self.database.query(
                "MATCH (p:WorkflowPlan {id:$plan})-[:USES_SOURCE]->(v:SourceVersion) "
                "OPTIONAL MATCH (source:Source {id:v.source_id}) "
                "OPTIONAL MATCH (a:Approval {id:$approval})-[permit:PERMITS_SOURCE]->(v) "
                "RETURN v.id,source.current_version_id,permit IS NOT NULL",
                {"plan": plan["id"], "approval": approval["id"]})
            if invalid and len(invalid) == plan.get("input_count") and all(
                    version == current and permitted for version, current, permitted in invalid):
                return True
        return False
