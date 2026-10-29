"""Write box ladder layouts (design doc §6.8): the user's T joint stacked
with merges.

    python scripts/make_box_ladder_fixture.py                 # the test fixture
    python scripts/make_box_ladder_fixture.py --modules 3,1 --out examples/box_ladder/x.yaml

A module, top down:

    L2  x-rail, center-hole long rail. A red splitter on its center hole
        (the T: the rail above drops into it) sends the marble both ways to
        holes 1 and 3 (+-18 cm), which drop it into a block on each side.
    M   on each side (x = +-18) a stack of n y-rails (long rails, holes
        1 -> 2, 36 cm), a switchback when n > 1, each dropping onto the next
    L1  x-rail, center-hole long rail: both branches come in at holes 1 and
        3 and roll to the center hole (a merge), which drops into the red
        splitter of the next module's L2 below.

The rails run on two lines each way (y = 0 and 36, x = +-18), so rails one
above the other at a tower are always collinear and the ladder's trick
works in both directions: a support stands on the hole just beyond a rail's
drop hole (5 cm on), where no marble rolls. L1's end holes (+-23) stand on
L2's end holes; an M's hole beyond its entry on the M below's hole beyond
its stop. The bottom module has no L1: its lowest M rails drop to the ground
(two exits).

--modules lists n per module, top first. Each module but the bottom one
takes two center-hole rails (the bottom one takes one).
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
D = 36.0                 # line spacing: an M's holes 1 -> 2
X = 18.0                 # M lines: L's holes 1 and 3
STEP = 6                 # a drop block (5) + a rail (1)
DROP = ("yellow", "green", "blue", "cyan")


def rot(direction: str) -> int:
    """rotation_deg of a block whose front faces `direction`."""
    return {"+y": 0, "-y": 180, "+x": 270, "-x": 90}[direction]


def m_holes(entry: float) -> dict[int, float]:
    """y of an M rail's holes: 1 = entry line, 2 = stop line, 0 and 3 the
    holes 5 cm beyond them."""
    if entry == 0.0:
        return {0: -5.0, 1: 0.0, 2: D, 3: D + 5}
    return {0: D + 5, 1: D, 2: 0.0, 3: -5.0}


FILL = ("orange_vertical", "green", "cyan", "blue", "yellow")
_fill = [0]


def filler(units: int) -> list[str]:
    """Blocks then purple drops (1 level each) for a column of `units`."""
    kinds = []
    for _ in range(units // 5):
        kinds.append(FILL[_fill[0] % len(FILL)])
        _fill[0] += 1
    return kinds + ["purple_drop"] * (units % 5)


def build(modules: list[int]) -> dict:
    rails, parts, supports = [], [], []
    count = Counter()

    def part(prefix, kind, x, y, z, rotation=0):
        count[prefix] += 1
        pid = f"{prefix}_{count[prefix]}"
        parts.append({"id": pid, "part_type": kind, "x_cm": x, "y_cm": y, "z_units": z, "rotation_deg": rotation})
        return pid

    def stack(prefix, kinds, x, y, z0):
        ids, z = [], z0
        for kind in kinds:
            ids.append(part(prefix, kind, x, y, z))
            z += 1 if kind in ("purple_drop", "wooden_foundation") else 5
        return ids

    def support(upper, hole, ids, lower=None, lower_hole=None):
        s = {"name": f"s{len(supports)}", "upper_rail_id": upper, "upper_hole_index": hole, "stack_part_ids": ids}
        if lower is not None:
            s.update({"lower_rail_id": lower, "lower_hole_index": lower_hole})
        supports.append(s)

    # Sequence top down: (kind, line, module); M rails stand for both sides.
    seq, line = [], 0.0
    for k, n in enumerate(modules):
        seq.append(("L2", line, k))
        for _ in range(n):
            seq.append(("M", line, k))          # entry line
            line = D - line
        if k < len(modules) - 1:
            seq.append(("L1", line, k))
    top_z = 6 + STEP * (len(seq) - 1)
    rows = [(kind, line, k, top_z - STEP * i) for i, (kind, line, k) in enumerate(seq)]

    drop_i = 0

    def drop_block():
        nonlocal drop_i
        drop_i += 1
        return DROP[drop_i % len(DROP)]

    for i, (kind, line, k, z) in enumerate(rows):
        below = rows[i + 1] if i + 1 < len(rows) else None
        if kind == "L2":
            rid = f"l2_{i}"
            rails.append({"id": rid, "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": line, "z_units": z,
                          "yaw_deg": 0.0, "flow_direction": "from_hole", "flow_hole": 2,
                          "hole_states": {1: "block_connected", 3: "block_connected"}})
            # drop columns onto the M rails below (their entry)
            for sx, side, hole in ((-1, "l", 1), (1, "r", 3)):
                b = part("drop", drop_block(), sx * X, line, z - 5, rot("+y" if line == 0.0 else "-y"))
                support(rid, hole, [b], f"m{i + 1}{side}", 1)
            red = part("red", "red_random_split", 0.0, line, z + 1, 90)
            if i == 0:
                supports.append({"name": "input", "upper_rail_id": None, "upper_hole_index": None,
                                 "stack_part_ids": [red], "lower_rail_id": rid, "lower_hole_index": 2})
            else:
                support(f"l1_{i - 1}", 2, [red], rid, 2)
                for hole, sx in ((0, -1), (4, 1)):     # L1's end holes on L2's
                    support(f"l1_{i - 1}", hole, stack("col", ["orange_vertical"], sx * 23.0, line, z + 1),
                            rid, hole)
        elif kind == "L1":
            rid = f"l1_{i}"
            rails.append({"id": rid, "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": line, "z_units": z,
                          "yaw_deg": 0.0, "flow_direction": "to_hole", "flow_hole": 2,
                          "hole_states": {2: "block_connected"}})
        else:
            ys = m_holes(line)
            last = below is None
            for sx, side in ((-1, "l"), (1, "r")):
                rid = f"m{i}{side}"
                yaw = 90.0 if line == 0.0 else 270.0
                a_end = -7.0 if line == 0.0 else D + 7
                rails.append({"id": rid, "rail_type": "straight_long", "x_cm": sx * X, "y_cm": a_end, "z_units": z,
                              "yaw_deg": yaw, "flow_direction": "a_to_b",
                              "hole_states": {} if last else {2: "block_connected"}})
                x = sx * X
                if last:
                    # exits: ground columns at both outer holes
                    for hole in (0, 3):
                        support(rid, hole, stack("ground", ["wooden_foundation", "green"], x, ys[hole], 0))
                    continue
                bkind, bline, _, bz = below
                if bkind == "M":
                    b = part("drop", drop_block(), x, ys[2], bz + 1, rot("+y" if bline == 0.0 else "-y"))
                    support(rid, 2, [b], f"m{i + 1}{side}", 1)
                else:                                   # onto L1, inward
                    b = part("drop", drop_block(), x, ys[2], bz + 1, rot("+x" if sx < 0 else "-x"))
                    support(rid, 2, [b], f"l1_{i + 1}", 1 if sx < 0 else 3)
            # the hole beyond the entry stands on the next M down (beyond its stop)
            nxt = next((j for j in range(i + 1, len(rows)) if rows[j][0] == "M"), None)
            for sx, side in ((-1, "l"), (1, "r")):
                rid = f"m{i}{side}"
                if nxt is None:
                    continue
                units = z - (rows[nxt][3] + 1)
                support(rid, 0, stack("col", filler(units), sx * X, ys[0], rows[nxt][3] + 1),
                        f"m{nxt}{side}", 3)

    bottom = rows[-1][0]
    assert bottom == "M"
    last = len(rows) - 1
    return {
        "schema_version": "0.1",
        "rails": rails, "parts": parts, "supports": supports,
        "routing_query": {"source": {"component_id": "red_1", "port": "top"},
                          "sinks": [{"component_id": f"m{last}l", "port": "hole:2"},
                                    {"component_id": f"m{last}r", "port": "hole:2"}]},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", default="1,1", help="M rails per side in each module, top first")
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "box-ladder.yaml")
    ap.add_argument("--name", default="box-ladder")
    args = ap.parse_args()
    modules = [int(n) for n in args.modules.split(",")]
    data = build(modules)
    levels = max(r["z_units"] for r in data["rails"]) + 6
    used = Counter(r["rail_type"] for r in data["rails"])
    data = {"schema_version": "0.1", "name": args.name,
            "description": (f"Box ladder, {len(modules)} modules ({args.modules} y-rails per side), {levels} levels: "
                            "T joints (a red splitter on a center hole) and merges, x- and y-rails bracing each "
                            "other (design doc §6.8)."),
            **{k: v for k, v in data.items() if k != "schema_version"}}
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"{levels} levels, rails {dict(used)}, parts {dict(Counter(p['part_type'] for p in data['parts']))} "
          f"-> {out}")


if __name__ == "__main__":
    main()
