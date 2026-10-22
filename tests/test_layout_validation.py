from dataclasses import replace
from pathlib import Path

import pytest

from quadrilla_solver.assembly import validate_assembly
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import validate_connectivity
from quadrilla_solver.layout_stability import analyze_global_stability
from quadrilla_solver.model import (
    Layout,
    PlacedPart,
    PlacedRail,
    PortRef,
    RouteLink,
    SupportLink,
    load_layout,
)
from quadrilla_solver.validation import validate_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")


def _example() -> Layout:
    return load_layout(ROOT / "examples" / "two-level-supported.yaml")


def test_common_layout_example_is_assemblable():
    result = validate_assembly(_example(), CATALOG)
    assert result.valid, result.reasons


def test_support_xy_mismatch_is_rejected():
    layout = _example()
    upper = next(x for x in layout.rails if x.id == "upper")
    shifted = replace(upper, x_cm=1.0)
    broken = replace(
        layout,
        rails=tuple(
            shifted if x.id == "upper" else x
            for x in layout.rails
        ),
    )

    result = validate_assembly(broken, CATALOG)
    assert not result.valid
    assert any(x.startswith("support_xy_mismatch:") for x in result.reasons)


def test_two_level_example_has_stable_global_com():
    result = analyze_global_stability(_example(), CATALOG)
    assert result.evaluable
    assert result.stable
    assert result.total_mass_g == pytest.approx(341.0)
    assert result.com_xyz_cm is not None
    assert 2.0 <= result.com_xyz_cm[0] <= 48.0
    assert result.com_xyz_cm[1] == pytest.approx(0.0)


def test_rectangular_ground_support_polygon_contains_com():
    rails = (
        PlacedRail("r0", "straight_long", 0, 0, 1),
        PlacedRail("r1", "straight_long", 0, 20, 1),
    )
    parts = (
        PlacedPart("f00", "wooden_foundation", 2, 0, 0),
        PlacedPart("f01", "wooden_foundation", 48, 0, 0),
        PlacedPart("f10", "wooden_foundation", 2, 20, 0),
        PlacedPart("f11", "wooden_foundation", 48, 20, 0),
    )
    supports = (
        SupportLink("r0", 0, ("f00",), name="r0a"),
        SupportLink("r0", 3, ("f01",), name="r0b"),
        SupportLink("r1", 0, ("f10",), name="r1a"),
        SupportLink("r1", 3, ("f11",), name="r1b"),
    )
    layout = Layout("rectangle", rails=rails, parts=parts, supports=supports)

    result = analyze_global_stability(layout, CATALOG)
    assert result.evaluable
    assert result.stable
    assert len(result.support_polygon_xy_cm) == 4
    assert result.margin_cm == pytest.approx(10.0)


def test_global_com_outside_support_polygon_is_unstable():
    base = _example()
    floating = PlacedRail(
        id="floating_mass",
        rail_type="straight_long",
        x_cm=0,
        y_cm=100,
        z_units=20,
    )
    layout = replace(base, rails=base.rails + (floating,))

    result = analyze_global_stability(layout, CATALOG)
    assert result.evaluable
    assert not result.stable
    assert any(x.startswith("global_tipping:") for x in result.reasons)


def test_connectivity_is_derived_from_same_layout():
    result = validate_connectivity(
        _example(),
        CATALOG,
        source=PortRef("upper", "end_a"),
        sinks=(PortRef("blue_column", "front"),),
    )
    assert result.valid, result.reasons
    assert result.reachable
    assert "blue_column:front" in result.reached_sinks
    assert "blue_column:top" in result.reachable_nodes
    assert "blue_column:front" in result.reachable_nodes


