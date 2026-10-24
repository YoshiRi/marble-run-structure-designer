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


# ---------------------------------------------------------------------------
# Shorter rails (user review: long rails used where a short one would do take
# space for nothing).

_SHORTER = {"straight_long": "straight_short", "straight_long_center": "straight_short"}


def shorten(layout: Layout, catalog: PartCatalog, rail_id: str, move_columns: bool = False) -> list[Layout]:
    """Candidate layouts with long straight `rail_id` replaced by a short one
    laid along the same line, so that every hole in use (supports, blocks on
    it, drop/dive holes, covers) and every linked end lands on the short
    rail's matching hole or end. Holes the marble now rolls over get covers.

    move_columns: a ground column that holds only this rail may move along
    the rail to a free hole of the short rail (the one nearest to where it
    stood). A long straight's holes sit only near its ends, so a rail long
    just to reach a far column (review of generated-layered-tower) can be
    shortened only by moving that column. The caller validates each
    candidate (collisions, statics, routing)."""
    rail = layout.rail_map()[rail_id]
    if rail.rail_type not in _SHORTER or rail.flow_direction != "a_to_b":
        return []
    long_spec = catalog.rails[rail.rail_type]
    short_type = _SHORTER[rail.rail_type]
    short = catalog.rails[short_type]
    holes = long_spec.holes_cm
    used, ends, start, end = _stretch(layout, catalog, rail)
    standing = {s.lower_hole_index for s in layout.supports if s.lower_rail_id == rail_id}
    movable = {}
    if move_columns:
        for s in layout.supports:
            i = s.upper_hole_index
            if (s.upper_rail_id == rail_id and s.lower_rail_id is None and i not in standing
                    and rail.hole_states.get(i) is None):
                movable[i] = s
    fixed = used - set(movable)

    offsets = {round(holes[i] - x, 6) for i in fixed for x in short.holes_cm} if fixed else \
        {round(start - 0.0, 6), round(end - short.length_cm, 6)}
    if "end_a" in ends:
        offsets = {o for o in offsets if abs(o) < 1e-6}
    if "end_b" in ends:
        offsets = {o for o in offsets if abs(o + short.length_cm - long_spec.length_cm) < 1e-6}
    heading = radians(rail.yaw_deg)
    out = []
    for o in sorted(offsets):
        if o < -1e-6 or o + short.length_cm > long_spec.length_cm + 1e-6:
            continue
        if start < o - 1e-6 or end > o + short.length_cm + 1e-6:
            continue  # the marble would roll off the shorter rail
        on_short = lambda pos: next((j for j, x in enumerate(short.holes_cm) if abs(x + o - pos) < 1e-6), None)
        index = {i: on_short(holes[i]) for i in fixed}
        if any(j is None for j in index.values()):
            continue
        shift: dict[str, tuple[float, float]] = {}
        for i, sup in sorted(movable.items()):
            j = on_short(holes[i])
            if j is None or j in index.values():
                free = [j for j in range(len(short.holes_cm)) if j not in index.values()]
                if not free:
                    break
                j = min(free, key=lambda j: abs(short.holes_cm[j] + o - holes[i]))
                d = short.holes_cm[j] + o - holes[i]
                for part_id in sup.stack_part_ids:
                    shift[part_id] = (d * _cos(heading), d * _sin(heading))
            index[i] = j
        else:
            states = {}
            for i, st in rail.hole_states.items():
                if int(i) in index:
                    states[index[int(i)]] = st
            for j, x in enumerate(short.holes_cm):
                if j not in states and start < x + o < end:
                    states[j] = "covered"
            new = replace(rail, rail_type=short_type,
                          x_cm=rail.x_cm + o * _cos(heading), y_cm=rail.y_cm + o * _sin(heading),
                          hole_states=dict(sorted(states.items())))
            supports = tuple(
                replace(s,
                        upper_hole_index=index[s.upper_hole_index] if s.upper_rail_id == rail_id else s.upper_hole_index,
                        lower_hole_index=index[s.lower_hole_index] if s.lower_rail_id == rail_id else s.lower_hole_index)
                for s in layout.supports)
            parts = tuple(replace(p, x_cm=p.x_cm + shift[p.id][0], y_cm=p.y_cm + shift[p.id][1])
                          if p.id in shift else p for p in layout.parts)
            rails = tuple(new if r.id == rail_id else r for r in layout.rails)
            out.append((len(shift), replace(layout, rails=rails, parts=parts, supports=supports)))
    # Fewest columns moved first.
    return [l for _, l in sorted(out, key=lambda t: t[0])]


def _stretch(layout: Layout, catalog: PartCatalog, rail: PlacedRail) -> tuple[set[int], set[str], float, float]:
    """Holes in use, linked ends, and the stretch [start, end] (cm along the
    rail) the marble rolls or must stay covered on."""
    rail_id = rail.id
    holes = catalog.rails[rail.rail_type].holes_cm
    used = {s.upper_hole_index for s in layout.supports if s.upper_rail_id == rail_id}
    standing = {s.lower_hole_index for s in layout.supports if s.lower_rail_id == rail_id}
    used |= standing
    used |= {int(i) for i, state in rail.hole_states.items() if state != "covered"}
    ends = {link.source.port for link in layout.route_links if link.source.component_id == rail_id}
    ends |= {link.target.port for link in layout.route_links if link.target.component_id == rail_id}
    stops = [holes[int(i)] for i, st in rail.hole_states.items() if st in ("block_connected", "open")]
    # The stretch the marble rolls: from the linked end or just past a block
    # standing on the rail, to the stop hole or end B.
    half = 2.25
    start = 0.0 if "end_a" in ends else min((holes[i] + half for i in standing), default=0.0)
    end = min(stops) if stops else catalog.rails[rail.rail_type].length_cm
    covered = {holes[int(i)] for i, st in rail.hole_states.items() if st == "covered"}
    if covered:
        start = min(start, min(covered))
        end = max(end, max(covered))
    return used, ends, start, end



def _cos(a: float) -> float:
    from math import cos
    v = cos(a)
    return 0.0 if abs(v) < 1e-12 else v


def _sin(a: float) -> float:
    from math import sin
    v = sin(a)
    return 0.0 if abs(v) < 1e-12 else v
