"""Large structural patterns the generator can place whole (design doc §6.2).

A pattern is given in its own local frame. The generator turns and moves it
into place, and materializes its columns like any other.

isosceles_triangle (the user's build, also an official example):

    apex   plate (3 holes) on the two side ends, two blocks up to the median
           |\\
     side  | \\  median (z 18): marble enters at the apex end, rolls to the base
           |  \\
    base   red splitter on the base's center hole sends it both ways along the
           base (z 12) into a block at each corner, down each side rail (z 6),
           out through the side's hole 2 just before the plate.

Local frame: base along x, centered; apex toward +y. The median's apex end
(hole 3) is where a drop block lands the marble ("feed").
"""
from __future__ import annotations

from math import atan2, degrees, sqrt
from typing import Any

from .catalog import PartCatalog


def isosceles_triangle(catalog: PartCatalog) -> dict[str, Any]:
    long_ = catalog.rails["straight_long"].holes_cm            # 2, 7, 43, 48
    center = catalog.rails["straight_long_center"].holes_cm    # 2, 7, 25, 43, 48
    plate = catalog.rails["plate_three_holes"].holes_cm        # 2.25, 6.75, 11.25
    pitch = plate[1] - plate[0]
    half = catalog.raw["geometry_cm"]["standard_block_footprint"]["width_cm"] / 2.0
    base_half = (center[4] - center[0]) / 2.0                 # corners 46 cm apart
    side = long_[3] - long_[1]                                 # 41 cm: 2nd hole -> end hole
    median = long_[2] - long_[1]                               # 36 cm: holes 1 -> 2
    apex = sqrt(side ** 2 - (base_half - pitch) ** 2)
    short = apex - median
    play = round(short / 2 + 0.005, 2)
    y1 = short / 2                                             # median hole 1, half the gap each end

    rails: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    for key, (bx, ax), base_hole, plate_hole, block in (
            ("side_left", (-base_half, -pitch), 0, 0, "blue"),
            ("side_right", (base_half, pitch), 4, 2, "yellow")):
        ux, uy = (ax - bx) / side, apex / side
        yaw = degrees(atan2(uy, ux))
        rails.append({"key": key, "type": "straight_long", "x": bx - long_[1] * ux, "y": -long_[1] * uy,
                      "z": 6, "yaw": yaw, "flow": "a_to_b",
                      # the corner block lands the marble at hole 1; the plate
                      # lies on the end hole, so it drops through hole 2 just
                      # before it
                      "holes": {}})
        for hole, xy in ((1, (bx, 0.0)), (3, (ax, apex))):
            columns.append({"xy": xy, "base_rail": None, "base_z": 0, "top_rail": key, "top_hole": hole,
                            "top_z": 6})
        # A block between side and base: a rail laid straight on a rail only
        # drops the marble through (user). It sends the marble down the side.
        columns.append({"xy": (bx, 0.0), "base_rail": key, "base_hole": 1, "base_z": 7, "top_rail": "base",
                        "top_hole": base_hole, "top_z": 12, "top_types": (block,), "rotation": yaw - 90})
        columns.append({"xy": (ax, apex), "base_rail": key, "base_hole": 3, "base_z": 7, "top_rail": "plate",
                        "top_hole": plate_hole, "top_z": 7})
    rails.append({"key": "base", "type": "straight_long_center", "x": -base_half - center[0], "y": 0.0, "z": 12,
                  "yaw": 0.0, "flow": "from_hole", "flow_hole": 2,
                  "holes": {0: "block_connected", 1: "covered", 3: "covered", 4: "block_connected"}})
    rails.append({"key": "plate", "type": "plate_three_holes", "x": -pitch - plate[0], "y": apex, "z": 7,
                  "yaw": 0.0})
    rails.append({"key": "median", "type": "straight_long", "x": 0.0, "y": y1 - long_[1], "z": 18, "yaw": 90.0,
                  "flow": "b_to_a", "holes": {1: "block_connected", 2: "covered"}})
    # The red splitter faces the base's two ends (user); the median takes the
    # 0.59 cm it is short as play at its two joints.
    columns.append({"xy": (0.0, y1), "base_rail": "base", "base_hole": 2, "base_z": 13, "top_rail": "median",
                    "top_hole": 1, "top_z": 18, "top_types": ("red_random_split",), "rotation": 90, "play": play})
    columns.append({"xy": (0.0, y1 + median), "base_rail": "plate", "base_hole": 1, "base_z": 8,
                    "top_rail": "median", "top_hole": 2, "top_z": 18, "play": play})
    return {
        "rails": rails,
        "columns": columns,
        "feed_xy": (0.0, y1 - long_[1] + long_[3]),   # median hole 3
        "feed_hole": 3,
        "feed_z": 19,
        # where the marble rolls (clear of the blocks standing on the rails)
        "rolls": [("median", long_[1], long_[3] - half), ("base", center[0], center[2] - half),
                  ("base", center[2] + half, center[4]),
                  ("side_left", long_[1] + half, long_[2]), ("side_right", long_[1] + half, long_[2])],
        "drops": [("side_left", 2), ("side_right", 2)],
        "covers": 3,
        "apex_cm": apex,
        "short_cm": short,
        "play_cm": play,
    }
