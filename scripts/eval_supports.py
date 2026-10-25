"""Compare the generator's greedy supports with the support solver.

    python scripts/eval_supports.py [--gallery] [--seeds 1-3] [--attempts 150]

For each build: strip the columns the marble never touches and solve them
again (quadrilla_solver.supports). Prints per-build and mean numbers: parts,
support-only parts, distinct column spots, footprint, weak towers.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quadrilla_solver import generator as g  # noqa: E402
from quadrilla_solver.catalog import load_catalog  # noqa: E402
from quadrilla_solver.collision import component_solids  # noqa: E402
from quadrilla_solver.model import load_layout  # noqa: E402
from quadrilla_solver.supports import resolve_supports, route_parts  # noqa: E402

SETS = ["OWNED"]  # the counted collection (catalog/inventory.yaml)


def measure(layout, catalog, source):
    on_route = route_parts(layout, catalog, source)
    support_parts = sum(len(s.stack_part_ids) for s in layout.supports
                        if not any(p in on_route for p in s.stack_part_ids))
    spots = {(round(p.x_cm, 1), round(p.y_cm, 1)) for p in layout.parts}
    solids = component_solids(layout, catalog)
    xs = [s.center_xy[0] for s in solids]
    ys = [s.center_xy[1] for s in solids]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys)) if solids else 0
    return {"parts": len(layout.parts), "support_parts": support_parts, "spots": len(spots),
            "footprint": round(area), "weak_towers": g.weak_towers(layout, catalog)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gallery", action="store_true")
    ap.add_argument("--seeds", default="1-3")
    ap.add_argument("--attempts", type=int, default=150)
    ap.add_argument("--drop-braces", action="store_true", help="also remove brace rails")
    args = ap.parse_args()
    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    budget = g.Budget.from_sets(g.resolve_set_paths(ROOT, SETS))
    counts = {k: (0 if k == "red_right_angle" else v) for k, v in budget.counts.items()}
    builds = []
    if args.gallery:
        for path in sorted((ROOT / "examples" / "gallery").glob("mr-*.yaml")):
            data = yaml.safe_load(path.read_text())
            builds.append((path.stem, load_layout(path), g.layout_source(data), list(g.layout_sinks(data))))
    else:
        a, _, b = args.seeds.partition("-")
        for seed in range(int(a), int(b or a) + 1):
            config = g.GeneratorConfig(exclude_parts=("red_right_angle",))
            for c in g.generate(catalog, budget, config=config, attempts=args.attempts, seed=seed, keep=5):
                builds.append((g.layout_id(c.layout), c.layout, c.source, list(c.sinks)))
    rows, solved, t0 = [], 0, time.time()
    for name, layout, source, sinks in builds:
        before = measure(layout, catalog, source)
        after_layout = resolve_supports(layout, catalog, counts, source, sinks, keep_braces=not args.drop_braces)
        if after_layout is None:
            print(f"{name}: no valid support solution")
            continue
        solved += 1
        after = measure(after_layout, catalog, source)
        rows.append((before, after))
        print(f"{name}: " + ", ".join(f"{k} {before[k]}->{after[k]}" for k in before))
    if rows:
        print(f"solved {solved}/{len(builds)} in {time.time() - t0:.1f} s")
        for k in rows[0][0]:
            print(f"  mean {k}: {statistics.mean(r[0][k] for r in rows):.1f} -> "
                  f"{statistics.mean(r[1][k] for r in rows):.1f}")


if __name__ == "__main__":
    main()
