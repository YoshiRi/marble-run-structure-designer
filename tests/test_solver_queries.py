from pathlib import Path

from quadrilla_solver.catalog import load_rail_specs, load_set_inventory
from quadrilla_solver.geometry import find_stacking_options, find_triangle
from quadrilla_solver.optimizer import maximize_straight_tower
from quadrilla_solver.stability import (
    check_support_chain,
    check_triangle_vertex_supports,
)


ROOT = Path(__file__).resolve().parents[1]


def test_short_rail_is_not_stably_supported_by_regular_long_rail():
    rails = load_rail_specs(ROOT / "catalog" / "parts.yaml")
    options = find_stacking_options(
        rails["straight_short"],
        rails["straight_long"],
    )
    assert options == ()


def test_short_rail_can_be_stably_supported_by_center_hole_long_rail():
    rails = load_rail_specs(ROOT / "catalog" / "parts.yaml")
    options = find_stacking_options(
        rails["straight_short"],
        rails["straight_long_center"],
    )
    spans = {o.span_cm for o in options}
    assert 18.0 in spans
    assert 23.0 in spans


def test_three_regular_long_rails_can_form_triangle_in_plan_view():
    rails = load_rail_specs(ROOT / "catalog" / "parts.yaml")
    rail = rails["straight_long"]
    triangle = find_triangle((rail, rail, rail))
    assert triangle is not None
    # Largest conservative end-to-end support span is holes 2 <-> 48.
    assert triangle.side_spans_cm == (46.0, 46.0, 46.0)


def test_triangle_stability_requires_all_three_vertex_support_chains():
    assert check_triangle_vertex_supports((True, True, True)).valid
    result = check_triangle_vertex_supports((True, True, False))
    assert not result.valid
    assert "triangle_vertex_2_unsupported" in result.reasons


def test_support_graph_reaches_ground_through_stable_rails():
    graph = {
        "upper": ("lower_left", "lower_right"),
        "lower_left": ("g1", "g2"),
        "lower_right": ("g3", "g4"),
    }
    result = check_support_chain(graph, {"g1", "g2", "g3", "g4"}, ("upper",))
    assert result.valid


def test_single_support_is_rejected():
    graph = {"upper": ("one_leg",)}
    result = check_support_chain(graph, {"one_leg"}, ("upper",))
    assert not result.valid


def _height(set_file: str):
    inv = load_set_inventory(ROOT / "catalog" / "sets" / set_file)
    sol = maximize_straight_tower(inv)
    assert sol is not None
    return sol


def test_basic_height_under_mvp_model():
    sol = _height("basic-qd001.yaml")
    assert sol.rail_levels == 3
    assert sol.height_units == 28


def test_speedway_height_under_mvp_model():
    sol = _height("speedway-qd101.yaml")
    assert sol.rail_levels == 2
    assert sol.height_units == 21


def test_funny_function_height_under_mvp_model():
    sol = _height("funny-function-qd003.yaml")
    assert sol.rail_levels == 4
    assert sol.height_units == 39


def test_twist_and_rail_height_under_mvp_model():
    sol = _height("twist-and-rail-qd005.yaml")
    assert sol.rail_levels == 7
    assert sol.height_units == 66
