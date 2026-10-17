"""Researcher → Planner → Archivist, with durable workflow and company memory."""

import asyncio
import json
import re
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, uuid4, uuid5
from weakref import WeakValueDictionary

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from relay.llm import OpenAICompatibleClient, get_model_config, validate_plan
from relay.access import AccessContext


class _State(TypedDict, total=False):
    question: str
    investigation_id: str
    created_at: str
    context: dict
    plan: dict
    steps: list[dict]
    result: dict
    turn: int
    investigation_ids: list[str]
    access: dict | None
    source_refs: list[dict]
    run_id: str | None


def _unique(values):
    return list(dict.fromkeys(values))


def _demo_plan(question: str, context: dict) -> dict:
    """Compose evidence from typed graph relationships; no model call is represented."""
    if context.get("permitted_run_outputs"):
        run = context["permitted_run_outputs"]
        paragraphs = [f"Guided demo: this review is {run['status'].replace('_', ' ')}."]
        for decision in run.get("decisions", []):
            paragraphs.append(f"{decision['gate_kind'].replace('_', ' ').capitalize()}: "
                              f"{decision['status'].replace('_', ' ')}.")
        for step in run.get("results", []):
            result = step.get("result", {})
            comparison = result.get("comparison")
            if comparison:
                paragraphs.append(f"The report records a difference of {comparison['difference']} "
                                  f"{comparison['currency']}. This alone does not establish a launch blocker.")
            else:
                paragraphs.append(f"{step['tool'].replace('_', ' ').capitalize()}: "
                    f"{step['status'].replace('_', ' ')}. " + json.dumps(result, ensure_ascii=False)[:1500])
        if not run.get("outputs"):
            paragraphs.append("No permitted completed report is available yet.")
        return {"answer": "\n\n".join(paragraphs), "source_ids": [], "node_ids": [], "actions": [],
                "output_ids": [item["id"] for item in run.get("outputs", [])]}
    if context.get("selected_sources"):
        refs = context.get("evidence_refs", [])
        sources = [s for s in context["sources"] if s["id"] in context["selected_sources"]]
        paragraphs = ["Guided demo: these are retrieved excerpts from your selected files. "
                      "A live model is needed to interpret a free-form question about them."]
        paragraphs.extend(f"{s['title']}: {s.get('excerpt', '')} [{s['id']}]" for s in sources)
        if context.get("truncated"):
            paragraphs.append("The evidence context is truncated; this is not an exhaustive file review.")
        if context.get("missing"):
            paragraphs.append("Some selected files have no readable extracted text yet.")
        return {"answer": "\n\n".join(paragraphs), "source_ids": [s["id"] for s in sources],
                "node_ids": [], "actions": [], "evidence_refs": refs}
    query = question.casefold()
    supported = re.search(
        r"launch|atlas|meridian|compan|payment|checkout|owner|owns|responsib|incident|"
        r"previous|earlier|block|dependenc|depend[sz]? on|team|what changed", query
    )
    if not supported:
        return {"answer": "This guided demo answers questions about the sample company's launch, "
                "payment dependencies, owners, and previous incidents. Try “What blocks the Atlas "
                "launch?”, “Who owns payments?”, or “What happened in the previous payment incident?”. "
                "A configured model can investigate other questions using the available company evidence.",
                "source_ids": [], "node_ids": [], "actions": []}

    nodes = {node["id"]: node for node in context["nodes"]}
    sources = {source["id"]: source for source in context["sources"]}
    cited: list[str] = []
    included: list[str] = []
    paragraphs: list[str] = []
    proposals: list[dict] = []

    def cite(item):
        evidence_ids = [source_id for source_id in item.get("source_ids", []) if source_id in sources]
        cited.extend(evidence_ids)
        return " ".join(f"[{source_id}]" for source_id in evidence_ids[:2])

    def include(node):
        included.append(node["id"])
        return cite(node)

    ownership = bool(re.search(r"owner|owns|responsib", query))
    history = bool(re.search(r"incident|previous|earlier", query))
    if ownership:
        owned = [node for node in nodes.values()
                 if node.get("owner") and node["kind"] in {"service", "project", "team"}]
        if "payment" in query:
            matches = [node for node in owned if "payment" in f"{node['id']} {node['label']}".casefold()]
            owned = matches or owned
        elif "launch" in query:
            owned = [node for node in owned if node["kind"] == "project"] or owned
        paragraphs.extend(f"{node['label']} is owned by {node['owner']}. {include(node)}"
                          for node in owned[:6])

    if history:
        incidents = [node for node in nodes.values() if node["kind"] == "incident"]
        for incident in incidents[:2]:
            evidence = [sources[sid] for sid in incident.get("source_ids", []) if sid in sources]
            if evidence:
                paragraphs.append(f"{incident['label']}: {evidence[0]['excerpt']} {include(incident)}")
            else:
                paragraphs.append(f"{incident['label']}: {incident.get('description', '')} {include(incident)}")
        if incidents:
            paragraphs.append("This is a recorded past outcome, not a guarantee of future recovery time.")

    if not ownership and not history:
        dependencies = [edge for edge in context["edges"] if edge["relation"] == "DEPENDS_ON"
                        and edge["source"] in nodes and edge["target"] in nodes]
        risky = [node for node in nodes.values() if node["kind"] == "service"
                 and node["status"] in {"at_risk", "blocked"}]
        if "payment" in query:
            payment = [node for node in nodes.values() if node["kind"] == "service"
                       and "payment" in f"{node['id']} {node['label']}".casefold()]
            risky = payment or risky
        if not risky:
            projects = [node for node in nodes.values() if node["kind"] == "project"]
            if projects:
                paragraphs.append("In the retrieved graph, no service is currently marked blocked or at risk. "
                                  "Launch dependencies still need their recorded owners' readiness review.")
            for project in projects[:3]:
                paragraphs.append(f"{project['label']} is recorded as {project['status'].replace('_', ' ')}. "
                                  f"{project.get('description', '')} {include(project)}")
                required = [edge for edge in dependencies if edge["source"] == project["id"]]
                if required:
                    labels = []
                    evidence_ids = list(project.get("source_ids", []))
                    for edge in required:
                        prerequisite = nodes[edge["target"]]
                        owner = f" ({prerequisite['owner']})" if prerequisite.get("owner") else ""
                        labels.append(prerequisite["label"] + owner)
                        include(prerequisite)
                        cite(edge)
                        evidence_ids.extend(edge["source_ids"])
                    evidence_ids = _unique(sid for sid in evidence_ids if sid in sources)
                    paragraphs.append("Required launch dependencies: " + ", ".join(labels) + ". "
                                      + " ".join(f"[{sid}]" for sid in evidence_ids[:2]))
                    if project.get("owner") and evidence_ids:
                        proposals.append({"title": f"Confirm {project['label']} readiness",
                                          "description": "Review the documented dependency sign-offs with "
                                          "their owners before approving the launch readiness decision.",
                                          "owner": project["owner"], "source_ids": evidence_ids})
        for origin in risky[:3]:
            owner = f"; owner: {origin['owner']}" if origin.get("owner") else ""
            paragraphs.append(f"{origin['label']} is recorded as {origin['status'].replace('_', ' ')}{owner}. "
                              f"{include(origin)}")
            paths = []
            queue = deque([[origin["id"]]])
            while queue and len(paths) < 12:
                path = queue.popleft()
                next_edges = [edge for edge in dependencies if edge["target"] == path[-1]
                              and edge["source"] not in path]
                if len(path) > 1 and (not next_edges or nodes[path[-1]]["kind"] == "project"):
                    paths.append(path)
                if len(path) < 8:
                    queue.extend(path + [edge["source"]] for edge in next_edges)
            for path in paths:
                for node_id in path:
                    include(nodes[node_id])
                path_edges = [edge for edge in dependencies
                              if (edge["target"], edge["source"]) in list(zip(path, path[1:]))]
                citations = _unique([sid for edge in path_edges for sid in edge["source_ids"] if sid in sources])
                cited.extend(citations)
                paragraphs.append("Recorded dependency impact: " + " → ".join(nodes[nid]["label"] for nid in path)
                                  + ". An outage can affect these dependents. "
                                  + " ".join(f"[{sid}]" for sid in citations[:2]))
            backups = [edge for edge in context["edges"] if edge["relation"] == "BACKUP_FOR"
                       and edge["target"] == origin["id"] and edge["source"] in nodes]
            for edge in backups:
                backup = nodes[edge["source"]]
                consumers = [usage for usage in context["edges"] if usage["relation"] == "CAN_USE"
                             and usage["target"] == backup["id"] and usage["source"] in nodes]
                for usage in consumers[:2]:
                    consumer = nodes[usage["source"]]
                    paragraphs.append(f"{consumer['label']} can use {backup['label']} as a documented "
                                      f"mitigation. Recovery remains a scenario assumption until an owner "
                                      f"validates it. {include(backup)} {include(consumer)} {cite(edge)} {cite(usage)}")
            if origin.get("owner") and origin.get("source_ids"):
                evidence_ids = [sid for sid in origin["source_ids"] if sid in sources]
                if evidence_ids:
                    proposals.append({"title": f"Review {origin['label']} readiness",
                                      "description": "Review the cited dependency evidence and recovery plan; "
                                      "confirm readiness with the recorded owner before changing the launch plan.",
                                      "owner": origin["owner"], "source_ids": evidence_ids})

    if not paragraphs:
        return {"answer": "The retrieved sample graph does not contain enough evidence to answer this "
                "question. Try asking about launch dependencies, payment owners, or the previous incident.",
                "source_ids": [], "node_ids": [], "actions": []}
    if proposals:
        paragraphs.append("The follow-up tasks below are proposals awaiting your approval; no work has been executed.")
    return {"answer": "\n\n".join(paragraphs), "source_ids": _unique(cited),
            "node_ids": _unique(included), "actions": proposals}


