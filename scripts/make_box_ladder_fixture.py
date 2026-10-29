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

--modules lists n per module, top first; "3/1" gives the left side three
y-rails and the right side one, which then drops down a hollow tower (same
parity). --crown spiral puts a twist on top as the input. Each module but the bottom one
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


def parse_modules(text: str) -> list[tuple[int, int]]:
    """"3,1" -> [(3, 3), (1, 1)]; "3/1,1" -> [(3, 1), (1, 1)] (left/right)."""
    out = []
    for item in text.split(","):
        left, _, right = item.partition("/")
        out.append((int(left), int(right or left)))
    return out


def build(modules: list[tuple[int, int]], crown: str = "red") -> dict:
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

    SIDES = ((-1, "l"), (1, "r"))
    # Sequence top down: (kind, entry line, sides present). A side with fewer
    # y-rails than the other drops its marble down a hollow tower to L1.
    seq, line = [], 0.0
    for k, (nl, nr) in enumerate(modules):
        if (nl - nr) % 2:
            raise ValueError(f"module {k}: {nl}/{nr}: both sides must end on the same line (same parity)")
        if k == len(modules) - 1 and nl != nr:
            raise ValueError("the bottom module must be symmetric (its y-rails exit)")
        seq.append(("L2", line, ()))
        for j in range(max(nl, nr)):
            seq.append(("M", line, tuple(side for sx, side in SIDES if j < (nl if side == "l" else nr))))
            line = D - line
        if k < len(modules) - 1:
            seq.append(("L1", line, ()))
    top_z = 6 + STEP * (len(seq) - 1)
    rows = [(kind, line, sides, top_z - STEP * i) for i, (kind, line, sides) in enumerate(seq)]

    drop_i = 0

    def drop_block():
        nonlocal drop_i
        drop_i += 1
        return DROP[drop_i % len(DROP)]

    def next_with(i, side=None, kind="M"):
        return next((j for j in range(i + 1, len(rows)) if rows[j][0] == kind
                     and (side is None or side in rows[j][2])), None)

    for i, (kind, line, sides, z) in enumerate(rows):
        if kind == "L2":
            rid = f"l2_{i}"
            rails.append({"id": rid, "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": line, "z_units": z,
                          "yaw_deg": 0.0, "flow_direction": "from_hole", "flow_hole": 2,
                          "hole_states": {1: "block_connected", 3: "block_connected"}})
            # drop columns onto the M rails below (their entry)
            for sx, side in SIDES:
                b = part("drop", drop_block(), sx * X, line, z - 5, rot("+y" if line == 0.0 else "-y"))
                support(rid, 1 if sx < 0 else 3, [b], f"m{i + 1}{side}", 1)
            red = part("red", "red_random_split", 0.0, line, z + 1, 90)
            if i > 0:
                support(f"l1_{i - 1}", 2, [red], rid, 2)
                for hole, sx in ((0, -1), (4, 1)):     # L1's end holes on L2's
                    support(f"l1_{i - 1}", hole, stack("col", ["orange_vertical"], sx * 23.0, line, z + 1),
                            rid, hole)
            elif crown == "spiral":
                # A twist on top: its funnel center on the red splitter, its
                # chute holes over L2's holes 4 and 3 (23 and 18 cm from the
                # funnel, as on a short rail). The input block stands on the
                # chute's tip hole; the hole over L2's drop hole is covered.
                sid = "spiral_top"
                rails.append({"id": sid, "rail_type": "spiral", "x_cm": 24.5, "y_cm": line, "z_units": z + 6,
                              "yaw_deg": 180.0, "flow_direction": "a_to_b",
                              "hole_states": {1: "covered", 2: "block_connected"}})
                support(sid, 2, [red], rid, 2)
                support(sid, 0, stack("col", ["orange_vertical", "purple_drop", "purple_drop", "purple_drop"],
                                      23.0, line, z + 1), rid, 4)
                top = part("input", "yellow", 23.0, line, z + 10, rot("-x"))
                supports.append({"name": "input", "upper_rail_id": None, "upper_hole_index": None,
                                 "stack_part_ids": [top], "lower_rail_id": sid, "lower_hole_index": 0})
            else:
                supports.append({"name": "input", "upper_rail_id": None, "upper_hole_index": None,
                                 "stack_part_ids": [red], "lower_rail_id": rid, "lower_hole_index": 2})
        elif kind == "L1":
            rid = f"l1_{i}"
            rails.append({"id": rid, "rail_type": "straight_long_center", "x_cm": -25.0, "y_cm": line, "z_units": z,
                          "yaw_deg": 0.0, "flow_direction": "to_hole", "flow_hole": 2,
                          "hole_states": {2: "block_connected"}})
        else:
            ys = m_holes(line)
            for sx, side in SIDES:
                if side not in sides:
                    continue
                rid = f"m{i}{side}"
                x = sx * X
                exit_ = next_with(i) is None
                rails.append({"id": rid, "rail_type": "straight_long", "x_cm": x,
                              "y_cm": -7.0 if line == 0.0 else D + 7, "z_units": z,
                              "yaw_deg": 90.0 if line == 0.0 else 270.0, "flow_direction": "a_to_b",
                              "hole_states": {} if exit_ else {2: "block_connected"}})
                if exit_:
                    # exits: ground columns at both outer holes
                    for hole in (0, 3):
                        support(rid, hole, stack("ground", ["wooden_foundation", "green"], x, ys[hole], 0))
                    continue
                below = rows[i + 1]
                if below[0] == "M" and side in below[2]:
                    b = part("drop", drop_block(), x, ys[2], below[3] + 1, rot("+y" if below[1] == 0.0 else "-y"))
                    support(rid, 2, [b], f"m{i + 1}{side}", 1)
                else:                                   # down to L1, inward
                    j = next_with(i, kind="L1")
                    units = z - (rows[j][3] + 1)
                    # a hollow tower: the marble falls through, the bottom block turns it inward
                    hollow = ["orange_vertical"] * ((units - 5) // 5) + ["purple_drop"] * ((units - 5) % 5)
                    ids = stack("drop", [drop_block()] + hollow, x, ys[2], rows[j][3] + 1)
                    parts[[p["id"] for p in parts].index(ids[0])]["rotation_deg"] = rot("+x" if sx < 0 else "-x")
                    support(rid, 2, ids, f"l1_{j}", 1 if sx < 0 else 3)
            # the hole beyond the entry stands on the next M down on that side
            for sx, side in SIDES:
                if side not in sides:
                    continue
                nxt = next_with(i, side)
                if nxt is None:
                    continue
                units = z - (rows[nxt][3] + 1)
                support(f"m{i}{side}", 0, stack("col", filler(units), sx * X, ys[0], rows[nxt][3] + 1),
                        f"m{nxt}{side}", 3)

    last = len(rows) - 1
    source = "input" if crown == "spiral" else "red_1"
    return {
        "schema_version": "0.1",
        "rails": rails, "parts": parts, "supports": supports,
        "routing_query": {"source": {"component_id": f"{source}_1" if crown == "spiral" else source,
                                     "port": "top"},
                          "sinks": [{"component_id": f"m{last}l", "port": "hole:2"},
                                    {"component_id": f"m{last}r", "port": "hole:2"}]},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", default="1,1", help="M rails per side in each module, top first")
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "box-ladder.yaml")
    ap.add_argument("--name", default="box-ladder")
    ap.add_argument("--crown", choices=("red", "spiral"), default="red", help="the input: a red splitter or a twist")
    args = ap.parse_args()
    modules = parse_modules(args.modules)
    data = build(modules, args.crown)
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
