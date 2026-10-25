"""Write tests/fixtures/triangle-isosceles.yaml: the user's isosceles triangle
base (design doc §6.2), built from the measured hole positions.

    python scripts/make_triangle_fixture.py

Sides: long rails on four ground columns (foundation + block), second
hole at a base corner, end hole at the apex. Base: a center-hole long rail
on a block standing on each side rail's corner hole (rails are not laid
straight on rails: a marble would only drop through, user). Apex: a 3-hole
plate on the two side ends. Median: a long rail (holes 1 and 2, 36 cm) from
a red splitter on the base's center hole (the splitter belongs at the base,
user) to two blocks on the plate's middle hole. It is 0.59 cm short of the
apex; the two median joints take half each as declared play (user: "it
fits by a miracle").
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
                      "flow_direction": "a_to_b",
                      # the plate lies on the end hole, so the marble drops
                      # through hole 2 just before it (onto the ground or a tray)
                      "hole_states": {1: "block_connected", 3: "block_connected"}})
        yaw = degrees(atan2(uy, ux))
        for hole, (x, y) in ((1, (bx, by)), (3, (ax, ay))):
            col = f"col_{side}_{hole}"
            parts += [{"id": f"{col}_foundation", "part_type": "wooden_foundation", "x_cm": r(x), "y_cm": r(y),
                       "z_units": 0, "rotation_deg": 0},
                      {"id": f"{col}_block", "part_type": "yellow", "x_cm": r(x), "y_cm": r(y),
                       "z_units": 1, "rotation_deg": int(round(yaw - 90)) % 360}]
            supports.append({"name": col, "upper_rail_id": f"side_{side}", "upper_hole_index": hole,
                             "stack_part_ids": [f"{col}_foundation", f"{col}_block"]})
    rails.append({"id": "base", "rail_type": "straight_long_center", "x_cm": -BASE_HALF - 2, "y_cm": 0.0,
                  "z_units": 12, "yaw_deg": 0.0, "flow_direction": "from_hole", "flow_hole": 2,
                  # the splitter stands on hole 2 and lands the marble on holes
                  # 1 and 3, covered so it rolls on to the end holes
                  "hole_states": {0: "block_connected", 1: "covered", 3: "covered", 4: "block_connected"}})
    for side, hole, block in (("left", 0, "blue"), ("right", 4, "yellow")):
        (x, y), (ax, ay) = corners[side], apex[side]
        # The corner block takes the marble from the base's end hole and
        # sends it down the side rail toward the apex (front = the side's way).
        yaw = degrees(atan2(ay - y, ax - x))
        parts.append({"id": f"corner_{side}", "part_type": block, "x_cm": r(x), "y_cm": r(y), "z_units": 7,
                      "rotation_deg": int(round(yaw - 90)) % 360})
        supports.append({"name": f"base_on_{side}", "upper_rail_id": "base", "upper_hole_index": hole,
                         "stack_part_ids": [f"corner_{side}"], "lower_rail_id": f"side_{side}",
                         "lower_hole_index": 1})
    rails.append({"id": "apex_plate", "rail_type": "plate_three_holes", "x_cm": r(-PITCH - 2.25),
                  "y_cm": r(APEX), "z_units": 7, "yaw_deg": 0.0})
    supports += [{"name": "plate_on_left", "upper_rail_id": "apex_plate", "upper_hole_index": 0,
                  "stack_part_ids": [], "lower_rail_id": "side_left", "lower_hole_index": 3},
                 {"name": "plate_on_right", "upper_rail_id": "apex_plate", "upper_hole_index": 2,
                  "stack_part_ids": [], "lower_rail_id": "side_right", "lower_hole_index": 3}]
    # Median: holes 1 and 2 (7 and 43 cm), centered between the base center
    # hole and the plate's middle hole.
    y1 = SHORT / 2
    # The marble comes in at the median's apex end, rolls to the base end and
    # drops into the red splitter, which sends it left and right along the
    # base (user: its outlets face the base's two ends).
    rails.append({"id": "median", "rail_type": "straight_long", "x_cm": 0.0, "y_cm": r(y1 - 7), "z_units": 18,
                  "yaw_deg": 90.0, "flow_direction": "b_to_a",
                  "hole_states": {1: "block_connected", 2: "covered", 3: "covered"}})
    parts += [{"id": "base_red", "part_type": "red_random_split", "x_cm": 0.0, "y_cm": r(y1), "z_units": 13,
               "rotation_deg": 90},
              {"id": "apex_low", "part_type": "green", "x_cm": 0.0, "y_cm": r(y1 + MEDIAN), "z_units": 8,
               "rotation_deg": 0},
              {"id": "apex_high", "part_type": "cyan", "x_cm": 0.0, "y_cm": r(y1 + MEDIAN), "z_units": 13,
               "rotation_deg": 0}]
    supports += [{"name": "median_on_base", "upper_rail_id": "median", "upper_hole_index": 1,
                  "stack_part_ids": ["base_red"], "lower_rail_id": "base", "lower_hole_index": 2, "play_cm": PLAY},
                 {"name": "median_on_plate", "upper_rail_id": "median", "upper_hole_index": 2,
                  "stack_part_ids": ["apex_low", "apex_high"], "lower_rail_id": "apex_plate",
                  "lower_hole_index": 1, "play_cm": PLAY}]
    data = {
        "schema_version": "0.1",
        "name": "triangle-isosceles",
        "description": (f"The user's isosceles triangle base: apex {APEX:.2f} cm from the base, median "
                        f"{MEDIAN:.0f} cm, {SHORT:.2f} cm short, taken up as {PLAY} cm play at each median joint."),
        "rails": rails, "parts": parts, "supports": supports,
        "routing_query": {"source": {"component_id": "median", "port": "end_b"},
                          "sinks": [{"component_id": "side_left", "port": "hole:2"},
                                    {"component_id": "side_right", "port": "hole:2"}]},
    }
    out = ROOT / "tests" / "fixtures" / "triangle-isosceles.yaml"
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"apex {APEX:.3f} cm, short {SHORT:.3f} cm, play {PLAY} cm per joint -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