def test_open_hole_breaks_rail_connectivity():
    layout = _example()
    lower = next(x for x in layout.rails if x.id == "lower")
    states = dict(lower.hole_states)
    states[2] = "open"
    open_lower = replace(lower, hole_states=states)
    broken = replace(
        layout,
        rails=tuple(
            open_lower if x.id == "lower" else x
            for x in layout.rails
        ),
    )

    result = validate_connectivity(
        broken,
        CATALOG,
        source=PortRef("lower", "end_a"),
        sinks=(PortRef("lower", "end_b"),),
    )
    assert not result.valid
    assert not result.reachable
    assert "lower:hole:2" in result.dead_ends


def test_combined_layout_validation_passes_golden_example():
    result = validate_layout(
        _example(),
        CATALOG,
        source=PortRef("upper", "end_a"),
        sinks=(PortRef("blue_column", "front"),),
    )
    assert result.valid
    assert result.assembly.valid
    assert result.global_stability.stable
    assert result.local_statics.evaluable
    assert result.local_statics.statics is not None
    assert result.local_statics.statics.valid
    assert result.connectivity is not None
    assert result.connectivity.valid


def test_routing_solver_exposes_shortest_node_path():
    result = validate_connectivity(
        _example(),
        CATALOG,
        source=PortRef("upper", "end_a"),
        sinks=(PortRef("blue_column", "front"),),
    )
    assert result.valid
    assert result.paths["blue_column:front"] == (
        "upper:end_a",
        "upper:hole:0",
        "blue_column:top",
        "blue_column:front",
    )


def test_unaligned_manual_link_is_rejected_not_rendered():
    from quadrilla_solver.model import RouteLink
    from quadrilla_solver.connectivity import build_routing_graph

    layout = _example()
    invalid = replace(layout, route_links=(
        RouteLink(PortRef("blue_column", "front"), PortRef("lower", "end_a")),
    ))
    graph = build_routing_graph(invalid, CATALOG)
    assert "lower:end_a" not in graph.edges["blue_column:front"]
    assert "route_link_geometry_mismatch:blue_column:front:lower:end_a" in graph.reasons
    result = validate_connectivity(
        invalid, CATALOG, PortRef("upper", "end_a"), (PortRef("lower", "end_b"),)
    )
    assert not result.reachable
    assert not result.valid


def test_three_level_example_has_physically_aligned_full_route():
    layout = load_layout(ROOT / "examples" / "three-level-physically-connected.yaml")
    assembly = validate_assembly(layout, CATALOG)
    assert assembly.valid, assembly.reasons
    result = validate_connectivity(
        layout, CATALOG, PortRef("upper", "end_a"), (PortRef("exit", "end_b"),)
    )
    assert result.valid, result.reasons
    assert result.paths["exit:end_b"][:6] == (
        "upper:end_a", "upper:hole:0", "blue_column:top",
        "blue_column:front", "exit:end_a", "exit:hole:0",
    )


def test_route_link_ports_match_catalogued_visible_openings():
    from quadrilla_solver.routing_geometry import port_pose, validate_route_link_geometry

    layout = load_layout(ROOT / "examples" / "three-level-physically-connected.yaml")
    link = layout.route_links[0]
    source = port_pose(layout, CATALOG, link.source)
    target = port_pose(layout, CATALOG, link.target)
    assert source is not None and target is not None
    # Blue block installed at 2u: its centered front hole opens at 3u (4.5 cm).
    assert source.position_cm[2] == pytest.approx(3 * 1.5)
    # The exit rail's groove is at the installation level, one unit lower,
    # at the same XY: the marble drops straight out of the hole.
    assert source.position_cm[:2] == pytest.approx(target.position_cm[:2], abs=1e-6)
    assert source.position_cm[2] - target.position_cm[2] == pytest.approx(1.5)
    assert sum(x * y for x, y in zip(source.outward, target.outward)) == pytest.approx(-1)
    assert validate_route_link_geometry(layout, CATALOG, link) is None

    # An arbitrary rail hole is not a surface connection for RouteLink.
    assert port_pose(layout, CATALOG, PortRef("exit", "hole:1")) is None
    # Nor may a block use a port not declared by the part catalog.
    assert port_pose(layout, CATALOG, PortRef("blue_column", "left")) is None


