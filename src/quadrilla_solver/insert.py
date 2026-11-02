"""Edits at a drop point (design: docs/editing.md, user 2026-11-03).

A drop point is a route column: the marble falls from an upper rail U (or is
put in, for the input) into a block b standing on a lower rail L, which sends
it along L. Two edits there:

split_at       b becomes a red splitter. Its second marble rolls back along
               L and leaves through the first free hole behind b (onto the
               ground, or hole to hole into a rail below); the holes between
               are covered. Nothing moves.

insert_switchback
               A switchback goes in between U and b: everything from b's top
               up is lifted by 12 levels (every column crossing that level
               gets 12 more levels of pass-through blocks, so all links and
               falls stay as they were, however many there are), and two
               rails go into the gap, one above the other in opposite
               directions along any heading: W1 (catches the marble from U,
               rolls out) and W2 (rolls back, drops into b). As in the ladder,
               W1's hole beyond its entry stands on W2's hole beyond its stop.
               W2's far end is supported by the support solver.

Both return candidate layouts (best first) with source and sinks; the caller
validates. ValueError (EditRefused, with a code) where the edit does not apply.
"""
from __future__ import annotations

from dataclasses import replace
from math import cos, radians, sin
from typing import Any, Iterable, Mapping, Sequence

from .catalog import PartCatalog
from .collision import component_solids, penetration_cm
from .model import Layout, PlacedPart, PlacedRail, PortRef, SupportLink, rail_hole_world
from .supports import resolve_supports, route_parts
from .validation import validate_layout

LIFT = 12                      # two rails, each a drop block (5) + a rail (1)
PASS = ("orange_vertical", "purple_drop")   # pass-through: 5 and 1 levels


class EditRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def drop_point(layout: Layout, catalog: PartCatalog, source: PortRef, part_id: str) -> SupportLink:
    """The route column whose bottom block is `part_id`, standing on a rail."""
    on_route = route_parts(layout, catalog, source)
    for s in layout.supports:
        if s.stack_part_ids and s.stack_part_ids[0] == part_id and s.lower_rail_id is not None:
            if part_id not in on_route:
                raise EditRefused("not_on_route", f"{part_id}: the marble does not pass this block")
            spec = catalog.raw.get("routing_blocks", {}).get(layout.part_map()[part_id].part_type, {})
            if not any(r.get("from") == "top" for r in spec.get("routes", [])):
                raise EditRefused("not_drop", f"{part_id}: not a block the marble drops into")
            return s
    raise EditRefused("not_drop", f"{part_id}: not a block standing on a rail")


def _direction(rail: PlacedRail, catalog: PartCatalog, hole: int, rotation: float) -> int:
    """+1 if a block at `hole` facing `rotation` sends the marble toward the
    rail's higher holes, -1 toward the lower ones."""
    a = rail_hole_world(rail, catalog, 0)
    b = rail_hole_world(rail, catalog, len(catalog.rails[rail.rail_type].holes_cm) - 1)
    ux, uy = b[0] - a[0], b[1] - a[1]
    fx, fy = cos(radians(rotation + 90)), sin(radians(rotation + 90))
    return 1 if ux * fx + uy * fy > 0 else -1


# ---- split here -------------------------------------------------------------

def split_at(layout: Layout, catalog: PartCatalog, source: PortRef, sinks: Sequence[PortRef],
             part_id: str) -> list[dict[str, Any]]:
    s = drop_point(layout, catalog, source, part_id)
    rails = layout.rail_map()
    lower = rails[s.lower_rail_id]
    if lower.flow_direction not in ("a_to_b", "b_to_a"):
        raise EditRefused("rail_pivot", f"{lower.id}: already flows to or from a hole")
    if catalog.rails[lower.rail_type].shape in ("arc", "compound_arc", "twist", "plate", "seesaw"):
        raise EditRefused("rail_shape", f"{lower.id}: only straight rails")
    part = layout.part_map()[part_id]
    hole = s.lower_hole_index
    holes = catalog.rails[lower.rail_type].holes_cm
    forward = _direction(lower, catalog, hole, part.rotation_deg or 0)
    behind = list(range(hole - 1, -1, -1)) if forward > 0 else list(range(hole + 1, len(holes)))
    held = {x.upper_hole_index for x in layout.supports if x.upper_rail_id == lower.id}
    stood = {x.lower_hole_index for x in layout.supports if x.lower_rail_id == lower.id}
    exit_hole = next((j for j in behind if j not in held and j not in stood
                      and lower.hole_states.get(j, "open") == "open"), None)
    if exit_hole is None or abs(holes[hole] - holes[exit_hole]) < 4.0:
        raise EditRefused("no_back_hole", f"{lower.id}: no free hole behind {part_id} for the second marble")
    between = [j for j in behind if (j - exit_hole) * (j - hole) < 0]
    if any(j in held or j in stood for j in between):
        raise EditRefused("no_back_hole", f"{lower.id}: something stands between {part_id} and the free hole")
    states = dict(lower.hole_states)
    for j in between:
        states[j] = "covered"
    new_rail = replace(lower, flow_direction="from_hole", flow_hole=hole, hole_states=states)
    parts = tuple(replace(p, part_type="red_random_split") if p.id == part_id else p for p in layout.parts)
    out = replace(layout, rails=tuple(new_rail if r.id == lower.id else r for r in layout.rails), parts=parts)
    new_sinks = tuple(sinks) + (PortRef(lower.id, f"hole:{exit_hole}"),)
    return [{"layout": out, "source": source, "sinks": new_sinks}]


