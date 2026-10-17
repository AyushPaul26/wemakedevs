"""Access-aware adapter for the existing company graph and manual task API.

GraphStore remains the persistence implementation for legacy records. Request
handlers and agents use this adapter, never its unscoped reads.
"""

from dataclasses import replace
import json

from relay.access import AccessError


class CompanyService:
    def __init__(self, store, access_service, evidence_service=None, run_context=None):
        self.store = store
        self.access = access_service
        self.evidence = evidence_service
        self.run_context = run_context

    def get_graph(self, access):
        self.access.require_member(access)
        graph = self.access.filter_graph(access, self.store.get_graph())
        graph["sources"] = [{key: value for key, value in source.items() if key != "excerpt"}
                            for source in graph["sources"]]
        return graph

    def list_memories(self, access, limit=30):
        self.access.require_member(access)
        return self.access.filter_records(access, self.store.list_memories(limit))

    def list_actions(self, access):
        self.access.require_member(access)
        return self.access.filter_records(access, self.store.list_actions())

    def stats(self, access):
        graph = self.get_graph(access)
        return {"entities": len(graph["nodes"]), "relationships": len(graph["edges"]),
                "memories": len(self.list_memories(access, 100)),
                "actions": len(self.list_actions(access))}

    def retrieve(self, question, *, access, source_refs=(), run_id=None):
        self.access.require_member(access)
        agent = replace(access, purpose="agent", run_id=run_id, step_id=None)
        # Filter before any excerpts reach an agent/model. Human ownership of a
        # Finance original never confers agent access.
        raw = self.store.retrieve(question)
        context = self.access.filter_graph(agent, raw)
        context["prior_memories"] = self.access.filter_records(agent, raw.get("prior_memories", []))
        selected = self.evidence.retrieve(agent, source_refs, question=question) if source_refs else {}
        selected_ids = {r.source_id if hasattr(r, "source_id") else r["source_id"] for r in source_refs}
        context.update({key: selected.get(key, default) for key, default in (
            ("chunks", []), ("evidence_refs", []), ("truncated", False), ("missing", []))})
        context["truncated"] = bool(context["truncated"])
        context["selected_sources"] = list(selected_ids)
        grouped = {}
        for chunk in context["chunks"]:
            ref = chunk.get("evidence_ref", chunk)
            source_id = ref.get("source_id")
            if source_id not in selected_ids:
                continue
            group = grouped.setdefault(source_id, {"id": source_id,
                "title": ref.get("title", source_id), "excerpt": ""})
            group["excerpt"] += chunk.get("text", "") + "\n"
        selected_sources = list(grouped.values())
        remaining = 24000
        bounded = []
        for source in selected_sources + [s for s in context["sources"] if s["id"] not in selected_ids]:
            text = source.get("excerpt", "")
            if not text or remaining <= 0:
                continue
            excerpt = text[:remaining]
            context["truncated"] |= len(excerpt) < len(text)
            bounded.append({**source, "excerpt": excerpt})
            remaining -= len(excerpt)
        context["sources"] = bounded
        if run_id:
            self.access.require(access, "run_read", run_id)
            if self.run_context:
                output = self.run_context(access, run_id)
                readable = [item for item in output.get("outputs", [])
                            if self.access.can_read(agent, item["id"])]
                if len(readable) != len(output.get("outputs", [])):
                    output["results"] = [item for item in output.get("results", [])
                                         if item.get("tool") == "company_context"]
                output["outputs"] = readable
                context["permitted_run_outputs"] = output
        return context

    def save_investigation(self, result, *, access):
        self.access.require_member(access)
        if result.get("evidence_refs") and self.evidence:
            self.evidence.validate_refs(replace(access, purpose="agent"), result["evidence_refs"])
        for source_id in result.get("source_ids", []):
            self.access.require(replace(access, purpose="agent"), "source_read", source_id)
        for ref in result.get("evidence_refs", []):
            self.access.require(replace(access, purpose="agent"), "evidence_read", ref["chunk_id"])
        if result.get("run_id"):
            self.access.require(access, "run_read", result["run_id"])
        for identifier in result.get("output_ids", []):
            self.access.require(replace(access, purpose="agent", run_id=result.get("run_id")),
                                "artifact_read", identifier)
        payload = {**result, "requester_id": access.member_id,
                   "workspace_id": access.workspace_id}
        actions = []
        for action in result.get("actions", []):
            action = {**action, "requester_id": access.member_id, "workspace_id": access.workspace_id,
                      "status": "proposed", "record_kind": "legacy_manual"}
            actions.append({"id": action["id"], "payload": json.dumps(action),
                            "created_at": action["created_at"]})
        # Private access metadata is present in the same mutation that publishes
        # the text, so another request cannot see a temporarily public record.
        self.store.database.query(
            "CREATE (i:Investigation {id:$id,payload:$payload,created_at:$created,"
            "requester_id:$member,workspace_id:$workspace,classification:'general',"
            "audience:[$member],run_id:$run}) "
            "FOREACH (action IN $actions | CREATE (a:Action {id:action.id,payload:action.payload,"
            "status:'proposed',record_kind:'legacy_manual',created_at:action.created_at,"
            "investigation_id:$id,requester_id:$member,workspace_id:$workspace,"
            "classification:'general',audience:[$member]}) CREATE (i)-[:PROPOSES]->(a))",
            {"id": result["id"], "payload": json.dumps(payload), "created": result["created_at"],
             "member": access.member_id, "workspace": access.workspace_id,
             "run": result.get("run_id", ""), "actions": actions})
        self.store.database.query(
            "MATCH (i:Investigation {id:$id}),(s:Source) WHERE s.id IN $sources "
            "MERGE (i)-[:CITES]->(s)", {"id": result["id"], "sources": result.get("source_ids", [])})
        for ref in result.get("evidence_refs", []):
            self.store.database.query(
                "MATCH (i:Investigation {id:$id}),(v:SourceVersion {id:$version}),"
                "(c:SourceChunk {id:$chunk}) MERGE (i)-[:CITES_VERSION]->(v) "
                "MERGE (i)-[:CITES_CHUNK]->(c)",
                {"id": result["id"], "version": ref["version_id"], "chunk": ref["chunk_id"]})
        return result

    def transition_action(self, access, action_id, target_status):
        self.access.require(access, "action_update", action_id)
        return self.store.transition_action(action_id, target_status)

    def simulate(self, access, origin_id, mitigation=False):
        self.access.require(access, "graph_read", origin_id)
        # Ripple traverses only company entities. Reject a scope containing any
        # hidden entity/evidence before the legacy simulator can write proposals.
        raw = self.store.get_graph()
        visible = self.access.filter_graph(access, raw)
        if (len(raw["nodes"]) != len(visible["nodes"])
                or len(raw["edges"]) != len(visible["edges"])):
            raise AccessError("Ripple requires access to the complete company dependency map", 403)
        return self.store.simulate(origin_id, mitigation, access=access)
