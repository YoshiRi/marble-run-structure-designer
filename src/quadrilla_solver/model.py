from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians, sin
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import yaml

from .catalog import PartCatalog

if TYPE_CHECKING:
    from .catalog import RailSpec


@dataclass(frozen=True)
class PortRef:
    component_id: str
    port: str

    @property
    def key(self) -> str:
        return f"{self.component_id}:{self.port}"


@dataclass(frozen=True)
class PlacedPart:
    id: str
    part_type: str
    x_cm: float
    y_cm: float
    z_units: float
    rotation_deg: int = 0


@dataclass(frozen=True)
class PlacedRail:
    """
    Rail placement.

    x_cm/y_cm is end-A of the rail centerline.
    z_units is the bottom/support-plane elevation of the rail.
    yaw_deg is the travel direction at end A (continuous in plan view).
    turn ("left"/"right") is the side a curved rail first bends toward;
    ignored for straight rails.
    """

    id: str
    rail_type: str
    x_cm: float
    y_cm: float
    z_units: float
    yaw_deg: float = 0.0
    flow_direction: str = "a_to_b"
    hole_states: Mapping[int, str] = field(default_factory=dict)
    turn: str = "left"


@dataclass(frozen=True)
class SupportLink:
    """
    One vertical support column for an upper rail.

    stack_part_ids are ordered from bottom to top.

    If lower_rail_id is None, the stack starts at ground z=0.
    Otherwise it starts on top of lower_rail_id at lower_hole_index.

    upper_rail_id None marks a free-standing stack that carries no rail, e.g.
    the entry block standing on a twist's chute hole. It must stand on a
    lower rail.
    """

    upper_rail_id: str | None
    upper_hole_index: int | None
    stack_part_ids: tuple[str, ...]
    lower_rail_id: str | None = None
    lower_hole_index: int | None = None
    name: str = ""


@dataclass(frozen=True)
class RouteLink:
    source: PortRef
    target: PortRef
    bidirectional: bool = False


@dataclass(frozen=True)
class Layout:
    name: str
    rails: tuple[PlacedRail, ...] = ()
    parts: tuple[PlacedPart, ...] = ()
    supports: tuple[SupportLink, ...] = ()
    route_links: tuple[RouteLink, ...] = ()
    routing_options: Mapping[str, Any] = field(default_factory=dict)

    def rail_map(self) -> dict[str, PlacedRail]:
        return {x.id: x for x in self.rails}

    def part_map(self) -> dict[str, PlacedPart]:
        return {x.id: x for x in self.parts}

    def component_ids(self) -> set[str]:
        return {x.id for x in self.rails} | {x.id for x in self.parts}


def rail_local_to_world(
    rail: PlacedRail,
    local_x_cm: float,
) -> tuple[float, float]:
    theta = radians(rail.yaw_deg)
    return (
        rail.x_cm + local_x_cm * cos(theta),
        rail.y_cm + local_x_cm * sin(theta),
    )


def rail_pose(
    rail: PlacedRail,
    spec: "RailSpec",
    s_cm: float,
) -> tuple[float, float, float]:
    """(x, y, heading in radians) on the centerline, s_cm from end A.

    Negative s_cm extrapolates before end A along the first segment.
    """
    x, y, heading = rail.x_cm, rail.y_cm, radians(rail.yaw_deg)
    if spec.shape != "arc":
        return x + s_cm * cos(heading), y + s_cm * sin(heading), heading
    rail_sign = -1 if rail.turn == "right" else 1
    remaining = s_cm
    segments = spec.segments
    for index, (length, seg_sign) in enumerate(segments):
        last = index == len(segments) - 1
        step = remaining if (last or remaining < 0) else min(remaining, length)
        sign = rail_sign * seg_sign
        r = spec.radius_cm
        cx = x - sign * r * sin(heading)
        cy = y + sign * r * cos(heading)
        heading += sign * step / r
        x = cx + sign * r * sin(heading)
        y = cy - sign * r * cos(heading)
        remaining -= step
        if remaining <= 1e-9:
            break
    return x, y, heading


def rail_hole_world(
    rail: PlacedRail,
    catalog: PartCatalog,
    hole_index: int,
) -> tuple[float, float, float]:
    spec = catalog.rails[rail.rail_type]
    if not 0 <= hole_index < len(spec.holes_cm):
        raise IndexError(
            f"{rail.id}: hole index {hole_index} outside {rail.rail_type}"
        )
    x, y, _ = rail_pose(rail, spec, spec.holes_cm[hole_index])
    return x, y, rail.z_units + spec.hole_level(hole_index)


def rail_com_world(
    rail: PlacedRail,
    catalog: PartCatalog,
) -> tuple[float, float, float]:
    spec = catalog.rails[rail.rail_type]
    com = spec.com_cm if spec.com_cm is not None else spec.length_cm / 2.0
    x, y, _ = rail_pose(rail, spec, com)
    return x, y, rail.z_units + spec.height_units / 2.0


def part_com_world(
    part: PlacedPart,
    catalog: PartCatalog,
) -> tuple[float, float, float]:
    height = catalog.height_units(part.part_type) or 0
    return part.x_cm, part.y_cm, part.z_units + height / 2.0


def load_layout(path: str | Path) -> Layout:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")

    rails = tuple(
        PlacedRail(
            id=str(x["id"]),
            rail_type=str(x["rail_type"]),
            x_cm=float(x["x_cm"]),
            y_cm=float(x["y_cm"]),
            z_units=float(x["z_units"]),
            yaw_deg=float(x.get("yaw_deg", 0)),
            flow_direction=str(x.get("flow_direction", "a_to_b")),
            hole_states={
                int(k): str(v)
                for k, v in (x.get("hole_states", {}) or {}).items()
            },
            turn=str(x.get("turn", "left")),
        )
        for x in data.get("rails", ())
    )

    parts = tuple(
        PlacedPart(
            id=str(x["id"]),
            part_type=str(x["part_type"]),
            x_cm=float(x["x_cm"]),
            y_cm=float(x["y_cm"]),
            z_units=float(x["z_units"]),
            rotation_deg=int(x.get("rotation_deg", 0)),
        )
        for x in data.get("parts", ())
    )

    supports = tuple(
        SupportLink(
            upper_rail_id=(
                str(x["upper_rail_id"]) if x.get("upper_rail_id") is not None else None
            ),
            upper_hole_index=(
                int(x["upper_hole_index"]) if x.get("upper_hole_index") is not None else None
            ),
            stack_part_ids=tuple(str(v) for v in x.get("stack_part_ids", ())),
            lower_rail_id=(
                str(x["lower_rail_id"])
                if x.get("lower_rail_id") is not None
                else None
            ),
            lower_hole_index=(
                int(x["lower_hole_index"])
                if x.get("lower_hole_index") is not None
                else None
            ),
            name=str(x.get("name", "")),
        )
        for x in data.get("supports", ())
    )

    route_links = tuple(
        RouteLink(
            source=PortRef(
                component_id=str(x["source"]["component_id"]),
                port=str(x["source"]["port"]),
            ),
            target=PortRef(
                component_id=str(x["target"]["component_id"]),
                port=str(x["target"]["port"]),
            ),
            bidirectional=bool(x.get("bidirectional", False)),
        )
        for x in data.get("route_links", ())
    )

    return Layout(
        name=str(data.get("name", path.stem)),
        rails=rails,
        parts=parts,
        supports=supports,
        route_links=route_links,
        routing_options=dict(data.get("routing_options", {}) or {}),
    )
