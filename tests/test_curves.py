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
    found = generate(CATALOG, budget, config=GeneratorConfig(curve_ready_bias=0.8), attempts=120, seed=4, keep=10)
    with_curves = [c for c in found if c.metrics["curved_rails"] > 0]
    assert with_curves
    for c in with_curves:
        assert validate_layout(c.layout, CATALOG, source=c.source, sinks=c.sinks).valid
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


def test_twist_drops_through_its_center_into_the_column_below():
    from quadrilla_solver.collision import solid_collisions

    layout = load_layout(ROOT / "tests" / "fixtures" / "twist-drop.yaml")
    result = validate_layout(layout, CATALOG, source=PortRef("upper", "end_a"),
                             sinks=(PortRef("exit", "end_b"),))
    assert result.valid, result
    path = result.connectivity.paths["exit:end_b"]
    steps = list(zip(path, path[1:]))
    # B on the first chute hole lands the marble on the chute; it rolls over
    # the covered second hole and the funnel drops it through its center into C.
    assert ("B:front", "twist:hole:1") in steps
    assert ("twist:hole:1", "twist:hole:2") in steps
    assert ("twist:hole:2", "C:top") in steps
    # Both chute holes mount 3 units above the center hole, 23 and 18 cm from
    # it (a short rail's holes, user-confirmed).
    spec = CATALOG.rails["spiral"]
    twist = layout.rail_map()["twist"]
    assert [rail_hole_world(twist, CATALOG, i)[2] for i in range(3)] == [8, 8, 5]
    assert [spec.holes_cm[2] - x for x in spec.holes_cm[:2]] == [23.0, 18.0]
    # A block reaching up into the funnel (off its center) collides with it.
    from dataclasses import replace
    from quadrilla_solver.model import PlacedPart
    blocked = replace(layout, parts=layout.parts + (PlacedPart("under", "blue", 6, 23, 2),))
    assert any("twist" in r and "under" in r for r in solid_collisions(blocked, CATALOG))


def test_twist_chute_is_a_plain_rail():
    """User: the chute connects like any rail. A bottom outlet on a chute hole
    drops straight through it into the column below (review: mr-c61a3513),
    and an open chute hole lets a rolling marble fall through."""
    from dataclasses import replace
    from quadrilla_solver.connectivity import build_routing_graph

    layout = load_layout(ROOT / "tests" / "fixtures" / "twist-drop.yaml")
    parts = tuple(replace(p, part_type="orange_vertical") if p.id == "B" else p for p in layout.parts)
    edges = build_routing_graph(replace(layout, parts=parts), CATALOG).edges
    assert edges["B:bottom"] == ("t0_4:top",)
    rails = tuple(replace(r, hole_states={2: "block_connected"}) if r.id == "twist" else r
                  for r in layout.rails)
    edges = build_routing_graph(replace(layout, rails=rails), CATALOG).edges
    assert edges.get("twist:hole:1", ()) == ()


def test_twist_center_hole_must_not_be_covered():
    layout = load_layout(ROOT / "tests" / "fixtures" / "twist-drop.yaml")
    from dataclasses import replace
    rails = tuple(replace(r, hole_states={1: "covered", 2: "covered"}) if r.id == "twist" else r
                  for r in layout.rails)
    reasons = validate_assembly(replace(layout, rails=rails), CATALOG).reasons
    assert "twist_center_hole_covered:twist" in reasons


def test_free_standing_stack_loads_its_rail_and_sits_on_its_hole():
    from dataclasses import replace
    from quadrilla_solver.layout_stability import analyze_layout_statics
    from quadrilla_solver.model import PlacedPart, SupportLink

    layout = load_layout(ROOT / "tests" / "fixtures" / "twist-drop.yaml")
    x, y, _ = rail_hole_world(layout.rail_map()["exit"], CATALOG, 2)
    loaded = replace(layout, parts=layout.parts + (PlacedPart("w", "blue", x, y, 2),),
                     supports=layout.supports + (SupportLink(None, None, ("w",), "exit", 2, name="weight"),))
    assert validate_assembly(loaded, CATALOG).valid
    exit_rail = analyze_layout_statics(loaded, CATALOG).statics.rails["exit"]
    assert any(load.source == "exit:point:weight" for load in exit_rail.applied_loads)
    off = replace(loaded, parts=tuple(replace(p, z_units=3) if p.id == "w" else p for p in loaded.parts))
    assert any(r.startswith("stack_z_mismatch:weight:w") for r in validate_assembly(off, CATALOG).reasons)


def test_long_rails_used_for_nothing_become_short():
    """Review of the dense-stack sample: two long rails a short one replaces."""
    import yaml
    from quadrilla_solver.generator import Budget, layout_sinks, layout_source, resolve_set_paths, shorten_rails

    path = ROOT / "tests" / "fixtures" / "dense-stack-long-rails.yaml"
    data = yaml.safe_load(path.read_text())
    layout = load_layout(path)
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["QD001", "QD003", "QD005"]))
    short = shorten_rails(layout, CATALOG, budget, layout_source(data), layout_sinks(data))
    changed = {r.id for r, s in zip(layout.rails, short.rails) if r.rail_type != s.rail_type}
    # rail6, rail7 in place; rail8 by moving a ground column along it.
    assert changed == {"rail6", "rail7", "rail8"}
    assert all(s.rail_type == "straight_short" for s in short.rails if s.id in changed)
    result = validate_layout(short, CATALOG, source=layout_source(data), sinks=layout_sinks(data))
    assert result.valid
    # Only parts of columns under a shortened rail move.
    moved = {p.id for p, q in zip(layout.parts, short.parts) if p != q}
    under = {pid for s in layout.supports if s.upper_rail_id in changed and s.lower_rail_id is None
             for pid in s.stack_part_ids}
    assert moved <= under


def test_rails_long_only_to_reach_a_far_column_become_short():
    """Review of generated-layered-tower: rail1, rail6, rail10 roll the marble a
    few cm but span 50 cm to reach a ground column; moving the column along
    the rail lets a short rail do."""
    import yaml
    from quadrilla_solver.generator import Budget, layout_sinks, layout_source, resolve_set_paths, shorten_rails
    from quadrilla_solver.substitution import shorten

    path = ROOT / "tests" / "fixtures" / "layered-tower-far-columns.yaml"
    data = yaml.safe_load(path.read_text())
    layout = load_layout(path)
    for rail_id in ("rail1", "rail6", "rail10"):
        assert not shorten(layout, CATALOG, rail_id)  # not without moving a column
        assert shorten(layout, CATALOG, rail_id, move_columns=True)
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["QD001", "QD003", "QD005"]))
    short = shorten_rails(layout, CATALOG, budget, layout_source(data), layout_sinks(data))
    changed = {r.id for r, s in zip(layout.rails, short.rails) if r.rail_type != s.rail_type}
    assert {"rail1", "rail6", "rail10"} <= changed
    result = validate_layout(short, CATALOG, source=layout_source(data), sinks=layout_sinks(data))
    assert result.valid
