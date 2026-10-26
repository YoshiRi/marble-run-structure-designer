"""Annealing over the generator's decision tape (anneal.py)."""
from __future__ import annotations

import random
from pathlib import Path

from quadrilla_solver.anneal import TapeRandom, anneal, grow, mutate
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, GeneratorConfig, layout_id, resolve_set_paths

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
BUDGET = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
CONFIG = GeneratorConfig(exclude_parts=("red_right_angle",), max_height_units=45, max_rails=14)


def _first_valid(base):
    fresh = random.Random(3)
    for _ in range(80):
        c, tape = grow(CATALOG, BUDGET, CONFIG, [], fresh, base)
        if c is not None:
            return c, tape
    raise AssertionError("no valid build")


def test_a_tape_replays_the_same_build():
    c, tape = _first_valid("triangle")
    again, _ = grow(CATALOG, BUDGET, CONFIG, tape, random.Random(999), "triangle")
    assert again is not None and layout_id(again.layout) == layout_id(c.layout)


def test_tape_random_draws_past_its_end_and_records():
    r = TapeRandom([0.5], random.Random(1))
    assert r.random() == 0.5
    r.choice([1, 2, 3])
    assert len(r.used()) == 2


def test_mutations_keep_a_prefix_or_the_length():
    rng = random.Random(0)
    tape = [0.1 * i for i in range(10)]
    for _ in range(50):
        new = mutate(tape, rng)
        assert len(new) <= len(tape)
        k = next((i for i, (a, b) in enumerate(zip(tape, new)) if a != b), len(new))
        assert new[:k] == tape[:k]


def test_annealing_never_returns_worse_than_its_start():
    _, tape = _first_valid("triangle")
    result = anneal(CATALOG, BUDGET, CONFIG, seed=2, iterations=25, base="triangle", start_tape=tape)
    assert result is not None
    assert result.best.score >= result.start.score
    assert result.best.metrics["triangles"] == 1


def test_turning_the_part_above_a_drop_keeps_the_build_valid():
    from quadrilla_solver.anneal import candidate_after_move, grow_state, junctions, rotate_above, upstream_rails
    _, tape = _first_valid("triangle")
    generator, state = grow_state(CATALOG, BUDGET, CONFIG, tape, "triangle")
    turned = 0
    for j in junctions(state):
        group = upstream_rails(state, state.columns[j].top_rail)
        assert not group & set(state.fixed)
        for q in (1, 2, 3):
            new = rotate_above(generator, state, j, q)
            if new is None:
                continue
            pivot = state.columns[j]
            assert (new.columns[j].x, new.columns[j].y) == (pivot.x, pivot.y)
            if candidate_after_move(generator, new, CONFIG, CATALOG, BUDGET) is not None:
                turned += 1
    assert turned >= 1
