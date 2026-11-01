from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .model import Layout


# Product presets often do not distinguish a center-hole long rail from the
# general long-rail count. Prefer an exact inventory key when present; only
# fall back to these pools when the source inventory lacks the exact subtype.
_FALLBACK_POOLS: dict[str, tuple[str, ...]] = {
    "straight_long_center": ("straight_long",),
}


@dataclass(frozen=True)
class Inventory:
    name: str
    counts: Mapping[str, int | None]
    source_path: Path | None = None


@dataclass(frozen=True)
class InventoryResult:
    valid: bool
    evaluable: bool
    used: Mapping[str, int]
    available: Mapping[str, int | None]
    remaining: Mapping[str, int | None]
    consumption: Mapping[str, str]
    reasons: tuple[str, ...] = ()


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


def _count_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        raw = value.get("count")
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw
    return None


def _merge_count(
    out: dict[str, int | None],
    key: str,
    value: Any,
) -> None:
    count = _count_value(value)
    if key not in out:
        out[key] = count
        return

    # Multiple categories referring to one canonical part are additive only
    # when both values are known. Unknown remains unknown.
    current = out[key]
    if current is None or count is None:
        out[key] = None
    else:
        out[key] = current + count


def load_inventory(path: str | Path) -> Inventory:
    """
    Load either:
    - a commercial set preset (top-level 'contents'), or
    - the user's owned inventory (top-level 'parts').

    Aggregate metadata such as routing_blocks_total, marbles, and notes is not
    treated as a usable physical part count.
    """

    path = Path(path)
    data = _read_yaml(path)
    counts: dict[str, int | None] = {}

    if isinstance(data.get("contents"), Mapping):
        root = data["contents"]
        name = str(data.get("set", {}).get("id", path.stem))
        groups = (
            "routing_blocks",
            "rails",
            "thin_and_structural_blocks",
            "special_parts",
            "routing_accessories",
            "non_routing_accessories",
        )
    elif isinstance(data.get("parts"), Mapping):
        root = data["parts"]
        name = str(data.get("name", path.stem))
        # Support both the corrected taxonomy and the earlier inventory file.
        groups = (
            "routing_blocks",
            "rails",
            "thin_and_structural_blocks",
            "structural_parts",
            "special_parts",
            "routing_accessories",
            "non_routing_accessories",
            "routing_modifiers",
        )
    else:
        raise ValueError(
            f"{path} is neither a set preset nor an owned inventory"
        )

    for group_name in groups:
        group = root.get(group_name, {})
        if not isinstance(group, Mapping):
            continue
        for part_type, value in group.items():
            if group_name == "routing_modifiers" and part_type == "accelerator":
                part_type = "accelerator_plate"
            _merge_count(counts, str(part_type), value)

    return Inventory(name=name, counts=counts, source_path=path)


def layout_usage(layout: Layout) -> dict[str, int]:
    used = Counter[str]()
    for rail in layout.rails:
        used[rail.rail_type] += 1
    for part in layout.parts:
        used[part.part_type] += 1
    return dict(sorted(used.items()))


def _resolve_pool(
    part_type: str,
    available: Mapping[str, int | None],
) -> str | None:
    if part_type in available:
        return part_type
    for fallback in _FALLBACK_POOLS.get(part_type, ()):
        if fallback in available:
            return fallback
    return None


def validate_inventory(
    layout: Layout,
    inventory: Inventory,
) -> InventoryResult:
    raw_usage = layout_usage(layout)
    pooled_usage: Counter[str] = Counter()
    consumption: dict[str, str] = {}
    reasons: list[str] = []
    evaluable = True

    for part_type, count in raw_usage.items():
        pool = _resolve_pool(part_type, inventory.counts)
        if pool is None:
            evaluable = False
            reasons.append(f"inventory_part_unlisted:{part_type}")
            continue
        consumption[part_type] = pool
        pooled_usage[pool] += count

    remaining: dict[str, int | None] = dict(inventory.counts)

    for pool, used_count in pooled_usage.items():
        available_count = inventory.counts.get(pool)
        if available_count is None:
            evaluable = False
            remaining[pool] = None
            reasons.append(f"inventory_count_unknown:{pool}")
            continue

        left = available_count - used_count
        remaining[pool] = left
        if left < 0:
            reasons.append(
                f"inventory_exceeded:{pool}:used={used_count}:"
                f"available={available_count}"
            )

    exceeded = any(x.startswith("inventory_exceeded:") for x in reasons)

    return InventoryResult(
        valid=evaluable and not exceeded,
        evaluable=evaluable,
        used=dict(sorted(pooled_usage.items())),
        available=dict(sorted(inventory.counts.items())),
        remaining=dict(sorted(remaining.items())),
        consumption=dict(sorted(consumption.items())),
        reasons=tuple(dict.fromkeys(reasons)),
    )
