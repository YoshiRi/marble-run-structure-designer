"""Rebuild a layout from hints (user, 2026-11-04; kept apart from detection).

Hints are what a person can tell from looking at a build:

    parts    how many of each part (rails, blocks, covers)
    towers   for every spot where parts stand one above the other: the parts
             bottom to top, with "R" where a rail lies across (e.g.
             foundation, green, R, yellow, purple, R)
    base     the shape it stands on: "grid" (free), "triangle", "ladder", "box"

`extract_hints` reads them off a known layout (the test oracle);
`hint_distance` compares two hint sets (0 = the same hints); `same_structure`
checks two layouts are the same build up to a turn and a shift; `solve`
searches with the generator under the hints (base -> generator settings,
parts -> the exact budget, towers -> the height) and keeps the closest
builds, then anneals the generator's decision tape toward distance 0.
"""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from math import cos, radians, sin
from typing import Any, Mapping, Sequence

from .catalog import PartCatalog
from .model import Layout

RAIL = "R"
BASES = ("grid", "triangle", "ladder", "box")


# ---- hints -------------------------------------------------------------------

def _key(x: float, y: float) -> tuple[float, float]:
    return (round(x * 2) / 2, round(y * 2) / 2)


def extract_hints(layout: Layout, catalog: PartCatalog, base: str = "grid", source=None) -> dict[str, Any]:
    parts = layout.part_map()
    rail_ids = {r.id for r in layout.rails}
    # a block whose side sends the marble into a rail's end (">"), or takes it
    # from one ("<"): a person sees the rail end touching the block
    marks: dict[str, str] = {}
    for link in layout.route_links:
        if link.source.component_id in parts and link.target.component_id in rail_ids:
            marks[link.source.component_id] = ">"
        elif link.target.component_id in parts and link.source.component_id in rail_ids:
            marks[link.target.component_id] = "<"
    usage = Counter(r.rail_type for r in layout.rails) + Counter(p.part_type for p in layout.parts)
    usage["cover"] = sum(1 for r in layout.rails for s in r.hole_states.values() if s == "covered")
    spots: dict[tuple[float, float], list[tuple[float, list[str]]]] = {}
    for s in layout.supports:
        stack = [parts[p] for p in s.stack_part_ids if p in parts]
        if not stack:
            continue
        tokens = ([RAIL] if s.lower_rail_id is not None else []) + [p.part_type + marks.get(p.id, "") for p in stack] + \
            ([RAIL] if s.upper_rail_id is not None else [])
        spots.setdefault(_key(stack[0].x_cm, stack[0].y_cm), []).append((stack[0].z_units, tokens))
    # which spots each rail lies on (or touches with its end): a person sees
    # which columns a rail rests on
    spot_of_part = {}
    for spot, runs in spots.items():
        pass
    rail_spots: dict[str, set] = {r.id: set() for r in layout.rails}
    for s in layout.supports:
        stack = [parts[p] for p in s.stack_part_ids if p in parts]
        if not stack:
            continue
        spot = _key(stack[0].x_cm, stack[0].y_cm)
        for rid in (s.upper_rail_id, s.lower_rail_id):
            if rid in rail_spots:
                rail_spots[rid].add(spot)
    for link in layout.route_links:
        for a, b in ((link.source.component_id, link.target.component_id),
                     (link.target.component_id, link.source.component_id)):
            if a in parts and b in rail_spots:
                rail_spots[b].add(_key(parts[a].x_cm, parts[a].y_cm))
    towers = []
    order = []
    for spot, runs in spots.items():
        order.append(spot)
        runs.sort()
        seq: list[str] = []
        for _, tokens in runs:
            if seq and seq[-1] == RAIL and tokens[:1] == [RAIL]:
                tokens = tokens[1:]       # the rail the stack below holds up
            seq += tokens
        towers.append(seq)
    ranked = sorted(range(len(towers)), key=lambda i: (-len(towers[i]), towers[i]))
    index_of = {order[i]: n for n, i in enumerate(ranked)}
    towers = [towers[i] for i in ranked]
    # rails lying the same way (parallel) share an axis; 0/1 only says
    # which rails are parallel and which cross at a right angle
    yaws = [r.yaw_deg % 180 for r in layout.rails]
    axis0 = yaws[0] if yaws else 0
    def axis(y):
        d = (y - axis0) % 180
        return 0 if min(d, 180 - d) < 1 else 1 if abs(d - 90) < 1 else None
    rails = sorted(({"type": r.rail_type, "towers": sorted(index_of[sp] for sp in rail_spots[r.id] if sp in index_of),
                     "axis": axis(y)}
                    for r, y in zip(layout.rails, yaws)), key=lambda x: (x["type"], x["towers"]))
    top = max((r.z_units for r in layout.rails), default=0)
    out = {"parts": {k: v for k, v in sorted(usage.items()) if v}, "towers": towers, "base": base,
           "top_level": int(top), "rails": rails}
    if source is not None:
        tower_of = {}
        for s in layout.supports:
            stack = [parts[p] for p in s.stack_part_ids if p in parts]
            if stack:
                for p in stack:
                    tower_of[p.id] = index_of[_key(stack[0].x_cm, stack[0].y_cm)]
        out["route"] = route_edges(layout, catalog, source, tower_of)
    return out


