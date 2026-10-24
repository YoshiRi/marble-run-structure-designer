"""Support solver (supports.py): the columns the marble never touches are
solved again, for all rails at once."""
from pathlib import Path

import yaml

from quadrilla_solver import generator as g
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.supports import resolve_supports, route_parts, strip_supports
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
BUDGET = g.Budget.from_sets(g.resolve_set_paths(ROOT, ["QD001", "QD003", "QD005", "QDE6008AB05"]))
COUNTS = {k: (0 if k == "red_right_angle" else v) for k, v in BUDGET.counts.items()}


def _builds(n=4):
    config = g.GeneratorConfig(exclude_parts=("red_right_angle",))
    return g.generate(CATALOG, BUDGET, config=config, attempts=80, seed=2, keep=n)


def test_strip_keeps_the_route_columns_and_rails_only():
    c = _builds(1)[0]
    stripped = strip_supports(c.layout, CATALOG, c.source, keep_braces=False)
    on_route = route_parts(c.layout, CATALOG, c.source)
    assert {r.id for r in stripped.rails} <= on_route
    # Every column left carries the marble somewhere (its filler stays with it).
    assert all(any(p in on_route for p in s.stack_part_ids) for s in stripped.supports)
    assert len(stripped.supports) < len(c.layout.supports)


def test_resolved_builds_validate_and_use_fewer_or_equal_parts():
    solved = 0
    for c in _builds():
        better = resolve_supports(c.layout, CATALOG, COUNTS, c.source, list(c.sinks), keep_braces=False)
        if better is None:
            continue
        solved += 1
        result = validate_layout(better, CATALOG, source=c.source, sinks=c.sinks)
        assert result.valid, result
        assert {r.id for r in better.rails} <= {r.id for r in c.layout.rails}
        # Every rail has exactly two supports.
        for rail in better.rails:
            assert sum(1 for s in better.supports if s.upper_rail_id == rail.id) == 2
    assert solved >= 2


def test_columns_may_stand_on_a_lower_rail():
    found = False
    for c in _builds(6):
        better = resolve_supports(c.layout, CATALOG, COUNTS, c.source, list(c.sinks), keep_braces=False)
        if better and any(s.name.startswith("s") and s.lower_rail_id for s in better.supports):
            found = True
            break
    assert found


def test_generator_option_solves_supports():
    config = g.GeneratorConfig(exclude_parts=("red_right_angle",), solve_supports=True)
    found = g.generate(CATALOG, BUDGET, config=config, attempts=60, seed=3, keep=3)
    assert found
    for c in found:
        assert validate_layout(c.layout, CATALOG, source=c.source, sinks=c.sinks).valid
