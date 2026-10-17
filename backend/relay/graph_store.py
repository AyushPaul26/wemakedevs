"""FalkorDB-backed facts, directed scenario analysis, memory, and internal actions.

Cypher structure is static except relation names selected from a closed whitelist.
User values always travel as query parameters. JSON payloads preserve the public API
shape while indexed properties and explicit relationships support graph retrieval.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from falkordb import FalkorDB

from .seed import EDGES, NODES, SOURCES


KINDS = {"project", "service", "person", "team", "document", "decision", "incident"}
STATUSES = {"healthy", "at_risk", "blocked", "active", "resolved"}
RELATIONS = {
    "DEPENDS_ON", "BACKUP_FOR", "CAN_USE", "OWNED_BY", "MEMBER_OF", "DOCUMENTS",
    "APPROVES", "AFFECTED", "RESOLVED_WITH", "RELATED_TO", "CALLS", "IMPORTS", "CONTAINS",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class GraphStore:
    def __init__(self, graph_name=None):
        self._host = os.getenv("RELAY_FALKORDB_HOST", "127.0.0.1")
        self._port = int(os.getenv("RELAY_FALKORDB_PORT", "6379"))
        self._graph_name = graph_name or os.getenv("RELAY_FALKORDB_GRAPH", "relay_demo")
        self._db = None
        self._graph = None
        self._connection_lock = Lock()

    def _connect(self):
        # falkordb-py probes Redis during construction. Defer that probe so the
        # HTTP application can start and return a useful 503 while the DB is down.
        if self._graph is None:
            with self._connection_lock:
                if self._graph is None:
                    db = FalkorDB(host=self._host, port=self._port, socket_connect_timeout=3,
                                  socket_timeout=10)
                    graph = db.select_graph(self._graph_name)
                    self._db, self._graph = db, graph

    @property
    def db(self):
        self._connect()
        return self._db

    @property
    def graph(self):
        self._connect()
        return self._graph

    def _query(self, query, **params):
        return self.graph.query(query, params=params or None, timeout=5000).result_set

    def health(self):
        return self._query("RETURN 1")[0][0] == 1

    def seed(self):
        """Upsert only the named fictional facts; never clear user-created records."""
        for source in SOURCES:
            self._put_source(source)
        for node in NODES:
            self._put_entity(node)
        for edge in EDGES:
            self._put_edge(edge)

    def _put_source(self, source):
        self._query(
            "MERGE (s:Source {id:$id}) SET s.payload=$payload, s.search=$search, "
            "s.updated_at=$updated_at",
            id=source["id"], payload=_json(source),
            search=f"{source['title']} {source['excerpt']}".lower(), updated_at=source["updated_at"],
        )

    def _put_entity(self, node):
        self._query(
            "MERGE (n:Entity {id:$id}) SET n.payload=$payload, n.kind=$kind, n.status=$status, "
            "n.source_ids=$source_ids, n.search=$search",
            id=node["id"], payload=_json(node), kind=node["kind"], status=node["status"],
            source_ids=node["source_ids"],
            search=f"{node['label']} {node['description']} {node.get('owner', '')}".lower(),
        )
        self._query(
            "MATCH (n:Entity {id:$id}), (s:Source) WHERE s.id IN $sources "
            "MERGE (n)-[:EVIDENCED_BY]->(s)", id=node["id"], sources=node["source_ids"],
        )

    def _put_edge(self, edge):
        relation = edge["relation"]
        if relation not in RELATIONS:
            raise ValueError("Unsupported relationship type")
        self._query(
            "MATCH (a:Entity {id:$source}), (b:Entity {id:$target}) "
            f"MERGE (a)-[r:{relation} {{id:$id}}]->(b) "
            "SET r.payload=$payload, r.source_ids=$source_ids",
            source=edge["source"], target=edge["target"], id=edge["id"],
            payload=_json(edge), source_ids=edge["source_ids"],
        )

    def get_graph(self):
        nodes = self._query("MATCH (n:Entity) RETURN n.payload ORDER BY n.id")
        edges = self._query("MATCH (:Entity)-[r]->(:Entity) RETURN r.payload ORDER BY r.id")
        sources = self._query("MATCH (s:Source) RETURN s.payload ORDER BY s.id")
        return {"nodes": [json.loads(row[0]) for row in nodes],
                "edges": [json.loads(row[0]) for row in edges],
                "sources": [json.loads(row[0]) for row in sources]}

    def stats(self):
        # Relationships describe the visible company graph; action count includes
        # proposed, approved, and completed records, not just outstanding work.
        return {
            "entities": self._query("MATCH (n:Entity) RETURN count(n)")[0][0],
            "relationships": self._query("MATCH (:Entity)-[r]->(:Entity) RETURN count(r)")[0][0],
            "memories": self._query("MATCH (n:Investigation) RETURN count(n)")[0][0],
            "actions": self._query("MATCH (n:Action) RETURN count(n)")[0][0],
        }

    def get_source(self, source_id):
        rows = self._query("MATCH (s:Source {id:$id}) RETURN s.payload", id=source_id)
        return json.loads(rows[0][0]) if rows else None

    def add_source(self, title, content):
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError("Source title must contain 1–300 characters")
        if not isinstance(content, str) or not content.strip() or len(content) > 30000:
            raise ValueError("Source content must contain 1–30000 characters")
        source = {"id": f"source-{uuid4().hex}", "title": title.strip(), "type": "document",
                  "excerpt": content, "updated_at": _now(), "author": "Workspace upload"}
        self._put_source(source)
        return source

    def retrieve(self, question):
        """Bounded graph context; graph adjacency is evidence context, not causal impact."""
        stopwords = {"what", "when", "where", "which", "who", "does", "have", "with", "that",
                     "this", "the", "and", "our", "for", "can", "how", "are", "happens", "tell"}
        terms = [word for word in re.findall(r"[a-z0-9]+", question.lower())
                 if len(word) > 2 and word not in stopwords][:20]
        if any(word in terms for word in ("payments", "payment", "gateway", "outage")):
            terms.extend(["payment", "checkout", "incident", "backup"])
        if any(word in terms for word in ("previous", "before", "incident", "history")):
            terms.extend(["incident", "timeout", "backup"])
        if any(word in terms for word in ("launch", "atlas", "company", "meridian")):
            terms.extend(["atlas", "launch"])
        rows = self._query(
            "MATCH (n:Entity) WHERE n.id='atlas-launch' OR "
            "any(term IN $terms WHERE n.search CONTAINS term) "
            "RETURN n.id ORDER BY n.id LIMIT 16", terms=list(set(terms)),
        )
        anchors = [row[0] for row in rows]
        rows = self._query(
            "MATCH (n:Entity) WHERE n.id IN $anchors "
            "OPTIONAL MATCH (n)-[]-(neighbor:Entity) "
            "WITH collect(DISTINCT n.id) + collect(DISTINCT neighbor.id) AS ids "
            "UNWIND ids AS id WITH DISTINCT id "
            "MATCH (entity:Entity {id:id}) RETURN entity.payload ORDER BY entity.id LIMIT 30",
            anchors=anchors,
        )
        nodes = [json.loads(row[0]) for row in rows]
        ids = [node["id"] for node in nodes]
        rows = self._query(
            "MATCH (a:Entity)-[r]->(b:Entity) WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN r.payload ORDER BY r.id LIMIT 60", ids=ids,
        )
        edges = [json.loads(row[0]) for row in rows]
        source_ids = sorted({sid for item in nodes + edges for sid in item["source_ids"]})
        rows = self._query(
            "MATCH (s:Source) WHERE s.id IN $ids OR "
            "any(term IN $terms WHERE s.search CONTAINS term) "
            "RETURN s.payload ORDER BY s.id LIMIT 20", ids=source_ids, terms=list(set(terms)),
        )
        return {"nodes": nodes, "edges": edges, "sources": [json.loads(row[0]) for row in rows],
                "prior_memories": self.list_memories(limit=5)}

    def _impact_paths(self, origin_id, excluded):
        # Direction is dependent -> prerequisite. Return reversed lists for a
        # readable origin -> impacted service -> impacted launch display.
        rows = self._query(
            "MATCH p=(dependent:Entity)-[:DEPENDS_ON*1..]->(origin:Entity {id:$origin}) "
            "WHERE dependent.id <> $origin AND "
            "all(edge IN relationships(p) WHERE NOT (edge.id IN $excluded)) "
            "RETURN [node IN nodes(p) | node.id], "
            "[edge IN relationships(p) | edge.source_ids] ORDER BY dependent.id",
            origin=origin_id, excluded=excluded,
        )
        paths = sorted({tuple(reversed(row[0])) for row in rows}, key=lambda path: (len(path), path))
        citations = {sid for row in rows for source_ids in row[1] for sid in source_ids}
        return [list(path) for path in paths], citations

    def simulate(self, origin_id, mitigation=False):
        rows = self._query("MATCH (n:Entity {id:$id}) RETURN n.payload", id=origin_id)
        if not rows or (origin := json.loads(rows[0][0]))["kind"] != "service":
            raise ValueError("Ripple origin must be an existing service node")
        baseline_paths, citations = self._impact_paths(origin_id, [])
        baseline_affected = sorted({path[-1] for path in baseline_paths})
        excluded = []
        assumptions = ["Dependency exposure counts show reachable dependents, not outage probability or financial loss."]
        if mitigation:
            backups = self._query(
                "MATCH (consumer:Entity)-[dep:DEPENDS_ON]->(origin:Entity {id:$origin}), "
                "(consumer)-[usable:CAN_USE]->(backup:Entity)-[fallback:BACKUP_FOR]->(origin) "
                "WHERE backup.status='healthy' "
                "RETURN dep.id, consumer.payload, backup.payload, usable.source_ids, fallback.source_ids",
                origin=origin_id,
            )
            for dep_id, consumer_json, backup_json, usable_sources, fallback_sources in backups:
                consumer, backup = json.loads(consumer_json), json.loads(backup_json)
                citations.update(usable_sources + fallback_sources)
                if backup["id"] == origin_id or backup["id"] in baseline_affected:
                    assumptions.append(f"{backup['label']} is also exposed to this outage through its "
                                       "dependencies, so it cannot support the recovery assumption.")
                    continue
                excluded.append(dep_id)
                assumptions.append(f"Assume {consumer['label']} successfully switches to {backup['label']} "
                                   "after its owner validates the documented failover. Other dependencies remain unchanged.")
            if not excluded:
                assumptions.append("No healthy, unexposed documented backup path supports mitigation for this service.")
        paths, remaining_citations = self._impact_paths(origin_id, excluded)
        citations.update(remaining_citations)
        citations.update(origin["source_ids"])
        affected = sorted({path[-1] for path in paths})
        scenario_id = f"ripple-{origin_id}-{'backup' if mitigation else 'baseline'}"
        source_ids = sorted(citations)
        summary = (f"{origin['label']} disruption exposes {len(affected)} dependent "
                   f"{'entity' if len(affected) == 1 else 'entities'}")
        if mitigation and excluded:
            summary += f", down from {len(baseline_affected)} under the documented backup assumption"
        summary += ". This is a hypothetical dependency count; authoritative graph facts are unchanged."
        self._query(
            "MERGE (s:Scenario {id:$id}) SET s.origin_id=$origin, s.mitigation=$mitigation "
            "WITH s MATCH (n:Entity {id:$origin}) MERGE (s)-[:ABOUT]->(n)",
            id=scenario_id, origin=origin_id, mitigation=mitigation,
        )
        actions = [{
            "id": f"{scenario_id}-owner-review", "title": f"Validate {origin['label']} recovery",
            "description": ("Review source evidence and confirm recovery assumptions with the service owner. "
                            "This internal task does not execute a failover or contact anyone."),
            "owner": origin.get("owner", "Service owner"), "status": "proposed",
            "investigation_id": scenario_id, "source_ids": source_ids, "created_at": _now(),
        }]
        if affected:
            actions.append({
                "id": f"{scenario_id}-impact-review", "title": "Review remaining dependency exposure",
                "description": f"Review {', '.join(affected)} with the affected owners before changing launch readiness.",
                "owner": "Mara Chen" if "atlas-launch" in baseline_affected else origin.get("owner", "Service owner"),
                "status": "proposed", "investigation_id": scenario_id,
                "source_ids": source_ids, "created_at": _now(),
            })
        self.save_actions(actions)
        stored_actions = [self._get_action(action["id"]) for action in actions]
        return {"scenario_id": scenario_id, "origin_id": origin_id, "mitigation": mitigation,
                "affected_ids": affected, "paths": paths, "summary": summary, "source_ids": source_ids,
                "actions": stored_actions, "risk_before": len(baseline_affected),
                "risk_after": len(affected), "assumptions": assumptions}

    def save_investigation(self, investigation):
        self.save_actions(investigation.get("actions", []))
        self._query(
            "MERGE (i:Investigation {id:$id}) SET i.payload=$payload, i.created_at=$created_at",
            id=investigation["id"], payload=_json(investigation), created_at=investigation["created_at"],
        )
        self._query(
            "MATCH (i:Investigation {id:$id}), (s:Source) WHERE s.id IN $sources "
            "MERGE (i)-[:CITES]->(s)", id=investigation["id"], sources=investigation["source_ids"],
        )
        self._query(
            "MATCH (i:Investigation {id:$id}), (n:Entity) WHERE n.id IN $nodes "
            "MERGE (i)-[:ABOUT]->(n)", id=investigation["id"], nodes=investigation["node_ids"],
        )
        self._query(
            "MATCH (i:Investigation {id:$id}), (a:Action) WHERE a.investigation_id=$id "
            "MERGE (i)-[:PROPOSES]->(a)", id=investigation["id"],
        )
        return self._hydrate_memory(investigation)

    def _hydrate_memory(self, investigation):
        result = dict(investigation)
        result["actions"] = [self._get_action(item["id"]) or item for item in result.get("actions", [])]
        return result

    def list_memories(self, limit=30):
        limit = max(0, min(int(limit), 100))
        rows = self._query(
            "MATCH (i:Investigation) RETURN i.payload ORDER BY i.created_at DESC, i.id DESC LIMIT $limit",
            limit=limit,
        )
        return [self._hydrate_memory(json.loads(row[0])) for row in rows]

    def save_actions(self, actions):
        for action in actions:
            if action.get("status", "proposed") not in {"proposed", "approved", "done"}:
                raise ValueError("Unsupported action status")
            # Creation is always a proposal. Only transition_action can approve it.
            self._query(
                "MERGE (a:Action {id:$id}) ON CREATE SET a.payload=$payload, a.status='proposed', "
                "a.created_at=$created_at, a.investigation_id=$investigation_id",
                id=action["id"], payload=_json(action), created_at=action["created_at"],
                investigation_id=action["investigation_id"],
            )
            self._query(
                "MATCH (a:Action {id:$id}), (s:Source) WHERE s.id IN $sources "
                "MERGE (a)-[:CITES]->(s)", id=action["id"], sources=action["source_ids"],
            )
            self._query(
                "MATCH (s:Scenario {id:$scenario}), (a:Action {id:$id}) MERGE (s)-[:PROPOSES]->(a)",
                scenario=action["investigation_id"], id=action["id"],
            )

    @staticmethod
    def _action_from_row(row):
        result = json.loads(row[0])
        result["status"] = row[1]
        if row[2]:
            result["approved_at"] = row[2]
        else:
            result.pop("approved_at", None)
        return result

    def _get_action(self, action_id):
        rows = self._query(
            "MATCH (a:Action {id:$id}) RETURN a.payload, a.status, a.approved_at", id=action_id,
        )
        return self._action_from_row(rows[0]) if rows else None

    def list_actions(self):
        rows = self._query(
            "MATCH (a:Action) RETURN a.payload, a.status, a.approved_at ORDER BY a.created_at DESC, a.id"
        )
        return [self._action_from_row(row) for row in rows]

    def transition_action(self, action_id, target_status):
        allowed = {"approved": ["proposed", "approved"], "done": ["approved", "done"]}
        if target_status not in allowed:
            raise ValueError("Actions may only transition to approved or done")
        rows = self._query(
            "MATCH (a:Action {id:$id}) WHERE a.status IN $allowed "
            "SET a.status=$target, a.approved_at=CASE WHEN $target='approved' AND "
            "a.approved_at IS NULL THEN $now ELSE a.approved_at END "
            "RETURN a.payload, a.status, a.approved_at",
            id=action_id, allowed=allowed[target_status], target=target_status, now=_now(),
        )
        if rows:
            return self._action_from_row(rows[0])
        if self._get_action(action_id) is None:
            raise KeyError(action_id)
        raise ValueError("Only proposed actions can be approved and only approved actions can be completed")

    def import_graphify(self, data, source_name):
        """Import a bounded Graphify graph into a provenance-isolated namespace.

        Accepted format: nodes [{id,label,kind,description?}] and edges
        [{source,target,relation}]. Imported relation names never become arbitrary Cypher.
        """
        if not isinstance(data, dict) or not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("A graph object and source name are required")
        raw_nodes, raw_edges = data.get("nodes", []), data.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise ValueError("Graph nodes and edges must be lists")
        if len(raw_nodes) > 500 or len(raw_edges) > 1000 or len(_json(data)) > 300000:
            raise ValueError("Graphify import exceeds the 500-node, 1000-edge, or 300 KB limit")
        namespace = "graphify-" + hashlib.sha256(source_name.encode()).hexdigest()[:12]
        source_id = f"{namespace}-source"
        normalized_nodes, normalized_edges, ids = [], [], set()
        for index, raw in enumerate(raw_nodes):
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
                raise ValueError("Each imported node needs a nonempty string id")
            if raw["id"] in ids:
                raise ValueError("Imported node IDs must be unique")
            ids.add(raw["id"])
            kind, status = raw.get("kind", "document"), raw.get("status", "active")
            if (not isinstance(kind, str) or not isinstance(status, str)
                    or kind not in KINDS or status not in STATUSES):
                raise ValueError("Unsupported imported node kind or status")
            label, description = raw.get("label", raw["id"]), raw.get("description", "Imported Graphify entity")
            if not isinstance(label, str) or not isinstance(description, str):
                raise ValueError("Imported labels and descriptions must be strings")
            normalized_nodes.append({"id": f"{namespace}-{raw['id']}", "label": label, "kind": kind,
                                     "description": description, "status": status, "source_ids": [source_id],
                                     "x": (index % 5) * 250, "y": (index // 5) * 150})
        for raw in raw_edges:
            if not isinstance(raw, dict):
                raise ValueError("Each imported edge must be an object")
            relation = raw.get("relation", "RELATED_TO")
            if not isinstance(relation, str) or relation not in RELATIONS:
                raise ValueError("Unsupported imported relationship type")
            if (not isinstance(raw.get("source"), str) or not isinstance(raw.get("target"), str)
                    or raw["source"] not in ids or raw["target"] not in ids):
                raise ValueError("Imported edge endpoints must refer to imported nodes")
            source, target = f"{namespace}-{raw['source']}", f"{namespace}-{raw['target']}"
            edge_id = hashlib.sha256(f"{source}:{relation}:{target}".encode()).hexdigest()[:24]
            normalized_edges.append({"id": f"{namespace}-edge-{edge_id}", "source": source,
                                     "target": target, "relation": relation,
                                     "label": relation.lower().replace("_", " "), "source_ids": [source_id]})
        # Validate the entire import before the first write.
        self._put_source({"id": source_id, "title": source_name.strip(), "type": "code",
                          "excerpt": "Graphify import; supplied graph structure, not semantic extraction.\n" + _json(data),
                          "updated_at": _now(), "author": "Graphify import"})
        for node in normalized_nodes:
            self._put_entity(node)
        for edge in normalized_edges:
            self._put_edge(edge)
        return {"nodes": len(normalized_nodes), "edges": len({edge['id'] for edge in normalized_edges})}
