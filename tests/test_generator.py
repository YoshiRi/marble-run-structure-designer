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
        for part, count in used.items():
            if part in ("straight_short", "straight_long"):
                assert count <= budget[part] + budget["straight_unspecified"], part
            else:
                assert count <= budget[part], part
        rails_used = used.get("straight_short", 0) + used.get("straight_long", 0)
        assert rails_used <= budget["straight_short"] + budget["straight_long"] + budget["straight_unspecified"]
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
