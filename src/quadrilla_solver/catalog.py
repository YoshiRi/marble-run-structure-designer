from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class RailSpec:
    """A rail measured along its centerline.

    Straight rails have shape "straight". Curved rails ("arc") follow
    `segments`: (length_cm, turn sign) pieces of a circle of `radius_cm`,
    sign +1 bending toward the placement's `turn`, -1 the other way.
    `holes_cm` are positions along the centerline from end A.
    """

    name: str
    length_cm: float
    holes_cm: tuple[float, ...]
    height_units: int = 1
    mass_g: float | None = None
    shape: str = "straight"
    radius_cm: float | None = None
    segments: tuple[tuple[float, int], ...] = ()
    needs_load_above: bool = False
    # Mount level of each hole relative to the rail's z_units (the twist's
    # chute hole sits 3 units above its center hole). Empty means all 0.
    hole_levels: tuple[int, ...] = ()
    com_cm: float | None = None

    def hole_level(self, index: int) -> int:
        return self.hole_levels[index] if self.hole_levels else 0

    def end_level(self, port: str) -> int:
        if not self.hole_levels:
            return 0
        return self.hole_levels[0] if port == "end_a" else self.hole_levels[-1]


@dataclass(frozen=True)
class SetInventory:
    set_id: str
    standard_blocks: int
    thin_blocks: int
    foundations: int
    straight_rails: int
    source_path: Path


@dataclass(frozen=True)
class PartCatalog:
    raw: Mapping[str, Any]
    rails: Mapping[str, RailSpec]

    def _find_part(self, part_type: str) -> tuple[str, Mapping[str, Any]] | None:
        for category in ("routing_blocks", "structural_parts", "special_parts"):
            group = self.raw.get(category, {})
            if isinstance(group, Mapping) and part_type in group:
                spec = group[part_type]
                if isinstance(spec, Mapping):
                    return category, spec

        accessories = self.raw.get("accessories", {})
        if isinstance(accessories, Mapping):
            for subcategory in ("routing_affecting", "non_routing"):
                group = accessories.get(subcategory, {})
                if isinstance(group, Mapping) and part_type in group:
                    spec = group[part_type]
                    if isinstance(spec, Mapping):
                        return f"accessories.{subcategory}", spec
        return None

    def has_part(self, part_type: str) -> bool:
        return part_type in self.rails or self._find_part(part_type) is not None

    def category(self, part_type: str) -> str | None:
        if part_type in self.rails:
            return "rails"
        found = self._find_part(part_type)
        return found[0] if found else None

    def part_spec(self, part_type: str) -> Mapping[str, Any] | None:
        found = self._find_part(part_type)
        return found[1] if found else None

    def height_units(self, part_type: str) -> int | None:
        if part_type in self.rails:
            return self.rails[part_type].height_units
        spec = self.part_spec(part_type)
        if spec is None:
            return None
        value = spec.get("height")
        return int(value) if value is not None else None

    def mass_g(self, part_type: str) -> float | None:
        if part_type in self.rails:
            return self.rails[part_type].mass_g

        found = self._find_part(part_type)
        if found is None:
            return None
        category, spec = found
        measured = _mass_value(dict(spec))
        if measured is not None:
            return measured

        if category == "routing_blocks" and int(spec.get("height", 0)) == self.standard_block_units():
            default_raw = (
                self.raw.get("mass_defaults", {})
                .get("standard_routing_block_g", {})
            )
            if isinstance(default_raw, (int, float)):
                return float(default_raw)
            if isinstance(default_raw, Mapping) and default_raw.get("value") is not None:
                return float(default_raw["value"])
        return None

    def standard_block_units(self) -> int:
        """Levels per standard block (5: 1 level = 1.2 cm, a block 6 cm)."""
        value = (self.raw.get("height_units") or {}).get("standard_block", 5)
        return int(value.get("value") if isinstance(value, Mapping) else value)

    def allowed_rotations(self, part_type: str) -> tuple[int, ...] | None:
        """Allowed rotations, or None when any angle is allowed."""
        spec = self.part_spec(part_type)
        if spec is None:
            return None
        rotations = spec.get("rotations_deg")
        if rotations is None or rotations == "any":
            return None
        return tuple(int(v) % 360 for v in rotations)

    def internal_routes(self, part_type: str) -> tuple[tuple[str, str], ...]:
        spec = self.part_spec(part_type)
        if spec is None:
            return ()
        result: list[tuple[str, str]] = []
        for route in spec.get("routes", ()) or ():
            if not isinstance(route, Mapping):
                continue
            source = route.get("from")
            if source is None:
                continue
            if route.get("to") is not None:
                result.append((str(source), str(route["to"])))
            for target in route.get("to_any_of", ()) or ():
                result.append((str(source), str(target)))
        return tuple(result)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


