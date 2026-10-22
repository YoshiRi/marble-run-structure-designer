"""Cascade layout generator (milestone M2, first version).

The generator grows a *descending cascade* from a top rail:

    rail --(block-connected hole)--> drop column --(side outlet)--> rail ...

* Every rail lies axis-aligned (0/90/180/270 deg) and rests on exactly two
  ground columns: a plain column under hole 1 and, at the far end, either a
  *drop column* (routing block on top, optional vertical pass-through parts
  above it) or another plain column when the rail is a leaf that ends the run.
* A drop column's side outlets feed new rails that start at the block face,
  either exactly at the outlet floor or one unit lower (drop-one).
* Red splitters fork the cascade into two branches.
* Columns are a foundation plus 4u blocks / 1u purple drop blocks.

Each construction is randomized and checked incrementally against the
inventory budget, the footprint, solid collisions and marble clearance.
Finished candidates must also pass the full layout validation (assembly,
stability, statics, connectivity, marble clearance) before being scored.
"""
from __future__ import annotations

import random
from math import pi, radians
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .catalog import PartCatalog
from .collision import Solid, component_solids, penetration_cm
from .connectivity import validate_connectivity
from .inventory import load_inventory
from .model import Layout, PlacedPart, PlacedRail, PortRef, RouteLink, SupportLink
from .validation import validate_layout

# Plan-view unit vectors for direction index 0..3 (0, 90, 180, 270 degrees).
_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
# Rotation that points a block's side port toward world direction index d.
_PORT_ROTATION_OFFSET = {"right": 0, "front": -90, "rear": 90, "left": 180}
# Pass-through parts that may sit above a drop block (top -> bottom routes).
_PASS_THROUGH = ("purple_drop", "orange_vertical")
# Preferred filler blocks: those least useful as drop blocks go first.
_FILLER_PREFERENCE = (
    "natural_drop", "orange_vertical", "cyan", "green", "blue", "yellow",
    "red_right_angle", "red_random_split",
)
_RAIL_KINDS = ("straight_short", "straight_long")
_MARBLE_DIAMETER_CM = 1.6
_TOL_CM = 0.05


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------

@dataclass
class Budget:
    """Countable parts. `straight_unspecified` rails can stand in for either
    straight length; covers are consumed by every covered hole."""

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

    def take(self, part: str, n: int = 1) -> bool:
        if part in _RAIL_KINDS:
            exact = min(self.counts[part], n)
            wildcard = n - exact
            if self.counts["straight_unspecified"] < wildcard:
                return False
            self.counts[part] -= exact
            self.counts["straight_unspecified"] -= wildcard
            return True
        if self.counts[part] < n:
            return False
        self.counts[part] -= n
        return True


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
    max_rails: int = 12


@dataclass
class _Outlet:
    block_id: str
    port: str
    x_cm: float
    y_cm: float
    floor_z: int        # outlet floor level in units (block z + 1)
    direction: int      # world direction index of the outlet
    depth: int          # rails above this outlet on the path


@dataclass
class _Build:
    budget: Budget
    rails: list[PlacedRail] = field(default_factory=list)
    parts: list[PlacedPart] = field(default_factory=list)
    supports: list[SupportLink] = field(default_factory=list)
    route_links: list[RouteLink] = field(default_factory=list)
    solids: list[Solid] = field(default_factory=list)
    leaves: list[str] = field(default_factory=list)
    dangling: list[str] = field(default_factory=list)
    max_depth: int = 0
    covers: int = 0

    def snapshot(self) -> tuple:
        return (self.budget.copy(), len(self.rails), len(self.parts), len(self.supports),
                len(self.route_links), len(self.solids), len(self.leaves), self.covers)

    def restore(self, snap: tuple) -> None:
        budget, nr, np_, ns, nl, nso, nle, covers = snap
        self.budget = budget
        del self.rails[nr:], self.parts[np_:], self.supports[ns:]
        del self.route_links[nl:], self.solids[nso:], self.leaves[nle:]
        self.covers = covers


