"""Write tests/fixtures/box-ladder.yaml: two modules of the box ladder
(design doc §6.8), the user's T joint stacked with merges.

    python scripts/make_box_ladder_fixture.py

A module, top down (18 levels):

    L2  x-rail, center-hole long rail. A red splitter on its center hole
        (the T: the rail above drops into it) sends the marble both ways to
        holes 1 and 3 (+-18 cm), which drop it into a block on each M.
    M   two y-rails at x = +-18 (long rails, holes 1 -> 2, 36 cm), each
        rolling the marble to the far line and dropping it onto
    L1  x-rail, center-hole long rail: both branches come in at holes 1 and
        3 and roll to the center hole (a merge), which drops into the red
        splitter of the next module's L2 below.

Modules alternate between the lines y = 0 and y = 36, so rails one above the
other at a tower are always collinear, and the ladder's trick works in both
directions: a support stands on the hole just beyond a rail's drop hole (5 cm
on), where no marble rolls. L1's end holes (+-23) stand on L2's end holes; an
M's hole beyond its entry stands on the M below's hole beyond its stop.

The bottom module has no L1 (three center-hole rails are owned): its M rails
drop to the ground (two exits).
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
D = 36.0                 # line spacing: an M's holes 1 -> 2
X = 18.0                 # M lines: L's holes 1 and 3


def rot(direction: str) -> int:
    """rotation_deg of a drop block whose front faces `direction`."""
    return {"+y": 0, "-y": 180, "+x": 270, "-x": 90}[direction]


def main() -> None:
    rails, parts, supports = [], [], []

    def part(pid, kind, x, y, z, rotation=0):
        parts.append({"id": pid, "part_type": kind, "x_cm": x, "y_cm": y, "z_units": z, "rotation_deg": rotation})
        return pid

    def support(name, upper, hole, stack, lower=None, lower_hole=None):
        s = {"name": name, "upper_rail_id": upper, "upper_hole_index": hole, "stack_part_ids": stack}
        if lower is not None:
            s.update({"lower_rail_id": lower, "lower_hole_index": lower_hole})
        supports.append(s)

    # ---- module 1 (bottom): L2 on y = 36, M from 36 to 0, exits ---------
    for sx, side in ((-1, "l"), (1, "r")):
        # yaw 270: a-end at y = 43; holes 0..3 at y = 41, 36, 0, -5
        rails.append({"id": f"m1{side}", "rail_type": "straight_long", "x_cm": sx * X, "y_cm": D + 7,
                      "z_units": 6, "yaw_deg": 270.0, "flow_direction": "a_to_b", "hole_states": {}})
        for hole, y in ((0, D + 5), (3, -5.0)):
            f = part(f"g_m1{side}{hole}_f", "wooden_foundation", sx * X, y, 0)
            b = part(f"g_m1{side}{hole}_b", "cyan", sx * X, y, 1)
            support(f"g_m1{side}{hole}", f"m1{side}", hole, [f, b])
    rails.append({"id": "l2_1", "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": D, "z_units": 12,
                  "yaw_deg": 0.0, "flow_direction": "from_hole", "flow_hole": 2,
                  "hole_states": {1: "block_connected", 3: "block_connected"}})
    for sx, side, hole in ((-1, "l", 1), (1, "r", 3)):
        b = part(f"d_l21{side}", "yellow", sx * X, D, 7, rot("-y"))
        support(f"d_l21{side}", "l2_1", hole, [b], f"m1{side}", 1)

    # ---- module 2 (top): L1 on y = 36, M from 0 to 36, L2 on y = 0 ------
    rails.append({"id": "l1_2", "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": D, "z_units": 18,
                  "yaw_deg": 0.0, "flow_direction": "to_hole", "flow_hole": 2,
                  "hole_states": {2: "block_connected"}})
    red = part("red_1", "red_random_split", 0.0, D, 13, 90)
    support("red_1", "l1_2", 2, [red], "l2_1", 2)
    for sx, side, hole in ((-1, "l", 0), (1, "r", 4)):
        b = part(f"s_l12{side}", "orange_vertical", sx * 23.0, D, 13)
        support(f"s_l12{side}", "l1_2", hole, [b], "l2_1", hole)
    for sx, side, hole in ((-1, "l", 1), (1, "r", 3)):
        # yaw 90: a-end at y = -7; holes 0..3 at y = -5, 0, 36, 41
        rails.append({"id": f"m2{side}", "rail_type": "straight_long", "x_cm": sx * X, "y_cm": -7.0,
                      "z_units": 24, "yaw_deg": 90.0, "flow_direction": "a_to_b",
                      "hole_states": {2: "block_connected"}})
        b = part(f"d_l12{side}", "blue", sx * X, D, 19, rot("+x" if sx < 0 else "-x"))
        support(f"d_l12{side}", f"m2{side}", 2, [b], "l1_2", hole)
        stack = [part(f"s_m{side}_{i}", kind, sx * X, -5.0, z)
                 for i, (kind, z) in enumerate((("green", 7), ("green", 12), ("cyan", 17),
                                                ("purple_drop", 22), ("purple_drop", 23)))]
        support(f"s_m{side}", f"m2{side}", 0, stack, f"m1{side}", 3)
    rails.append({"id": "l2_2", "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": 0.0, "z_units": 30,
                  "yaw_deg": 0.0, "flow_direction": "from_hole", "flow_hole": 2,
                  "hole_states": {1: "block_connected", 3: "block_connected"}})
    for sx, side, hole in ((-1, "l", 1), (1, "r", 3)):
        b = part(f"d_l22{side}", "green", sx * X, 0.0, 25, rot("+y"))
        support(f"d_l22{side}", "l2_2", hole, [b], f"m2{side}", 1)
    top = part("input_red", "red_random_split", 0.0, 0.0, 31, 90)
    supports.append({"name": "input", "upper_rail_id": None, "upper_hole_index": None, "stack_part_ids": [top],
                     "lower_rail_id": "l2_2", "lower_hole_index": 2})

    data = {
        "schema_version": "0.1",
        "name": "box-ladder",
        "description": ("Box ladder, two modules: T joints (a red splitter on a center hole) and merges, "
                        "x- and y-rails bracing each other (design doc §6.8)."),
        "rails": rails, "parts": parts, "supports": supports,
        "routing_query": {"source": {"component_id": "input_red", "port": "top"},
                          "sinks": [{"component_id": "m1l", "port": "hole:2"},
                                    {"component_id": "m1r", "port": "hole:2"}]},
    }
    out = ROOT / "tests" / "fixtures" / "box-ladder.yaml"
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
