"""Graphify's directed metadata must survive its undirected export wrapper."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from relay.graphify_adapter import load_graphify_file, normalize_graphify


def exported_graph(edge_key="links"):
    return {
        "directed": False,
        "nodes": [
            {"id": "checkout", "label": "Checkout", "type": "service"},
            {"id": "payments", "label": "charge()", "type": "function",
             "source_file": "src/payments.py", "source_location": "L42"},
        ],
        edge_key: [
            {"source": "payments", "target": "checkout", "_src": "checkout",
             "_tgt": "payments", "relation": "calls", "source_file": "src/checkout.py",
             "source_location": "L8", "confidence": "EXTRACTED"},
        ],
    }


@pytest.mark.parametrize("edge_key", ["links", "edges"])
def test_preserves_true_direction_and_code_provenance(edge_key):
    result = normalize_graphify(exported_graph(edge_key))
    assert result["edges"][0]["source"] == "checkout"
    assert result["edges"][0]["target"] == "payments"
    assert result["edges"][0]["relation"] == "CALLS"
    assert result["edges"][0]["source_location"] == "L8"
    assert result["nodes"][1]["source_file"] == "src/payments.py"
    assert result["nodes"][1]["source_location"] == "L42"
    assert result["nodes"][1]["node_type"] == "function"
    assert result["nodes"][1]["kind"] == "document"
    assert result["nodes"][0]["kind"] == "service"


def test_only_explicit_dependencies_enter_outage_traversals():
    raw = exported_graph()
    for relation, expected in [("imports_from", "IMPORTS"), ("contains", "CONTAINS"),
                               ("uses", "RELATED_TO"), ("related_to", "RELATED_TO"),
                               ("depends_on", "DEPENDS_ON")]:
        raw["links"][0]["relation"] = relation
        edge = normalize_graphify(raw)["edges"][0]
        assert edge["relation"] == expected
        assert edge["original_relation"] == relation


def test_normalizes_nested_metadata_without_reading_referenced_file():
    raw = exported_graph()
    raw["nodes"][1] = {"id": "payments", "metadata": {
        "node_type": "function", "file_path": "/not/a/real/repo/payments.py", "line": 27}}
    node = normalize_graphify(raw)["nodes"][1]
    assert node["source_file"] == "/not/a/real/repo/payments.py"
    assert node["source_location"] == "L27"
    assert node["node_type"] == "function"


@pytest.mark.parametrize("mutation,match", [
    (lambda d: d["nodes"].append(dict(d["nodes"][0])), "unique"),
    (lambda d: d["links"][0].update(target="missing"), "endpoints"),
    (lambda d: d["links"][0].pop("_tgt"), "together"),
    (lambda d: d["links"][0].update(_src="payments", _tgt="payments"), "endpoints"),
    (lambda d: d["nodes"][0].update(id="bad\x00id"), "control"),
    (lambda d: d["nodes"][0].update(label={"not": "text"}), "string"),
    (lambda d: d.update(nodes=[{"id": str(i)} for i in range(501)]), "500"),
    (lambda d: d.update(links=d["links"] * 1001), "1000"),
    (lambda d: d.update(edges=[]), "both"),
])
def test_rejects_invalid_export_before_import(mutation, match):
    raw = exported_graph()
    mutation(raw)
    with pytest.raises(ValueError, match=match):
        normalize_graphify(raw)


def test_relationship_names_cannot_become_arbitrary_query_types():
    raw = exported_graph()
    raw["links"][0]["relation"] = "TYPE`) DELETE n //"
    edge = normalize_graphify(raw)["edges"][0]
    assert edge["relation"] == "RELATED_TO"
    assert edge["original_relation"] == "TYPE`) DELETE n //"


def test_reader_requires_local_regular_utf8_json_file(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(exported_graph()))
    assert load_graphify_file(graph)["nodes"][0]["label"] == "Checkout"
    with pytest.raises(ValueError, match="regular file"):
        load_graphify_file(tmp_path)
    graph.write_text('{"nodes": [], "nodes": [], "edges": []}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_graphify_file(graph)
    graph.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="2 MiB"):
        load_graphify_file(graph)


def test_cli_validation_does_not_require_running_database(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(exported_graph()))
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/import_graphify.py"), str(graph),
         "--source-name", "checkout-example", "--validate-only"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"validated": True, "nodes": 2, "edges": 1}
