from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .catalog import load_rail_specs, load_set_inventory
from .geometry import find_stacking_options, find_triangle
from .optimizer import maximize_straight_tower
from .stability import check_triangle_vertex_supports


def short_on_long(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    rails = load_rail_specs(root / "catalog" / "parts.yaml")
    short = rails["straight_short"]
    regular = rails["straight_long"]
    center = rails["straight_long_center"]

    regular_options = find_stacking_options(short, regular)
    center_options = find_stacking_options(short, center)

    return {
        "short_on_regular_long": {
            "assembly_possible": bool(regular_options),
            "stable_two_point_geometry": bool(regular_options),
            "options": [asdict(x) for x in regular_options],
        },
        "short_on_center_long": {
            "assembly_possible": bool(center_options),
            "stable_two_point_geometry": bool(center_options),
            "options": [asdict(x) for x in center_options],
        },
    }


def triangle_with_long_rails(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    rails = load_rail_specs(root / "catalog" / "parts.yaml")
    long_rail = rails["straight_long"]
    triangle = find_triangle((long_rail, long_rail, long_rail))
    if triangle is None:
        return {
            "plan_geometry_possible": False,
            "assembly_possible": None,
            "stability": None,
        }

    stability = check_triangle_vertex_supports((True, True, True))
    return {
        "plan_geometry_possible": True,
        "assembly_possible": None,
        "assembly_note": (
            "Plan-view closure is proven, but full stacked assembly still needs "
            "explicit joint-Z/overlap rules at triangle vertices."
        ),
        "solution": asdict(triangle),
        "stability_if_all_three_vertices_have_stable_downward_support": asdict(stability),
    }


def max_height_for_preset(repo_root: str | Path, relative_preset: str) -> dict:
    root = Path(repo_root)
    inv = load_set_inventory(root / relative_preset)
    solution = maximize_straight_tower(inv)
    return {
        "inventory": asdict(inv),
        "solution": asdict(solution) if solution else None,
    }
