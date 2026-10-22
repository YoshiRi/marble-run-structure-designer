"""Curved rails: geometry, collision, stability rule, substitution, parity."""
from __future__ import annotations

import json
import shutil
import subprocess
from math import degrees, dist
from pathlib import Path

import pytest

from quadrilla_solver.assembly import validate_assembly
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.collision import solid_collisions
from quadrilla_solver.connectivity import build_routing_graph, validate_connectivity
from quadrilla_solver.generator import (
    Budget, GeneratorConfig, generate, layout_to_dict, resolve_set_paths,
)
from quadrilla_solver.model import Layout, PlacedRail, PortRef, load_layout, rail_hole_world, rail_pose
from quadrilla_solver.substitution import eligible_rails, substitute
from quadrilla_solver.validation import validate_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
FOUR_WAY = ROOT / "examples" / "generated" / "generated-four-way.yaml"


def _holes(rail):
    return [rail_hole_world(rail, CATALOG, i)[:2] for i in range(len(CATALOG.rails[rail.rail_type].holes_cm))]


def test_curve_holes_sit_on_the_23_cm_lattice():
    short = PlacedRail("c", "curved_short", 0, 0, 1, yaw_deg=0, turn="left")
    a, b = _holes(short)
    assert dist(a, b) == pytest.approx(23.0, abs=1e-6)
    # 60 degrees between the end-hole tangents.
    spec = CATALOG.rails["curved_short"]
    turn = rail_pose(short, spec, spec.holes_cm[1])[2] - rail_pose(short, spec, spec.holes_cm[0])[2]
    assert degrees(turn) == pytest.approx(60.0, abs=1e-6)

    s_curve = PlacedRail("s", "s_curve", 0, 0, 1, yaw_deg=0)
    a, m, b = _holes(s_curve)
    assert dist(a, m) == pytest.approx(23.0, abs=1e-6)
    assert dist(m, b) == pytest.approx(23.0, abs=1e-6)
    assert dist(a, b) == pytest.approx(46.0, abs=1e-6)  # collinear, like long rail holes 0/2/4

    long_curve = PlacedRail("l", "curved_long", 0, 0, 1, yaw_deg=0)
    a, m, b = _holes(long_curve)
    assert dist(a, b) == pytest.approx(23.0 * 3 ** 0.5, abs=1e-6)  # second lattice neighbor


def test_curve_collides_with_a_straight_only_on_the_same_level():
    straight = PlacedRail("st", "straight_short", 0, 0, 1)
    curve = substitute(
        Layout("x", rails=(PlacedRail("cv", "straight_short", 0, 0, 1),)), CATALOG, "cv", "left"
    ).rails[0]
    assert solid_collisions(Layout("same", rails=(straight, curve)), CATALOG)
    lifted = PlacedRail(curve.id, curve.rail_type, curve.x_cm, curve.y_cm, 2,
                        yaw_deg=curve.yaw_deg, turn=curve.turn)
    assert solid_collisions(Layout("stacked", rails=(straight, lifted)), CATALOG) == ()


def test_curves_need_load_above():
    lone = Layout("lone", rails=(PlacedRail("c", "curved_short", 0, 0, 1),))
    assert "curve_needs_load_above:c" in validate_assembly(lone, CATALOG).reasons
    s_curve = Layout("s", rails=(PlacedRail("s", "s_curve", 0, 0, 1),))
    assert not any(r.startswith("curve_needs_load_above") for r in validate_assembly(s_curve, CATALOG).reasons)


def test_s_curve_substitution_keeps_the_layout_valid():
    layout = load_layout(FOUR_WAY)
    assert "rail7" in eligible_rails(layout)
    leaves = tuple(PortRef(r.id, "end_b") for r in layout.rails
                   if "block_connected" not in r.hole_states.values())
    for turn in ("left", "right"):
        swapped = substitute(layout, CATALOG, "rail7", turn)
        rail = swapped.rail_map()["rail7"]
        assert rail.rail_type == "s_curve" and rail.turn == turn
        result = validate_layout(swapped, CATALOG, source=PortRef("rail0", "end_a"), sinks=leaves)
        assert result.valid, result
        # The marble still rolls along the swapped rail.
        assert any(n.startswith("rail7:") for n in result.connectivity.reachable_nodes)
        # Blocks standing on it turned with the tangent (+-30 degrees).
        before = {p.id: p.rotation_deg for p in layout.parts}
        on_rail = [s.stack_part_ids[0] for s in swapped.supports if s.lower_rail_id == "rail7"]
        assert on_rail
        for pid in on_rail:
            delta = (swapped.part_map()[pid].rotation_deg - before[pid]) % 360
            assert delta in (30, 330)


def test_rails_fed_by_an_explicit_link_are_not_swapped():
    layout = load_layout(FOUR_WAY)
    linked = {l.target.component_id for l in layout.route_links}
    assert linked and not linked & set(eligible_rails(layout))


def test_generator_uses_curves_when_the_inventory_has_them():
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["QD001", "QD003", "QD005", "QDE6008AB05"]))
    found = generate(CATALOG, budget, config=GeneratorConfig(), attempts=120, seed=4, keep=3)
    with_curves = [c for c in found if c.metrics["curved_rails"] > 0]
    assert with_curves
    for c in with_curves:
        leaves = tuple(PortRef(r.id, "end_b") for r in c.layout.rails
                       if "block_connected" not in r.hole_states.values())
        assert validate_layout(c.layout, CATALOG, source=PortRef("rail0", "end_a"), sinks=leaves).valid
        assert c.usage.get("curved_short", 0) <= budget.counts["curved_short"]
        assert c.usage.get("s_curve", 0) <= budget.counts["s_curve"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_browser_routes_along_a_curve_like_python():
    from test_routing_browser_parity import NODE_SCRIPT

    layout = substitute(load_layout(FOUR_WAY), CATALOG, "rail7", "left")
    data = layout_to_dict(layout)
    sink = "rail9:end_b"
    completed = subprocess.run(
        ["node", "-e", NODE_SCRIPT],
        input=json.dumps({"layout": data, "catalog": CATALOG.raw, "source": "rail0:end_a", "sink": sink}),
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    browser = json.loads(completed.stdout)
    python_graph = build_routing_graph(layout, CATALOG)
    assert browser["graph"]["edges"] == {k: list(v) for k, v in python_graph.edges.items()}
    assert browser["graph"]["reasons"] == list(python_graph.reasons)
    python_result = validate_connectivity(layout, CATALOG, PortRef("rail0", "end_a"), (PortRef(*sink.split(":", 1)),))
    assert browser["result"]["reachableNodes"] == list(python_result.reachable_nodes)
    assert any(n.startswith("rail7:") for n in browser["result"]["reachableNodes"])
