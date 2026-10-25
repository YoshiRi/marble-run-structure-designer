"""Write tests/fixtures/triangle-isosceles.yaml: the user's isosceles triangle
base (design doc §6.2), built from the measured hole positions.

    python scripts/make_triangle_fixture.py

Base: a center-hole long rail on top, its end holes over the side rails'
second holes. Sides: long rails on four ground columns (foundation +
block), second hole at a base corner, end hole at the apex. Apex: a 3-hole
plate on the two side ends. Median: a long rail (holes 1 and 2, 36 cm)
from a block on the base's center hole to a red splitter on the plate's
middle hole. It is 0.59 cm short of the apex; the two median joints take
half each as declared play (user: "it fits by a miracle").
"""
from __future__ import annotations

from math import atan2, degrees, hypot, sqrt
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PITCH = 4.5          # plate hole pitch (catalog plate_*: beam)
BASE_HALF = 23.0     # base corners: end holes 2 and 48 of a 50 cm rail
SIDE = 41.0          # side: holes at 7 and 48
MEDIAN = 36.0        # median: holes at 7 and 43
APEX = sqrt(SIDE ** 2 - (BASE_HALF - PITCH) ** 2)
SHORT = APEX - MEDIAN
PLAY = round(SHORT / 2 + 0.005, 2)


def r(v: float) -> float:
    return round(v, 6)


def main() -> None:
    rails, parts, supports = [], [], []
    corners = {"left": (-BASE_HALF, 0.0), "right": (BASE_HALF, 0.0)}
    apex = {"left": (-PITCH, APEX), "right": (PITCH, APEX)}
    for side in ("left", "right"):
        (bx, by), (ax, ay) = corners[side], apex[side]
        ux, uy = (ax - bx) / SIDE, (ay - by) / SIDE
        rails.append({"id": f"side_{side}", "rail_type": "straight_long", "x_cm": r(bx - 7 * ux),
                      "y_cm": r(by - 7 * uy), "z_units": 6, "yaw_deg": r(degrees(atan2(uy, ux))),
                      "hole_states": {1: "block_connected", 3: "block_connected"}})
        for hole, (x, y) in ((1, (bx, by)), (3, (ax, ay))):
            col = f"col_{side}_{hole}"
            parts += [{"id": f"{col}_foundation", "part_type": "wooden_foundation", "x_cm": r(x), "y_cm": r(y),
                       "z_units": 0, "rotation_deg": 0},
                      {"id": f"{col}_block", "part_type": "yellow", "x_cm": r(x), "y_cm": r(y),
                       "z_units": 1, "rotation_deg": 0}]
            supports.append({"name": col, "upper_rail_id": f"side_{side}", "upper_hole_index": hole,
                             "stack_part_ids": [f"{col}_foundation", f"{col}_block"]})
    rails.append({"id": "base", "rail_type": "straight_long_center", "x_cm": -BASE_HALF - 2, "y_cm": 0.0,
                  "z_units": 7, "yaw_deg": 0.0, "hole_states": {0: "block_connected", 2: "block_connected",
                                                                4: "block_connected"}})
    supports += [{"name": "base_on_left", "upper_rail_id": "base", "upper_hole_index": 0, "stack_part_ids": [],
                  "lower_rail_id": "side_left", "lower_hole_index": 1},
                 {"name": "base_on_right", "upper_rail_id": "base", "upper_hole_index": 4, "stack_part_ids": [],
                  "lower_rail_id": "side_right", "lower_hole_index": 1}]
    rails.append({"id": "apex_plate", "rail_type": "plate_three_holes", "x_cm": r(-PITCH - 2.25),
                  "y_cm": r(APEX), "z_units": 7, "yaw_deg": 0.0})
    supports += [{"name": "plate_on_left", "upper_rail_id": "apex_plate", "upper_hole_index": 0,
                  "stack_part_ids": [], "lower_rail_id": "side_left", "lower_hole_index": 3},
                 {"name": "plate_on_right", "upper_rail_id": "apex_plate", "upper_hole_index": 2,
                  "stack_part_ids": [], "lower_rail_id": "side_right", "lower_hole_index": 3}]
    # Median: holes 1 and 2 (7 and 43 cm), centered between the base center
    # hole and the plate's middle hole.
    y1 = SHORT / 2
    rails.append({"id": "median", "rail_type": "straight_long", "x_cm": 0.0, "y_cm": r(y1 - 7), "z_units": 13,
                  "yaw_deg": 90.0, "hole_states": {1: "block_connected", 2: "block_connected"}})
    parts += [{"id": "median_foot", "part_type": "blue", "x_cm": 0.0, "y_cm": r(y1), "z_units": 8, "rotation_deg": 0},
              {"id": "apex_red", "part_type": "red_random_split", "x_cm": 0.0, "y_cm": r(y1 + MEDIAN),
               "z_units": 8, "rotation_deg": 0}]
    supports += [{"name": "median_on_base", "upper_rail_id": "median", "upper_hole_index": 1,
                  "stack_part_ids": ["median_foot"], "lower_rail_id": "base", "lower_hole_index": 2, "play_cm": PLAY},
                 {"name": "median_on_plate", "upper_rail_id": "median", "upper_hole_index": 2,
                  "stack_part_ids": ["apex_red"], "lower_rail_id": "apex_plate", "lower_hole_index": 1,
                  "play_cm": PLAY}]
    data = {
        "schema_version": "0.1",
        "name": "triangle-isosceles",
        "description": (f"The user's isosceles triangle base: apex {APEX:.2f} cm from the base, median "
                        f"{MEDIAN:.0f} cm, {SHORT:.2f} cm short, taken up as {PLAY} cm play at each median joint."),
        "rails": rails, "parts": parts, "supports": supports,
    }
    out = ROOT / "tests" / "fixtures" / "triangle-isosceles.yaml"
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"apex {APEX:.3f} cm, short {SHORT:.3f} cm, play {PLAY} cm per joint -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