class CascadeGenerator:
    def __init__(self, catalog: PartCatalog, budget: Budget, config: GeneratorConfig,
                 rng: random.Random):
        self.catalog = catalog
        self.base_budget = budget
        self.config = config
        self.rng = rng
        geometry = catalog.raw.get("geometry_cm", {})
        footprint = geometry.get("standard_block_footprint", {})
        self.block_half = float(footprint.get("width_cm", 4.5)) / 2.0
        self.drop_outlets = self._drop_block_outlets()

    # ---- catalog-derived routing facts ---------------------------------
    def _drop_block_outlets(self) -> dict[str, tuple[tuple[str, ...], bool]]:
        """Block types whose top opening routes to side ports."""
        out = {}
        for name, spec in (self.catalog.raw.get("routing_blocks") or {}).items():
            if spec.get("height") != 4:
                continue
            for route in spec.get("routes") or ():
                if route.get("from") != "top":
                    continue
                targets = ([route["to"]] if route.get("to") else []) + list(route.get("to_any_of") or ())
                sides = tuple(t for t in targets if t in _PORT_ROTATION_OFFSET)
                if sides and len(sides) == len(targets):
                    out[name] = (sides, route.get("selection") == "random")
        return out

    # ---- geometry helpers -----------------------------------------------
    def _rail_point(self, rail: PlacedRail, local_x: float) -> tuple[float, float]:
        dx, dy = _DIRS[int(rail.yaw_deg) // 90 % 4]
        return rail.x_cm + local_x * dx, rail.y_cm + local_x * dy

    def _within_footprint(self, solid: Solid) -> bool:
        half_w, half_d = self.config.footprint_cm[0] / 2.0, self.config.footprint_cm[1] / 2.0
        hx, hy = solid.half_extents_xy
        # Axis-aligned solids only (0/90/180/270 deg).
        quarter = round(solid.angle_rad / (pi / 2)) % 2
        ex, ey = (hy, hx) if quarter else (hx, hy)
        cx, cy = solid.center_xy
        return abs(cx) + ex <= half_w + 1e-9 and abs(cy) + ey <= half_d + 1e-9

    def _accept(self, build: _Build, new: Sequence[Solid], corridors: Sequence[Solid] = ()) -> bool:
        """Add solids if they stay in the footprint and hit nothing."""
        everything = list(new) + list(corridors)
        for solid in new:
            if not self._within_footprint(solid):
                return False
        for candidate in everything:
            for existing in build.solids:
                if candidate.id.endswith("#marble") and existing.id.endswith("#marble"):
                    continue
                if penetration_cm(candidate, existing) > _TOL_CM:
                    return False
        for corridor in corridors:
            for solid in new:
                if solid.id == corridor.id.split("#")[0]:
                    continue
                if penetration_cm(corridor, solid) > _TOL_CM:
                    return False
        build.solids.extend(everything)
        return True

    def _part_solids(self, parts: Sequence[PlacedPart]) -> list[Solid]:
        return component_solids(Layout("tmp", parts=tuple(parts)), self.catalog)

    def _rail_solid(self, rail: PlacedRail) -> Solid:
        return component_solids(Layout("tmp", rails=(rail,)), self.catalog)[0]

    def _corridor(self, rail: PlacedRail, start: float, end: float) -> Solid:
        unit = 1.5
        a = self._rail_point(rail, start)
        b = self._rail_point(rail, end)
        top = (rail.z_units + 1) * unit
        return Solid(
            f"{rail.id}#marble", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
            ((end - start) / 2.0, _MARBLE_DIAMETER_CM / 2.0), radians(rail.yaw_deg),
            top, top + _MARBLE_DIAMETER_CM,
        )

    # ---- columns --------------------------------------------------------
    def _column(self, build: _Build, prefix: str, x: float, y: float, top_z: int,
                top_types: Sequence[str]) -> list[PlacedPart] | None:
        """Ground column whose top surface is at top_z (units).

        Bottom to top: foundation, fillers, then top_types in order.
        """
        heights = {t: int(self.catalog.height_units(t) or 0) for t in top_types}
        fill = top_z - 1 - sum(heights[t] for t in top_types)
        if fill < 0:
            return None
        budget = build.budget
        if not budget.take("wooden_foundation"):
            return None
        sequence = ["wooden_foundation"]
        blocks_needed, thin_needed = divmod(fill, 4)
        for _ in range(blocks_needed):
            filler = next((t for t in _FILLER_PREFERENCE if budget.counts[t] > 0), None)
            if filler is not None:
                budget.take(filler)
                sequence.append(filler)
            elif budget.take("purple_drop", 4):
                sequence.extend(["purple_drop"] * 4)
            else:
                return None
        if not budget.take("purple_drop", thin_needed):
            return None
        sequence.extend(["purple_drop"] * thin_needed)
        for t in top_types:
            if not budget.take(t):
                return None
            sequence.append(t)

        parts, z = [], 0
        for k, part_type in enumerate(sequence):
            parts.append(PlacedPart(f"{prefix}_{k}_{part_type}", part_type, x, y, z))
            z += int(self.catalog.height_units(part_type))
        return parts

    def _drop_top(self, block_type: str) -> list[str]:
        """Drop block plus an optional pass-through stack above it."""
        types = [block_type]
        if self.rng.random() < self.config.pass_through_probability:
            choice = self.rng.choice(("purple_drop", "purple_drop2", "orange_vertical"))
            types += ["purple_drop", "purple_drop"] if choice == "purple_drop2" else [choice]
        return types

    # ---- rails ----------------------------------------------------------
    def _place_rail(self, build: _Build, rail_id: str, kind: str, x: float, y: float,
                    z: int, direction: int, stop_hole: int | None) -> PlacedRail | None:
        """Rail plus hole-1 plain column; stop_hole=None means a leaf rail."""
        spec = self.catalog.rails[kind]
        holes = len(spec.holes_cm)
        far_hole = stop_hole if stop_hole is not None else holes - 1
        covered = range(far_hole if stop_hole is not None else holes)
        if not build.budget.take(kind) or not build.budget.take("cover", len(covered)):
            return None
        states = {i: "covered" for i in covered}
        if stop_hole is not None:
            states[stop_hole] = "block_connected"
        rail = PlacedRail(rail_id, kind, x, y, z, yaw_deg=90.0 * direction,
                          flow_direction="a_to_b", hole_states=states)
        end = spec.holes_cm[stop_hole] if stop_hole is not None else spec.length_cm
        corridor = self._corridor(rail, 0.0, end)

        hx, hy = self._rail_point(rail, spec.holes_cm[1])
        near = self._column(build, f"{rail_id}_h1", hx, hy, z, [])
        if near is None:
            return None
        new_parts = list(near)
        if stop_hole is None:
            fx, fy = self._rail_point(rail, spec.holes_cm[far_hole])
            far = self._column(build, f"{rail_id}_h{far_hole}", fx, fy, z, [])
            if far is None:
                return None
            new_parts += far
        if not self._accept(build, [self._rail_solid(rail)] + self._part_solids(new_parts), [corridor]):
            return None
        build.rails.append(rail)
        build.parts.extend(new_parts)
        build.covers += len(covered)
        build.supports.append(SupportLink(rail_id, 1, tuple(p.id for p in near), name=f"{rail_id}_near"))
        if stop_hole is None:
            build.supports.append(SupportLink(rail_id, far_hole, tuple(p.id for p in far),
                                              name=f"{rail_id}_far"))
            build.leaves.append(f"{rail_id}:end_b")
        return rail

    def _place_drop_column(self, build: _Build, rail: PlacedRail, hole: int,
                           incoming: int, depth: int) -> list[_Outlet] | None:
        """Drop column under rail's hole; returns its outlets."""
        options = list(self.drop_outlets)
        weights = [self.config.split_probability if self.drop_outlets[t][1] else 1.0 - self.config.split_probability
                   for t in options]
        for block_type in self._weighted_order(options, weights):
            sides, _ = self.drop_outlets[block_type]
            if build.budget.counts[block_type] <= 0:
                continue
            top_types = self._drop_top(block_type)
            heights = sum(int(self.catalog.height_units(t)) for t in top_types)
            block_z = int(rail.z_units) - heights
            if block_z < 1:
                continue
            x, y = self._rail_point(rail, self.catalog.rails[rail.rail_type].holes_cm[hole])
            for turn in self.rng.sample(range(4), 4):
                # Point the first outlet port toward incoming + turn.
                first_dir = (incoming + turn) % 4
                rotation = (90 * first_dir + _PORT_ROTATION_OFFSET[sides[0]]) % 360
                # Lookahead: every outlet must have room for at least a short rail.
                if not all(self._short_rail_fits(x, y, self._port_direction(port, rotation))
                           for port in sides):
                    continue
                snap = build.snapshot()
                column = self._column(build, f"{rail.id}_h{hole}", x, y, int(rail.z_units), top_types)
                if column is None:
                    build.restore(snap)
                    continue
                block_index = len(column) - len(top_types)
                block = column[block_index]
                column[block_index] = PlacedPart(block.id, block.part_type, x, y, block.z_units, rotation)
                if not self._accept(build, self._part_solids(column)):
                    build.restore(snap)
                    continue
                build.parts.extend(column)
                build.supports.append(SupportLink(rail.id, hole, tuple(p.id for p in column),
                                                  name=f"{rail.id}_drop"))
                outlets = []
                for port in sides:
                    d = self._port_direction(port, rotation)
                    ox = x + self.block_half * _DIRS[d][0]
                    oy = y + self.block_half * _DIRS[d][1]
                    outlets.append(_Outlet(block.id, port, ox, oy, block_z + 1, d, depth))
                return outlets
        return None

    def _short_rail_fits(self, x: float, y: float, direction: int) -> bool:
        """Would a short rail leaving this block face stay in the footprint?"""
        dx, dy = _DIRS[direction]
        length = self.catalog.rails["straight_short"].length_cm
        half_w = self.config.footprint_cm[0] / 2.0
        half_d = self.config.footprint_cm[1] / 2.0
        reach = self.block_half + length
        rail_half_width = self.block_half  # rail width equals block width
        far_x, far_y = x + dx * reach, y + dy * reach
        return (abs(far_x) + abs(dy) * rail_half_width <= half_w + 1e-9
                and abs(far_y) + abs(dx) * rail_half_width <= half_d + 1e-9)

    @staticmethod
    def _port_direction(port: str, rotation: int) -> int:
        return ((rotation - _PORT_ROTATION_OFFSET[port]) // 90) % 4

    def _weighted_order(self, items: list[str], weights: list[float]) -> list[str]:
        keyed = [(self.rng.random() ** (1.0 / max(w, 1e-6)), item) for item, w in zip(items, weights)]
        return [item for _, item in sorted(keyed, reverse=True)]

    # ---- growing the cascade ---------------------------------------------
    def _grow(self, build: _Build, outlet: _Outlet, queue: list[_Outlet]) -> None:
        """Attach a rail to an outlet: continuing if possible, else a leaf."""
        rail_id = f"rail{len(build.rails)}"
        heights = [outlet.floor_z - 1, outlet.floor_z - 2]  # exact, drop-one
        attempts = []
        for z in heights:
            for kind in _RAIL_KINDS:
                attempts.append((z, kind))
        self.rng.shuffle(attempts)
        can_continue = len(build.rails) < self.config.max_rails
        for continuing in ((True, False) if can_continue else (False,)):
            for z, kind in attempts:
                if z < 1:
                    continue
                snap = build.snapshot()
                stop = self.rng.choice((2, 3)) if continuing else None
                rail = self._place_rail(build, rail_id, kind, outlet.x_cm, outlet.y_cm, z,
                                        outlet.direction, stop)
                if rail is None:
                    build.restore(snap)
                    continue
                build.route_links.append(RouteLink(PortRef(outlet.block_id, outlet.port),
                                                   PortRef(rail_id, "end_a")))
                if continuing:
                    outlets = self._place_drop_column(build, rail, stop, outlet.direction, outlet.depth + 1)
                    if outlets is None:
                        build.restore(snap)
                        continue
                    queue.extend(outlets)
                build.max_depth = max(build.max_depth, outlet.depth + 1)
                return
        build.dangling.append(f"{outlet.block_id}:{outlet.port}")

    def build_once(self) -> _Build | None:
        build = _Build(self.base_budget.copy())
        top_z = self.config.max_height_units
        direction = self.rng.randrange(4)
        kind = self.rng.choice(_RAIL_KINDS)
        stop = self.rng.choice((2, 3))
        length = self.catalog.rails[kind].length_cm
        # Start so that the top rail is roughly centered in the footprint.
        sx = -length / 2 * _DIRS[direction][0]
        sy = -length / 2 * _DIRS[direction][1]
        top = self._place_rail(build, "rail0", kind, sx, sy, top_z, direction, stop)
        if top is None:
            return None
        build.max_depth = 1
        queue = self._place_drop_column(build, top, stop, direction, 1)
        if queue is None:
            return None
        while queue:
            outlet = queue.pop(self.rng.randrange(len(queue)))
            self._grow(build, outlet, queue)
        return build


# --------------------------------------------------------------------------
# Scoring, validation and output
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    layout: Layout
    score: float
    metrics: Mapping[str, Any]
    usage: Mapping[str, int]


def _metrics(build: _Build, catalog: PartCatalog) -> dict[str, Any]:
    reached_cm = 0.0
    for rail in build.rails:
        spec = catalog.rails[rail.rail_type]
        stops = [i for i, s in rail.hole_states.items() if s == "block_connected"]
        reached_cm += spec.holes_cm[stops[0]] if stops else spec.length_cm
    splits = sum(1 for p in build.parts if p.part_type in ("red_random_split", "red_right_angle")
                 and any(link.source.component_id == p.id for link in build.route_links))
    return {
        "levels": build.max_depth,
        "rails": len(build.rails),
        "rolling_length_cm": round(reached_cm, 1),
        "exits": len(build.leaves) + len(build.dangling),
        "rail_exits": len(build.leaves),
        "open_block_outlets": len(build.dangling),
        "random_branches": splits,
        "covers": build.covers,
    }


def score(metrics: Mapping[str, Any]) -> float:
    """Levels and rolling length, plus branches and exits (user priorities)."""
    return (
        10.0 * metrics["levels"]
        + 0.1 * metrics["rolling_length_cm"]
        + 6.0 * metrics["rail_exits"]
        + 4.0 * metrics["random_branches"]
        - 8.0 * metrics["open_block_outlets"]
    )


def _usage(build: _Build) -> dict[str, int]:
    used = Counter(r.rail_type for r in build.rails) + Counter(p.part_type for p in build.parts)
    used["cover"] = build.covers
    return dict(sorted(used.items()))


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
        build = generator.build_once()
        if build is None or len(build.rails) < 2:
            continue
        layout = Layout(
            f"generated-{seed}-{attempt}",
            rails=tuple(build.rails), parts=tuple(build.parts),
            supports=tuple(build.supports), route_links=tuple(build.route_links),
        )
        sinks = tuple(PortRef(*s.split(":", 1)) for s in build.leaves + build.dangling)
        result = validate_layout(layout, catalog, source=PortRef("rail0", "end_a"), sinks=sinks)
        if not result.valid:
            continue
        metrics = _metrics(build, catalog)
        signature = (metrics["levels"], metrics["rails"], metrics["exits"],
                     tuple(sorted(Counter(p.part_type for p in build.parts).items())))
        candidate = Candidate(layout, score(metrics), metrics, _usage(build))
        if signature not in found or found[signature].score < candidate.score:
            found[signature] = candidate
    ranked = sorted(found.values(), key=lambda c: c.score, reverse=True)
    return ranked[:keep]


def layout_to_yaml_dict(candidate: Candidate, *, name: str, description: str,
                        generator_info: Mapping[str, Any]) -> dict[str, Any]:
    layout = candidate.layout

    def num(v: float) -> float | int:
        v = round(float(v), 4)
        return int(v) if v == int(v) else v

    return {
        "schema_version": "0.1",
        "name": name,
        "description": description,
        "generator": dict(generator_info),
        "metrics": dict(candidate.metrics),
        "inventory_used": dict(candidate.usage),
        "rails": [
            {"id": r.id, "rail_type": r.rail_type, "x_cm": num(r.x_cm), "y_cm": num(r.y_cm),
             "z_units": num(r.z_units), "yaw_deg": num(r.yaw_deg), "flow_direction": r.flow_direction,
             "hole_states": dict(sorted(r.hole_states.items()))}
            for r in layout.rails
        ],
        "parts": [
            {"id": p.id, "part_type": p.part_type, "x_cm": num(p.x_cm), "y_cm": num(p.y_cm),
             "z_units": num(p.z_units), **({"rotation_deg": p.rotation_deg} if p.rotation_deg else {})}
            for p in layout.parts
        ],
        "supports": [
            {"name": s.name, "upper_rail_id": s.upper_rail_id, "upper_hole_index": s.upper_hole_index,
             "stack_part_ids": list(s.stack_part_ids)}
            for s in layout.supports
        ],
        "route_links": [
            {"source": {"component_id": l.source.component_id, "port": l.source.port},
             "target": {"component_id": l.target.component_id, "port": l.target.port}}
            for l in layout.route_links
        ],
        "routing_query": {"source": {"component_id": "rail0", "port": "end_a"}},
    }
