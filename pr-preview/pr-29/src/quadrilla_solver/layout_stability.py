from __future__ import annotations

from dataclasses import replace, dataclass
from math import hypot
from typing import Iterable

from .catalog import PartCatalog
from .model import Layout, part_com_world, rail_com_world, rail_hole_world
from .statics import PointMass, RailBody, StructureStatics, SupportConnection, analyze_structure


@dataclass(frozen=True)
class GlobalStabilityResult:
    evaluable: bool
    stable: bool
    total_mass_g: float
    com_xyz_cm: tuple[float, float, float] | None
    support_polygon_xy_cm: tuple[tuple[float, float], ...]
    margin_cm: float | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LayoutStaticsResult:
    evaluable: bool
    statics: StructureStatics | None
    reasons: tuple[str, ...] = ()


def _cross(
    o: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(
    points: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return tuple(pts)

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return tuple(lower[:-1] + upper[:-1])


def _distance_point_segment(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = p[0] - a[0], p[1] - a[1]
    vv = vx * vx + vy * vy
    if vv <= 1e-18:
        return hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    qx, qy = a[0] + t * vx, a[1] + t * vy
    return hypot(p[0] - qx, p[1] - qy)


def _support_margin(
    point: tuple[float, float],
    hull: tuple[tuple[float, float], ...],
    tolerance_cm: float,
) -> tuple[bool, float]:
    if not hull:
        return False, float("-inf")

    if len(hull) == 1:
        d = hypot(point[0] - hull[0][0], point[1] - hull[0][1])
        return d <= tolerance_cm, 0.0 if d <= tolerance_cm else -d

    if len(hull) == 2:
        d = _distance_point_segment(point, hull[0], hull[1])
        return d <= tolerance_cm, 0.0 if d <= tolerance_cm else -d

    # Monotonic-chain hull is CCW. Signed perpendicular distance to every
    # boundary edge is positive inside, zero on the edge, negative outside.
    margins: list[float] = []
    for i, a in enumerate(hull):
        b = hull[(i + 1) % len(hull)]
        edge_len = hypot(b[0] - a[0], b[1] - a[1])
        if edge_len <= 1e-18:
            continue
        margins.append(_cross(a, b, point) / edge_len)

    margin = min(margins) if margins else float("-inf")
    return margin >= -tolerance_cm, margin


def analyze_global_stability(
    layout: Layout,
    catalog: PartCatalog,
    *,
    tolerance_cm: float = 1e-6,
) -> GlobalStabilityResult:
    """
    Compute global 3D center of mass and compare its XY projection with the
    convex hull of ground support points.

    This is a global tipping check. It complements, rather than replaces, the
    per-rail recursive reaction calculation.
    """

    weighted_x = weighted_y = weighted_z = 0.0
    total_mass = 0.0
    reasons: list[str] = []

    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is None:
            reasons.append(f"unknown_rail:{rail.id}:{rail.rail_type}")
            continue
        if spec.mass_g is None:
            reasons.append(f"unknown_mass:{rail.id}:{rail.rail_type}")
            continue
        x, y, z = rail_com_world(rail, catalog)
        total_mass += spec.mass_g
        weighted_x += spec.mass_g * x
        weighted_y += spec.mass_g * y
        weighted_z += spec.mass_g * z

    for part in layout.parts:
        mass = catalog.mass_g(part.part_type)
        if mass is None:
            reasons.append(f"unknown_mass:{part.id}:{part.part_type}")
            continue
        x, y, z = part_com_world(part, catalog)
        total_mass += mass
        weighted_x += mass * x
        weighted_y += mass * y
        weighted_z += mass * z

    ground_points: list[tuple[float, float]] = []
    rails = layout.rail_map()
    for support in layout.supports:
        if support.lower_rail_id is not None:
            continue
        upper = rails.get(support.upper_rail_id)
        if upper is None or upper.rail_type not in catalog.rails:
            continue
        try:
            x, y, _ = rail_hole_world(
                upper, catalog, support.upper_hole_index
            )
        except IndexError:
            continue
        ground_points.append((x, y))

    hull = convex_hull(ground_points)

    if total_mass <= 0:
        reasons.append("no_known_mass")
        return GlobalStabilityResult(
            evaluable=False,
            stable=False,
            total_mass_g=0.0,
            com_xyz_cm=None,
            support_polygon_xy_cm=hull,
            margin_cm=None,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    com = (
        weighted_x / total_mass,
        weighted_y / total_mass,
        weighted_z / total_mass,
    )

    if not hull:
        reasons.append("no_ground_support_points")

    unknown_mass = any(x.startswith("unknown_mass:") for x in reasons)
    if unknown_mass or not hull:
        return GlobalStabilityResult(
            evaluable=False,
            stable=False,
            total_mass_g=total_mass,
            com_xyz_cm=com,
            support_polygon_xy_cm=hull,
            margin_cm=None,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    stable, margin = _support_margin((com[0], com[1]), hull, tolerance_cm)
    if not stable:
        reasons.append(
            f"global_tipping:com=({com[0]:.6g},{com[1]:.6g})"
        )

    return GlobalStabilityResult(
        evaluable=True,
        stable=stable,
        total_mass_g=total_mass,
        com_xyz_cm=com,
        support_polygon_xy_cm=hull,
        margin_cm=margin,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def analyze_layout_statics(
    layout: Layout,
    catalog: PartCatalog,
) -> LayoutStaticsResult:
    """
    Convert a Layout support graph into the existing 1D recursive rail statics
    model. Exactly two support links per rail are required by this MVP helper.
    """

    rails = layout.rail_map()
    parts = layout.part_map()
    by_upper: dict[str, list] = {rail.id: [] for rail in layout.rails}
    reasons: list[str] = []

    for support in layout.supports:
        if support.upper_rail_id in by_upper:
            by_upper[support.upper_rail_id].append(support)

    # A free-standing stack (it holds up no rail) is a point load on the rail
    # it stands on, e.g. the input block or a twist's entry block.
    point_masses: dict[str, list[PointMass]] = {rail.id: [] for rail in layout.rails}
    for i, support in enumerate(layout.supports):
        if support.upper_rail_id is not None or support.lower_rail_id not in point_masses:
            continue
        lower = rails[support.lower_rail_id]
        lower_spec = catalog.rails.get(lower.rail_type)
        hole = support.lower_hole_index
        if lower_spec is None or hole is None or not 0 <= hole < len(lower_spec.holes_cm):
            continue
        masses = [catalog.mass_g(parts[pid].part_type) for pid in support.stack_part_ids if pid in parts]
        if any(m is None for m in masses):
            reasons.append(f"unknown_mass:{support.name or f'support_{i}'}")
            continue
        point_masses[lower.id].append(
            PointMass(support.name or f"free_stack_{i}", lower_spec.holes_cm[hole], float(sum(masses))))

    bodies: dict[str, RailBody] = {}
    extra_masses: dict[str, list[PointMass]] = {}

    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is None:
            reasons.append(f"unknown_rail:{rail.id}:{rail.rail_type}")
            continue
        if spec.mass_g is None:
            reasons.append(f"unknown_mass:{rail.id}:{rail.rail_type}")
            continue

        supports = by_upper.get(rail.id, [])
        if len(supports) < 2:
            reasons.append(
                f"statics_needs_two_supports:{rail.id}:{len(supports)}"
            )
            continue

        converted: list[SupportConnection] = []
        for idx, support in enumerate(supports):
            if not 0 <= support.upper_hole_index < len(spec.holes_cm):
                reasons.append(
                    f"invalid_upper_hole:{rail.id}:{support.upper_hole_index}"
                )
                continue

            transfer_mass = 0.0
            mass_known = True
            for part_id in support.stack_part_ids:
                part = parts.get(part_id)
                if part is None:
                    reasons.append(
                        f"unknown_stack_part:{rail.id}:{part_id}"
                    )
                    mass_known = False
                    continue
                mass = catalog.mass_g(part.part_type)
                if mass is None:
                    reasons.append(
                        f"unknown_mass:{part.id}:{part.part_type}"
                    )
                    mass_known = False
                    continue
                transfer_mass += mass

            if not mass_known:
                continue

            target_x = None
            if support.lower_rail_id is not None:
                lower = rails.get(support.lower_rail_id)
                if lower is None:
                    reasons.append(
                        f"unknown_lower_rail:{rail.id}:{support.lower_rail_id}"
                    )
                    continue
                lower_spec = catalog.rails.get(lower.rail_type)
                if (
                    lower_spec is None
                    or support.lower_hole_index is None
                    or not 0 <= support.lower_hole_index < len(lower_spec.holes_cm)
                ):
                    reasons.append(
                        f"invalid_lower_hole:{rail.id}:{support.lower_rail_id}"
                    )
                    continue
                target_x = lower_spec.holes_cm[support.lower_hole_index]

            converted.append(
                SupportConnection(
                    x_cm=spec.holes_cm[support.upper_hole_index],
                    target_id=support.lower_rail_id,
                    target_x_cm=target_x,
                    transfer_mass_g=transfer_mass,
                    name=support.name or f"{rail.id}_support_{idx}",
                )
            )

        if len(converted) > 2 and len(converted) == len(supports):
            # More than two columns (e.g. a collector held at both ends and at
            # its center drop column): tipping is checked on the outermost two,
            # which is conservative (a middle column only helps). A middle
            # column's own weight still goes down to the rail it stands on.
            ordered = sorted(converted, key=lambda c: c.x_cm)
            for middle in ordered[1:-1]:
                if middle.target_id is not None:
                    extra_masses.setdefault(middle.target_id, []).append(
                        PointMass(middle.name, middle.target_x_cm, middle.transfer_mass_g))
            converted = [ordered[0], ordered[-1]]
        if len(converted) == 2:
            bodies[rail.id] = RailBody(
                id=rail.id,
                length_cm=spec.length_cm,
                mass_g=spec.mass_g,
                supports=(converted[0], converted[1]),
                com_cm=spec.com_cm,
                point_masses=tuple(point_masses.get(rail.id, ())),
            )

    for target, masses in extra_masses.items():
        if target in bodies:
            body = bodies[target]
            bodies[target] = replace(body, point_masses=body.point_masses + tuple(masses))

    if reasons or len(bodies) != len(layout.rails):
        return LayoutStaticsResult(
            evaluable=False,
            statics=None,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    return LayoutStaticsResult(
        evaluable=True,
        statics=analyze_structure(bodies),
        reasons=(),
    )
