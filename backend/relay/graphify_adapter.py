"""Bounded, dependency-free reader for Graphify node-link JSON exports.

Graphify writes undirected wrappers while retaining directional arc metadata.
Read that metadata directly; loading into an undirected graph first loses it.
"""

import json
import stat
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_BYTES = 300_000
KINDS = {"project", "service", "person", "team", "document", "decision", "incident"}
RELATIONS = {
    "depends_on": "DEPENDS_ON",
    "calls": "CALLS",
    "imports": "IMPORTS",
    "imports_from": "IMPORTS",
    "contains": "CONTAINS",
}


def _text(value, field, limit=512, *, multiline=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    allowed = {"\n", "\r", "\t"} if multiline else set()
    if any((ord(char) < 32 or ord(char) == 127) and char not in allowed for char in value):
        raise ValueError(f"{field} contains unsupported control characters")
    return value.strip()


def _first(raw, *keys, default=None):
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Graphify metadata must be an object")
    for values in (raw, metadata):
        for key in keys:
            if values.get(key) is not None and values[key] != "":
                return values[key]
    return default


def _provenance(raw):
    result = {}
    source_file = _first(raw, "source_file", "file_path", "file", "path")
    if source_file is not None:
        result["source_file"] = _text(source_file, "source_file", 2048)
    location = _first(raw, "source_location")
    line = _first(raw, "line", "line_number")
    if location is not None:
        result["source_location"] = _text(location, "source_location", 80)
    elif line is not None:
        if type(line) is not int or not 1 <= line <= 10_000_000:
            raise ValueError("line must be a positive integer no greater than 10000000")
        result["source_location"] = f"L{line}"
    confidence = _first(raw, "confidence")
    if confidence is not None:
        result["confidence"] = _text(confidence, "confidence", 80)
    return result


def normalize_graphify(data):
    """Return GraphStore's whitelist format, preserving selected source metadata.

    Code symbols map to document nodes, rather than pretending every function
    is an operational service. Unknown relations remain noncausal RELATED_TO.
    """
    if not isinstance(data, dict):
        raise ValueError("Graphify export must be a JSON object")
    if "links" in data and "edges" in data:
        raise ValueError("Export cannot contain both links and edges; choose one collection")
    nodes = data.get("nodes")
    edges = data.get("links", data.get("edges"))
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Graphify export requires nodes and links (or edges) lists")
    if len(nodes) > 500 or len(edges) > 1000:
        raise ValueError("Graphify import is limited to 500 nodes and 1000 edges")
    result = {"nodes": [], "edges": []}
    ids = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ValueError("Each Graphify node must be an object")
        node_id = _text(raw.get("id"), "node id", 256)
        if node_id in ids:
            raise ValueError("Graphify node IDs must be unique")
        ids.add(node_id)
        node_type = _text(_first(raw, "node_type", "kind", "type", default="code"),
                          "node_type", 80)
        description = _first(raw, "description", default=f"Imported Graphify {node_type}.")
        node = {
            "id": node_id,
            "label": _text(_first(raw, "label", "name", default=node_id), "node label"),
            "kind": node_type.lower() if node_type.lower() in KINDS else "document",
            "description": _text(description, "description", 4000, multiline=True),
            "status": "active",
            "node_type": node_type,
            **_provenance(raw),
        }
        result["nodes"].append(node)
    for raw in edges:
        if not isinstance(raw, dict):
            raise ValueError("Each Graphify edge must be an object")
        source = _text(raw.get("source"), "edge source", 256)
        target = _text(raw.get("target"), "edge target", 256)
        if source not in ids or target not in ids:
            raise ValueError("Graphify edge endpoints must refer to imported nodes")
        if ("_src" in raw) != ("_tgt" in raw):
            raise ValueError("Graphify _src and _tgt direction markers must appear together")
        if "_src" in raw:
            true_source = _text(raw["_src"], "edge _src", 256)
            true_target = _text(raw["_tgt"], "edge _tgt", 256)
            if sorted((true_source, true_target)) != sorted((source, target)):
                raise ValueError("Graphify direction markers must match the edge endpoints")
            source, target = true_source, true_target
        relation = _text(_first(raw, "relation", "type", default="related_to"),
                         "edge relation", 80)
        result["edges"].append({
            "source": source, "target": target,
            "relation": RELATIONS.get(relation.lower(), "RELATED_TO"),
            "original_relation": relation,
            **_provenance(raw),
        })
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError("Normalized Graphify import exceeds 300 KB; export a smaller scope")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonfinite JSON value {value} is unsupported")


def load_graphify_file(path):
    """Read only the explicitly supplied regular file, never referenced paths."""
    path = Path(path)
    try:
        details = path.stat()
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("Graphify input must be a local regular file")
        if details.st_size > MAX_FILE_BYTES:
            raise ValueError("Graphify input exceeds the 2 MiB file limit")
        with path.open("rb") as handle:
            contents = handle.read(MAX_FILE_BYTES + 1)
        if len(contents) > MAX_FILE_BYTES:
            raise ValueError("Graphify input exceeds the 2 MiB file limit")
        data = json.loads(contents.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Could not read Graphify export: supply a local UTF-8 JSON file") from exc
    return normalize_graphify(data)
