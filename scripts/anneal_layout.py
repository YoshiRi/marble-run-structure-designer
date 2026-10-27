"""Improve generated builds by simulated annealing over the generator's
decision tape (src/quadrilla_solver/anneal.py) and write before/after pairs.

    python scripts/anneal_layout.py --base triangle --height 45 --seeds 1,4 \\
        --restarts 150 --iterations 300 --out-dir examples/anneal

Each seed: the best of `restarts` random builds on the base is the start;
annealing then polishes it. Writes <id>.yaml for start and best, and
index.json with scores and metrics.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml

from quadrilla_solver.anneal import anneal, grow
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, GeneratorConfig, layout_id, layout_to_yaml_dict, resolve_set_paths

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("levels", "rails", "parts", "exits", "merges", "switchbacks", "shared_towers", "twists", "triangles",
        "rolling_length_cm", "footprint_area_cm2")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="triangle")
    ap.add_argument("--height", type=int, default=45)
    ap.add_argument("--rails", type=int, default=14)
    ap.add_argument("--seeds", default="1,4")
    ap.add_argument("--restarts", type=int, default=150)
    ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "examples" / "anneal")
    args = ap.parse_args()
    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    budget = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
    config = GeneratorConfig(exclude_parts=("red_right_angle",), max_height_units=args.height,
                             max_rails=args.rails)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for seed in (int(s) for s in args.seeds.split(",")):
        fresh = random.Random(seed)
        start = start_tape = None
        for _ in range(args.restarts):
            c, tape = grow(catalog, budget, config, [], fresh, args.base)
            if c is not None and (start is None or c.score > start.score):
                start, start_tape = c, tape
        if start is None:
            print(f"seed {seed}: no build on base {args.base}")
            continue
        result = anneal(catalog, budget, config, seed=seed, iterations=args.iterations, base=args.base,
                        start_tape=start_tape, t_start=3.0, t_end=0.1)
        entry = {"seed": seed, "base": args.base}
        for label, c in (("start", start), ("annealed", result.best)):
            lid = layout_id(c.layout)
            data = layout_to_yaml_dict(c, name=f"{lid} ({label})",
                                       description=f"seed {seed}, base {args.base}: {label}, score {c.score:.1f}",
                                       generator_info={"anneal": label, "seed": seed, "score": round(c.score, 1)})
            (args.out_dir / f"{lid}.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
            entry[label] = {"id": lid, "file": f"examples/anneal/{lid}.yaml", "score": round(c.score, 1),
                            "metrics": {k: c.metrics.get(k) for k in KEYS}}
        entry["valid_neighbours"] = f"{result.valid}/{result.evaluated}"
        index.append(entry)
        print(f"seed {seed}: {entry['start']['id']} {entry['start']['score']} -> "
              f"{entry['annealed']['id']} {entry['annealed']['score']}")
    (args.out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")


if __name__ == "__main__":
    main()
