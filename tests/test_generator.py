from pathlib import Path

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import (
    Budget, GeneratorConfig, generate, layout_to_yaml_dict, resolve_set_paths,
)
from quadrilla_solver.model import PortRef
from quadrilla_solver.validation import validate_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
SETS = ["QD001", "QD003", "QD005"]


def _budget() -> Budget:
    return Budget.from_sets(resolve_set_paths(ROOT, SETS))


def _run(seed: int):
    return generate(CATALOG, _budget(), config=GeneratorConfig(), attempts=60, seed=seed, keep=3)


def test_generation_is_deterministic_for_a_seed():
    first = [c.layout for c in _run(5)]
    second = [c.layout for c in _run(5)]
    assert first and first == second


def test_generated_layouts_validate_and_respect_the_set_inventory():
    budget = _budget().counts
    for candidate in _run(11):
        layout = candidate.layout
        leaves = [f"{r.id}:end_b" for r in layout.rails
                  if "block_connected" not in r.hole_states.values()]
        sinks = tuple(PortRef(*s.split(":", 1)) for s in leaves)
        result = validate_layout(layout, CATALOG, source=PortRef("rail0", "end_a"), sinks=sinks)
        assert result.valid, result
        assert result.marble_clearance == ()
        assert all(r.yaw_deg % 90 == 0 for r in layout.rails)

        used = candidate.usage
        # Center-hole long rails draw from the long-rail count; unspecified
        # straight rails can stand in for either length.
        short = used.get("straight_short", 0)
        long_ = used.get("straight_long", 0) + used.get("straight_long_center", 0)
        overflow = max(0, short - budget["straight_short"]) + max(0, long_ - budget["straight_long"])
        assert overflow <= budget["straight_unspecified"]
        for part, count in used.items():
            if not part.startswith("straight_"):
                assert count <= budget[part], part
        covered = sum(1 for r in layout.rails for s in r.hole_states.values() if s == "covered")
        assert used["cover"] == covered


def test_unknown_set_id_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="unknown set id"):
        resolve_set_paths(ROOT, ["QD999"])


def test_yaml_round_trip_keeps_the_layout_valid(tmp_path):
    import yaml

    from quadrilla_solver.model import load_layout

    candidate = _run(3)[0]
    data = layout_to_yaml_dict(candidate, name="round-trip", description="test",
                               generator_info={"seed": 3})
    path = tmp_path / "layout.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    loaded = load_layout(path)
    assert loaded.rails == candidate.layout.rails
    assert loaded.parts == candidate.layout.parts
    assert loaded.supports == candidate.layout.supports


def test_published_generated_examples_stay_valid():
    from quadrilla_solver.model import load_layout

    paths = sorted((ROOT / "examples" / "generated").glob("*.yaml"))
    assert paths
    for path in paths:
        layout = load_layout(path)
        leaves = [f"{r.id}:end_b" for r in layout.rails
                  if "block_connected" not in r.hole_states.values()]
        sinks = tuple(PortRef(*s.split(":", 1)) for s in leaves)
        result = validate_layout(layout, CATALOG, source=PortRef("rail0", "end_a"), sinks=sinks)
        assert result.valid, (path.name, result)


def test_generator_stacks_columns_on_rails_and_lands_marbles():
    from quadrilla_solver.connectivity import build_routing_graph

    candidates = _run(1)
    assert any(c.metrics["columns_on_rails"] > 0 for c in candidates)
    best = candidates[0]
    on_rail = [s for s in best.layout.supports if s.lower_rail_id is not None]
    assert on_rail
    edges = build_routing_graph(best.layout, CATALOG).edges
    # At least one landing edge: a block outlet feeding a rail hole directly.
    rails = {r.id for r in best.layout.rails}
    landing = [(src, dst) for src, dsts in edges.items() for dst in dsts
               if src.split(":")[0] not in rails and dst.split(":")[0] in rails
               and ":hole:" in dst]
    assert landing


def test_layout_id_is_stable_and_survives_yaml_round_trips(tmp_path):
    import yaml

    from quadrilla_solver.generator import layout_id
    from quadrilla_solver.model import load_layout

    candidate = _run(3)[0]
    first = layout_id(candidate.layout)
    assert first.startswith("mr-") and len(first) == 11
    data = layout_to_yaml_dict(candidate, name="x", description="y", generator_info={})
    assert data["layout_id"] == first
    path = tmp_path / "layout.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert layout_id(load_layout(path)) == first
    # Names and metrics do not change the ID; the build does.
    renamed = layout_to_yaml_dict(candidate, name="other", description="z", generator_info={"a": 1})
    assert renamed["layout_id"] == first
    from dataclasses import replace
    moved = replace(candidate.layout, parts=tuple(
        replace(p, x_cm=p.x_cm + 1) if i == 0 else p for i, p in enumerate(candidate.layout.parts)))
    assert layout_id(moved) != first


def test_gallery_index_matches_its_layouts():
    import json

    from quadrilla_solver.generator import layout_id
    from quadrilla_solver.model import load_layout

    index = json.loads((ROOT / "examples" / "gallery" / "index.json").read_text())
    assert index["layouts"]
    for entry in index["layouts"]:
        path = ROOT / entry["file"]
        assert path.exists(), entry["file"]
        assert layout_id(load_layout(path)) == entry["id"] == path.stem
        leaves = [f"{r.id}:end_b" for r in load_layout(path).rails
                  if "block_connected" not in r.hole_states.values()]
        result = validate_layout(load_layout(path), CATALOG, source=PortRef("rail0", "end_a"),
                                 sinks=tuple(PortRef(*s.split(":", 1)) for s in leaves))
        assert result.valid, entry["id"]
