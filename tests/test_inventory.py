from dataclasses import replace
from pathlib import Path

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.inventory import (
    Inventory,
    layout_usage,
    load_inventory,
    validate_inventory,
)
from quadrilla_solver.model import PlacedPart, PlacedRail, load_layout
from quadrilla_solver.validation import validate_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")


def _example():
    return load_layout(ROOT / "tests" / "fixtures" / "two-level-supported.yaml")


def test_layout_usage_counts_parts_and_rails():
    usage = layout_usage(_example())
    assert usage == {
        "blue": 1,
        "green": 1,
        "straight_long_center": 1,
        "straight_short": 1,
        "wooden_foundation": 2,
    }


def test_speedway_preset_rejects_missing_short_rail():
    inv = load_inventory(ROOT / "catalog" / "sets" / "speedway-qd101.yaml")
    result = validate_inventory(_example(), inv)

    assert not result.valid
    assert not result.evaluable
    assert "inventory_part_unlisted:straight_short" in result.reasons


def test_long_center_consumes_long_pool_when_preset_does_not_split_variant():
    layout = replace(
        _example(),
        rails=tuple(x for x in _example().rails if x.id == "lower"),
        parts=tuple(
            x for x in _example().parts
            if x.id in {"foundation_left", "foundation_right"}
        ),
        supports=tuple(
            x for x in _example().supports
            if x.upper_rail_id == "lower"
        ),
        route_links=(),
    )
    inv = load_inventory(ROOT / "catalog" / "sets" / "speedway-qd101.yaml")
    result = validate_inventory(layout, inv)

    assert result.valid
    assert result.consumption["straight_long_center"] == "straight_long"
    assert result.used["straight_long"] == 1
    assert result.remaining["straight_long"] == 1


def test_exact_center_variant_count_wins_over_fallback_pool():
    inv = Inventory(
        name="manual",
        counts={
            "straight_long": 10,
            "straight_long_center": 1,
            "wooden_foundation": 2,
        },
    )
    layout = replace(
        _example(),
        rails=tuple(x for x in _example().rails if x.id == "lower"),
        parts=tuple(
            x for x in _example().parts
            if x.id in {"foundation_left", "foundation_right"}
        ),
        supports=tuple(
            x for x in _example().supports
            if x.upper_rail_id == "lower"
        ),
        route_links=(),
    )

    result = validate_inventory(layout, inv)
    assert result.valid
    assert result.consumption["straight_long_center"] == "straight_long_center"
    assert result.remaining["straight_long_center"] == 0
    assert result.remaining["straight_long"] == 10


def test_inventory_exceeded_is_reported():
    layout = replace(
        _example(),
        parts=_example().parts
        + (
            PlacedPart("extra_blue_1", "blue", 0, 0, 0),
            PlacedPart("extra_blue_2", "blue", 0, 0, 0),
        ),
    )
    inv = load_inventory(ROOT / "catalog" / "sets" / "speedway-qd101.yaml")
    result = validate_inventory(layout, inv)

    assert not result.valid
    assert any(
        x == "inventory_exceeded:blue:used=3:available=2"
        for x in result.reasons
    )


def test_unknown_owned_count_is_not_treated_as_unlimited():
    owned = load_inventory(ROOT / "catalog" / "inventory.yaml")
    inv = Inventory(name="partly counted",
                    counts={**owned.counts, "wooden_foundation": None})
    result = validate_inventory(_example(), inv)

    assert not result.valid
    assert not result.evaluable
    assert any(x.startswith("inventory_count_unknown:") for x in result.reasons)


def test_combined_validation_can_apply_inventory_constraint():
    base = _example()
    inv = Inventory(
        name="enough",
        counts={
            "straight_long_center": 1,
            "straight_short": 1,
            "wooden_foundation": 2,
            "blue": 1,
            "green": 1,
        },
    )
    result = validate_layout(base, CATALOG, inventory=inv)

    assert result.inventory is not None
    assert result.inventory.valid
    assert result.valid


def test_owned_inventory_is_counted():
    inv = load_inventory(ROOT / "catalog" / "inventory.yaml")
    assert inv.counts["yellow"] == 14
    assert inv.counts["purple_drop"] == 39
    assert inv.counts["seesaw"] == 4
    assert inv.counts["straight_long_center"] == 3
    assert inv.counts["straight_long"] == 8
    assert inv.counts["straight_short"] == 2
    assert inv.counts["accelerator_plate"] == 19 and inv.counts["cover"] == 9
    assert "unmodeled" not in inv.counts and "plate_one_hole" not in inv.counts
