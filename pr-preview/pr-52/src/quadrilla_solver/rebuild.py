"""Rebuild one rail's window of a layout (design doc §9, user 2026-11-03).

The layout is cut at a route rail R into three parts:

    upper   rails above R. Kept as one rigid piece, moved (up, and sideways
            when the new route lands elsewhere) so its drop lands on the new
            window; its own internal columns move with it.
    window  R. Removed and grown again bottom-up (the generator's own step),
            one or more rails, under the user's intent: "rebuild" (another
            route), "add_rail" (one rail more) or "split" (a red splitter,
            its second branch merging hole to hole or leaving as an exit).
    lower   rails at R's level and below. Fixed, columns and all.

The window starts from the block R drops into (on a lower rail) and ends with
a block under the upper part's drop hole (or the input block when R was the
top rail). Every support not in the lower part is solved again by the
support solver, then the result is validated. Candidates come best first.

Refused (ValueError, with the reason): a rail the marble does not use, a
rail that drops in more than one place, and cuts where the upper part reaches
the lower part other than through R (another route link across the cut).
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import replace
from typing import Any, Mapping, Sequence

from .catalog import PartCatalog
from .connectivity import build_routing_graph
from .model import Layout, PlacedPart, PortRef, SupportLink, rail_hole_world
from .supports import SupportSolver, resolve_supports, route_parts
from .validation import validate_layout

INTENTS = ("rebuild", "add_rail", "split")


class RebuildRefused(ValueError):
    """Why a window cannot be rebuilt; `code` for the viewer's message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sets(layout: Layout, rail_id: str) -> tuple[set[str], set[str]]:
    rails = layout.rail_map()
    r = rails[rail_id]
    lower = {x.id for x in layout.rails if x.id != rail_id and x.z_units <= r.z_units}
    upper = {x.id for x in layout.rails if x.z_units > r.z_units}
    return lower, upper


def _owner(support: SupportLink) -> str | None:
    """The rail a column belongs to: the rail it holds up, else (a free-
    standing stack) the rail it stands on."""
    return support.upper_rail_id if support.upper_rail_id is not None else support.lower_rail_id


def plan_cut(layout: Layout, catalog: PartCatalog, source: PortRef, rail_id: str) -> dict[str, Any]:
    """Split the layout at `rail_id`; raises ValueError where it cannot."""
    rails = layout.rail_map()
    if rail_id not in rails:
        raise RebuildRefused("no_rail", f"no rail {rail_id}")
    on_route = route_parts(layout, catalog, source)
    if rail_id not in on_route:
        raise RebuildRefused("not_on_route", f"{rail_id}: the marble does not use this rail")
    lower, upper = _sets(layout, rail_id)
    parts = layout.part_map()

    out_links, in_links, free_inputs = [], [], []
    lower_supports, upper_supports = [], []
    for s in layout.supports:
        route = any(p in on_route for p in s.stack_part_ids)
        top, bottom = s.upper_rail_id, s.lower_rail_id
        if top == rail_id:
            if route and bottom in lower:
                out_links.append(s)
            continue                                  # R's plain columns: solved again
        if top is None:                               # free-standing stack
            if bottom == rail_id:
                free_inputs.append(s)
            elif bottom in upper:
                upper_supports.append(s)
            else:
                lower_supports.append(s)
            continue
        if top in lower:
            lower_supports.append(s)
            continue
        # top in upper
        if bottom in upper:
            upper_supports.append(s)
        elif bottom == rail_id:
            if route:
                in_links.append(s)
        elif route:
            raise RebuildRefused("cross_link", f"{rail_id}: the part above also reaches the part below through "
                                 f"{s.name or top}; rebuilding here would cut that route")
    if len(out_links) != 1:
        raise RebuildRefused("drops", f"{rail_id}: the marble must drop from this rail into exactly one block "
                             f"below (found {len(out_links)})")
    if len(in_links) > 1:
        raise RebuildRefused("multi_in", f"{rail_id}: more than one route comes down onto this rail")
    if upper and not in_links:
        raise RebuildRefused("no_in", f"{rail_id}: no route comes down onto this rail from above")
    # Route edges across the cut other than through R (falls hole to hole).
    owner = {p: _owner(s) for s in layout.supports for p in s.stack_part_ids}
    side = {}
    for rid in lower:
        side[rid] = "lower"
    for rid in upper:
        side[rid] = "upper"
    for pid, rid in owner.items():
        if rid in side:
            side[pid] = side[rid]
    for s in in_links + out_links:
        for p in s.stack_part_ids:
            side[p] = "link"
    graph = build_routing_graph(layout, catalog)
    for a, targets in graph.edges.items():
        ca = a.split(":", 1)[0]
        for b in targets:
            cb = b.split(":", 1)[0]
            if {side.get(ca), side.get(cb)} == {"upper", "lower"}:
                raise RebuildRefused("cross_fall", f"{rail_id}: the part above also drops into the part below "
                                     f"({ca} → {cb})")
    return {"rail": rails[rail_id], "lower": lower, "upper": upper, "out": out_links[0],
            "in": in_links[0] if in_links else None, "free_inputs": free_inputs,
            "lower_supports": lower_supports, "upper_supports": upper_supports, "parts": parts}


