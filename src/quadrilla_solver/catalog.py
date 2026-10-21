from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RailSpec:
    name: str
    length_cm: float
    holes_cm: tuple[float, ...]
    height_units: int = 1
    mass_g: float | None = None


@dataclass(frozen=True)
class SetInventory:
    set_id: str
    standard_blocks: int
    thin_blocks: int
    foundations: int
    straight_rails: int
    source_path: Path


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
    data = _load_yaml(Path(parts_path))
    blocks = data.get("routing_blocks", {})
    default_raw = (
        data.get("mass_defaults", {})
        .get("standard_routing_block_g", {})
    )
    default_mass: float | None = None
    if isinstance(default_raw, (int, float)):
        default_mass = float(default_raw)
    elif isinstance(default_raw, dict) and default_raw.get("value") is not None:
        default_mass = float(default_raw["value"])

    result: dict[str, float | None] = {}
    for name, spec in blocks.items():
        if not isinstance(spec, dict):
            result[name] = None
            continue
        measured = _mass_value(spec)
        if measured is not None:
            result[name] = measured
            continue

        # Temporary 55 g fallback applies only to unmeasured standard-height
        # routing blocks, not thin blocks or unrelated accessories.
        if int(spec.get("height", 0)) == 4:
            result[name] = default_mass
        else:
            result[name] = None
    return result


def load_rail_specs(parts_path: str | Path) -> dict[str, RailSpec]:
    data = _load_yaml(Path(parts_path))
    rails = data.get("rails", {})
    result: dict[str, RailSpec] = {}
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

    # Height optimization intentionally uses only straight rails whose structural
    # behavior is represented by the MVP solver. Curves and spirals are deferred.
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
