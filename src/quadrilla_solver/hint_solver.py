"""Solve a layout from hints by construction (see hints.py for the hints).

Stage A, geometry. Every tower is a list of parts bottom to top with "R"
where a rail lies across. Walking it gives the levels of its rail holes
(foundation 1, blocks 5, purple 1, rail 1); a tower that stands on a rail
knows them up to an offset. Rails are found by depth-first search: take an
uncovered rail hole of a placed tower, lay a rail of a remaining type there
(which of its holes, which of four headings), and let the rail's other holes
take towers: a placed tower standing there must have a rail hole at that
level, an unplaced tower may be put there. Done when every tower is placed,
every rail hole of every tower lies on a rail and the rail counts are used.

Stage B, the route. The input is the top of the highest free-standing stack.
A block sends the marble along the rail it stands on (which way is chosen);
the marble drops at the first uncovered hole ahead, into the block standing
below it, or falls out (an exit). Holes it must pass are covered. Choices
are searched so every route block is reached and the cover count matches;
the rail flows and hole states follow. The validators decide.

Grid headings only for now (bases grid, ladder, box).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from math import cos, hypot, radians, sin
from typing import Any, Iterator, Mapping, Sequence

from .catalog import PartCatalog
from .model import Layout, PlacedPart, PlacedRail, PortRef, SupportLink, rail_hole_world

RAIL = "R"
RAIL_TYPES = ("straight_long", "straight_long_center", "straight_short")
TOL = 0.4


@dataclass
class Tower:
    index: int
    tokens: list[str]
    on_rail: bool                 # stands on a rail (its first token is R)
    levels: list[int]             # rail hole levels, relative to its base
    top: int                      # height of its last part, relative
    ends: list[int] = field(default_factory=list)   # levels where a rail's end touches its side


def parse_towers(towers: Sequence[Sequence[str]], catalog: PartCatalog) -> list[Tower]:
    out = []
    for i, tokens in enumerate(towers):
        lv, levels, ends = 0, [], []
        for t in tokens:
            if t == RAIL:
                levels.append(lv)
                lv += 1
            else:
                if t[-1] in "<>":
                    ends.append(lv)
                lv += catalog.height_units(t.rstrip("<>"))
        out.append(Tower(i, list(tokens), bool(tokens) and tokens[0] == RAIL, levels, lv, ends))
    return out


@dataclass
class Rail:
    kind: str
    z: int
    holes: list[tuple[float, float]]
    yaw: float
    taken: dict[int, int] = field(default_factory=dict)   # hole -> tower
    end_tower: int | None = None                          # the tower at its end (side link)


@dataclass
class State:
    pos: dict[int, tuple[float, float]] = field(default_factory=dict)
    base: dict[int, int] = field(default_factory=dict)    # absolute level of each tower's level 0
    rails: list[Rail] = field(default_factory=list)
    left: Counter = field(default_factory=Counter)

    def copy(self) -> "State":
        return State(dict(self.pos), dict(self.base),
                     [Rail(r.kind, r.z, r.holes, r.yaw, dict(r.taken), r.end_tower) for r in self.rails],
                     Counter(self.left))


def _near(a, b) -> bool:
    return abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


class GeometrySolver:
    def __init__(self, towers: list[Tower], rail_counts: Mapping[str, int], catalog: PartCatalog,
                 max_nodes: int = 200000, rail_towers: Sequence[Mapping[str, Any]] | None = None):
        self.towers, self.catalog = towers, catalog
        # optional hint: for each rail, its type and the towers it lies on
        self.rail_towers = [(r["type"], frozenset(r["towers"])) for r in rail_towers] if rail_towers else None
        self.counts = Counter({k: v for k, v in rail_counts.items() if k in RAIL_TYPES})
        self.nodes, self.max_nodes = 0, max_nodes

    def _incidences(self, s: State) -> list[tuple[int, int, str]]:
        """Rail holes ("hole") and side links ("end") of placed towers
        (absolute level) not yet on a rail."""
        covered = {(t, r.z) for r in s.rails for t in r.taken.values()}
        ends = {(r.end_tower, r.z) for r in s.rails if r.end_tower is not None}
        out = []
        for t, base in s.base.items():
            for lv in self.towers[t].levels:
                if (t, base + lv) not in covered:
                    out.append((t, base + lv, "hole"))
            for lv in self.towers[t].ends:
                if (t, base + lv) not in ends:
                    out.append((t, base + lv, "end"))
        return sorted(out, key=lambda x: (x[2] != "end", x[1], x[0]))

    def _blocked(self, s: State, xy, z: int, tower_ok: int | None) -> bool:
        """A rail at level z through xy would cut a placed tower's stack."""
        for t, p in s.pos.items():
            if t == tower_ok or hypot(p[0] - xy[0], p[1] - xy[1]) > 4.5 - 1e-6:
                continue
            base, tw = s.base[t], self.towers[t]
            if base <= z < base + tw.top and (z - base) not in tw.levels:
                return True
        return False

    def _rail_clear(self, s: State, holes, z: int, kind: str) -> bool:
        a, b = holes[0], holes[-1]
        for r in s.rails:
            if r.z != z:
                continue
            # parallel or crossing rails on one level: reject any closeness
            for p in (r.holes[0], r.holes[-1], ((r.holes[0][0] + r.holes[-1][0]) / 2, (r.holes[0][1] + r.holes[-1][1]) / 2)):
                if _seg_dist(p, a, b) < 4.5:
                    return False
            for p in (a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
                if _seg_dist(p, r.holes[0], r.holes[-1]) < 4.5:
                    return False
        return True

    def solve(self) -> Iterator[State]:
        if not self.towers:
            return
        root = max((t for t in self.towers if not t.on_rail), key=lambda t: (t.top, len(t.levels)), default=None)
        if root is None:
            return
        s = State(pos={root.index: (0.0, 0.0)}, base={root.index: 0}, left=Counter(self.counts))
        yield from self._dfs(s, first=True)

    def _key(self, s: State):
        rails = frozenset((r.kind, r.z, tuple(sorted((round(x, 1), round(y, 1)) for x, y in r.holes))) for r in s.rails)
        towers = frozenset((t, round(p[0], 1), round(p[1], 1), s.base[t]) for t, p in s.pos.items())
        return rails, towers

    def _dfs(self, s: State, first: bool = False) -> Iterator[State]:
        self.nodes += 1
        if self.nodes > self.max_nodes:
            return
        key = self._key(s)
        seen = self.__dict__.setdefault("_seen", set())
        if key in seen:
            return
        seen.add(key)
        open_ = self._incidences(s)
        if not open_:
            if len(s.pos) == len(self.towers) and not +s.left:
                yield s
            return
        if not +s.left:
            return
        levels_needed = {z for _, z, w in open_ if w == "hole"}
        for tw in self.towers:
            if tw.index not in s.pos and not tw.on_rail:
                levels_needed |= set(tw.levels)
        if len(levels_needed) > sum(s.left.values()):
            return
        t, z, what = open_[0]
        here = s.pos[t]
        for kind in [k for k in RAIL_TYPES if s.left[k] > 0]:
            holes_cm = self.catalog.rails[kind].holes_cm
            if what == "end":
                # the rail's end touches the tower's side, the rail runs away from it
                for yaw in ((0.0,) if first else (0.0, 90.0, 180.0, 270.0)):
                    h = radians(yaw)
                    ex, ey = here[0] + 2.25 * cos(h), here[1] + 2.25 * sin(h)
                    holes = [(ex + x * cos(h), ey + x * sin(h)) for x in holes_cm]
                    if not self._rail_clear(s, holes, z, kind):
                        continue
                    yield from self._fill(s, kind, z, holes, yaw, -1, t, 0, {}, None, t)
                continue
            for k in range(len(holes_cm)):
                for yaw in ((0.0,) if first else (0.0, 90.0, 180.0, 270.0)):
                    h = radians(yaw)
                    holes = [(here[0] + (x - holes_cm[k]) * cos(h), here[1] + (x - holes_cm[k]) * sin(h))
                             for x in holes_cm]
                    if not self._rail_clear(s, holes, z, kind):
                        continue
                    yield from self._fill(s, kind, z, holes, yaw, k, t, 0, {k: t})

    def _fill(self, s: State, kind, z, holes, yaw, k0, t0, j, taken, bases=None, end_tower=None) -> Iterator[State]:
        """Decide hole j of the new rail: a placed tower there (forced), an
        unplaced tower, or nothing."""
        bases = bases or {}
        if j == len(holes):
            # a rail rests on at least two columns (a stack standing on it does not hold it)
            all_bases = {**s.base, **bases}
            held = sum(1 for t in taken.values() if not (self.towers[t].on_rail and z - all_bases[t] == 0))
            if held < 2:
                return
            if self.rail_towers is not None:
                mine = frozenset(taken.values()) | ({end_tower} if end_tower is not None else set())
                used = Counter((r.kind, frozenset(r.taken.values()) | ({r.end_tower} if r.end_tower is not None else set()))
                               for r in s.rails)
                want = Counter(self.rail_towers)
                if want[(kind, mine)] - used[(kind, mine)] <= 0:
                    return
            nxt = s.copy()
            nxt.rails.append(Rail(kind, z, holes, yaw, dict(taken), end_tower))
            nxt.left[kind] -= 1
            for hole, t in taken.items():
                if t not in nxt.pos:
                    nxt.pos[t] = holes[hole]
            nxt.base.update(bases)
            yield from self._dfs(nxt)
            return
        if j == k0:
            yield from self._fill(s, kind, z, holes, yaw, k0, t0, j + 1, taken, bases, end_tower)
            return
        xy = holes[j]
        at = [t for t, p in s.pos.items() if _near(p, xy)]
        if at:
            t = at[0]
            if (z - s.base[t]) in self.towers[t].levels:
                yield from self._fill(s, kind, z, holes, yaw, k0, t0, j + 1, {**taken, j: t}, bases, end_tower)
            elif not self._blocked(s, xy, z, end_tower):
                yield from self._fill(s, kind, z, holes, yaw, k0, t0, j + 1, taken, bases, end_tower)
            return
        if self._blocked(s, xy, z, end_tower):
            return
        placed_now = set(taken.values())
        for tw in self.towers:
            if tw.index in s.pos or tw.index in placed_now:
                continue
            cands = [z - lv for lv in tw.levels] if tw.on_rail else ([0] if z in tw.levels else [])
            for base in dict.fromkeys(cands):
                if base < 0:
                    continue
                yield from self._fill(s, kind, z, holes, yaw, k0, t0, j + 1, {**taken, j: tw.index},
                                      {**bases, tw.index: base}, end_tower)
        yield from self._fill(s, kind, z, holes, yaw, k0, t0, j + 1, taken, bases, end_tower)   # leave free



def _seg_dist(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))
