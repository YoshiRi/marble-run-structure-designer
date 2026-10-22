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
from math import cos, radians, sin
from typing import Iterable

from .catalog import PartCatalog
from .model import Layout, PlacedRail


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


def rail_solid(rail: PlacedRail, catalog: PartCatalog) -> Solid | None:
    spec = catalog.rails.get(rail.rail_type)
    if spec is None:
        return None
    unit = _geometry(catalog, "height_unit", 1.5)
    width = _geometry(catalog, "rail_width_cm", 4.5)
    theta = radians(rail.yaw_deg)
    half = spec.length_cm / 2.0
    return Solid(
        rail.id,
        (rail.x_cm + half * cos(theta), rail.y_cm + half * sin(theta)),
        (half, width / 2.0),
        theta,
        rail.z_units * unit,
        (rail.z_units + spec.height_units) * unit,
    )


def component_solids(layout: Layout, catalog: PartCatalog) -> list[Solid]:
    unit = _geometry(catalog, "height_unit", 1.5)
    width, depth = _block_footprint(catalog)
    solids: list[Solid] = []
    for rail in layout.rails:
        solid = rail_solid(rail, catalog)
        if solid is not None:
            solids.append(solid)
    for part in layout.parts:
        height = _part_body_height_cm(catalog, part.part_type, unit)
        if height is None:
            continue
        solids.append(Solid(
            part.id,
            (part.x_cm, part.y_cm),
            (width / 2.0, depth / 2.0),
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
        if penetration_cm(a, b) > tolerance_cm:
            first, second = sorted((a.id, b.id))
            reasons.append(f"solid_collision:{first}:{second}")
    return tuple(sorted(reasons))


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
    unit = _geometry(catalog, "height_unit", 1.5)
    reached: dict[str, list[float]] = {}
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
        if local_x is not None:
            reached.setdefault(rail.id, []).append(local_x)

    solids = component_solids(layout, catalog)
    reasons = []
    for rail_id, xs in sorted(reached.items()):
        start, end = min(xs), max(xs)
        if end - start <= 0:
            continue
        rail = rails[rail_id]
        spec = catalog.rails[rail.rail_type]
        theta = radians(rail.yaw_deg)
        mid = (start + end) / 2.0
        top = (rail.z_units + spec.height_units) * unit
        corridor = Solid(
            f"{rail_id}#marble",
            (rail.x_cm + mid * cos(theta), rail.y_cm + mid * sin(theta)),
            ((end - start) / 2.0, marble_diameter_cm / 2.0),
            theta,
            top,
            top + marble_diameter_cm,
        )
        for solid in solids:
            if solid.id == rail_id:
                continue
            if penetration_cm(corridor, solid) > tolerance_cm:
                reasons.append(f"marble_path_blocked:{rail_id}:{solid.id}")
    return tuple(reasons)