def _lower_obstacles(layout: Layout, catalog: PartCatalog, cut: Mapping[str, Any], counts) -> list:
    """Where the lower part's marbles roll and fall (new columns keep out)."""
    out = cut["out"]
    keep = {p for s in cut["lower_supports"] for p in s.stack_part_ids} | set(out.stack_part_ids)
    sub = Layout("lower", rails=tuple(r for r in layout.rails if r.id in cut["lower"]),
                 parts=tuple(p for p in layout.parts if p.id in keep),
                 supports=tuple(cut["lower_supports"]) + (replace(out, upper_rail_id=None, upper_hole_index=None),))
    first = out.stack_part_ids[0]
    solver = SupportSolver(sub, catalog, counts, PortRef(first, "top"), ())
    # The marble paths, less those the boundary block itself touches (it
    # stands where its outlet's path begins; the new block stands there too).
    from .collision import component_solids, penetration_cm
    own = [o for o in component_solids(sub, catalog) if o.id in set(out.stack_part_ids)]
    return [o for o in solver.obstacles if ("#" in o.id or o.id.endswith("marble"))
            and not any(penetration_cm(o, b) > 1e-6 for b in own)]


def rebuild(layout: Layout, catalog: PartCatalog, counts: Mapping[str, int], source: PortRef,
            sinks: Sequence[PortRef], rail_id: str, intent: str = "rebuild", seed: int = 1,
            attempts: int = 40, keep: int = 3, min_support_g: float | None = None,
            stats: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Candidate layouts with `rail_id`'s window grown again under `intent`.
    Each: {"layout", "source", "sinks", "rails", "shift": (dx, dy, dz)}."""
    from .generator import Budget, CascadeGenerator, Column, GeneratorConfig, Solid, _State

    if intent not in INTENTS:
        raise ValueError(f"unknown intent {intent!r}")
    cut = plan_cut(layout, catalog, source, rail_id)
    rails = layout.rail_map()
    parts = cut["parts"]
    lower, upper = cut["lower"], cut["upper"]
    out = cut["out"]

    # Budget left for the window: everything minus the lower and upper parts.
    upper_parts = {p for s in cut["upper_supports"] for p in s.stack_part_ids}
    if cut["in"] is not None:
        upper_parts |= set(cut["in"].stack_part_ids)
    used_upper = Counter(rails[r].rail_type for r in upper) + Counter(parts[p].part_type for p in upper_parts)
    budget = Budget(Counter({k: max(0, v - used_upper.get(k, 0)) for k, v in counts.items()}))

    config = GeneratorConfig(strategy="bottom_up", max_height_units=999, max_rails=99,
                             up_split_probability=1.0 if intent == "split" else 0.0, max_exits=3)
    obstacles = _lower_obstacles(layout, catalog, cut, counts)
    first = parts[out.stack_part_ids[0]]
    block0 = first.part_type
    flow0 = (float(first.rotation_deg or 0) + 90.0) % 360
    n_rails = {"rebuild": (1, 2), "add_rail": (2, 2), "split": (2, 3)}[intent]

    stats = stats if stats is not None else {}
    note = lambda k: stats.__setitem__(k, stats.get(k, 0) + 1)
    rng = random.Random(seed)
    r0 = cut["rail"]
    # the window as it is: a candidate equal to it is no change
    results, seen = [], {((r0.rail_type, round(r0.x_cm, 1), round(r0.y_cm, 1), round(r0.z_units), round(r0.yaw_deg)),)}
    for attempt in range(attempts):
        gen = CascadeGenerator(catalog, budget, config, random.Random(rng.random()))
        gen.work = 400
        gen._feet = set()
        state = _State()
        state.counters.update({"rail": 900, "c": 900})
        for rid in lower:
            state.rails[rid] = rails[rid]
            state.fixed.append(rid)
        for i, s in enumerate(cut["lower_supports"]):        # occupancy, solids, budget
            stack = [parts[p] for p in s.stack_part_ids]
            ground = s.lower_rail_id is None
            kinds = tuple(p.part_type for p in stack if p.part_type != "wooden_foundation")
            if not stack:
                continue
            base_z = 0 if ground else stack[0].z_units
            top_z = base_z + sum(gen.heights[p.part_type] for p in stack)
            state.columns[f"lowerc{i}"] = Column(f"lowerc{i}", stack[-1].x_cm, stack[-1].y_cm, s.lower_rail_id,
                                                 s.lower_hole_index, int(base_z), s.upper_rail_id,
                                                 s.upper_hole_index, int(top_z), kinds)
        for o in obstacles:
            state.corridors[o.id] = o
        # grow the window
        lower_rail, hole, flow = rails[out.lower_rail_id], out.lower_hole_index, flow0
        block_z, point = int(first.z_units), (first.x_cm, first.y_cm)
        fronts = [b for b, outs in gen.drop_blocks.items() if outs == ("front",) and budget.counts[b] > 0]
        target = rng.randint(*n_rails)
        ok = True
        for step in range(target):
            grown = gen._grow_up(state, lower_rail, hole, flow, block_z, point,
                                 [block0] if step == 0 else fronts, 999, no_split=step == 0)
            if grown is None:
                ok = False
                break
            state, lower_rail, hole, flow, block_z, point = grown
        if not ok:
            note("grow")
            continue
        window = [rid for rid in state.rails if rid not in lower]
        if intent == "split" and not any(c.top_types[:1] == ("red_random_split",) for c in state.columns.values()
                                         if not c.id.startswith("lowerc")):
            note("no split")
            continue
        # the block the upper part drops into (or the input block)
        if cut["in"] is not None:
            in_first = parts[cut["in"].stack_part_ids[0]]
            in_types = tuple(parts[p].part_type for p in cut["in"].stack_part_ids)
        else:
            src = next((s for s in cut["free_inputs"]), None)
            in_types = tuple(parts[p].part_type for p in src.stack_part_ids) if src else ("yellow",)
        rotation = int(round(flow - 90)) % 360
        top_z = block_z + sum(gen.heights[t] for t in in_types)
        col = Column(state.new_id("c"), round(point[0], 6), round(point[1], 6), lower_rail.id, hole, block_z,
                     None, None, top_z, in_types, rotation)
        if gen._hits(state, [col.solid(gen.half)]):
            note("input hits")
            continue
        state.columns[col.id] = col
        state.input_column = col.id
        if not gen._feasible(state):
            note("budget")
            continue
        built, _, block_ids = gen.materialize(state, layout.name)
        new_cols = {c for c in state.columns if not c.startswith("lowerc")}
        w_supports = [s for s in built.supports if s.name in new_cols]
        w_parts = {p for s in w_supports for p in s.stack_part_ids}
        input_parts = [s.stack_part_ids for s in w_supports if s.name == col.id][0]

        # move the upper part onto the new input column
        shift = (0.0, 0.0, 0.0)
        u_rails, u_parts, u_supports = [], [], []
        if cut["in"] is not None:
            u = rails[cut["in"].upper_rail_id]
            ux, uy, _ = rail_hole_world(u, catalog, cut["in"].upper_hole_index)
            spec = catalog.rails[u.rail_type]
            dz = top_z - (u.z_units + spec.hole_level(cut["in"].upper_hole_index))
            shift = (point[0] - ux, point[1] - uy, dz)
            dx, dy, dz = shift
            u_rails = [replace(rails[r], x_cm=rails[r].x_cm + dx, y_cm=rails[r].y_cm + dy,
                               z_units=rails[r].z_units + dz) for r in upper]
            u_parts = [replace(parts[p], x_cm=parts[p].x_cm + dx, y_cm=parts[p].y_cm + dy,
                               z_units=parts[p].z_units + dz) for p in sorted(upper_parts - set(cut["in"].stack_part_ids))]
            u_supports = list(cut["upper_supports"])
            # the input column: same ids as the old link's blocks where they fit
            renamed = dict(zip(input_parts, cut["in"].stack_part_ids))
            w_parts -= set(input_parts)
            built_parts = {p.id: p for p in built.parts}
            for new, old in renamed.items():
                u_parts.append(replace(built_parts[new], id=old))
            u_supports.append(SupportLink(u.id, cut["in"].upper_hole_index, tuple(renamed[p] for p in input_parts),
                                          lower_rail.id, hole, name=cut["in"].name or "input_link"))
            w_supports = [s for s in w_supports if s.name != col.id]
            new_source = source
        else:
            new_source = PortRef(block_ids[col.id], "top")

        keep_lower = {p for s in cut["lower_supports"] for p in s.stack_part_ids}
        merged = Layout(
            layout.name,
            rails=tuple(r for r in layout.rails if r.id in lower) + tuple(state.rails[r] for r in window) + tuple(u_rails),
            parts=tuple(p for p in layout.parts if p.id in keep_lower)
                  + tuple(p for p in built.parts if p.id in w_parts) + tuple(u_parts),
            supports=tuple(cut["lower_supports"]) + tuple(w_supports) + tuple(u_supports),
            route_links=tuple(l for l in layout.route_links
                              if l.source.component_id in lower | upper and l.target.component_id in lower | upper),
            routing_options=layout.routing_options,
        )
        new_sinks = tuple(s for s in sinks if s.component_id in lower | upper)
        new_sinks += tuple(PortRef(*leaf.split(":", 1)) for leaf in state.leaves)
        new_sinks += tuple(PortRef(block_ids[c], p) for c, p in state.dangling)
        solved = resolve_supports(merged, catalog, counts, new_source, new_sinks, keep_braces=True,
                                  min_support_g=min_support_g, fixed_rails=lower)
        if solved is None:
            note("supports")
            continue
        result = validate_layout(solved, catalog, source=new_source, sinks=new_sinks)
        if not result.valid:
            note("invalid")
            continue
        key = tuple(sorted((r.rail_type, round(r.x_cm, 1), round(r.y_cm, 1), round(r.z_units), round(r.yaw_deg))
                           for r in solved.rails if r.id in window))
        if key in seen:
            note("duplicate")
            continue
        seen.add(key)
        # Prefer: the upper part where it was, few new ground columns and
        # tall single towers, few parts.
        from .generator import weak_towers
        old_ground = sum(1 for x in layout.supports if x.lower_rail_id is None and x.upper_rail_id is not None)
        new_ground = sum(1 for x in solved.supports if x.lower_rail_id is None and x.upper_rail_id is not None)
        cost = (abs(shift[0]) + abs(shift[1]) + 0.5 * abs(shift[2]) + 1.0 * len(solved.parts)
                + 10.0 * max(0, new_ground - old_ground) + 15.0 * weak_towers(solved, catalog))
        results.append({"layout": solved, "source": new_source, "sinks": new_sinks, "rails": window,
                        "shift": shift, "cost": cost})
        if len(results) >= keep * 3:
            break
    results.sort(key=lambda c: c["cost"])
    return results[:keep]
