"""Cascade layout generator (milestone M2).

The generator grows a descending cascade from a top rail. A marble rolls
along each rail to a block-connected *stop hole* and drops into a routing
block (a *drop block*) whose side outlets send it to the next rail. Two drop
modes exist:

* **ground drop**: the drop block tops a column on the ground; each side
  outlet feeds a new rail starting at the block face, at the outlet floor or
  one unit lower.
* **landing drop**: the drop block stands on a new rail beneath it and lands
  the marble on that rail, past the block face (see docs/layout.md). Long
  rails have a center hole, so a rail can drop at its center and leave its
  other half free as a platform for columns from above.

Columns are abstract while building: a base (ground or a rail hole), the
rail hole they hold up, and the routing parts at their top. When a new lower
rail passes exactly through an existing column at one of its holes, the
column is *split* into a part under that rail and a part standing on it, so
upper columns end up standing on lower rails. Filler parts (4u blocks, 1u
purple drop blocks, foundations on the ground) are composed at the end.

Every step is checked against the set inventory, the footprint, solid
collisions and marble clearance; every rail keeps exactly two supports with
an accepted hole pair. Finished candidates must pass the full validation
(assembly, stability, statics, connectivity, clearance) before scoring.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field, replace
from math import pi, radians
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .catalog import PartCatalog
from .collision import Solid, penetration_cm, rail_solids
from .geometry import valid_support_pairs
from .inventory import load_inventory
from .model import Layout, PlacedPart, PlacedRail, PortRef, RouteLink, SupportLink
from .substitution import CURVE_FOR_STRAIGHT, eligible_rails, substitute
from .validation import validate_layout

_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
# Rotation that points a block's side port toward world direction index d:
# rotation = 90 * d + offset.
_PORT_ROTATION_OFFSET = {"right": 0, "front": -90, "rear": 90, "left": 180}
_FILLER_PREFERENCE = (
    "natural_drop", "orange_vertical", "cyan", "green", "blue", "yellow",
    "red_right_angle", "red_random_split",
)
_RAIL_KINDS = ("straight_short", "straight_long", "straight_long_center")
# Inventory pool each rail kind draws from (presets do not list center holes
# separately); `straight_unspecified` is a wildcard for any straight rail.
_RAIL_POOL = {"straight_short": "straight_short", "straight_long": "straight_long",
              "straight_long_center": "straight_long", "spiral": "spiral"}
# The twist may be listed as one pool or by size; all are treated as one size.
_SPIRAL_POOLS = ("spiral", "spiral_large", "spiral_small")


def _spiral_capacity(counts: Mapping[str, int]) -> int:
    return sum(counts.get(k, 0) for k in _SPIRAL_POOLS)
# Holes a straight can be swapped to a curve on (substitution.py): building on
# them keeps rails curve-ready.
_CURVE_READY = {"straight_short": {0, 3}, "straight_long_center": {0, 2, 4}}
_UNIT_CM = 1.5
_MARBLE_DIAMETER_CM = 1.6
_TOL_CM = 0.05
_AXIS_TOL_CM = 0.01


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------

@dataclass
class Budget:
    counts: Counter

    @classmethod
    def from_sets(cls, set_paths: Iterable[str | Path]) -> "Budget":
        total: Counter = Counter()
        for path in set_paths:
            for part, count in load_inventory(path).counts.items():
                if isinstance(count, int):
                    total[part] += count
        return cls(total)

    def copy(self) -> "Budget":
        return Budget(Counter(self.counts))


def resolve_set_paths(repo_root: Path, set_ids: Sequence[str]) -> list[Path]:
    index = yaml.safe_load((repo_root / "catalog" / "sets" / "index.yaml").read_text())
    by_id = {}
    for group in index.get("presets", {}).values():
        for entry in group:
            by_id[str(entry["id"]).upper()] = repo_root / "catalog" / "sets" / entry["file"]
    missing = [s for s in set_ids if s.upper() not in by_id]
    if missing:
        raise ValueError(f"unknown set id(s): {', '.join(missing)}; known: {', '.join(sorted(by_id))}")
    return [by_id[s.upper()] for s in set_ids]


# --------------------------------------------------------------------------
# Construction state
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GeneratorConfig:
    max_height_units: int = 24
    footprint_cm: tuple[float, float] = (90.0, 90.0)
    split_probability: float = 0.45
    pass_through_probability: float = 0.35
    landing_probability: float = 0.6
    max_rails: int = 12
    curve_ready_bias: float = 0.5  # chance to try curve-ready holes first
    twist_probability: float = 0.5  # chance to try a twist first for a landing drop


@dataclass(frozen=True)
class Column:
    id: str
    x: float
    y: float
    base_rail: str | None      # None = ground
    base_hole: int | None
    base_z: int                # level of the surface the column stands on
    top_rail: str
    top_hole: int
    top_z: int                 # level of the rail bottom it holds up
    top_types: tuple[str, ...] = ()   # bottom -> top, e.g. (drop block, pass parts)
    block_rotation: int = 0           # rotation of top_types[0]

    def filler_units(self, heights: Mapping[str, int]) -> int:
        foundation = 1 if self.base_rail is None else 0
        return self.top_z - self.base_z - foundation - sum(heights[t] for t in self.top_types)

    def solid(self, half: float) -> Solid:
        return Solid(self.id, (self.x, self.y), (half, half), 0.0,
                     self.base_z * _UNIT_CM, self.top_z * _UNIT_CM)


@dataclass(frozen=True)
class _Outlet:
    block_column: str
    block_id: str
    port: str
    x_cm: float
    y_cm: float
    floor_z: int
    direction: int
    depth: int


@dataclass
class _State:
    rails: dict[str, PlacedRail] = field(default_factory=dict)
    columns: dict[str, Column] = field(default_factory=dict)
    corridors: dict[str, Solid] = field(default_factory=dict)
    route_links: list[tuple[str, str, str]] = field(default_factory=list)  # (column id, port, rail id)
    leaves: list[str] = field(default_factory=list)
    dangling: list[tuple[str, str]] = field(default_factory=list)  # (column id, port)
    covers: int = 0
    max_depth: int = 0
    counters: dict[str, int] = field(default_factory=dict)

    def copy(self) -> "_State":
        return _State(dict(self.rails), dict(self.columns), dict(self.corridors),
                      list(self.route_links), list(self.leaves), list(self.dangling),
                      self.covers, self.max_depth, dict(self.counters))

    def new_id(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0)
        self.counters[prefix] = n + 1
        return f"{prefix}{n}"


class CascadeGenerator:
    def __init__(self, catalog: PartCatalog, budget: Budget, config: GeneratorConfig,
                 rng: random.Random):
        self.catalog = catalog
        self.budget = budget
        self.config = config
        self.rng = rng
        footprint = catalog.raw.get("geometry_cm", {}).get("standard_block_footprint", {})
        self.half = float(footprint.get("width_cm", 4.5)) / 2.0
        self.heights = {
            name: int(spec["height"])
            for group in ("routing_blocks", "structural_parts")
            for name, spec in (catalog.raw.get(group) or {}).items()
            if isinstance(spec, Mapping) and spec.get("height") is not None
        }
        self.drop_blocks = self._drop_block_outlets()
        self.work = 0  # rail placements left in the current build
        self.filler_blocks = [t for t in _FILLER_PREFERENCE if self.heights.get(t) == 4]
        self.support_pairs = {
            kind: {tuple(sorted((spec.holes_cm.index(p.hole_a_cm), spec.holes_cm.index(p.hole_b_cm))))
                   for p in valid_support_pairs(spec)}
            for kind, spec in catalog.rails.items()
        }

    # ---- catalog facts ---------------------------------------------------
    def _drop_block_outlets(self) -> dict[str, tuple[str, ...]]:
        out = {}
        for name, spec in (self.catalog.raw.get("routing_blocks") or {}).items():
            if spec.get("height") != 4:
                continue
            for route in spec.get("routes") or ():
                if route.get("from") != "top":
                    continue
                targets = ([route["to"]] if route.get("to") else []) + list(route.get("to_any_of") or ())
                if targets and all(t in _PORT_ROTATION_OFFSET for t in targets):
                    out[name] = tuple(targets)
        return out

    @staticmethod
    def _port_direction(port: str, rotation: int) -> int:
        return ((rotation - _PORT_ROTATION_OFFSET[port]) // 90) % 4

    # ---- geometry ----------------------------------------------------------
    def _point(self, rail: PlacedRail, local_x: float) -> tuple[float, float]:
        dx, dy = _DIRS[int(round(rail.yaw_deg / 90)) % 4]
        return rail.x_cm + local_x * dx, rail.y_cm + local_x * dy

    def _corridor(self, rail: PlacedRail, start: float, end: float) -> Solid:
        a, b = self._point(rail, start), self._point(rail, end)
        top = (rail.z_units + 1) * _UNIT_CM
        return Solid(f"{rail.id}#marble", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
                     ((end - start) / 2.0, _MARBLE_DIAMETER_CM / 2.0), radians(rail.yaw_deg),
                     top, top + _MARBLE_DIAMETER_CM)

    def _in_footprint(self, solid: Solid) -> bool:
        hw, hd = self.config.footprint_cm[0] / 2.0, self.config.footprint_cm[1] / 2.0
        hx, hy = solid.half_extents_xy
        if round(solid.angle_rad / (pi / 2)) % 2:
            hx, hy = hy, hx
        return abs(solid.center_xy[0]) + hx <= hw + 1e-9 and abs(solid.center_xy[1]) + hy <= hd + 1e-9

    def _solids(self, state: _State) -> list[Solid]:
        solids = [piece for r in state.rails.values() for piece in rail_solids(r, self.catalog)]
        solids += [c.solid(self.half) for c in state.columns.values()]
        return solids

    def _hits(self, state: _State, candidates: Sequence[Solid], ignore: set[str] = frozenset()) -> list[str]:
        """Ids of existing solids/corridors that a candidate penetrates."""
        hits = []
        existing = self._solids(state) + list(state.corridors.values())
        for cand in candidates:
            for other in existing:
                if other.id in ignore or other.id == cand.id:
                    continue
                if cand.id.endswith("#marble") and other.id.endswith("#marble"):
                    continue
                if penetration_cm(cand, other) > _TOL_CM:
                    hits.append(other.id)
        return hits

    # ---- inventory --------------------------------------------------------
    def _feasible(self, state: _State) -> bool:
        counts = self.budget.counts
        used: Counter = Counter()
        for rail in state.rails.values():
            used[_RAIL_POOL[rail.rail_type]] += 1
        if used["spiral"] > _spiral_capacity(counts):
            return False
        wildcard_needed = sum(max(0, used[p] - counts[p]) for p in ("straight_short", "straight_long"))
        if wildcard_needed > counts["straight_unspecified"]:
            return False
        if state.covers > counts["cover"]:
            return False
        top_used: Counter = Counter(t for c in state.columns.values() for t in c.top_types)
        ground = sum(1 for c in state.columns.values() if c.base_rail is None)
        if ground > counts["wooden_foundation"]:
            return False
        for part, n in top_used.items():
            if n > counts[part]:
                return False
        fill = [c.filler_units(self.heights) for c in state.columns.values()]
        if any(f < 0 for f in fill):
            return False
        blocks_free = sum(max(0, counts[t] - top_used[t]) for t in self.filler_blocks)
        purples_free = counts["purple_drop"] - top_used["purple_drop"]
        blocks_used = min(sum(f // 4 for f in fill), blocks_free)
        return sum(fill) - 4 * blocks_used <= purples_free

    # ---- supports -----------------------------------------------------------
    def _supports_of(self, state: _State, rail_id: str) -> list[Column]:
        return [c for c in state.columns.values() if c.top_rail == rail_id]

    def _valid_pair(self, kind: str, holes: Sequence[int]) -> bool:
        return len(holes) == 2 and tuple(sorted(holes)) in self.support_pairs[kind]

    def _level(self, rail: PlacedRail, hole: int) -> int:
        """Mount level of a rail hole (the twist's chute hole sits 3 higher)."""
        return int(rail.z_units) + self.catalog.rails[rail.rail_type].hole_level(hole)

    def _plain_column(self, state: _State, rail: PlacedRail, hole: int) -> Column:
        x, y = self._point(rail, self.catalog.rails[rail.rail_type].holes_cm[hole])
        return Column(state.new_id("c"), x, y, None, None, 0, rail.id, hole, self._level(rail, hole))

    def _split_crossed_columns(self, state: _State, rail: PlacedRail,
                               corridor: Solid | None) -> list[int] | None:
        """Split every column the new rail passes through at one of its holes.

        Returns the rail holes now supported by the lower halves, or None if
        the rail hits anything that cannot be split.
        """
        spec = self.catalog.rails[rail.rail_type]
        body = rail_solids(rail, self.catalog)
        hits = set(self._hits(state, body + ([corridor] if corridor else [])))
        split_holes = []
        for hit in sorted(hits):
            column = state.columns.get(hit)
            if column is None:
                return None
            hole = next((i for i, hx in enumerate(spec.holes_cm)
                         if abs(self._point(rail, hx)[0] - column.x) < _AXIS_TOL_CM
                         and abs(self._point(rail, hx)[1] - column.y) < _AXIS_TOL_CM), None)
            if hole is None:
                return None
            level = self._level(rail, hole)
            lower = replace(column, id=state.new_id("c"), top_rail=rail.id, top_hole=hole,
                            top_z=level, top_types=(), block_rotation=0)
            upper = replace(column, base_rail=rail.id, base_hole=hole, base_z=level + 1)
            if lower.filler_units(self.heights) < (0 if lower.base_rail is None else 1):
                return None
            if upper.top_z - upper.base_z < 1 or upper.filler_units(self.heights) < 0:
                return None
            del state.columns[column.id]
            state.columns[lower.id] = lower
            state.columns[upper.id] = upper
            split_holes.append(hole)
        return split_holes

    # ---- placing rails ---------------------------------------------------------
    def _place_rail(self, state: _State, kind: str, x: float, y: float, z: int, direction: int,
                    entry_x: float, stop: int | None, keep_free: Sequence[int] = ()) -> PlacedRail | None:
        """Add a rail whose marble enters at local entry_x and stops at `stop`
        (None: rolls off end B). Adds splits and plain supports so that the
        rail ends with exactly two supports (the drop column at `stop` is
        added later by the caller and counts as one)."""
        if self.work <= 0:
            return None
        self.work -= 1
        spec = self.catalog.rails[kind]
        holes = spec.holes_cm
        end_x = holes[stop] if stop is not None else spec.length_cm
        if end_x <= entry_x + 1e-6 or z < 1:
            return None
        covered = [i for i, hx in enumerate(holes) if entry_x < hx < end_x]
        states = {i: "covered" for i in covered}
        if stop is not None:
            states[stop] = "block_connected"
        rail = PlacedRail(state.new_id("rail"), kind, x, y, z, yaw_deg=90.0 * direction,
                          flow_direction="a_to_b", hole_states=states)
        body = rail_solids(rail, self.catalog)
        # The twist's marble path runs inside its own funnel: no corridor.
        corridor = None if spec.shape == "twist" else self._corridor(rail, entry_x, end_x)
        if not all(self._in_footprint(piece) for piece in body):
            return None
        split = self._split_crossed_columns(state, rail, corridor)
        if split is None or (stop is not None and stop in split):
            return None
        if any(h in keep_free for h in split):
            return None
        state.rails[rail.id] = rail
        if corridor is not None:
            state.corridors[rail.id] = corridor
        state.covers += len(covered)

        needed = 2 - len(split) - (1 if stop is not None else 0)
        fixed = list(split) + ([stop] if stop is not None else [])
        if needed < 0:
            return None
        if needed == 0:
            if not self._valid_pair(kind, fixed):
                return None
        else:
            options = [h for h in range(len(holes)) if h not in fixed]
            # Prefer a column right under a block standing on this rail (tower),
            # then holes that keep the rail curve-ready.
            self.rng.shuffle(options)
            ready = self._curve_ready(kind)
            options.sort(key=lambda h: (h not in keep_free, h not in ready))
            choices = ([(h,) for h in options] if needed == 1 else
                       [(a, b) for i, a in enumerate(options) for b in options[i + 1:]])
            chosen = next((c for c in choices if self._valid_pair(kind, fixed + list(c))), None)
            if chosen is None:
                return None
            new_columns = [self._plain_column(state, rail, h) for h in chosen]
            if self._hits(state, [c.solid(self.half) for c in new_columns]):
                return None
            for column in new_columns:
                state.columns[column.id] = column
        if corridor is not None and self._hits(state, [corridor], ignore={rail.id}):
            return None
        return rail if self._feasible(state) else None

    # ---- drop blocks --------------------------------------------------------
    def _drop_types(self, block: str) -> tuple[str, ...]:
        if self.rng.random() >= self.config.pass_through_probability:
            return (block,)
        return self.rng.choice(((block, "purple_drop"), (block, "purple_drop", "purple_drop"),
                                (block, "orange_vertical")))

    def _block_order(self) -> list[str]:
        p = self.config.split_probability
        keyed = []
        for name, outlets in self.drop_blocks.items():
            weight = p if len(outlets) > 1 else 1.0 - p
            if self.budget.counts[name] > 0:
                keyed.append((self.rng.random() ** (1.0 / max(weight, 1e-6)), name))
        return [name for _, name in sorted(keyed, reverse=True)]

    def _drop(self, state: _State, rail: PlacedRail, hole: int, incoming: int,
              depth: int) -> tuple[_State, list[_Outlet]] | None:
        """Place a drop block under the stop hole; returns new state + outlets."""
        hx, hy = self._point(rail, self.catalog.rails[rail.rail_type].holes_cm[hole])
        modes = ["landing", "ground"] if self.rng.random() < self.config.landing_probability \
            else ["ground", "landing"]
        for mode in modes:
            for block in self._block_order():
                outlets = self.drop_blocks[block]
                top_types = self._drop_types(block)
                block_z = self._level(rail, hole) - sum(self.heights[t] for t in top_types)
                for turn in self.rng.sample(range(4), 4):
                    first = (incoming + turn) % 4
                    rotation = (90 * first + _PORT_ROTATION_OFFSET[outlets[0]]) % 360
                    dirs = {port: self._port_direction(port, rotation) for port in outlets}
                    result = (self._landing_drop if mode == "landing" else self._ground_drop)(
                        state, rail, hole, hx, hy, block, top_types, block_z, rotation, dirs, depth)
                    if result is not None:
                        return result
        return None

    def _ground_drop(self, state, rail, hole, hx, hy, block, top_types, block_z, rotation, dirs, depth):
        if block_z < 1:
            return None
        if not all(self._room_for_rail(hx, hy, d) for d in dirs.values()):
            return None
        trial = state.copy()
        column = Column(trial.new_id("c"), hx, hy, None, None, 0, rail.id, hole,
                        self._level(rail, hole), top_types, rotation)
        if self._hits(trial, [column.solid(self.half)]):
            return None
        trial.columns[column.id] = column
        if not self._feasible(trial):
            return None
        outlets = [self._outlet(column, port, d, block_z, depth) for port, d in dirs.items()]
        return trial, outlets

    def _landing_drop(self, state, rail, hole, hx, hy, block, top_types, block_z, rotation, dirs, depth):
        """The drop block stands on a new rail and lands the marble on it."""
        ports = list(dirs)
        land_port = self.rng.choice(ports)
        d = dirs[land_port]
        # Other outlets must not face back against the landing rail's flow.
        if any(dirs[p] == (d + 2) % 4 for p in ports if p != land_port):
            return None
        kinds = self.rng.sample(_RAIL_KINDS, len(_RAIL_KINDS))
        twists_left = _spiral_capacity(self.budget.counts) - sum(
            1 for r in state.rails.values() if r.rail_type == "spiral")
        if "spiral" in self.catalog.rails and twists_left > 0:
            first = self.rng.random() < self.config.twist_probability
            kinds = ["spiral"] + kinds if first else kinds + ["spiral"]
        for kind in kinds:
            spec = self.catalog.rails[kind]
            twist = spec.shape == "twist"
            ready = self._curve_ready(kind)
            order = [0] if twist else self.rng.sample(range(len(spec.holes_cm)), len(spec.holes_cm))
            order.sort(key=lambda h: h not in ready)
            for k in order:
                # The block stands on hole k: the rail's placement level sits
                # below it by one unit plus that hole's mount level.
                rail_z = block_z - 1 - spec.hole_level(k)
                if rail_z < 1:
                    continue
                landing = spec.holes_cm[k] + self.half
                downstream = [i for i, hx_ in enumerate(spec.holes_cm) if hx_ > landing + 1.0]
                preferred = [i for i in downstream if i in ready] or downstream
                stops = ([self.rng.choice(preferred)] if downstream else []) + [None]
                if len(state.rails) >= self.config.max_rails:
                    stops = [None]
                if twist:  # the funnel always drops through its center hole
                    stops = [len(spec.holes_cm) - 1] if len(state.rails) < self.config.max_rails else []
                for stop in stops:
                    trial = state.copy()
                    sx = hx - spec.holes_cm[k] * _DIRS[d][0]
                    sy = hy - spec.holes_cm[k] * _DIRS[d][1]
                    lower = self._place_rail(trial, kind, sx, sy, rail_z, d, landing, stop,
                                             keep_free=(k,))
                    if lower is None:
                        continue
                    column = Column(trial.new_id("c"), hx, hy, lower.id, k, block_z, rail.id, hole,
                                    self._level(rail, hole), top_types, rotation)
                    if column.filler_units(self.heights) < 0 or self._hits(trial, [column.solid(self.half)]):
                        continue
                    trial.columns[column.id] = column
                    if not self._feasible(trial):
                        continue
                    outlets = []
                    for port, pd in dirs.items():
                        if port == land_port:
                            continue
                        if not self._room_for_rail(hx, hy, pd):
                            break
                        outlets.append(self._outlet(column, port, pd, block_z, depth))
                    else:
                        trial.max_depth = max(trial.max_depth, depth + 1)
                        if stop is None:
                            trial.leaves.append(f"{lower.id}:end_b")
                            return trial, outlets
                        sub = self._drop(trial, lower, stop, d, depth + 1)
                        if sub is not None:
                            next_state, more = sub
                            return next_state, outlets + more
        return None

    def _curve_ready(self, kind: str) -> set[int]:
        if self.rng.random() >= self.config.curve_ready_bias:
            return set()
        return _CURVE_READY.get(kind, set())

    def _outlet(self, column: Column, port: str, d: int, block_z: int, depth: int) -> _Outlet:
        return _Outlet(column.id, port, port, column.x + self.half * _DIRS[d][0],
                       column.y + self.half * _DIRS[d][1], block_z + 1, d, depth)

    def _room_for_rail(self, x: float, y: float, d: int) -> bool:
        reach = self.half + self.catalog.rails["straight_short"].length_cm
        fx, fy = x + _DIRS[d][0] * reach, y + _DIRS[d][1] * reach
        hw, hd = self.config.footprint_cm[0] / 2.0, self.config.footprint_cm[1] / 2.0
        return (abs(fx) + abs(_DIRS[d][1]) * self.half <= hw + 1e-9
                and abs(fy) + abs(_DIRS[d][0]) * self.half <= hd + 1e-9)

    # ---- growing ------------------------------------------------------------
    def _grow(self, state: _State, outlet: _Outlet) -> tuple[_State, list[_Outlet]]:
        """Attach a rail to a block outlet (exact level or drop-one)."""
        can_continue = len(state.rails) < self.config.max_rails
        options = [(z, kind) for z in (outlet.floor_z - 1, outlet.floor_z - 2) for kind in _RAIL_KINDS]
        self.rng.shuffle(options)
        for continuing in ((True, False) if can_continue else (False,)):
            for z, kind in options:
                spec = self.catalog.rails[kind]
                stops = [i for i in range(len(spec.holes_cm)) if spec.holes_cm[i] > 5.0] if continuing else [None]
                stop = self.rng.choice(stops)
                trial = state.copy()
                rail = self._place_rail(trial, kind, outlet.x_cm, outlet.y_cm, z, outlet.direction, 0.0, stop)
                if rail is None:
                    continue
                trial.route_links.append((outlet.block_column, outlet.port, rail.id))
                trial.max_depth = max(trial.max_depth, outlet.depth + 1)
                if stop is None:
                    trial.leaves.append(f"{rail.id}:end_b")
                    return trial, []
                sub = self._drop(trial, rail, stop, outlet.direction, outlet.depth + 1)
                if sub is not None:
                    return sub
        state = state.copy()
        state.dangling.append((outlet.block_column, outlet.port))
        return state, []

    def build_once(self, work: int = 400) -> _State | None:
        self.work = work
        state = _State()
        direction = self.rng.randrange(4)
        kind = self.rng.choice(_RAIL_KINDS)
        spec = self.catalog.rails[kind]
        stop = self.rng.choice([i for i in range(len(spec.holes_cm)) if spec.holes_cm[i] > 15])
        sx = -spec.length_cm / 2 * _DIRS[direction][0]
        sy = -spec.length_cm / 2 * _DIRS[direction][1]
        top = self._place_rail(state, kind, sx, sy, self.config.max_height_units, direction, 0.0, stop)
        if top is None:
            return None
        state.max_depth = 1
        result = self._drop(state, top, stop, direction, 1)
        if result is None:
            return None
        state, queue = result
        while queue:
            outlet = queue.pop(self.rng.randrange(len(queue)))
            state, more = self._grow(state, outlet)
            queue.extend(more)
        return state

    # ---- materializing parts ---------------------------------------------
    def materialize(self, state: _State, name: str) -> tuple[Layout, dict[str, int], dict[str, str]]:
        counts = self.budget.counts
        top_used = Counter(t for c in state.columns.values() for t in c.top_types)
        free = Counter({t: max(0, counts[t] - top_used[t]) for t in self.filler_blocks})
        parts: list[PlacedPart] = []
        supports: list[SupportLink] = []
        block_ids: dict[str, str] = {}
        for column in sorted(state.columns.values(), key=lambda c: (c.base_z, c.id)):
            fill = column.filler_units(self.heights)
            sequence = ["wooden_foundation"] if column.base_rail is None else []
            for _ in range(fill // 4):
                filler = next((t for t in self.filler_blocks if free[t] > 0), None)
                if filler is None:
                    sequence += ["purple_drop"] * 4
                else:
                    free[filler] -= 1
                    sequence.append(filler)
            sequence += ["purple_drop"] * (fill % 4)
            first_top = len(sequence)
            sequence += list(column.top_types)
            z = column.base_z
            ids = []
            for k, part_type in enumerate(sequence):
                rotation = column.block_rotation if (k == first_top and column.top_types) else 0
                pid = f"{column.id}_{k}_{part_type}"
                parts.append(PlacedPart(pid, part_type, column.x, column.y, z, rotation))
                if k == first_top and column.top_types:
                    block_ids[column.id] = pid
                ids.append(pid)
                z += self.heights[part_type]
            supports.append(SupportLink(column.top_rail, column.top_hole, tuple(ids),
                                        column.base_rail, column.base_hole, name=column.id))
        links = tuple(RouteLink(PortRef(block_ids[col], port), PortRef(rail, "end_a"))
                      for col, port, rail in state.route_links)
        layout = Layout(name, rails=tuple(state.rails.values()), parts=tuple(parts),
                        supports=tuple(supports), route_links=links)
        usage = Counter(r.rail_type for r in layout.rails) + Counter(p.part_type for p in parts)
        usage["cover"] = state.covers
        return layout, dict(sorted(usage.items())), block_ids


# --------------------------------------------------------------------------
# Scoring, validation and output
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    layout: Layout
    score: float
    metrics: Mapping[str, Any]
    usage: Mapping[str, int]


def score(metrics: Mapping[str, Any]) -> float:
    """Levels and rolling length, then branches and exits (user priorities);
    small bonuses for columns standing on rails (stacked, compact builds) and
    for curved rails (variety)."""
    return (
        10.0 * metrics["levels"]
        + 0.1 * metrics["rolling_length_cm"]
        + 6.0 * metrics["rail_exits"]
        + 4.0 * metrics["random_branches"]
        + 2.0 * metrics["columns_on_rails"]
        + 3.0 * metrics.get("curved_rails", 0)
        + 5.0 * metrics.get("twists", 0)
        - 8.0 * metrics["open_block_outlets"]
    )


def layout_usage(layout: Layout) -> dict[str, int]:
    used = Counter(r.rail_type for r in layout.rails) + Counter(p.part_type for p in layout.parts)
    used["cover"] = sum(1 for r in layout.rails for s in r.hole_states.values() if s == "covered")
    return dict(sorted(used.items()))


def _within_budget(usage: Mapping[str, int], counts: Mapping[str, int]) -> bool:
    short = usage.get("straight_short", 0)
    long_ = usage.get("straight_long", 0) + usage.get("straight_long_center", 0)
    overflow = max(0, short - counts.get("straight_short", 0)) + max(0, long_ - counts.get("straight_long", 0))
    if overflow > counts.get("straight_unspecified", 0):
        return False
    if usage.get("spiral", 0) > _spiral_capacity(counts):
        return False
    return all(n <= counts.get(part, 0) for part, n in usage.items()
               if not part.startswith("straight_") and part != "spiral")


def add_curves(layout: Layout, catalog: PartCatalog, budget: Budget, rng: random.Random,
               source: PortRef, sinks: Sequence[PortRef]) -> Layout:
    """Swap eligible straights for curves while the layout stays valid."""
    if not any(budget.counts[c] > 0 for c, _ in CURVE_FOR_STRAIGHT.values()):
        return layout
    candidates = eligible_rails(layout)
    rng.shuffle(candidates)
    for rail_id in candidates:
        for turn in rng.sample(("left", "right"), 2):
            trial = substitute(layout, catalog, rail_id, turn)
            if not _within_budget(layout_usage(trial), budget.counts):
                break
            if validate_layout(trial, catalog, source=source, sinks=sinks).valid:
                layout = trial
                break
    return layout


def _metrics(state: _State, layout: Layout, catalog: PartCatalog) -> dict[str, Any]:
    rolling = sum(c.half_extents_xy[0] * 2 for c in state.corridors.values())
    splits = sum(1 for c in state.columns.values()
                 if len(c.top_types) and c.top_types[0] in ("red_random_split", "red_right_angle"))
    return {
        "levels": state.max_depth,
        "rails": len(state.rails),
        "rolling_length_cm": round(rolling, 1),
        "exits": len(state.leaves) + len(state.dangling),
        "rail_exits": len(state.leaves),
        "open_block_outlets": len(state.dangling),
        "random_branches": splits,
        "columns_on_rails": sum(1 for c in state.columns.values() if c.base_rail is not None),
        "covers": state.covers,
        "parts": len(layout.parts),
    }


def generate(
    catalog: PartCatalog,
    budget: Budget,
    *,
    config: GeneratorConfig = GeneratorConfig(),
    attempts: int = 500,
    seed: int = 0,
    keep: int = 3,
) -> list[Candidate]:
    rng = random.Random(seed)
    generator = CascadeGenerator(catalog, budget, config, rng)
    found: dict[tuple, Candidate] = {}
    for attempt in range(attempts):
        state = generator.build_once()
        if state is None or len(state.rails) < 2:
            continue
        layout, usage, block_ids = generator.materialize(state, f"generated-{seed}-{attempt}")
        sinks = tuple(PortRef(*leaf.split(":", 1)) for leaf in state.leaves)
        sinks += tuple(PortRef(block_ids[col], port) for col, port in state.dangling)
        if not sinks:
            continue
        result = validate_layout(layout, catalog, source=PortRef("rail0", "end_a"), sinks=sinks)
        if not result.valid or set(result.connectivity.reached_sinks) != {s.key for s in sinks}:
            continue
        layout = add_curves(layout, catalog, budget, rng, PortRef("rail0", "end_a"), sinks)
        usage = layout_usage(layout)
        metrics = _metrics(state, layout, catalog)
        metrics["curved_rails"] = sum(1 for r in layout.rails if catalog.rails[r.rail_type].shape == "arc")
        metrics["twists"] = sum(1 for r in layout.rails if catalog.rails[r.rail_type].shape == "twist")
        metrics["covers"] = usage.get("cover", 0)
        signature = (metrics["levels"], metrics["rails"], metrics["exits"], metrics["columns_on_rails"],
                     metrics["curved_rails"],
                     tuple(sorted(Counter(p.part_type for p in layout.parts).items())))
        candidate = Candidate(layout, score(metrics), metrics, usage)
        if signature not in found or found[signature].score < candidate.score:
            found[signature] = candidate
    return sorted(found.values(), key=lambda c: c.score, reverse=True)[:keep]


def _rail_dict(r: PlacedRail, num) -> dict[str, Any]:
    out = {"id": r.id, "rail_type": r.rail_type}
    if r.rail_type in ("straight_short", "straight_long", "straight_long_center"):
        out.update(x_cm=num(r.x_cm), y_cm=num(r.y_cm), yaw_deg=num(r.yaw_deg))
    else:  # curves: keep precision so holes stay on their columns
        out.update(x_cm=round(r.x_cm, 7), y_cm=round(r.y_cm, 7), yaw_deg=round(r.yaw_deg, 7), turn=r.turn)
    out.update(z_units=num(r.z_units), flow_direction=r.flow_direction,
               hole_states=dict(sorted(r.hole_states.items())))
    return out


def layout_to_dict(layout: Layout, source_rail: str = "rail0") -> dict[str, Any]:
    """Layout YAML structure (rails, parts, supports, links, routing query)."""

    def num(v: float) -> float | int:
        v = round(float(v), 4)
        return int(v) if v == int(v) else v

    def support(s: SupportLink) -> dict[str, Any]:
        out = {"name": s.name, "upper_rail_id": s.upper_rail_id, "upper_hole_index": s.upper_hole_index,
               "stack_part_ids": list(s.stack_part_ids)}
        if s.lower_rail_id is not None:
            out["lower_rail_id"] = s.lower_rail_id
            out["lower_hole_index"] = s.lower_hole_index
        return out

    return {
        "rails": [_rail_dict(r, num) for r in layout.rails],
        "parts": [
            {"id": p.id, "part_type": p.part_type, "x_cm": num(p.x_cm), "y_cm": num(p.y_cm),
             "z_units": num(p.z_units), **({"rotation_deg": p.rotation_deg} if p.rotation_deg else {})}
            for p in layout.parts
        ],
        "supports": [support(s) for s in layout.supports],
        "route_links": [
            {"source": {"component_id": l.source.component_id, "port": l.source.port},
             "target": {"component_id": l.target.component_id, "port": l.target.port}}
            for l in layout.route_links
        ],
        "routing_query": {"source": {"component_id": source_rail, "port": "end_a"}},
    }


def layout_to_yaml_dict(candidate: Candidate, *, name: str, description: str,
                        generator_info: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "name": name,
        "description": description,
        "generator": dict(generator_info),
        "metrics": dict(candidate.metrics),
        "inventory_used": dict(candidate.usage),
        **layout_to_dict(candidate.layout),
    }
