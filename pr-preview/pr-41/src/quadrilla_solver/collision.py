"""Coarse solid collision and marble clearance checks.

Every rail and part is approximated by its bounding box: an oriented
rectangle in plan view extruded between two heights. Two solids collide only
when they penetrate each other by more than a small tolerance on every axis,
so parts that merely touch (a block standing on a rail, two blocks side by
side, a rail starting at a block face) are accepted. Connector pegs that sit
inside rail holes are not modeled as solids.

This is a conservative schematic check. It does not model rounded corners,
internal channels or the rail groove profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import atan2, cos, hypot, radians, sin
from typing import Iterable

from .catalog import PartCatalog
from .model import Layout, PlacedRail, rail_pose


@dataclass(frozen=True)
class Solid:
    id: str
    center_xy: tuple[float, float]
    half_extents_xy: tuple[float, float]
    angle_rad: float
    z_min_cm: float
    z_max_cm: float


def _geometry(catalog: PartCatalog, key: str, fallback: float) -> float:
    value = catalog.raw.get("geometry_cm", {}).get(key, fallback)
    if isinstance(value, dict):
        value = value.get("value", fallback)
    return float(value)


def _block_footprint(catalog: PartCatalog) -> tuple[float, float]:
    footprint = catalog.raw.get("geometry_cm", {}).get("standard_block_footprint", {})
    if isinstance(footprint, dict):
        return float(footprint.get("width_cm", 4.5)), float(footprint.get("depth_cm", 4.5))
    return 4.5, 4.5


def _part_body_height_cm(catalog: PartCatalog, part_type: str, unit_cm: float) -> float | None:
    spec = catalog.part_spec(part_type)
    if spec is not None:
        body = spec.get("body_height_cm")
        if isinstance(body, dict):
            body = body.get("value")
        if body is not None:
            return float(body)
    height = catalog.height_units(part_type)
    return None if height is None else height * unit_cm


def _strip_solids(rail: PlacedRail, catalog: PartCatalog, start: float, end: float,
                  half_width: float, z_min: float, z_max: float, solid_id: str) -> list[Solid]:
    """Boxes covering the rail centerline between start and end (cm along it).

    Straight rails give one box; curved rails a chain of short chords, each
    widened by its sagitta so the chain covers the arc.
    """
    spec = catalog.rails[rail.rail_type]
    if end - start <= 0:
        return []
    pieces = 1 if spec.shape != "arc" else max(1, int((end - start) / 3.0 + 0.999))
    solids = []
    step = (end - start) / pieces
    for i in range(pieces):
        a = rail_pose(rail, spec, start + i * step)
        b = rail_pose(rail, spec, start + (i + 1) * step)
        chord = hypot(b[0] - a[0], b[1] - a[1])
        sagitta = 0.0
        if spec.shape == "arc" and spec.radius_cm:
            sagitta = spec.radius_cm - (spec.radius_cm ** 2 - (chord / 2) ** 2) ** 0.5
        solids.append(Solid(
            solid_id,
            ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
            (chord / 2.0, half_width + sagitta),
            atan2(b[1] - a[1], b[0] - a[0]),
            z_min, z_max,
        ))
    return solids


def _twist_solids(rail: PlacedRail, catalog: PartCatalog, unit: float, width: float) -> list[Solid]:
    """Chute box (sloping, so it spans two units) plus a square around the funnel."""
    spec = catalog.rails[rail.rail_type]
    raw = catalog.raw.get("special_rails", {}).get(rail.rail_type, {})
    rim = raw.get("funnel_rim_diameter_cm", 23)
    rim = float(rim.get("value", 23) if isinstance(rim, dict) else rim)
    center = spec.holes_cm[-1]
    chute_end = center - rim / 2.0
    z0 = rail.z_units * unit
    top = spec.hole_levels[0] if spec.hole_levels else 3
    # Flat past the last chute hole (a block may stand there), then sloping
    # one unit down to the rim.
    flat_end = spec.holes_cm[-2] + width / 2.0
    solids = _strip_solids(rail, catalog, 0.0, flat_end, width / 2.0,
                           z0 + top * unit, z0 + (top + 1) * unit, rail.id)
    pieces = 4
    for i in range(pieces):
        s0 = flat_end + (chute_end - flat_end) * i / pieces
        s1 = flat_end + (chute_end - flat_end) * (i + 1) / pieces
        drop_hi = (s1 - flat_end) / (chute_end - flat_end)  # fraction of a unit
        drop_lo = (s0 - flat_end) / (chute_end - flat_end)
        solids += _strip_solids(rail, catalog, s0, s1, width / 2.0,
                                z0 + (top - drop_hi) * unit, z0 + (top + 1 - drop_lo) * unit, rail.id)
    cx, cy, heading = rail_pose(rail, spec, center)
    solids.append(Solid(rail.id, (cx, cy), (rim / 2.0, rim / 2.0), heading, z0, z0 + top * unit))
    return solids


def rail_solids(rail: PlacedRail, catalog: PartCatalog) -> list[Solid]:
    spec = catalog.rails.get(rail.rail_type)
    if spec is None:
        return []
    unit = _geometry(catalog, "height_unit", 1.5)
    width = _geometry(catalog, "rail_width_cm", 4.5)
    if spec.shape == "twist":
        return _twist_solids(rail, catalog, unit, width)
    return _strip_solids(rail, catalog, 0.0, spec.length_cm, width / 2.0,
                         rail.z_units * unit, (rail.z_units + spec.height_units) * unit, rail.id)


def rail_solid(rail: PlacedRail, catalog: PartCatalog) -> Solid | None:
    """Single bounding solid of a straight rail (first piece of a curve)."""
    solids = rail_solids(rail, catalog)
    return solids[0] if solids else None


def marble_corridor(rail: PlacedRail, catalog: PartCatalog, start: float, end: float,
                    marble_diameter_cm: float = 1.6) -> list[Solid]:
    """Space a marble needs above the groove between start and end."""
    spec = catalog.rails[rail.rail_type]
    unit = _geometry(catalog, "height_unit", 1.5)
    top = (rail.z_units + spec.height_units) * unit
    return _strip_solids(rail, catalog, start, end, marble_diameter_cm / 2.0,
                         top, top + marble_diameter_cm, f"{rail.id}#marble")


def component_solids(layout: Layout, catalog: PartCatalog) -> list[Solid]:
    unit = _geometry(catalog, "height_unit", 1.5)
    width, depth = _block_footprint(catalog)
    solids: list[Solid] = []
    for rail in layout.rails:
        solids.extend(rail_solids(rail, catalog))
    for part in layout.parts:
        height = _part_body_height_cm(catalog, part.part_type, unit)
        if height is None:
            continue
        spec = catalog.part_spec(part.part_type) or {}
        footprint = spec.get("footprint_cm") or {}
        half = ((float(footprint["length"]) / 2.0, float(footprint["width"]) / 2.0)
                if "length" in footprint else (width / 2.0, depth / 2.0))
        solids.append(Solid(
            part.id,
            (part.x_cm, part.y_cm),
            half,
            radians(part.rotation_deg),
            part.z_units * unit,
            part.z_units * unit + height,
        ))
    return solids


def _axes(solid: Solid) -> tuple[tuple[float, float], tuple[float, float]]:
    c, s = cos(solid.angle_rad), sin(solid.angle_rad)
    return (c, s), (-s, c)


def _projection_radius(solid: Solid, axis: tuple[float, float]) -> float:
    (ux, uy), (vx, vy) = _axes(solid)
    hx, hy = solid.half_extents_xy
    return hx * abs(ux * axis[0] + uy * axis[1]) + hy * abs(vx * axis[0] + vy * axis[1])


def penetration_cm(a: Solid, b: Solid) -> float:
    """Smallest overlap over all separating axes; <= 0 means no contact."""
    z_overlap = min(a.z_max_cm, b.z_max_cm) - max(a.z_min_cm, b.z_min_cm)
    if z_overlap <= 0:
        return z_overlap
    dx = b.center_xy[0] - a.center_xy[0]
    dy = b.center_xy[1] - a.center_xy[1]
    # Far apart in top view (bounding circles do not meet): no contact. The
    # exact gap is not needed; callers only test for overlap.
    reach = hypot(*a.half_extents_xy) + hypot(*b.half_extents_xy)
    if dx * dx + dy * dy > reach * reach:
        return -1.0
    smallest = z_overlap
    for axis in (*_axes(a), *_axes(b)):
        distance = abs(dx * axis[0] + dy * axis[1])
        overlap = _projection_radius(a, axis) + _projection_radius(b, axis) - distance
        smallest = min(smallest, overlap)
        if smallest <= 0:
            return smallest
    return smallest


def solid_collisions(
    layout: Layout,
    catalog: PartCatalog,
    *,
    tolerance_cm: float = 0.05,
) -> tuple[str, ...]:
    """Pairs of rails/parts whose bodies interpenetrate."""
    reasons = []
    for a, b in combinations(component_solids(layout, catalog), 2):
        if a.id == b.id:
            continue  # pieces of the same curved rail
        if penetration_cm(a, b) > tolerance_cm:
            first, second = sorted((a.id, b.id))
            reasons.append(f"solid_collision:{first}:{second}")
    return tuple(sorted(set(reasons)))


def _rail_node_local_x(node_port: str, spec) -> float | None:
    if node_port == "end_a":
        return 0.0
    if node_port == "end_b":
        return spec.length_cm
    if node_port.startswith("hole:"):
        index = int(node_port.split(":", 1)[1])
        if 0 <= index < len(spec.holes_cm):
            return spec.holes_cm[index]
    return None


def marble_clearance_conflicts(
    layout: Layout,
    catalog: PartCatalog,
    reachable_nodes: Iterable[str],
    *,
    marble_diameter_cm: float = 1.6,
    tolerance_cm: float = 0.05,
) -> tuple[str, ...]:
    """Solids standing in the way of a marble rolling along a reached rail.

    For every rail the marble reaches, the space just above the groove
    between the first and last reached point must be free. A block standing
    on a hole the marble rolls over, for example, blocks the path.
    """
    # Per stretch: a pivot rail (collector or seesaw) has one on each side.
    reached: dict[tuple[str, int], list[float]] = {}
    rails = layout.rail_map()
    for node in reachable_nodes:
        component, _, port = node.partition(":")
        rail = rails.get(component)
        if rail is None:
            continue
        spec = catalog.rails.get(rail.rail_type)
        if spec is None:
            continue
        local_x = _rail_node_local_x(port, spec)
        if local_x is None:
            continue
        sides = [0]
        if rail.flow_direction in ("to_hole", "from_hole") and rail.flow_hole is not None \
                and 0 <= rail.flow_hole < len(spec.holes_cm):
            pivot = spec.holes_cm[rail.flow_hole]
            sides = [s for s, keep in ((-1, local_x <= pivot + 1e-6), (1, local_x >= pivot - 1e-6)) if keep]
        for side in sides:
            reached.setdefault((rail.id, side), []).append(local_x)

    solids = component_solids(layout, catalog)
    # A block with side-entry notches (the natural-wood merge) standing on a
    # rail's drop hole takes the marble in and drops it through the hole:
    # it is not in the way of that rail's marble (user, 2026-10-27).
    parts = layout.part_map()
    entries: dict[str, set[str]] = {}
    for s in layout.supports:
        if s.upper_rail_id is not None or s.lower_rail_id not in rails or not s.stack_part_ids:
            continue
        lower = rails[s.lower_rail_id]
        if lower.hole_states.get(s.lower_hole_index) != "block_connected":
            continue
        first = parts.get(s.stack_part_ids[0])
        spec = catalog.part_spec(first.part_type) if first else None
        if spec and (spec.get("port_visualization") or {}).get("side_entry_notches"):
            entries.setdefault(lower.id, set()).add(first.id)
    reasons = []
    for (rail_id, _), xs in sorted(reached.items()):
        start, end = min(xs), max(xs)
        if end - start <= 0 or catalog.rails[rails[rail_id].rail_type].shape == "twist":
            continue  # the twist's path runs inside its own funnel
        corridor = marble_corridor(rails[rail_id], catalog, start, end, marble_diameter_cm)
        for solid in solids:
            if solid.id == rail_id or solid.id in entries.get(rail_id, ()):
                continue
            if any(penetration_cm(piece, solid) > tolerance_cm for piece in corridor):
                reasons.append(f"marble_path_blocked:{rail_id}:{solid.id}")
    return tuple(dict.fromkeys(reasons))