def route_edges(layout: Layout, catalog: PartCatalog, source, tower_of: Mapping[str, int]) -> list[list[int]]:
    """What a person sees the marble do: from which tower it rolls over to
    which tower ([a, b]), and from which tower it leaves the run ([a, -1])."""
    from .connectivity import build_routing_graph
    edges = build_routing_graph(layout, catalog).edges
    found: set[tuple[int, int]] = set()
    start = source.key
    seen = {(start, None)}
    stack = [(start, tower_of.get(start.split(":", 1)[0]))]
    while stack:
        node, last = stack.pop()
        here = tower_of.get(node.split(":", 1)[0])
        if here is not None:
            if last is not None and here != last:
                found.add((last, here))
            last = here
        nxt = edges.get(node, ())
        if not nxt and last is not None:
            found.add((last, -1))
        for n in nxt:
            if (n, last) not in seen:
                seen.add((n, last))
                stack.append((n, last))
    return sorted([a, b] for a, b in found)


def _edit(a: Sequence[str], b: Sequence[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def hint_distance(target: Mapping[str, Any], cand: Mapping[str, Any]) -> float:
    """Parts: total count difference. Towers: each target tower matched to a
    distinct candidate tower (greedy, longest first) by edit distance; an
    unmatched tower costs its length."""
    keys = set(target["parts"]) | set(cand["parts"])
    d = sum(abs(target["parts"].get(k, 0) - cand["parts"].get(k, 0)) for k in keys)
    pool = [list(t) for t in cand["towers"]]
    for t in target["towers"]:
        if not pool:
            d += len(t)
            continue
        costs = [_edit(t, c) for c in pool]
        i = min(range(len(pool)), key=costs.__getitem__)
        d += costs[i]
        pool.pop(i)
    d += sum(len(c) for c in pool)
    return float(d)


def _points(layout: Layout, catalog: PartCatalog) -> list[tuple[str, float, float, float]]:
    """Every part's place and every rail hole's place (a rail laid the other
    way round is the same rail)."""
    from .model import rail_hole_world
    pts = [(p.part_type, p.x_cm, p.y_cm, p.z_units) for p in layout.parts]
    for r in layout.rails:
        for k in range(len(catalog.rails[r.rail_type].holes_cm)):
            x, y, z = rail_hole_world(r, catalog, k)
            pts.append(("hole:" + r.rail_type, x, y, z))
    return pts


def _canon(pts, quarter: int, mirror: bool) -> tuple:
    c, s = round(cos(radians(90 * quarter))), round(sin(radians(90 * quarter)))
    out = [(k, c * x - s * (-y if mirror else y), s * x + c * (-y if mirror else y), z) for k, x, y, z in pts]
    mx, my = min(o[1] for o in out), min(o[2] for o in out)
    return tuple(sorted((k, round(x - mx), round(y - my), round(z)) for k, x, y, z in out))


def same_structure(a: Layout, b: Layout, catalog: PartCatalog) -> bool:
    """The same parts and rail holes at the same places, up to a quarter
    turn, a mirror and a shift (to the centimetre)."""
    pa, pb = _points(a, catalog), _points(b, catalog)
    if len(pa) != len(pb):
        return False
    target = _canon(pa, 0, False)
    return any(_canon(pb, q, m) == target for q in range(4) for m in (False, True))


# ---- solving -----------------------------------------------------------------

def config_for(hints: Mapping[str, Any], **extra):
    """Generator settings for the base hint and the height of the towers."""
    from .generator import GeneratorConfig
    base = hints.get("base", "grid")
    height = int(hints.get("top_level", 30)) + 6
    rails = sum(v for k, v in hints["parts"].items() if k.startswith(("straight", "curved", "s_curve", "spiral")))
    common = dict(max_height_units=height, max_rails=max(2, rails), exclude_parts=(), **extra)
    if base == "triangle":
        return GeneratorConfig(strategy="bottom_up", **common)
    if base in ("ladder", "box"):
        return GeneratorConfig(strategy="bottom_up", up_base=base, **common)
    return GeneratorConfig(bases={"free": 1.0}, triangle_probability=0.0, **common)


@dataclass
class Solution:
    candidate: Any
    distance: float
    tape: list[float] = field(default_factory=list)


def _grow(catalog, budget, config, tape, fresh, name):
    from .anneal import TapeRandom
    from .generator import CascadeGenerator, candidate_from_state
    rng = TapeRandom(tape, fresh)
    gen = CascadeGenerator(catalog, budget, config, rng)
    state = gen.build_up_once() if config.strategy == "bottom_up" else gen.build_once()
    if state is None or len(state.rails) < 2:
        return None, rng.used()
    cand = candidate_from_state(gen, state, config, catalog, budget, rng, name)
    return cand, rng.used()


def solve(hints: Mapping[str, Any], catalog: PartCatalog, *, seed: int = 1, starts: int = 300,
          anneal_steps: int = 200, keep: int = 3, base_override=None) -> list[Solution]:
    from .anneal import mutate
    from .generator import Budget
    config = base_override or config_for(hints)
    budget = Budget(Counter(hints["parts"]))
    rng, fresh = random.Random(seed), random.Random(seed * 7919 + 1)
    pool: list[Solution] = []
    for i in range(starts):
        cand, tape = _grow(catalog, budget, config, [], fresh, f"hint-{i}")
        if cand is None:
            continue
        d = hint_distance(hints, extract_hints(cand.layout, catalog, hints.get("base", "grid")))
        pool.append(Solution(cand, d, tape))
        if d == 0:
            break
    pool.sort(key=lambda s: s.distance)
    best = pool[:keep]
    out = []
    for start in best:
        current = best_here = start
        for step in range(anneal_steps):
            if best_here.distance == 0:
                break
            t = 4.0 * (0.1 / 4.0) ** (step / max(1, anneal_steps - 1))
            cand, tape = _grow(catalog, budget, config, mutate(current.tape, rng), fresh, f"hint-a{step}")
            if cand is None:
                continue
            d = hint_distance(hints, extract_hints(cand.layout, catalog, hints.get("base", "grid")))
            if d <= current.distance or rng.random() < math.exp((current.distance - d) / t):
                current = Solution(cand, d, tape)
                if d < best_here.distance:
                    best_here = current
        out.append(best_here)
    out.sort(key=lambda s: s.distance)
    return out
