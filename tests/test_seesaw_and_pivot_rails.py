"""Seesaw (random distributor on a center-hole rail) and pivot rails
(collector: both ends into one hole; outward: from one hole to both ends)."""
import copy
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import build_routing_graph
from quadrilla_solver.generator import layout_sinks, layout_source
from quadrilla_solver.model import layout_from_dict
from quadrilla_solver.scoring import layout_metrics
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
SEESAW = yaml.safe_load((ROOT / "tests" / "fixtures" / "seesaw-split.yaml").read_text())


def check(data):
    return validate_layout(layout_from_dict(data), CATALOG, source=layout_source(data), sinks=list(layout_sinks(data)))


def edit(data, fn):
    data = copy.deepcopy(data)
    fn(data)
    return data


def part(data, pid):
    return next(p for p in data["parts"] if p["id"] == pid)


def rail(data, rid):
    return next(r for r in data["rails"] if r["id"] == rid)


def test_seesaw_splits_a_falling_marble_to_both_arms():
    result = check(SEESAW)
    assert result.valid, result
    assert set(result.connectivity.reached_sinks) == {"host:hole:1", "host:end_b"}
    assert "seesaw:top" in result.connectivity.paths["host:end_b"]


@pytest.mark.parametrize("change, reason", [
    (lambda d: d["supports"][2].update(lower_hole_index=1), "seesaw_needs_center_hole"),
    (lambda d: part(d, "seesaw").update(rotation_deg=90), "seesaw_not_along_rail"),
    (lambda d: rail(d, "host").update(flow_direction="a_to_b"), "seesaw_rail_must_flow_outward"),
    (lambda d: rail(d, "host").update(rail_type="straight_long"), "seesaw_needs_center_hole"),
])
def test_seesaw_mount_rules(change, reason):
    result = check(edit(SEESAW, change))
    assert any(r.startswith(reason) for r in result.assembly.reasons), result.assembly.reasons


def test_seesaw_is_fed_only_from_within_the_drop_limit():
    def higher(d):  # 16 levels above the seesaw base: beyond the 12-level limit
        rail(d, "feeder")["z_units"] = 21
    graph = build_routing_graph(layout_from_dict(edit(SEESAW, higher)), CATALOG)
    assert "seesaw:top" not in graph.edges.get("feeder:hole:2", ())
    graph = build_routing_graph(layout_from_dict(SEESAW), CATALOG)
    assert "seesaw:top" in graph.edges["feeder:hole:2"]


def test_a_covered_hole_above_does_not_feed_the_seesaw():
    covered = edit(SEESAW, lambda d: rail(d, "feeder")["hole_states"].update({2: "covered"}))
    graph = build_routing_graph(layout_from_dict(covered), CATALOG)
    assert "seesaw:top" not in graph.edges.get("feeder:hole:2", ())


def test_collector_rail_runs_from_both_ends_into_its_pivot_hole():
    data = {"rails": [{"id": "c", "rail_type": "straight_long_center", "x_cm": 0, "y_cm": 0, "z_units": 3,
                       "flow_direction": "to_hole", "flow_hole": 2, "hole_states": {1: "covered", 3: "covered"}}],
            "parts": [], "supports": []}
    edges = build_routing_graph(layout_from_dict(data), CATALOG).edges
    assert edges["c:end_a"] == ("c:hole:0",)
    assert edges["c:hole:1"] == ("c:hole:2",)
    assert edges["c:end_b"] == ("c:hole:4",)
    assert edges["c:hole:3"] == ("c:hole:2",)
    assert edges["c:hole:2"] == ()  # the collector hole: the marble drops here


def test_outward_rail_runs_from_its_pivot_to_both_ends():
    data = {"rails": [{"id": "o", "rail_type": "straight_long_center", "x_cm": 0, "y_cm": 0, "z_units": 3,
                       "flow_direction": "from_hole", "flow_hole": 2, "hole_states": {0: "covered", 4: "covered"}}],
            "parts": [], "supports": []}
    edges = build_routing_graph(layout_from_dict(data), CATALOG).edges
    assert edges["o:hole:0"] == ("o:end_a",) and edges["o:hole:4"] == ("o:end_b",)
    assert edges["o:end_a"] == () and edges["o:end_b"] == ()


def test_pivot_rails_need_a_valid_pivot_hole():
    bad = edit(SEESAW, lambda d: rail(d, "host").update(flow_hole=None))
    assert any(r.startswith("invalid_flow_hole:host") for r in check(bad).assembly.reasons)


def test_merges_metric_counts_a_join():
    # Both seesaw arms' routes do not join; the seesaw itself is a split.
    assert layout_metrics(layout_from_dict(SEESAW), CATALOG, layout_source(SEESAW))["merges"] == 0