def test_three_level_complete_layout_stability():
    layout = load_layout(ROOT / "examples" / "three-level-physically-connected.yaml")
    result = validate_layout(
        layout, CATALOG, source=PortRef("upper", "end_a"),
        sinks=(PortRef("exit", "end_b"),),
    )
    assert result.valid, result


def test_purple_drop_block_height_matches_one_unit_rail():
    from quadrilla_solver.routing_geometry import port_pose

    purple = CATALOG.raw["routing_blocks"]["purple_drop"]
    rail = CATALOG.raw["rails"]["straight_long"]
    assert purple["height"] == 1
    assert rail["height"] == 1
    assert purple["body_height_cm"]["value"] == pytest.approx(1.5)

    layout = Layout(
        "purple-height",
        parts=(PlacedPart("purple", "purple_drop", 0, 0, 2),),
    )
    top = port_pose(layout, CATALOG, PortRef("purple", "top"))
    bottom = port_pose(layout, CATALOG, PortRef("purple", "bottom"))
    assert top is not None and bottom is not None
    assert top.position_cm[2] - bottom.position_cm[2] == pytest.approx(1.5)


def test_centered_side_ports_drop_one_but_never_climb():
    """Cyan passes left -> right through centered holes at level +1.

    Out of the right hole the marble may drop one unit onto a rail at the
    installation level; a rail one unit below the left hole cannot feed it.
    """
    from quadrilla_solver.routing_geometry import port_pose, validate_route_link_geometry

    cyan = PlacedPart("cyan", "cyan", 0, 0, 2)
    # Rails along x: one leaving the right hole, one arriving at the left hole.
    out_rail = PlacedRail("out", "straight_short", 2.25, 0, 1)
    in_rail = PlacedRail("in", "straight_short", -2.25 - 27, 0, 1)
    layout = Layout(
        "cyan-levels",
        rails=(out_rail, in_rail),
        parts=(cyan,),
        route_links=(
            RouteLink(PortRef("cyan", "right"), PortRef("out", "end_a")),
            RouteLink(PortRef("in", "end_b"), PortRef("cyan", "left")),
        ),
    )
    right = port_pose(layout, CATALOG, PortRef("cyan", "right"))
    assert right is not None and right.position_cm[2] == pytest.approx(3 * 1.5)

    drop_out, climb_in = layout.route_links
    assert validate_route_link_geometry(layout, CATALOG, drop_out) is None
    assert validate_route_link_geometry(layout, CATALOG, climb_in) is not None
    assert validate_route_link_geometry(
        replace(layout, rails=(out_rail, replace(in_rail, z_units=2))), CATALOG, climb_in
    ) is None


def test_bottom_outlets_drop_down_the_support_column():
    layout = load_layout(ROOT / "tests" / "fixtures" / "stack-drop.yaml")
    assert validate_assembly(layout, CATALOG).valid
    result = validate_connectivity(
        layout, CATALOG, PortRef("upper", "end_a"), (PortRef("blue_mid", "front"),)
    )
    assert result.valid, result.reasons
    assert result.paths["blue_mid:front"] == (
        "upper:end_a", "upper:hole:0", "orange_top:top", "orange_top:bottom",
        "blue_mid:top", "blue_mid:front",
    )
    from quadrilla_solver.connectivity import build_routing_graph

    edges = build_routing_graph(layout, CATALOG).edges
    # Bottom of a stack on a lower rail drops through that hole into the
    # column below it.
    assert edges["blue_mid:bottom"] == ("yellow_base:top",)
    # Inside a stack: green's side-drop outlet feeds cyan's top opening...
    assert edges["green_top:bottom"] == ("cyan_mid:top",)
    # ...but cyan has no bottom outlet, so nothing drops further from it.
    assert "cyan_mid:bottom" not in edges
