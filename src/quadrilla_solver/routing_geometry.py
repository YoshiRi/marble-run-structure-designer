"""Conservative physical port alignment for directed routing links.

Port positions are based on the same catalog dimensions and conventions as the
schematic 3D viewer. This validates openings and mating surfaces, NOT hidden
internal channel geometry or real marble dynamics.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, radians, sin, sqrt

from .catalog import PartCatalog
from .model import Layout, PortRef, RouteLink, rail_pose


@dataclass(frozen=True)
class PortPose:
    position_cm: tuple[float, float, float]
    outward: tuple[float, float, float]


def _dimension(catalog: PartCatalog, key: str, fallback: float) -> float:
    value = catalog.raw.get("geometry_cm", {}).get(key, fallback)
    if isinstance(value, dict):
        value = value.get("value", fallback)
    return float(value)


def port_pose(layout: Layout, catalog: PartCatalog, ref: PortRef) -> PortPose | None:
    """World XYZ pose of a *real catalogued opening* (cm, Z vertical)."""
    height_scale = _dimension(catalog, "height_unit", 1.5)
    rail = layout.rail_map().get(ref.component_id)
    if rail is not None:
        spec = catalog.rails.get(rail.rail_type)
        if spec is None or ref.port not in ("end_a", "end_b"):
            return None
        local_x = 0.0 if ref.port == "end_a" else spec.length_cm
        x, y, angle = rail_pose(rail, spec, local_x)
        direction = -1.0 if ref.port == "end_a" else 1.0
        return PortPose(
            (x, y, (rail.z_units + spec.height_units) * height_scale),
            (direction * cos(angle), direction * sin(angle), 0.0),
        )

    part = layout.part_map().get(ref.component_id)
    if part is None:
        return None
    spec = catalog.part_spec(part.part_type)
    if spec is None or ref.port not in (spec.get("ports") or ()):
        return None
    height_units = catalog.height_units(part.part_type)
    if height_units is None:
        return None

    width = 4.5
    depth = 4.5
    footprint = catalog.raw.get("geometry_cm", {}).get("standard_block_footprint", {})
    if isinstance(footprint, dict):
        width = float(footprint.get("width_cm", 4.5))
        depth = float(footprint.get("depth_cm", 4.5))
    body_height = spec.get("body_height_cm")
    if isinstance(body_height, dict):
        body_height = body_height.get("value")
    h = float(body_height) if body_height is not None else height_units * height_scale
    # Centered side holes open with their floor one height unit above the
    # block's installation level: exactly the groove height of a rail laid
    # at that same level (physically confirmed). Side-entry notches feeding
    # a downward route open at the installation level itself.
    side_z = min(height_scale, h)
    if ref.port in (spec.get("port_visualization", {}).get("side_entry_notches") or ()):
        side_z = 0.0
    local = {
        "top": (0.0, 0.0, h, (0.0, 0.0, 1.0)),
        "bottom": (0.0, 0.0, 0.0, (0.0, 0.0, -1.0)),
        "front": (0.0, depth / 2, side_z, (0.0, 1.0, 0.0)),
        "rear": (0.0, -depth / 2, side_z, (0.0, -1.0, 0.0)),
        "right": (width / 2, 0.0, side_z, (1.0, 0.0, 0.0)),
        "left": (-width / 2, 0.0, side_z, (-1.0, 0.0, 0.0)),
    }.get(ref.port)
    if local is None:
        return None
    lx, ly, lz, normal = local
    angle = radians(part.rotation_deg)
    c, s = cos(angle), sin(angle)
    return PortPose(
        (part.x_cm + lx * c - ly * s,
         part.y_cm + lx * s + ly * c,
         part.z_units * height_scale + lz),
        (normal[0] * c - normal[1] * s,
         normal[0] * s + normal[1] * c,
         normal[2]),
    )


def _supports_flow(
    layout: Layout, catalog: PartCatalog, ref: PortRef, *, output: bool
) -> bool:
    rail = layout.rail_map().get(ref.component_id)
    if rail is not None:
        downstream = "end_b" if rail.flow_direction == "a_to_b" else "end_a"
        upstream = "end_a" if rail.flow_direction == "a_to_b" else "end_b"
        return ref.port == (downstream if output else upstream)
    part = layout.part_map().get(ref.component_id)
    if part is None:
        return False
    spec = catalog.part_spec(part.part_type)
    if spec is None:
        return False
    for route in spec.get("routes", ()) or ():
        if output and ref.port in (
            ([route["to"]] if route.get("to") is not None else [])
            + list(route.get("to_any_of", ()) or ())
        ):
            return True
        if not output and route.get("from") == ref.port:
            return True
    return False


def _allows_side_entry_plus_one(
    layout: Layout,
    catalog: PartCatalog,
    source: PortRef,
    target: PortRef,
    source_pose: PortPose,
    target_pose: PortPose,
    *,
    position_tolerance_cm: float,
    opposite_normal_dot_max: float,
) -> bool:
    """Allow a rail groove one height unit above an open-bottom side inlet."""
    if not layout.routing_options.get("allow_side_entry_plus_one", False):
        return False

    rail = layout.rail_map().get(source.component_id)
    if rail is None or source.port not in ("end_a", "end_b"):
        return False
    part = layout.part_map().get(target.component_id)
    if part is None:
        return False
    spec = catalog.part_spec(part.part_type)
    if spec is None:
        return False
    side_notches = spec.get("port_visualization", {}).get("side_entry_notches") or ()
    if target.port not in side_notches:
        return False

    dx = source_pose.position_cm[0] - target_pose.position_cm[0]
    dy = source_pose.position_cm[1] - target_pose.position_cm[1]
    vertical_gap = source_pose.position_cm[2] - target_pose.position_cm[2]
    normal_dot = sum(x * y for x, y in zip(source_pose.outward, target_pose.outward))
    height_unit_cm = _dimension(catalog, "height_unit", 1.5)
    return (
        hypot(dx, dy) <= position_tolerance_cm
        and abs(vertical_gap - height_unit_cm) <= position_tolerance_cm
        and normal_dot <= opposite_normal_dot_max
    )


def _allows_side_exit_drop_one(
    layout: Layout,
    catalog: PartCatalog,
    source: PortRef,
    target: PortRef,
    source_pose: PortPose,
    target_pose: PortPose,
    *,
    position_tolerance_cm: float,
    opposite_normal_dot_max: float,
) -> bool:
    """Allow a centered side outlet to drop one unit onto a rail groove.

    A centered side hole sits at installation level +1, but the marble can
    also roll straight out onto a rail whose groove is at the block's
    installation level (physically confirmed), i.e. one unit lower.
    """
    part = layout.part_map().get(source.component_id)
    if part is None or source.port not in ("front", "rear", "left", "right"):
        return False
    spec = catalog.part_spec(part.part_type)
    if spec is None:
        return False
    if source.port in (spec.get("port_visualization", {}).get("side_entry_notches") or ()):
        return False
    rail = layout.rail_map().get(target.component_id)
    if rail is None or target.port not in ("end_a", "end_b"):
        return False

    dx = source_pose.position_cm[0] - target_pose.position_cm[0]
    dy = source_pose.position_cm[1] - target_pose.position_cm[1]
    drop = source_pose.position_cm[2] - target_pose.position_cm[2]
    normal_dot = sum(x * y for x, y in zip(source_pose.outward, target_pose.outward))
    height_unit_cm = _dimension(catalog, "height_unit", 1.5)
    return (
        hypot(dx, dy) <= position_tolerance_cm
        and abs(drop - height_unit_cm) <= position_tolerance_cm
        and normal_dot <= opposite_normal_dot_max
    )


def validate_route_link_geometry(
    layout: Layout,
    catalog: PartCatalog,
    link: RouteLink,
    *,
    position_tolerance_cm: float = 0.35,
    opposite_normal_dot_max: float = -0.95,
) -> str | None:
    """Return a reason and reject a link unless its two ports physically mate."""
    source, target = link.source, link.target
    label = f"{source.key}:{target.key}"
    a = port_pose(layout, catalog, source)
    b = port_pose(layout, catalog, target)
    if a is None or b is None:
        return f"route_link_unsupported_port:{label}"

    def valid_direction(s: PortRef, t: PortRef) -> bool:
        return (
            _supports_flow(layout, catalog, s, output=True)
            and _supports_flow(layout, catalog, t, output=False)
        )

    if not valid_direction(source, target) or (
        link.bidirectional and not valid_direction(target, source)
    ):
        return f"route_link_invalid_direction:{label}"
    distance = sqrt(sum((x - y) ** 2 for x, y in zip(a.position_cm, b.position_cm)))
    normal_dot = sum(x * y for x, y in zip(a.outward, b.outward))
    if distance > position_tolerance_cm or normal_dot > opposite_normal_dot_max:
        tolerances = dict(
            position_tolerance_cm=position_tolerance_cm,
            opposite_normal_dot_max=opposite_normal_dot_max,
        )
        if not (
            _allows_side_entry_plus_one(layout, catalog, source, target, a, b, **tolerances)
            or _allows_side_exit_drop_one(layout, catalog, source, target, a, b, **tolerances)
        ):
            return f"route_link_geometry_mismatch:{label}"
    return None