class InvestigationService:
    def __init__(self, store: Any, checkpoint_path: str | Path = ".data/checkpoints.sqlite", model_client=None):
        self.store = store
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        config = get_model_config()
        self._owns_model = model_client is None and config.mode == "live"
        self.model_client = model_client or (OpenAICompatibleClient(config) if self._owns_model else None)
        self.mode = "live" if self.model_client is not None else "demo"
        self.provider = getattr(getattr(self.model_client, "config", config), "provider", "OpenAI-compatible")
        self._session_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def _research(self, state: _State) -> dict:
        access = AccessContext(**state["access"]) if state.get("access") else None
        if access is None:
            context = await asyncio.to_thread(self.store.retrieve, state["question"])
        else:
            context = await asyncio.to_thread(self.store.retrieve, state["question"], access=access,
                source_refs=state.get("source_refs", []), run_id=state.get("run_id"))
        previous = len(context.get("prior_memories", []))
        turn = state.get("turn", 0) + 1
        return {"context": context, "turn": turn, "steps": [{"agent": "Researcher",
                "label": "Evidence retrieved", "detail": f"Read {len(context['nodes'])} graph entities and "
                f"{len(context['sources'])} sources; found {previous} previous investigations. Session turn {turn}.",
                "status": "complete"}]}

    async def _plan(self, state: _State) -> dict:
        if self.model_client:
            plan = await self.model_client.generate(state["question"], state["context"])
            plan = validate_plan(plan, state["context"])
        else:
            plan = _demo_plan(state["question"], state["context"])
        detail = ("Synthesized the retrieved evidence with the configured model." if self.model_client else
                  "Guided demo: composed the answer from recorded dependencies, owners, and source excerpts.")
        return {"plan": plan, "steps": state["steps"] + [{"agent": "Planner", "label": "Evidence reviewed",
                "detail": detail + f" Prepared {len(plan['actions'])} proposals awaiting approval.", "status": "complete"}]}

    async def _archive(self, state: _State) -> dict:
        actions = [{**proposal, "id": f"action-{uuid5(NAMESPACE_URL, state['investigation_id'] + ':' + str(i))}",
                    "status": "proposed", "investigation_id": state["investigation_id"],
                    "created_at": state["created_at"]} for i, proposal in enumerate(state["plan"]["actions"])]
        steps = state["steps"] + [{"agent": "Archivist", "label": "Memory saved",
                 "detail": "Saved the investigation and proposed follow-ups to FalkorDB. "
                 "Task approval remains a separate human action.", "status": "complete"}]
        result = {"id": state["investigation_id"], "question": state["question"],
                  "answer": state["plan"]["answer"], "source_ids": state["plan"]["source_ids"],
                  "node_ids": state["plan"]["node_ids"], "steps": steps, "actions": actions,
                  "created_at": state["created_at"], "mode": self.mode}
        if state["plan"].get("evidence_refs"):
            result["evidence_refs"] = state["plan"]["evidence_refs"]
        if state["plan"].get("output_ids"):
            result["output_ids"] = state["plan"]["output_ids"]
        if state.get("run_id"):
            result["run_id"] = state["run_id"]
        access = AccessContext(**state["access"]) if state.get("access") else None
        if access is None:
            await asyncio.to_thread(self.store.save_actions, actions)
            await asyncio.to_thread(self.store.save_investigation, result)
        else:
            for action in actions:
                action.update(requester_id=access.member_id, workspace_id=access.workspace_id,
                              evidence_refs=result.get("evidence_refs", []))
            result.update(requester_id=access.member_id, workspace_id=access.workspace_id)
            await asyncio.to_thread(self.store.save_investigation, result, access=access)
        return {"result": result, "steps": steps,
                "investigation_ids": (state.get("investigation_ids", []) + [result["id"]])[-100:]}

    async def investigate(self, question: str, session_id: str | None = None, *, access=None,
                          source_refs=(), run_id=None) -> dict:
        question = question.strip()
        if not question or len(question) > 2000:
            raise ValueError("Question must contain between 1 and 2000 characters.")
        thread_id = session_id or str(uuid4())
        if access is not None:
            thread_id = f"{access.workspace_id}:{access.member_id}:{thread_id}"
        # Each active request keeps its lock alive; idle sessions need no in-memory registry.
        lock = self._session_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            async with AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                workflow = StateGraph(_State)
                workflow.add_node("researcher", self._research)
                workflow.add_node("planner", self._plan)
                workflow.add_node("archivist", self._archive)
                workflow.add_edge(START, "researcher")
                workflow.add_edge("researcher", "planner")
                workflow.add_edge("planner", "archivist")
                workflow.add_edge("archivist", END)
                graph = workflow.compile(checkpointer=saver)
                state = await graph.ainvoke(
                    {"question": question, "investigation_id": f"investigation-{uuid4()}",
                     "created_at": datetime.now(timezone.utc).isoformat(),
                     "access": asdict(access) if access else None,
                     "source_refs": [r.model_dump() if hasattr(r, "model_dump") else r
                                     for r in source_refs], "run_id": run_id},
                    {"configurable": {"thread_id": thread_id}},
                )
                return state["result"]

    async def aclose(self) -> None:
        if self._owns_model:
            await self.model_client.aclose()
