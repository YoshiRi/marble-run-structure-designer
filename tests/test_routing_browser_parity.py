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
const {buildGraph, trace, listInputHoles, analyzeOutcomes} = require("./viewer/routing.js");
const {layout, catalog, source, sink} = JSON.parse(fs.readFileSync(0, "utf8"));
const graph = buildGraph(layout, catalog);
process.stdout.write(JSON.stringify({
  graph,
  result: trace(graph, source, sink),
  inputHoles: listInputHoles(layout, catalog, graph),
  outcomes: analyzeOutcomes(layout, catalog, graph, source),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for parity check")
@pytest.mark.parametrize(
    "case,source,sink",
    [
        ("golden", "upper:end_a", "blue_column:front"),
        ("open_hole", "lower:end_a", "lower:end_b"),
        ("covered_slope", "lower:end_a", "lower:end_b"),
        ("reversed", "upper:end_b", "green_column:front"),
        ("red_random_branch", "split:top", "split:rear"),
        ("unknown_link", "upper:end_a", "blue_column:front"),
        ("bad_support_port", "upper:end_a", "blue_column:front"),
        ("bidirectional", "cyan0:right", "cyan1:left"),
        ("side_entry_aligned", "entry:end_a", "drop:bottom"),
        ("side_entry_plus_one_disallowed", "entry:end_a", "drop:bottom"),
        ("side_entry_plus_one_allowed", "entry:end_a", "drop:bottom"),
        ("aligned_rail_exit", "upper:end_a", "exit:end_b"),
        ("misaligned_rail_exit", "upper:end_a", "exit:end_b"),
        ("wrong_flow_direction", "upper:end_a", "exit:end_b"),
        ("wrong_port", "upper:end_a", "exit:end_b"),
        ("misaligned_support", "upper:end_a", "exit:end_b"),
        ("rotated_port", "upper:end_a", "exit:end_b"),
        ("side_exit_exact_level", "upper:end_a", "exit:end_b"),
        ("side_exit_drop_two", "upper:end_a", "exit:end_b"),
        ("stack_drop", "upper:end_a", "blue_mid:front"),
        ("stack_drop_from_rear", "blue_mid:rear", "yellow_base:front"),
        ("landing_tower", "top:end_a", "exit:end_b"),
        ("twist_drop", "feed:end_a", "exit:end_b"),
        ("twist_landing", "feed:end_a", "exit:end_b"),
    ],
)
def test_browser_graph_and_path_match_python(case, source, sink, tmp_path):
    example = ("three-level-physically-connected.yaml" if case in {
        "aligned_rail_exit", "misaligned_rail_exit", "wrong_flow_direction",
        "wrong_port", "misaligned_support", "rotated_port",
        "side_exit_exact_level", "side_exit_drop_two",
    } else "two-level-supported.yaml")
    if case == "landing_tower":
        example = "landing-tower.yaml"
    if case.startswith("twist_"):
        example = "twist-drop.yaml"
    if case.startswith("stack_drop"):
        example = "stack-drop.yaml"
    with (ROOT / "tests" / "fixtures" / example).open() as f:
        layout_data = yaml.safe_load(f)
    layout_data = deepcopy(layout_data)

    if case in {
        "side_entry_aligned", "side_entry_plus_one_disallowed",
        "side_entry_plus_one_allowed",
    }:
        rail_z = 1 if case == "side_entry_aligned" else 2
        layout_data = {
            "name": case,
            "rails": [{
                "id": "entry", "rail_type": "straight_short",
                "x_cm": 0, "y_cm": -29.25, "z_units": rail_z,
                "yaw_deg": 90, "flow_direction": "a_to_b",
                "hole_states": {0: "covered", 1: "covered", 2: "covered", 3: "covered"},
            }],
            "parts": [{
                "id": "drop", "part_type": "blue",
                "x_cm": 0, "y_cm": 0, "z_units": 2,
            }],
            "route_links": [{
                "source": {"component_id": "entry", "port": "end_b"},
                "target": {"component_id": "drop", "port": "rear"},
            }],
        }
        if case == "side_entry_plus_one_allowed":
            layout_data["routing_options"] = {"allow_side_entry_plus_one": True}

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
                {"id": "cyan0", "part_type": "cyan", "x_cm": 0,
                 "y_cm": 0, "z_units": 0},
                {"id": "cyan1", "part_type": "cyan", "x_cm": 4.5,
                 "y_cm": 0, "z_units": 0},
            ],
            "route_links": [{
                "source": {"component_id": "cyan0", "port": "right"},
                "target": {"component_id": "cyan1", "port": "left"},
                "bidirectional": True,
            }],
        }

    if case == "misaligned_rail_exit":
        next(r for r in layout_data["rails"] if r["id"] == "exit")["y_cm"] += 1
    elif case == "wrong_flow_direction":
        next(r for r in layout_data["rails"] if r["id"] == "exit")["flow_direction"] = "b_to_a"
    elif case == "wrong_port":
        layout_data["route_links"][0]["source"]["port"] = "top"
    elif case == "misaligned_support":
        next(p for p in layout_data["parts"] if p["id"] == "blue_column")["x_cm"] += 1
    elif case == "rotated_port":
        next(p for p in layout_data["parts"] if p["id"] == "blue_column")["rotation_deg"] = 90
    elif case == "side_exit_exact_level":
        # Groove exactly at the hole floor (installation level + 1).
        next(r for r in layout_data["rails"] if r["id"] == "exit")["z_units"] = 2
    elif case == "side_exit_drop_two":
        # Two units below the hole floor: not a physical connection.
        next(r for r in layout_data["rails"] if r["id"] == "exit")["z_units"] = 0
    elif case == "twist_landing":
        # A yellow on the chute hole, front along the twist: lands on the chute.
        entry = next(p for p in layout_data["parts"] if p["id"] == "E")
        entry.update(part_type="yellow", rotation_deg=0)

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

    if case in {"side_entry_aligned", "side_entry_plus_one_allowed"}:
        assert python_result.valid and python_result.reachable, python_result.reasons
    elif case in {"aligned_rail_exit", "side_exit_exact_level"}:
        assert python_result.valid and python_result.reachable, python_result.reasons
    elif case == "side_exit_drop_two":
        assert not python_result.reachable
        assert any(reason.startswith("route_link_geometry_mismatch:") for reason in python_result.reasons)
    elif case == "side_entry_plus_one_disallowed":
        assert not python_result.valid and not python_result.reachable
        assert any(reason.startswith("route_link_geometry_mismatch:") for reason in python_result.reasons)

    if case == "red_random_branch":
        assert browser["outcomes"]["complete"]
        assert browser["outcomes"]["estimated"]
        probabilities = {exit["node"]: exit["probability"] for exit in browser["outcomes"]["exits"]}
        assert probabilities == {"split:front": 0.5, "split:rear": 0.5}
    elif case == "aligned_rail_exit":
        assert browser["outcomes"]["complete"]
        assert browser["outcomes"]["exits"] == [{
            "node": "exit:end_b", "kind": "rail_end",
            "label": "exit · end B (rail exit)", "probability": 1,
        }]
        assert any(hole["key"] == "upper:hole:0" for hole in browser["inputHoles"])