# ---- lift everything above a level ------------------------------------------

def lift_above(layout: Layout, catalog: PartCatalog, level: int, dz: int,
               skip: Iterable[str] = ()) -> Layout:
    """Raise every rail at or above `level` by `dz`. A column whose rail on
    top is raised but whose base is not gets `dz` levels of pass-through
    blocks at its first part boundary at or above `level`; columns standing on
    raised rails move whole. Supports named in `skip` are left as they are."""
    skip = set(skip)
    height = catalog.height_units
    parts = layout.part_map()
    rail_map = layout.rail_map()
    raised = {r.id for r in layout.rails if r.z_units >= level}
    rails = tuple(replace(r, z_units=r.z_units + dz) if r.id in raised else r for r in layout.rails)
    moved: dict[str, PlacedPart] = {}
    added: list[PlacedPart] = []
    supports = []
    fill = ["orange_vertical"] * (dz // 5) + ["purple_drop"] * (dz % 5)
    for s in layout.supports:
        if s.name in skip:
            supports.append(s)
            continue
        stack = [parts[p] for p in s.stack_part_ids]
        if s.lower_rail_id in raised:
            for p in stack:
                moved[p.id] = replace(p, z_units=p.z_units + dz)
            supports.append(s)
            continue
        if s.upper_rail_id not in raised:
            supports.append(s)
            continue
        split = len(stack)
        for i, p in enumerate(stack):
            if p.z_units >= level:
                split = i
                break
            if p.z_units + height(p.part_type) > level:
                split = i + 1
                break
        if split > 0:
            z = stack[split - 1].z_units + height(stack[split - 1].part_type)
        elif s.lower_rail_id is not None:
            z = rail_map[s.lower_rail_id].z_units + 1
        else:
            z = 0
        for p in stack[split:]:
            moved[p.id] = replace(p, z_units=p.z_units + dz)
        x, y = (stack[0].x_cm, stack[0].y_cm) if stack else rail_hole_world(
            rail_map[s.upper_rail_id], catalog, s.upper_hole_index)[:2]
        ids = []
        for t in fill:
            pid = f"lift{len(added)}_{t}"
            added.append(PlacedPart(pid, t, x, y, z, 0))
            ids.append(pid)
            z += height(t)
        supports.append(replace(s, stack_part_ids=tuple(s.stack_part_ids[:split]) + tuple(ids)
                                + tuple(s.stack_part_ids[split:])))
    all_parts = tuple(moved.get(p.id, p) for p in layout.parts) + tuple(added)
    return replace(layout, rails=rails, parts=all_parts, supports=tuple(supports))


# ---- insert a switchback ------------------------------------------------------

def _rail_at(rail_id: str, kind: str, catalog: PartCatalog, entry_xy, heading_deg: float, z: int,
             entry: int, states: Mapping[int, str]) -> PlacedRail:
    holes = catalog.rails[kind].holes_cm
    h = radians(heading_deg)
    ax, ay = entry_xy[0] - holes[entry] * cos(h), entry_xy[1] - holes[entry] * sin(h)
    return PlacedRail(rail_id, kind, round(ax, 4), round(ay, 4), z, yaw_deg=round(heading_deg % 360, 4),
                      flow_direction="a_to_b", hole_states=dict(states))


def insert_switchback(layout: Layout, catalog: PartCatalog, counts: Mapping[str, int], source: PortRef,
                      sinks: Sequence[PortRef], part_id: str, keep: int = 3,
                      headings: Sequence[float] | None = None) -> list[dict[str, Any]]:
    s = drop_point(layout, catalog, source, part_id)
    parts = layout.part_map()
    rails = layout.rail_map()
    b = parts[part_id]
    level = int(b.z_units + catalog.height_units(b.part_type))     # b's top: the cut
    bx, by = b.x_cm, b.y_cm
    lifted = lift_above(layout, catalog, level, LIFT, skip={s.name})
    lp = lifted.part_map()
    # The old column: b stays; what stood on b (passes) is lifted with U.
    above = [lp[p] if p in lp else parts[p] for p in s.stack_part_ids[1:]]
    above = [replace(p, z_units=parts[p.id].z_units + LIFT) for p in above]
    lifted = replace(lifted, parts=tuple(next((a for a in above if a.id == p.id), p) for p in lifted.parts),
                     supports=tuple(x for x in lifted.supports if x.name != s.name))
    lower = rails[s.lower_rail_id]
    flow_l = (b.rotation_deg or 0) + 90.0
    u_dir = None
    if s.upper_rail_id is not None:
        u = lifted.rail_map()[s.upper_rail_id]
        u_dir = u.yaw_deg
    if headings is None:
        base = [flow_l + 180, flow_l + 90, flow_l - 90, flow_l] + ([u_dir, u_dir + 180] if u_dir is not None else [])
        headings = list(dict.fromkeys(round(h % 360, 3) for h in base + [k * 30.0 for k in range(12)]))
    existing = {r.id for r in layout.rails} | {p.id for p in layout.parts}
    n = 0
    while f"sw{n}a" in existing:
        n += 1
    w1_id, w2_id = f"sw{n}a", f"sw{n}b"
    solids = [o for o in component_solids(lifted, catalog)]
    xs0 = [r.x_cm for r in layout.rails] + [p.x_cm for p in layout.parts]
    ys0 = [r.y_cm for r in layout.rails] + [p.y_cm for p in layout.parts]
    area0 = (max(xs0) - min(xs0)) * (max(ys0) - min(ys0))
    out = []
    for kind in ("straight_long", "straight_short"):
        holes = catalog.rails[kind].holes_cm
        span = holes[2] - holes[1]
        for heading in headings:
            h = radians(heading)
            q = (bx + span * cos(h), by + span * sin(h))
            w1 = _rail_at(w1_id, kind, catalog, (bx, by), heading, level + 6, 1, {2: "block_connected"})
            w2 = _rail_at(w2_id, kind, catalog, q, heading + 180, level, 1, {2: "block_connected"})
            e_type = b.part_type if b.part_type in ("yellow", "blue", "green", "cyan") else "yellow"
            e = PlacedPart(f"{w1_id}_in", e_type, bx, by, level + 7, int(round(heading - 90)) % 360)
            e2 = PlacedPart(f"{w1_id}_turn", "green" if e_type != "green" else "blue", round(q[0], 4),
                            round(q[1], 4), level + 1, int(round(heading + 90)) % 360)
            mx, my, _ = rail_hole_world(w1, catalog, 0)
            m = PlacedPart(f"{w1_id}_rest", "cyan", round(mx, 4), round(my, 4), level + 1, 0)
            new_solids = component_solids(Layout("n", rails=(w1, w2), parts=(e, e2, m)), catalog)
            clash = False
            for ns in new_solids:
                for o in solids:
                    if o.id in (part_id, lower.id) or o.id in s.stack_part_ids:
                        continue
                    if s.upper_rail_id and o.id == s.upper_rail_id:
                        continue
                    if penetration_cm(ns, o) > 0.05:
                        clash = True
                        break
                if clash:
                    break
            if clash:
                continue
            new_supports = [
                SupportLink(w2_id, 2, (part_id,), lower.id, s.lower_hole_index, name=s.name),
                SupportLink(w1_id, 2, (e2.id,), w2_id, 1, name=f"{w1_id}_turn"),
                SupportLink(w1_id, 0, (m.id,), w2_id, 3, name=f"{w1_id}_rest"),
                SupportLink(s.upper_rail_id, s.upper_hole_index, (e.id,) + tuple(p.id for p in above),
                            w1_id, 1, name=f"{w1_id}_in"),
            ]
            trial = replace(lifted, rails=lifted.rails + (w1, w2), parts=lifted.parts + (e, e2, m),
                            supports=lifted.supports + tuple(new_supports))
            new_source = PortRef(e.id, "top") if s.upper_rail_id is None else source
            solved = resolve_supports(trial, catalog, counts, new_source, sinks, keep_braces=True,
                                      fixed_rails=[r.id for r in layout.rails])
            if solved is None:
                continue
            result = validate_layout(solved, catalog, source=new_source, sinks=sinks)
            if not result.valid:
                continue
            ground = sum(1 for x in solved.supports if x.lower_rail_id is None and x.upper_rail_id is not None)
            # keep it within the build's top view where possible
            xs = [v for r in solved.rails for v in (r.x_cm,)] + [p.x_cm for p in solved.parts]
            ys = [r.y_cm for r in solved.rails] + [p.y_cm for p in solved.parts]
            grow = (max(xs) - min(xs)) * (max(ys) - min(ys)) - area0
            out.append({"layout": solved, "source": new_source, "sinks": tuple(sinks), "rails": [w1_id, w2_id],
                        "lift": LIFT, "heading": heading, "kind": kind,
                        "cost": len(solved.parts) + 8 * ground + max(0.0, grow) / 100.0
                        + (0 if kind == "straight_long" else 3)})
            if len(out) >= 24:
                break
        if len(out) >= 24:
            break
    out.sort(key=lambda c: c["cost"])
    return out[:keep]
