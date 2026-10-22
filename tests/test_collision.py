from pathlib import Path

from quadrilla_solver.assembly import validate_assembly
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.collision import marble_clearance_conflicts, solid_collisions
from quadrilla_solver.connectivity import validate_connectivity
from quadrilla_solver.model import Layout, PlacedPart, PlacedRail, PortRef, load_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")


def test_examples_have_no_collisions():
    for name in ("three-level-physically-connected", "two-level-supported", "random-split"):
        layout = load_layout(ROOT / "tests" / "fixtures" / f"{name}.yaml")
        assert solid_collisions(layout, CATALOG) == (), name


def test_touching_blocks_are_accepted_but_overlapping_blocks_collide():
    touching = Layout("touching", parts=(
        PlacedPart("a", "blue", 0, 0, 0),
        PlacedPart("b", "blue", 4.5, 0, 0),   # face to face
        PlacedPart("c", "blue", 0, 0, 4),     # stacked on a
    ))
    assert solid_collisions(touching, CATALOG) == ()

    overlapping = Layout("overlap", parts=(
        PlacedPart("a", "blue", 0, 0, 0),
        PlacedPart("b", "blue", 3.0, 0, 0),
    ))
    assert solid_collisions(overlapping, CATALOG) == ("solid_collision:a:b",)


def test_crossing_rails_collide_only_at_the_same_level():
    rails = (
        PlacedRail("x", "straight_long", 0, 0, 1, yaw_deg=0),
        PlacedRail("y", "straight_long", 25, -25, 1, yaw_deg=90),
    )
    assert solid_collisions(Layout("cross", rails=rails), CATALOG) == (
        "solid_collision:x:y",
    )
    stacked = (rails[0], PlacedRail("y", "straight_long", 25, -25, 2, yaw_deg=90))
    assert solid_collisions(Layout("over", rails=stacked), CATALOG) == ()


def test_rotated_rail_collision_uses_its_real_footprint():
    # A 45-degree rail passing near a block corner: bounding circles would
    # overlap, the oriented boxes do not.
    layout = Layout(
        "diagonal",
        rails=(PlacedRail("r", "straight_long", 0, 0, 0, yaw_deg=45),),
        parts=(PlacedPart("p", "blue", 12, 0, 0),),
    )
    assert solid_collisions(layout, CATALOG) == ()
    moved = Layout(
        "diagonal-hit",
        rails=layout.rails,
        parts=(PlacedPart("p", "blue", 10, 8, 0),),
    )
    assert solid_collisions(moved, CATALOG) == ("solid_collision:p:r",)


def test_block_standing_on_the_marble_path_is_reported():
    layout = load_layout(ROOT / "tests" / "fixtures" / "three-level-physically-connected.yaml")
    connectivity = validate_connectivity(
        layout, CATALOG, PortRef("upper", "end_a"), (PortRef("exit", "end_b"),)
    )
    assert marble_clearance_conflicts(layout, CATALOG, connectivity.reachable_nodes) == ()

    # Stand a block on the exit rail's hole 2, which the marble rolls over.
    blocked = Layout(
        layout.name,
        rails=layout.rails,
        parts=layout.parts + (PlacedPart("obstacle", "yellow", 2, 2.25 + 20, 2),),
        supports=layout.supports,
        route_links=layout.route_links,
        routing_options=layout.routing_options,
    )
    assert validate_assembly(blocked, CATALOG).reasons == ()
    connectivity = validate_connectivity(
        blocked, CATALOG, PortRef("upper", "end_a"), (PortRef("exit", "end_b"),)
    )
    assert marble_clearance_conflicts(blocked, CATALOG, connectivity.reachable_nodes) == (
        "marble_path_blocked:exit:obstacle",
    )