def _mass_value(spec: dict[str, Any]) -> float | None:
    raw = spec.get("mass_g")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict) and raw.get("value") is not None:
        return float(raw["value"])
    return None


def load_routing_block_masses(parts_path: str | Path) -> dict[str, float | None]:
    catalog = load_catalog(parts_path)
    blocks = catalog.raw.get("routing_blocks", {})
    return {
        name: catalog.mass_g(name)
        for name in blocks
        if isinstance(name, str)
    }


def load_rail_specs(parts_path: str | Path) -> dict[str, RailSpec]:
    data = _load_yaml(Path(parts_path))
    rails = data.get("rails", {})
    result: dict[str, RailSpec] = {}
    for name, spec in (data.get("special_rails") or {}).items():
        if not isinstance(spec, dict) or spec.get("shape") != "twist":
            continue
        result[name] = RailSpec(
            name=name,
            length_cm=float(spec["centerline_length_cm"]),
            holes_cm=tuple(float(x) for x in spec["hole_positions_cm"]),
            height_units=int(spec.get("height", 1)),
            mass_g=_mass_value(spec),
            shape="twist",
            hole_levels=tuple(int(v) for v in spec.get("hole_mount_levels_units", ())),
            com_cm=float(spec["com_cm"]) if spec.get("com_cm") is not None else None,
        )
    for name, spec in (data.get("curved_rails") or {}).items():
        if not isinstance(spec, dict):
            continue
        radius = spec.get("hole_circle_radius_cm")
        radius = float(radius.get("value") if isinstance(radius, dict) else radius)
        length = float(spec["centerline_length_cm"])
        if spec.get("segments"):
            segments = tuple(
                (float(seg["length_cm"]), -1 if seg.get("turn") == "opposite" else 1)
                for seg in spec["segments"]
            )
        else:
            segments = ((length, 1),)
        result[name] = RailSpec(
            name=name,
            length_cm=length,
            holes_cm=tuple(float(x) for x in spec["hole_arc_positions_cm"]),
            height_units=int(spec.get("height", 1)),
            mass_g=_mass_value(spec),
            shape="arc",
            radius_cm=radius,
            segments=segments,
            needs_load_above=spec.get("stability") == "needs_load_above",
        )
    for name, spec in rails.items():
        if not isinstance(spec, dict):
            continue
        length = spec.get("length_cm")
        holes = spec.get("hole_positions_cm")
        if length is None or holes is None:
            continue
        result[name] = RailSpec(
            name=name,
            length_cm=float(length),
            holes_cm=tuple(float(x) for x in holes),
            height_units=int(spec.get("height", 1)),
            mass_g=_mass_value(spec),
        )
    return result


def load_catalog(parts_path: str | Path) -> PartCatalog:
    path = Path(parts_path)
    raw = _load_yaml(path)
    return PartCatalog(raw=raw, rails=load_rail_specs(path))


def load_set_inventory(path: str | Path) -> SetInventory:
    path = Path(path)
    data = _load_yaml(path)
    contents = data.get("contents", {})
    set_meta = data.get("set", {})

    standard_blocks = int(
        contents.get(
            "routing_blocks_total",
            sum(
                int(v)
                for v in contents.get("routing_blocks", {}).values()
                if isinstance(v, int)
            ),
        )
    )

    thin = contents.get("thin_and_structural_blocks", {})
    thin_blocks = int(thin.get("purple_drop", 0) or 0)
    foundations = int(thin.get("wooden_foundation", 0) or 0)

    straight_rails = 0
    for name, value in contents.get("rails", {}).items():
        if not name.startswith("straight_"):
            continue
        if isinstance(value, int):
            straight_rails += value
        elif isinstance(value, dict):
            straight_rails += int(value.get("count", 0) or 0)

    return SetInventory(
        set_id=str(set_meta.get("id", path.stem)),
        standard_blocks=standard_blocks,
        thin_blocks=thin_blocks,
        foundations=foundations,
        straight_rails=straight_rails,
        source_path=path,
    )
