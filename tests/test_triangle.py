"""The user's isosceles triangle base (design doc §6.2)."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import build_routing_graph
from quadrilla_solver.model import layout_from_dict
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
DATA = yaml.safe_load((ROOT / "tests" / "fixtures" / "triangle-isosceles.yaml").read_text())


def _validate(data):
    return validate_layout(layout_from_dict(data), CATALOG)


def test_the_triangle_stands():
    result = _validate(DATA)
    assert result.valid, result


def test_the_median_fits_only_with_its_declared_play():
    for name in ("median_on_base", "median_on_plate"):
        data = copy.deepcopy(DATA)
        next(s for s in data["supports"] if s["name"] == name)["play_cm"] = 0.0
        reasons = _validate(data).assembly.reasons
        assert any(r.startswith(f"support_xy_mismatch:{name}") for r in reasons), reasons


def test_play_is_capped_by_the_catalog():
    data = copy.deepcopy(DATA)
    next(s for s in data["supports"] if s["name"] == "median_on_base")["play_cm"] = 0.8
    assert any(r.startswith("support_play_too_large:median_on_base") for r in _validate(data).assembly.reasons)


def test_nothing_rolls_on_the_plate():
    graph = build_routing_graph(layout_from_dict(DATA), CATALOG)
    assert not any(n.startswith("apex_plate:") and targets for n, targets in graph.edges.items())


def test_without_the_apex_columns_the_sides_tip():
    data = copy.deepcopy(DATA)
    data["supports"] = [s for s in data["supports"] if s["name"] not in ("col_left_3", "col_right_3")]
    assert not _validate(data).valid


def test_the_marble_splits_at_the_base_and_runs_down_both_sides():
    from quadrilla_solver.generator import layout_sinks, layout_source
    result = validate_layout(layout_from_dict(DATA), CATALOG, source=layout_source(DATA), sinks=layout_sinks(DATA))
    assert result.valid
    assert set(result.connectivity.reached_sinks) == {"side_left:hole:2", "side_right:hole:2"}


def test_the_fixture_is_recognized_as_a_triangle_base():
    from quadrilla_solver.generator import layout_source
    from quadrilla_solver.scoring import layout_metrics
    assert layout_metrics(layout_from_dict(DATA), CATALOG, layout_source(DATA))["triangles"] == 1


def test_the_generator_places_triangles_on_request():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(triangle_probability=1.0, max_height_units=45, max_rails=14,
                             exclude_parts=("red_right_angle",))
    found = [c for c in generate(CATALOG, budget, config=config, attempts=60, seed=1, keep=20)
             if c.metrics["triangles"]]
    assert found
    best = found[0]
    # both sides are exits, and the pattern keeps its own supports
    assert best.metrics["exits"] >= 2
    assert any(s.play_cm for s in best.layout.supports)


def test_the_pattern_matches_the_fixture_geometry():
    from quadrilla_solver.patterns import isosceles_triangle
    tri = isosceles_triangle(CATALOG)
    assert abs(tri["apex_cm"] - 36.589) < 1e-3 and tri["play_cm"] == 0.3


def test_a_base_lottery_of_only_triangles_keeps_only_triangle_builds():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(bases={"triangle": 1.0}, max_height_units=45, max_rails=14,
                             exclude_parts=("red_right_angle",))
    found = generate(CATALOG, budget, config=config, attempts=60, seed=1, keep=10)
    assert found and all(c.metrics["triangles"] == 1 for c in found)
    # the pattern keeps its own supports (the median's play) after solving
    assert all(any(s.play_cm for s in c.layout.supports) for c in found)


def test_unknown_bases_are_refused():
    import pytest
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    with pytest.raises(ValueError):
        generate(CATALOG, budget, config=GeneratorConfig(bases={"pyramid": 1.0}), attempts=1)


def test_bottom_up_grows_a_valid_route_up_from_the_triangle():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(strategy="bottom_up", max_height_units=45, max_rails=14,
                             exclude_parts=("red_right_angle",))
    stats = {}
    found = generate(CATALOG, budget, config=config, attempts=20, seed=1, keep=5, stats=stats)
    assert found and stats["valid"] >= 10
    for c in found:
        assert c.metrics["triangles"] == 1
        assert c.metrics["rails"] >= 7          # the base's five and at least two above
        assert c.source.port == "top"


def test_the_site_map_keeps_bottom_up_columns_off_the_ground():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    base = dict(strategy="bottom_up", max_height_units=45, max_rails=14, exclude_parts=("red_right_angle",))
    with_sites = generate(CATALOG, budget, config=GeneratorConfig(**base), attempts=30, seed=1, keep=5)
    without = generate(CATALOG, budget, config=GeneratorConfig(**base, up_sites=False), attempts=30, seed=1, keep=5)
    mean = lambda cs, k: sum(c.metrics[k] for c in cs) / len(cs)
    assert mean(with_sites, "ground_columns") < mean(without, "ground_columns")
    assert mean(with_sites, "parts") < mean(without, "parts")


def test_curves_need_a_block_on_each_end_and_get_one():
    from quadrilla_solver.generator import Budget, load_curve_ends, layout_sinks, layout_source, resolve_set_paths
    data = yaml.safe_load((ROOT / "examples" / "bottom_up" / "mr-6cd8d488.yaml").read_text())
    layout = layout_from_dict(data)
    assert validate_layout(layout, CATALOG, source=layout_source(data), sinks=layout_sinks(data)).valid
    # without the block on the curve's far end the curve tips
    stripped = [s for s in layout.supports if not s.name.startswith("ce")]
    bare = layout_from_dict({**data, "supports": [s for s in data["supports"] if not s["name"].startswith("ce")]})
    assert len(stripped) < len(layout.supports)
    assert any(r.startswith("curve_needs_load_above:") for r in validate_layout(bare, CATALOG).assembly.reasons)


def test_a_split_branch_merges_through_a_hole_below():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(strategy="bottom_up", max_height_units=30, max_rails=14,
                             exclude_parts=("red_right_angle",))
    found = generate(CATALOG, budget, config=config, attempts=40, seed=1, keep=10)
    merged = [c for c in found if c.metrics["merges"] >= 1]
    assert merged
    for c in merged:
        assert validate_layout(c.layout, CATALOG, source=c.source, sinks=c.sinks).valid


def test_the_ladder_base_climbs_between_two_towers():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(strategy="bottom_up", up_base="ladder", max_height_units=45, max_rails=16,
                             exclude_parts=("red_right_angle",))
    found = generate(CATALOG, budget, config=config, attempts=40, seed=1, keep=10)
    assert found
    best = max(found, key=lambda c: c.metrics["switchbacks"])
    assert best.metrics["switchbacks"] >= 2
    result = validate_layout(best.layout, CATALOG, source=best.source, sinks=best.sinks)
    assert result.valid
    # the cross feet give it width: it must not stand on a line (one rail deep)
    assert result.global_stability.margin_cm > 10


def test_the_box_ladder_fixture_stands_splits_and_merges():
    from quadrilla_solver.model import PortRef
    data = yaml.safe_load((ROOT / "tests" / "fixtures" / "box-ladder.yaml").read_text())
    layout = layout_from_dict(data)
    q = data["routing_query"]
    source = PortRef(q["source"]["component_id"], q["source"]["port"])
    sinks = tuple(PortRef(s["component_id"], s["port"]) for s in q["sinks"])
    result = validate_layout(layout, CATALOG, source=source, sinks=sinks)
    assert result.valid
    assert set(result.connectivity.reached_sinks) == {s.key for s in sinks}
    # x- and y-rails brace each other: a wide support polygon
    assert result.global_stability.margin_cm > 15
    yaws = {round(r.yaw_deg) % 180 for r in layout.rails}
    assert yaws == {0, 90}
