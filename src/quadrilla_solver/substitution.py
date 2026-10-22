"""Swap straight rails for curved rails with the same hole positions.

A short curve's end holes coincide with a short straight's holes 0 and 3, and
an S-curve's three holes with a center-hole long rail's holes 0, 2 and 4.
Columns and blocks below the rail are unaffected. A block standing directly on
the rail must turn with the curve's tangent (blocks rotate freely on their peg),
so the swap is allowed only when:

* the rail uses no other holes (supports, blocks standing on it, drop holes),
* the marble does not enter it through an explicit route link at its end
  (the feeding outlet would no longer face the curve's end), and
* every block standing on it sends the marble nowhere but onto this rail (no
  route links from it): a 90-degree turn elsewhere would be rotated away.

The caller re-validates the whole layout; stability (curves need load above),
collisions and routing are checked there.
"""
from __future__ import annotations

from dataclasses import replace
from math import atan2, degrees, hypot, radians

from .catalog import PartCatalog
from .model import Layout, PlacedRail, rail_hole_world, rail_pose

# straight type -> (curve type, straight hole index -> curve hole index)
CURVE_FOR_STRAIGHT = {
    "straight_short": ("curved_short", {0: 0, 3: 1}),
    "straight_long_center": ("s_curve", {0: 0, 2: 1, 4: 2}),
}


def _used_holes(layout: Layout, rail: PlacedRail) -> set[int]:
    used = {s.upper_hole_index for s in layout.supports if s.upper_rail_id == rail.id}
    used |= {s.lower_hole_index for s in layout.supports if s.lower_rail_id == rail.id}
    used |= {i for i, state in rail.hole_states.items() if state == "block_connected"}
    return used


def eligible_rails(layout: Layout) -> list[str]:
    """Rails whose swap to a curve keeps every connection intact."""
    linked = {link.source.component_id for link in layout.route_links}
    linked |= {link.target.component_id for link in layout.route_links}
    out = []
    for rail in layout.rails:
        if rail.rail_type not in CURVE_FOR_STRAIGHT or rail.id in linked:
            continue
        _, hole_map = CURVE_FOR_STRAIGHT[rail.rail_type]
        if not _used_holes(layout, rail) <= set(hole_map):
            continue
        standing = [s.stack_part_ids[0] for s in layout.supports
                    if s.lower_rail_id == rail.id and s.stack_part_ids]
        if any(part_id in linked for part_id in standing):
            continue
        out.append(rail.id)
    return out


def substitute(layout: Layout, catalog: PartCatalog, rail_id: str, turn: str) -> Layout:
    """Layout with `rail_id` replaced by its curve bending toward `turn`."""
    rail = layout.rail_map()[rail_id]
    curve_type, hole_map = CURVE_FOR_STRAIGHT[rail.rail_type]
    curve = catalog.rails[curve_type]
    keys = sorted(hole_map)
    first = rail_hole_world(rail, catalog, keys[0])
    last = rail_hole_world(rail, catalog, keys[-1])
    chord = atan2(last[1] - first[1], last[0] - first[0])
    sign = -1 if turn == "right" else 1
    # Each 60-degree arc meets its chord at 30 degrees.
    probe = PlacedRail("probe", curve_type, first[0], first[1], rail.z_units,
                       yaw_deg=degrees(chord - sign * radians(30)), turn=turn)
    ex, ey, eh = rail_pose(probe, curve, -curve.holes_cm[0])
    states = {hole_map[i]: s for i, s in rail.hole_states.items() if i in hole_map}
    new_rail = PlacedRail(rail.id, curve_type, ex, ey, rail.z_units, yaw_deg=degrees(eh),
                          flow_direction=rail.flow_direction, hole_states=states, turn=turn)
    for old, new in hole_map.items():
        a = rail_hole_world(rail, catalog, old)
        b = rail_hole_world(new_rail, catalog, new)
        assert hypot(a[0] - b[0], a[1] - b[1]) < 0.01, (rail_id, old, a, b)

    supports = []
    rotations: dict[str, int] = {}
    for s in layout.supports:
        if s.upper_rail_id == rail.id:
            s = replace(s, upper_hole_index=hole_map[s.upper_hole_index])
        if s.lower_rail_id == rail.id:
            new_hole = hole_map[s.lower_hole_index]
            s = replace(s, lower_hole_index=new_hole)
            tangent = rail_pose(new_rail, curve, curve.holes_cm[new_hole])[2]
            rotations[s.stack_part_ids[0]] = round(degrees(tangent) - rail.yaw_deg)
        supports.append(s)
    parts = tuple(
        replace(p, rotation_deg=(p.rotation_deg + rotations[p.id]) % 360) if p.id in rotations else p
        for p in layout.parts
    )
    rails = tuple(new_rail if r.id == rail.id else r for r in layout.rails)
    return replace(layout, rails=rails, parts=parts, supports=tuple(supports))
