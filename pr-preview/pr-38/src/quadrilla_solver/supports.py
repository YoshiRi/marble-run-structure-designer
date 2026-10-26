"""Support solver (design doc §6.3 / §4 "search"): place the columns that only
hold rails up, for all rails at once, after the marble's route is fixed.

In generated builds most parts (about three quarters) sit in columns the
marble never touches. The generator places them greedily, one rail at a time.
This module removes them and solves the supports as one combinatorial
problem:

* each rail needs exactly two supports on a valid hole pair (end + end, or
  end + center); the route's own columns (drop columns, blocks standing on
  rails) count and stay;
* a new column stands on the ground or on a lower rail whose hole lies right
  under it (a tower through several rails), never under a hole the marble
  falls through, and never in the marble's path or another part;
* cost: parts used, minus a bonus for reusing a spot that already has a
  column (towers and frames instead of scattered posts).

Depth-first search over rails bottom-up with branch-and-bound; the best few
solutions are validated in order and the first valid one is returned.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from itertools import combinations
from math import hypot
from typing import Iterable, Mapping, Sequence

from .catalog import PartCatalog
from .collision import Solid, component_solids, marble_corridor, penetration_cm, _rail_node_local_x
from .connectivity import build_routing_graph
from .geometry import valid_support_pairs
from .model import Layout, PlacedPart, PortRef, SupportLink, rail_hole_world
from .validation import validate_layout

_FILLERS = ("natural_drop", "orange_vertical", "cyan", "green", "blue", "yellow",
            "red_right_angle", "red_random_split")
_TOL = 0.05
_ALIGN_CM = 0.35


@dataclass(frozen=True)
class Column:
    rail_id: str          # the rail it holds up
    hole: int
    x: float
    y: float
    base_rail: str | None  # None: ground
    base_hole: int | None
    base_z: float          # level it starts at
    top_z: float           # level of the rail bottom it holds


def reachable_nodes(layout: Layout, catalog: PartCatalog, source: PortRef) -> set[str]:
    edges = build_routing_graph(layout, catalog).edges
    seen, stack = {source.key}, [source.key]
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def route_parts(layout: Layout, catalog: PartCatalog, source: PortRef) -> set[str]:
    return {n.split(":", 1)[0] for n in reachable_nodes(layout, catalog, source)}


def strip_supports(layout: Layout, catalog: PartCatalog, source: PortRef,
                   keep_braces: bool = True, fixed_rails: Iterable[str] = ()) -> Layout:
    """Remove the columns and counterweights the marble never touches. Rails
    the marble never touches (braces tying towers) stay with `keep_braces`
    (their supports are solved again), else they go too. Rails in
    `fixed_rails` (a placed pattern such as the triangle) keep their own
    supports as they are."""
    on_route = route_parts(layout, catalog, source)
    fixed = set(fixed_rails)
    rails = tuple(r for r in layout.rails if r.id in on_route or keep_braces or r.id in fixed)
    keep_rails = {r.id for r in rails}
    supports = []
    for s in layout.supports:
        if s.upper_rail_id in fixed:
            supports.append(s)
            continue
        if not any(p in on_route for p in s.stack_part_ids):
            continue
        if (s.upper_rail_id is not None and s.upper_rail_id not in keep_rails) or \
                (s.lower_rail_id is not None and s.lower_rail_id not in keep_rails):
            continue
        supports.append(s)
    kept_parts = {p for s in supports for p in s.stack_part_ids}
    parts = tuple(p for p in layout.parts if p.id in kept_parts)
    links = tuple(l for l in layout.route_links
                  if l.source.component_id in keep_rails | kept_parts
                  and l.target.component_id in keep_rails | kept_parts)
    return replace(layout, rails=rails, parts=parts, supports=tuple(supports), route_links=links)


class SupportSolver:
    def __init__(self, layout: Layout, catalog: PartCatalog, counts: Mapping[str, int],
                 source: PortRef, sinks: Sequence[PortRef], share_bonus: float = 2.0,
                 tower_bonus: float = 4.0,
                 max_nodes: int = 20000, keep: int = 12):
        self.layout, self.catalog, self.source, self.sinks = layout, catalog, source, tuple(sinks)
        self.unit = float(catalog.raw["geometry_cm"]["height_unit"]["value"])
        self.block = catalog.standard_block_units()
        self.half = 2.25
        self.share_bonus, self.max_nodes, self.keep = share_bonus, max_nodes, keep
        self.tower_bonus = tower_bonus
        # Holes with a stack standing on them: a support right under one
        # completes a tower (the score's shared_towers).
        self.stood_on = {(s.lower_rail_id, s.lower_hole_index) for s in layout.supports
                         if s.lower_rail_id is not None}
        used = Counter(r.rail_type for r in layout.rails) + Counter(p.part_type for p in layout.parts)
        self.free = Counter({k: max(0, v - used.get(k, 0)) for k, v in counts.items()})
        self.reached = reachable_nodes(layout, catalog, source)
        self.obstacles = self._obstacles()
        # Spots worth sharing: existing parts, and holes of every rail (a
        # column under one rail's hole that another rail also has above or
        # below can become a tower through both).
        self.spots = [(p.x_cm, p.y_cm) for p in layout.parts]
        self.hole_spots: dict[str, list[tuple[float, float]]] = {
            r.id: [rail_hole_world(r, catalog, i)[:2] for i in range(len(catalog.rails[r.rail_type].holes_cm))]
            for r in layout.rails}

    # ---- what a new column may not touch -----------------------------------
    def _obstacles(self) -> list[Solid]:
        solids = component_solids(self.layout, self.catalog)
        rails = self.layout.rail_map()
        xs: dict[str, list[float]] = {}
        r = 0.8
        for node in self.reached:
            rid, _, port = node.partition(":")
            rail = rails.get(rid)
            if rail is None:
                continue
            spec = self.catalog.rails[rail.rail_type]
            x = _rail_node_local_x(port, spec)
            if x is None:
                continue
            xs.setdefault(rid, []).append(x)
            # The marble falls through an open hole it reaches, or off an exit end.
            falls = port.startswith("hole:") and rail.hole_states.get(int(port[5:]), "open") == "open"
            falls |= port in ("end_a", "end_b") and not any(
                e for e in build_routing_graph(self.layout, self.catalog).edges.get(node, ()))
            if falls:
                hx, hy, hz = rail_hole_world(rail, self.catalog, int(port[5:])) if port.startswith("hole:") \
                    else (*self._end_xy(rail, spec, port), rail.z_units)
                solids.append(Solid(f"{node}#fall", (hx, hy), (r, r), 0.0, 0.0, hz * self.unit))
        for rid, values in xs.items():
            lo, hi = min(values), max(values)
            if hi - lo > 0 and self.catalog.rails[rails[rid].rail_type].shape != "twist":
                solids.extend(marble_corridor(rails[rid], self.catalog, lo, hi))
        return solids

    def _end_xy(self, rail, spec, port):
        from .model import rail_pose
        x, y, _ = rail_pose(rail, spec, 0.0 if port == "end_a" else spec.length_cm)
        return x, y

    # ---- options per rail ----------------------------------------------------
    def _kept_holes(self, rail_id: str) -> set[int]:
        return {s.upper_hole_index for s in self.layout.supports if s.upper_rail_id == rail_id}

    def _column_options(self, rail, hole: int) -> list[Column]:
        spec = self.catalog.rails[rail.rail_type]
        x, y, _ = rail_hole_world(rail, self.catalog, hole)
        top = rail.z_units + spec.hole_level(hole)
        bases: list[tuple[str | None, int | None, float]] = [(None, None, 0.0)]
        for lower in self.layout.rails:
            if lower.id == rail.id:
                continue
            lspec = self.catalog.rails[lower.rail_type]
            for k in range(len(lspec.holes_cm)):
                lx, ly, _ = rail_hole_world(lower, self.catalog, k)
                if hypot(lx - x, ly - y) > _ALIGN_CM:
                    continue
                base = lower.z_units + lspec.hole_level(k) + lspec.height_units
                if base > top - 1e-6:
                    continue
                node = f"{lower.id}:hole:{k}"
                state = lower.hole_states.get(k, "open")
                if state == "block_connected" or (state == "open" and node in self.reached):
                    continue  # the marble needs this hole
                if any(s.lower_rail_id == lower.id and s.lower_hole_index == k for s in self.layout.supports):
                    continue
                bases.append((lower.id, k, base))
        out = []
        for base_rail, base_hole, base in bases:
            height = top - base - (1 if base_rail is None else 0)
            if height < 0:
                continue
            column = Column(rail.id, hole, x, y, base_rail, base_hole, base, top)
            solid = self._solid(column)
            ignore = {rail.id} | ({base_rail} if base_rail else set())
            if any(o.id not in ignore and penetration_cm(solid, o) > _TOL for o in self.obstacles):
                continue
            out.append(column)
        return out

    def _solid(self, c: Column) -> Solid:
        return Solid(f"col:{c.rail_id}:{c.hole}", (c.x, c.y), (self.half, self.half), 0.0,
                     c.base_z * self.unit, c.top_z * self.unit)

    def _parts_of(self, c: Column) -> tuple[int, int, int]:
        """(foundations, blocks, purples)."""
        foundation = 1 if c.base_rail is None else 0
        height = int(round(c.top_z - c.base_z)) - foundation
        return foundation, height // self.block, height % self.block

    def _cost(self, c: Column) -> float:
        f, b, p = self._parts_of(c)
        shared = any(hypot(c.x - sx, c.y - sy) < _ALIGN_CM for sx, sy in self.spots) or any(
            hypot(c.x - sx, c.y - sy) < _ALIGN_CM
            for rid, spots in self.hole_spots.items() if rid != c.rail_id for sx, sy in spots)
        tower = self.tower_bonus if (c.rail_id, c.hole) in self.stood_on else 0.0
        return f + b + p - (self.share_bonus if shared or c.base_rail is not None else 0.0) - tower

    def _choices(self, rail) -> list[tuple[float, tuple[Column, ...]]]:
        spec = self.catalog.rails[rail.rail_type]
        kept = self._kept_holes(rail.id)
        need = 2 - len(kept)
        if need <= 0:
            return [(0.0, ())]
        pairs = {tuple(sorted((spec.holes_cm.index(p.hole_a_cm), spec.holes_cm.index(p.hole_b_cm))))
                 for p in valid_support_pairs(spec)}
        holes = [h for h in range(len(spec.holes_cm)) if h not in kept]
        out = []
        for combo in combinations(holes, need):
            if tuple(sorted(kept | set(combo))) not in pairs:
                continue
            options = [self._column_options(rail, h) for h in combo]
            if any(not o for o in options):
                continue
            def product(i):
                if i == len(options):
                    yield ()
                    return
                for c in options[i]:
                    for rest in product(i + 1):
                        yield (c, *rest)
            for cols in product(0):
                out.append((sum(self._cost(c) for c in cols), cols))
        return sorted(out, key=lambda t: t[0])

    # ---- search -------------------------------------------------------------
    def solve(self) -> list[tuple[float, tuple[Column, ...]]]:
        rails = sorted(self.layout.rails, key=lambda r: r.z_units)
        choices = [self._choices(r) for r in rails]
        if any(not c for c in choices):
            return []
        best: list[tuple[float, tuple[Column, ...]]] = []
        nodes = 0

        def ok(cols: Sequence[Column], new: Sequence[Column]) -> bool:
            for c in new:
                s = self._solid(c)
                for other in cols:
                    if other.base_rail == c.rail_id and hypot(other.x - c.x, other.y - c.y) < _ALIGN_CM:
                        continue  # a column standing on the rail this one holds: a tower
                    if c.base_rail == other.rail_id and hypot(other.x - c.x, other.y - c.y) < _ALIGN_CM:
                        continue
                    if penetration_cm(s, self._solid(other)) > _TOL:
                        return False
                if any(o.base_rail == c.base_rail and o.base_hole == c.base_hole and c.base_rail
                       for o in cols):
                    return False
            return True

        def inventory_ok(cols: Sequence[Column]) -> bool:
            f = sum(self._parts_of(c)[0] for c in cols)
            b = sum(self._parts_of(c)[1] for c in cols)
            p = sum(self._parts_of(c)[2] for c in cols)
            blocks = sum(self.free[t] for t in _FILLERS)
            purples = self.free["purple_drop"]
            spare = max(0, blocks - b)
            return f <= self.free["wooden_foundation"] and (b <= blocks or (b - blocks) * self.block <= purples) \
                and p + max(0, b - blocks) * self.block <= purples + 0 * spare

        def dfs(i: int, cols: tuple[Column, ...], cost: float) -> None:
            nonlocal nodes
            nodes += 1
            if nodes > self.max_nodes:
                return
            if len(best) >= self.keep and cost >= best[-1][0]:
                return
            if i == len(rails):
                best.append((cost, cols))
                best.sort(key=lambda t: t[0])
                del best[self.keep:]
                return
            for c_cost, new in choices[i]:
                if not ok(cols, new):
                    continue
                total = cols + new
                if not inventory_ok(total):
                    continue
                dfs(i + 1, total, cost + c_cost)

        dfs(0, (), 0.0)
        return best

    # ---- build ---------------------------------------------------------------
    def build(self, cols: Sequence[Column]) -> Layout:
        free = Counter(self.free)
        parts = list(self.layout.parts)
        supports = list(self.layout.supports)
        for n, c in enumerate(cols):
            f, b, p = self._parts_of(c)
            sequence = ["wooden_foundation"] * f
            for _ in range(b):
                filler = next((t for t in _FILLERS if free[t] > 0), None)
                if filler is None:
                    sequence += ["purple_drop"] * self.block
                else:
                    free[filler] -= 1
                    sequence.append(filler)
            sequence += ["purple_drop"] * p
            z = c.base_z
            ids = []
            for k, t in enumerate(sequence):
                pid = f"s{n}_{k}_{t}"
                # rounded like the YAML writer so a saved layout loads back equal
                parts.append(PlacedPart(pid, t, round(c.x, 4), round(c.y, 4), z, 0))
                ids.append(pid)
                z += self.catalog.height_units(t)
            supports.append(SupportLink(c.rail_id, c.hole, tuple(ids), c.base_rail, c.base_hole, name=f"s{n}"))
        return replace(self.layout, parts=tuple(parts), supports=tuple(supports))


def resolve_supports(layout: Layout, catalog: PartCatalog, counts: Mapping[str, int], source: PortRef,
                     sinks: Sequence[PortRef], weak_tower_weight: float = 15.0, keep_braces: bool = True,
                     min_support_g: float | None = None, fixed_rails: Iterable[str] = (),
                     **options) -> Layout | None:
    """Strip the supports of a valid build and solve them again; None if no
    valid solution was found."""
    from .generator import support_reactions_g, weak_towers

    stripped = strip_supports(layout, catalog, source, keep_braces=keep_braces, fixed_rails=fixed_rails)
    options.setdefault("keep", 40)
    solver = SupportSolver(stripped, catalog, counts, source, sinks, **options)
    best = None
    # Solutions come cheapest first and the rank only adds penalties, so stop
    # once the cost alone cannot beat the best; check the cheap things
    # (rank, overhang rule) before the full validation.
    for cost, cols in solver.solve():
        if best is not None and cost >= best[0]:
            break
        trial = solver.build(cols)
        # Weak towers weigh like the score does (15 points vs ~1 per part).
        rank = cost + weak_tower_weight * weak_towers(trial, catalog)
        if best is not None and rank >= best[0]:
            continue
        if min_support_g is not None:
            # The style rule on overhanging loads (review 3), as the generator applies it.
            reactions = support_reactions_g(trial, catalog, overhang_only=True)
            if reactions is None or any(g < min_support_g for g in reactions.values()):
                continue
        result = validate_layout(trial, catalog, source=source, sinks=sinks)
        if not (result.valid and set(result.connectivity.reached_sinks) == {s.key for s in sinks}):
            continue
        best = (rank, trial)
    return best[1] if best else None
