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
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quadrilla_solver.box_ladder import build, parse_modules  # noqa: E402


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
