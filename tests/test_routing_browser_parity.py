"""Check browser routing semantics against the canonical Python graph solver."""
from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import build_routing_graph, validate_connectivity
from quadrilla_solver.model import PortRef, load_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
CATALOG_DATA = CATALOG.raw

NODE_SCRIPT = r"""
const fs = require("node:fs");
const {buildGraph, trace} = require("./viewer/routing.js");
const {layout, catalog, source, sink} = JSON.parse(fs.readFileSync(0, "utf8"));
const graph = buildGraph(layout, catalog);
process.stdout.write(JSON.stringify({graph, result: trace(graph, source, sink)}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for parity check")
@pytest.mark.parametrize(
    "case,source,sink",
    [
        ("golden", "upper:end_a", "lower:end_b"),
        ("open_hole", "upper:end_a", "lower:end_b"),
        ("covered_slope", "upper:end_a", "lower:end_b"),
        ("reversed", "upper:end_b", "lower:end_b"),
        ("red_random_branch", "split:top", "split:rear"),
        ("unknown_link", "upper:end_a", "lower:end_b"),
        ("bad_support_port", "upper:end_a", "lower:end_b"),
        ("bidirectional", "yellow:front", "blue:front"),
    ],
)
def test_browser_graph_and_path_match_python(case, source, sink, tmp_path):
    with (ROOT / "examples" / "two-level-supported.yaml").open() as f:
        layout_data = yaml.safe_load(f)
    layout_data = deepcopy(layout_data)

    if case == "open_hole":
        layout_data["rails"][0]["hole_states"][2] = "open"
    elif case == "covered_slope":
        layout_data["rails"][0]["hole_states"][2] = "covered_slope"
    elif case == "reversed":
        layout_data["rails"][1]["flow_direction"] = "b_to_a"
    elif case == "red_random_branch":
        layout_data = {
            "name": "branch",
            "parts": [{"id": "split", "part_type": "red_random_split",
                       "x_cm": 0, "y_cm": 0, "z_units": 0}],
        }
    elif case == "unknown_link":
        layout_data["route_links"].append({
            "source": {"component_id": "ghost", "port": "top"},
            "target": {"component_id": "lower", "port": "end_a"},
        })
    elif case == "bad_support_port":
        layout_data["parts"][2]["part_type"] = "wooden_foundation"
    elif case == "bidirectional":
        layout_data = {
            "name": "bidi",
            "parts": [
                {"id": "yellow", "part_type": "yellow", "x_cm": 0,
                 "y_cm": 0, "z_units": 0},
                {"id": "blue", "part_type": "blue", "x_cm": 10,
                 "y_cm": 0, "z_units": 0},
            ],
            "route_links": [{
                "source": {"component_id": "blue", "port": "front"},
                "target": {"component_id": "yellow", "port": "front"},
                "bidirectional": True,
            }],
        }

    layout_file = tmp_path / "layout.yaml"
    layout_file.write_text(yaml.safe_dump(layout_data))
    layout = load_layout(layout_file)
    python_graph = build_routing_graph(layout, CATALOG)
    source_ref = PortRef(*source.split(":", 1))
    sink_ref = PortRef(*sink.split(":", 1))
    python_result = validate_connectivity(layout, CATALOG, source_ref, (sink_ref,))

    completed = subprocess.run(
        ["node", "-e", NODE_SCRIPT],
        input=json.dumps({
            "layout": layout_data,
            "catalog": CATALOG_DATA,
            "source": source,
            "sink": sink,
        }),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    browser = json.loads(completed.stdout)
    assert browser["graph"]["edges"] == {
        key: list(targets) for key, targets in python_graph.edges.items()
    }
    assert browser["graph"]["reasons"] == list(python_graph.reasons)
    assert browser["result"]["reachable"] == python_result.reachable
    assert browser["result"]["valid"] == python_result.valid
    assert browser["result"]["reachableNodes"] == list(python_result.reachable_nodes)
    assert browser["result"]["deadEnds"] == list(python_result.dead_ends)
    assert browser["result"]["reasons"] == list(python_result.reasons)
    assert browser["result"]["path"] == list(python_result.paths.get(sink, ()))
