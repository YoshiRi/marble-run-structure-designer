from pathlib import Path

from quadrilla_solver.catalog import load_catalog
import yaml

from quadrilla_solver.generator import (
    layout_sinks, layout_source,
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
        sinks = candidate.sinks
        assert sinks
        result = validate_layout(layout, CATALOG, source=candidate.source, sinks=sinks)
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
        data = yaml.safe_load(path.read_text())
        sinks = layout_sinks(data)
        result = validate_layout(layout, CATALOG, source=layout_source(data), sinks=sinks)
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
        result = validate_layout(load_layout(path), CATALOG,
                                 source=layout_source(yaml.safe_load(path.read_text())),
                                 sinks=layout_sinks(yaml.safe_load(path.read_text())))
        assert result.valid, entry["id"]


def test_exits_are_contained_and_capped():
    """Default rule: branches end at a block outlet or by diving through an
    open rail hole (never off a rail end), at most max_exits of them."""
    found = []
    for seed in (2, 7):
        found += generate(CATALOG, _budget(), config=GeneratorConfig(twist_probability=0.9),
                          attempts=60, seed=seed, keep=10)
    assert found
    for c in found:
        assert 1 <= len(c.sinks) <= 2
        rails = c.layout.rail_map()
        for sink in c.sinks:
            assert sink.port != "end_b" and sink.port != "end_a"
            if sink.component_id in rails:
                index = int(sink.port.split(":")[1])
                assert rails[sink.component_id].hole_states[index] == "open"
        assert c.metrics["exits"] == len(c.sinks)
    three = generate(CATALOG, _budget(), config=GeneratorConfig(max_exits=3, split_probability=0.9),
                     attempts=60, seed=3, keep=10)
    assert max(len(c.sinks) for c in three) <= 3


def test_twists_are_fed_like_rails():
    """Review (mr-c61a3513): a bottom outlet on a chute hole drops through it,
    so twists are entered only by landing on the chute or at its tip."""
    from quadrilla_solver.connectivity import build_routing_graph

    found = generate(CATALOG, _budget(), config=GeneratorConfig(twist_probability=0.9),
                     attempts=80, seed=5, keep=10)
    twisted = [c for c in found if c.metrics["twists"]]
    assert twisted
    for c in twisted:
        edges = build_routing_graph(c.layout, CATALOG).edges
        twists = {r.id for r in c.layout.rails if r.rail_type == "spiral"}
        into = [(src, dst) for src, dsts in edges.items() for dst in dsts
                if dst.split(":")[0] in twists and src.split(":")[0] not in twists]
        assert into
        assert all(not src.endswith(":bottom") for src, _ in into)

def test_input_goes_straight_into_a_block_standing_on_a_rail():
    """No input rail: the marble is put into the top of a free-standing stack
    on a rail, so no columns are spent on holding up an input rail."""
    found = _run(11)
    assert found
    for c in found:
        assert c.source.port == "top"
        support = next(s for s in c.layout.supports if c.source.component_id in s.stack_part_ids)
        assert support.upper_rail_id is None and support.lower_rail_id is not None
        assert support.stack_part_ids[-1] == c.source.component_id


def test_weak_towers_are_counted_and_penalized():
    from quadrilla_solver.generator import score, weak_towers
    from quadrilla_solver.model import load_layout

    # Stacks braced along one axis count once they reach min_blocks.
    layout = load_layout(ROOT / "tests" / "fixtures" / "landing-tower.yaml")
    assert weak_towers(layout, CATALOG, min_blocks=1) >= 1
    assert weak_towers(layout, CATALOG, min_blocks=99) == 0
    # One rule, a penalty (user decision): candidates may keep weak towers.
    base = {"levels": 5, "rolling_length_cm": 100, "random_branches": 0, "columns_on_rails": 0}
    assert score({**base, "weak_towers": 1}) < score({**base, "weak_towers": 0})

def test_excluded_parts_are_never_used():
    found = generate(CATALOG, _budget(), config=GeneratorConfig(exclude_parts=("red_right_angle",)),
                     attempts=60, seed=11, keep=10)
    assert found
    assert all(c.usage.get("red_right_angle", 0) == 0 for c in found)


def test_every_rail_support_keeps_pressing():
    """Review 3: moments about each rail's supports; the lighter support must
    keep at least min_support_reaction_g (counterweights may be added)."""
    from quadrilla_solver.generator import support_reactions_g

    for c in _run(11):
        reactions = support_reactions_g(c.layout, CATALOG, overhang_only=True)
        assert reactions is not None
        assert all(g >= GeneratorConfig().min_support_reaction_g - 1e-6 for g in reactions.values())


def test_balance_rejects_an_overhang_it_cannot_counter():
    from dataclasses import replace

    from quadrilla_solver.generator import balance, support_reactions_g
    from quadrilla_solver.model import PlacedPart, SupportLink, load_layout, rail_hole_world

    layout = load_layout(ROOT / "tests" / "fixtures" / "twist-drop.yaml")
    # A blue alone on the exit rail's overhanging hole 0 nearly unloads hole 3's support.
    x, y, _ = rail_hole_world(layout.rail_map()["exit"], CATALOG, 0)
    heavy = replace(layout, parts=layout.parts + (PlacedPart("lone", "blue", x, y, 2),),
                    supports=layout.supports + (SupportLink(None, None, ("lone",), "exit", 0, name="lone"),))
    assert support_reactions_g(heavy, CATALOG, overhang_only=True)["exit"] < 20
    assert "exit" not in support_reactions_g(layout, CATALOG, overhang_only=True)
    # Every other exit hole lies under the rolling marble: no place for a counterweight.
    source, sinks = PortRef("upper", "end_a"), (PortRef("exit", "end_b"),)
    assert balance(heavy, CATALOG, _budget(), source, sinks, 20) is None
    assert balance(layout, CATALOG, _budget(), source, sinks, 20) == layout


def test_weak_towers_get_brace_rails():
    """Review 3 (user's choice): tie tall stacks with rails across them."""
    found = generate(CATALOG, _budget(), attempts=80, seed=1, keep=200)
    braced = [c for c in found if c.metrics["braces"] > 0]
    assert braced
    unbraced = generate(CATALOG, _budget(), config=GeneratorConfig(brace_towers=False),
                        attempts=80, seed=1, keep=200)
    assert len(found) > len(unbraced)
    for c in braced[:3]:
        assert validate_layout(c.layout, CATALOG, source=c.source, sinks=c.sinks).valid
        linked = {l.source.component_id for l in c.layout.route_links} | {l.target.component_id for l in c.layout.route_links}
        braces = [r for r in c.layout.rails if not r.hole_states and r.id not in linked]
        assert braces


def test_brace_rails_stay_straight():
    found = generate(CATALOG, _budget(), config=GeneratorConfig(curve_ready_bias=0.9),
                     attempts=80, seed=1, keep=200)
    linked = lambda c: {l.source.component_id for l in c.layout.route_links} | \
        {l.target.component_id for l in c.layout.route_links}
    braces = [r for c in found if c.metrics["braces"]
              for r in c.layout.rails if not r.hole_states and r.id not in linked(c)]
    assert braces
    assert all(r.rail_type.startswith("straight_") for r in braces)


def test_generate_reports_attempt_counts():
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["QD001", "QD003", "QD005"]))
    stats = {}
    generate(CATALOG, budget, config=GeneratorConfig(), attempts=20, seed=1, keep=2, stats=stats)
    assert stats["attempts"] == 20 and 0 <= stats["valid"] <= 20


def test_seesaw_diamond_builds_validate_and_merge():
    """Design doc §6.1: a seesaw split whose two arms feed one collector rail."""
    from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
    from quadrilla_solver.validation import validate_layout
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["QD001", "QD003", "QD005", "QDE6008AB05"]))
    config = GeneratorConfig(exclude_parts=("red_right_angle",), seesaw_probability=1.0,
                             weights={"merges": 25.0})
    found = [c for c in generate(CATALOG, budget, config=config, attempts=120, seed=1, keep=20)
             if any(p.part_type == "seesaw" for p in c.layout.parts)]
    assert found, "no seesaw diamond in 120 attempts"
    for c in found:
        assert c.metrics["merges"] >= 1
        rails = {r.flow_direction for r in c.layout.rails}
        assert {"from_hole", "to_hole"} <= rails
        result = validate_layout(c.layout, CATALOG, source=c.source, sinks=c.sinks)
        assert result.valid
