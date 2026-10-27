"""Improve a generated build by simulated annealing (user idea, 2026-10-26).

The generator grows a build from a stream of random decisions: the
direction of a rail, which hole it stops at, the block of a drop, whether
to switch back or merge... Here that stream is recorded as a *tape*. A
neighbour is the same tape with a change:

- **re-roll from k**: keep the first k decisions, draw the rest afresh. The
  upper part of the build stays; everything grown after decision k is grown
  again (rails re-attached, other drops, another base placement).
- **point change**: one decision gets a new value and the rest are replayed,
  e.g. another block for one drop, another stop hole, a switchback taken.
- **nudge**: one decision moves a little, which often keeps its choice.

Every neighbour is grown by the generator itself and goes through the same
validation and post-passes (support solving, shortening, curves, balance) as
generate(), so every accepted step is a buildable layout. The score is the
same as the generator's (scoring.py); a worse neighbour is accepted with
probability exp(delta / T), T falling geometrically from t_start to t_end.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .catalog import PartCatalog
from .generator import (
    Budget, Candidate, CascadeGenerator, GeneratorConfig, _base_config, _has_base, candidate_from_state,
)


class TapeRandom(random.Random):
    """random.Random whose draws come from a tape of floats in [0, 1); past
    its end it draws from `fresh` and appends. Every method of Random
    reduces to random() or getrandbits(), so both read the tape."""

    def __init__(self, tape: list[float], fresh: random.Random):
        self.tape = list(tape)
        self.pos = 0
        self.fresh = fresh
        super().__init__(0)

    def _next(self) -> float:
        if self.pos < len(self.tape):
            value = self.tape[self.pos]
        else:
            value = self.fresh.random()
            self.tape.append(value)
        self.pos += 1
        return value

    def random(self) -> float:  # noqa: D401 - random.Random API
        return self._next()

    def getrandbits(self, k: int) -> int:
        return int(self._next() * (1 << k)) if k else 0

    def used(self) -> list[float]:
        return self.tape[:self.pos]


@dataclass
class AnnealResult:
    start: Candidate
    best: Candidate
    best_tape: list[float]
    history: list[dict[str, Any]] = field(default_factory=list)
    evaluated: int = 0
    valid: int = 0


def grow(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, tape: list[float],
         fresh: random.Random, base: str | None = None, name: str = "annealed"
         ) -> tuple[Candidate | None, list[float]]:
    """Grow one build from a tape; returns (candidate or None, tape used)."""
    rng = TapeRandom(tape, fresh)
    generator = CascadeGenerator(catalog, budget, _base_config(config, base) if base else config, rng)
    state = generator.build_once()
    generator.config = config
    if state is None or len(state.rails) < 2 or (base and not _has_base(state, base)):
        return None, rng.used()
    candidate = candidate_from_state(generator, state, config, catalog, budget, rng, name)
    return candidate, rng.used()


def mutate(tape: list[float], rng: random.Random) -> list[float]:
    if not tape:
        return []
    n = len(tape)
    kind = rng.random()
    if kind < 0.45:   # re-roll from k
        return tape[:rng.randrange(n)]
    out = list(tape)
    i = rng.randrange(n)
    if kind < 0.8:    # point change
        out[i] = rng.random()
    else:             # nudge
        out[i] = (out[i] + rng.gauss(0.0, 0.05)) % 1.0
    return out


def anneal(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, *, seed: int = 1,
           iterations: int = 300, base: str | None = None, start_tape: list[float] | None = None,
           t_start: float = 8.0, t_end: float = 0.3, max_starts: int = 400,
           progress: Callable[[int, AnnealResult], Any] | None = None) -> AnnealResult | None:
    """Anneal from `start_tape` (or the first valid random build)."""
    rng = random.Random(seed)
    fresh = random.Random(seed * 7919 + 1)
    evaluated = valid = 0
    current, tape = None, list(start_tape or [])
    for _ in range(max_starts if not start_tape else 1):
        current, tape = grow(catalog, budget, config, tape, fresh, base)
        evaluated += 1
        if current is not None:
            break
        tape = []
    if current is None:
        return None
    valid += 1
    result = AnnealResult(start=current, best=current, best_tape=list(tape))
    for i in range(iterations):
        t = t_start * (t_end / t_start) ** (i / max(1, iterations - 1))
        candidate, new_tape = grow(catalog, budget, config, mutate(tape, rng), fresh, base)
        evaluated += 1
        accepted = False
        if candidate is not None:
            valid += 1
            delta = candidate.score - current.score
            if delta >= 0 or rng.random() < math.exp(delta / t):
                current, tape, accepted = candidate, new_tape, True
                if current.score > result.best.score:
                    result.best, result.best_tape = current, list(tape)
        result.history.append({"i": i, "t": round(t, 3), "valid": candidate is not None,
                               "score": round(candidate.score, 2) if candidate else None,
                               "current": round(current.score, 2), "best": round(result.best.score, 2),
                               "accepted": accepted})
        if progress is not None:
            progress(i, result)
    result.evaluated, result.valid = evaluated, valid
    return result


# ---- layout-level moves on the grown state ----------------------------------
# Unlike a tape change, these keep the rest of the build in place.

def grow_state(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, tape: list[float],
               base: str | None = None):
    """(generator, state) grown from a tape, without the post-passes."""
    rng = TapeRandom(tape, random.Random(0))
    generator = CascadeGenerator(catalog, budget, _base_config(config, base) if base else config, rng)
    state = generator.build_once()
    generator.config = config
    return generator, state


def upstream_rails(state, rail_id: str) -> set[str]:
    """Rails the marble passes before reaching `rail_id` (and `rail_id`)."""
    feeds: dict[str, set[str]] = {}
    for col in state.columns.values():
        if col.top_types and col.top_rail and col.base_rail:
            feeds.setdefault(col.base_rail, set()).add(col.top_rail)
    for col_id, _port, rail in state.route_links:
        col = state.columns.get(col_id)
        if col is not None and col.top_rail:
            feeds.setdefault(rail, set()).add(col.top_rail)
    out, todo = set(), [rail_id]
    while todo:
        rid = todo.pop()
        if rid in out:
            continue
        out.add(rid)
        todo.extend(feeds.get(rid, ()))
    return out


def junctions(state) -> list[str]:
    """Drop columns whose upper part could turn about them: a route column
    between two rails, with rails above it."""
    return [cid for cid, c in state.columns.items()
            if c.top_types and c.top_rail and c.base_rail and c.top_rail not in state.fixed]


def rotate_above(generator, state, junction: str, quarter: int):
    """Turn everything upstream of a drop column by quarter x 90 degrees about
    the column's axis (user review of mr-a5c66ca1: "turn this four-corner
    frame by 90 degrees"). The column itself stays; its upper rail turns
    about it. Plain support columns of the turned part are dropped (the
    support solver puts them back). Returns the new state, or None if the
    turned part hits the rest or leaves the footprint."""
    from math import cos, radians, sin
    from dataclasses import replace

    from .collision import Solid

    pivot = state.columns[junction]
    group = upstream_rails(state, pivot.top_rail)
    if pivot.base_rail in group or any(r in state.fixed for r in group):
        return None
    a = radians(90 * quarter)
    c, s = cos(a), sin(a)
    px, py = pivot.x, pivot.y

    def turn(x: float, y: float) -> tuple[float, float]:
        dx, dy = x - px, y - py
        return round(px + c * dx - s * dy, 6), round(py + s * dx + c * dy, 6)

    new = state.copy()
    moved_ids: set[str] = set()
    for rid in group:
        rail = state.rails[rid]
        x, y = turn(rail.x_cm, rail.y_cm)
        new.rails[rid] = replace(rail, x_cm=x, y_cm=y, yaw_deg=round((rail.yaw_deg + 90 * quarter) % 360, 6))
    for cid, col in list(state.columns.items()):
        if cid == junction:
            continue
        holds = col.top_rail in group or (col.top_rail is None and col.base_rail in group)
        if not holds:
            continue
        if not col.top_types:        # a plain support: solved again later
            del new.columns[cid]
            continue
        x, y = turn(col.x, col.y)
        new.columns[cid] = replace(col, x=x, y=y, block_rotation=(col.block_rotation + 90 * quarter) % 360)
        moved_ids.add(cid)
    for key, solid in list(state.corridors.items()):
        owner = key.split("#", 1)[0]
        if owner in group or owner in moved_ids:
            x, y = turn(*solid.center_xy)
            new.corridors[key] = Solid(solid.id, (x, y), solid.half_extents_xy,
                                       solid.angle_rad + a, solid.z_min_cm, solid.z_max_cm)
            moved_ids.add(key)
    # The turned part may not hit the rest (its own plain supports are gone).
    rest = new.copy()
    for rid in group:
        del rest.rails[rid]
    for cid in moved_ids:
        rest.columns.pop(cid, None)
        rest.corridors.pop(cid, None)
    candidates = [p for rid in group for p in generator._rail_solids(new.rails[rid])]
    candidates += [new.columns[cid].solid(generator.half) for cid in moved_ids if cid in new.columns]
    candidates += [new.corridors[k] for k in moved_ids if k in new.corridors]
    # The footprint is a size limit, not a place: check the whole build's
    # top-view extent rather than the fixed box around the origin.
    every = [p for r in new.rails.values() for p in generator._rail_solids(r)]
    every += [col.solid(generator.half) for col in new.columns.values()]
    xs = [v for p in every for v in _extent(p)[0]]
    ys = [v for p in every for v in _extent(p)[1]]
    if max(xs) - min(xs) > generator.config.footprint_cm[0] + 1e-6 or \
            max(ys) - min(ys) > generator.config.footprint_cm[1] + 1e-6:
        return None
    if generator._hits(rest, candidates, ignore={junction}):
        return None
    return new


def _extent(solid) -> tuple[tuple[float, float], tuple[float, float]]:
    from math import cos, sin
    (cx, cy), (hx, hy), a = solid.center_xy, solid.half_extents_xy, solid.angle_rad
    ex = abs(hx * cos(a)) + abs(hy * sin(a))
    ey = abs(hx * sin(a)) + abs(hy * cos(a))
    return (cx - ex, cx + ex), (cy - ey, cy + ey)


def candidate_after_move(generator, state, config: GeneratorConfig, catalog: PartCatalog, budget: Budget,
                         name: str = "moved"):
    """The post-passes for a moved state whose supports must be solved again
    first: materialize, solve supports, validate, shorten, curves, balance."""
    from .generator import (
        Candidate, PortRef, _metrics, add_curves, balance, component_solids, layout_metrics, layout_usage,
        score, shorten_rails, validate_layout,
    )
    from .supports import resolve_supports

    layout, usage, block_ids = generator.materialize(state, name)
    sinks = tuple(PortRef(*leaf.split(":", 1)) for leaf in state.leaves)
    sinks += tuple(PortRef(block_ids[col], port) for col, port in state.dangling)
    source = generator.source
    counts = dict(generator.budget.counts)
    layout = resolve_supports(layout, catalog, counts, source, sinks, keep_braces=False,
                              min_support_g=config.min_support_reaction_g, fixed_rails=state.fixed)
    if layout is None:
        return None
    result = validate_layout(layout, catalog, source=source, sinks=sinks)
    if not result.valid or set(result.connectivity.reached_sinks) != {s.key for s in sinks}:
        return None
    layout = shorten_rails(layout, catalog, generator.budget, source, sinks)
    layout = add_curves(layout, catalog, budget, random.Random(0), source, sinks,
                        keep_straight=list(state.braces) + list(state.fixed))
    layout = balance(layout, catalog, generator.budget, source, sinks, config.min_support_reaction_g)
    if layout is None:
        return None
    solids = component_solids(layout, catalog)
    usage = layout_usage(layout)
    metrics = _metrics(state, layout, catalog, result.connectivity.paths, solids, block_ids)
    metrics["curved_rails"] = sum(1 for r in layout.rails if catalog.rails[r.rail_type].shape == "arc")
    metrics["twists"] = sum(1 for r in layout.rails if catalog.rails[r.rail_type].shape == "twist")
    metrics["covers"] = usage.get("cover", 0)
    metrics.update(layout_metrics(layout, catalog, source))
    return Candidate(layout, score(metrics, config.weights), metrics, usage, sinks, source)


def apply_moves(generator, state, moves: list[tuple[str, int]]):
    """Apply layout-level moves in order; a move that does not fit is skipped."""
    for junction, quarter in moves:
        if junction not in state.columns:
            continue
        turned = rotate_above(generator, state, junction, quarter)
        if turned is not None:
            state = turned
    return state


def anneal_with_moves(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, start_tape: list[float], *,
                      seed: int = 1, iterations: int = 200, base: str | None = None, p_tape: float = 0.3,
                      t_start: float = 3.0, t_end: float = 0.1) -> AnnealResult | None:
    """Anneal over (tape, layout moves). A tape change re-grows and drops the
    moves; otherwise a turn is added, removed or changed. Every candidate is
    scored after the same support solving (candidate_after_move)."""
    rng = random.Random(seed)
    fresh = random.Random(seed * 7919 + 1)

    def evaluate(tape, moves):
        r = TapeRandom(tape, fresh)
        generator = CascadeGenerator(catalog, budget, _base_config(config, base) if base else config, r)
        state = generator.build_once()
        generator.config = config
        if state is None or len(state.rails) < 2 or (base and not _has_base(state, base)):
            return None, r.used(), []
        moved = apply_moves(generator, state, moves)
        return candidate_after_move(generator, moved, config, catalog, budget), r.used(), junctions(state)

    current, tape, joints = evaluate(start_tape, [])
    if current is None:
        return None
    moves: list[tuple[str, int]] = []
    result = AnnealResult(start=current, best=current, best_tape=list(tape))
    result.best_moves = []  # type: ignore[attr-defined]
    valid = 1
    for i in range(iterations):
        t = t_start * (t_end / t_start) ** (i / max(1, iterations - 1))
        new_tape, new_moves = tape, list(moves)
        if rng.random() < p_tape or not joints:
            new_tape, new_moves = mutate(tape, rng), []
        else:
            roll = rng.random()
            if new_moves and roll < 0.3:
                new_moves.pop(rng.randrange(len(new_moves)))
            elif new_moves and roll < 0.5:
                k = rng.randrange(len(new_moves))
                new_moves[k] = (new_moves[k][0], rng.choice((1, 2, 3)))
            else:
                new_moves.append((rng.choice(joints), rng.choice((1, 2, 3))))
        candidate, used, new_joints = evaluate(new_tape, new_moves)
        accepted = False
        if candidate is not None:
            valid += 1
            delta = candidate.score - current.score
            if delta >= 0 or rng.random() < math.exp(delta / t):
                current, tape, moves, joints, accepted = candidate, used, new_moves, new_joints, True
                if current.score > result.best.score:
                    result.best, result.best_tape = current, list(tape)
                    result.best_moves = list(moves)  # type: ignore[attr-defined]
        result.history.append({"i": i, "valid": candidate is not None, "current": round(current.score, 2),
                               "best": round(result.best.score, 2), "accepted": accepted, "moves": len(moves)})
    result.evaluated, result.valid = iterations + 1, valid
    return result
