"""Generate marble-run layouts from commercial set inventories.

Example:
    python scripts/generate_layout.py --sets QD001,QD003,QD005 --attempts 800 \
        --seed 7 --keep 3 --out-dir examples/generated
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import (
    Budget, GeneratorConfig, generate, layout_to_yaml_dict, resolve_set_paths,
)

ROOT = Path(__file__).resolve().parents[1]


def _footprint(text: str) -> tuple[float, float]:
    try:
        w, d = (float(v) for v in text.lower().split("x"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("footprint must be WIDTHxDEPTH in cm, e.g. 90x90") from error
    return w, d


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sets", default="QD001,QD003,QD005",
                        help="comma-separated set ids whose combined contents bound the inventory "
                             "(add QDE6008AB05, the older Twist set, for curved rails)")
    parser.add_argument("--max-height", type=int, default=24, help="top rail level in height units (1u = 1.5 cm)")
    parser.add_argument("--footprint", type=_footprint, default=(90.0, 90.0), help="WIDTHxDEPTH in cm")
    parser.add_argument("--max-rails", type=int, default=12)
    parser.add_argument("--split-probability", type=float, default=0.45)
    parser.add_argument("--curve-bias", type=float, default=0.5,
                        help="chance to build on holes that let straights become curves (needs curves in --sets)")
    parser.add_argument("--max-exits", type=int, default=2, help="most branch outputs (exits) per layout")
    parser.add_argument("--exit-style", choices=("contained", "any"), default="contained",
                        help="contained: exits are block side outlets or dives through open rail holes; "
                             "any: rails may also roll off their end")
    parser.add_argument("--twist-probability", type=float, default=0.5)
    parser.add_argument("--attempts", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="write each kept layout as YAML here (otherwise only print a summary)")
    parser.add_argument("--name-prefix", default="generated")
    args = parser.parse_args()

    set_ids = [s.strip() for s in args.sets.split(",") if s.strip()]
    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    budget = Budget.from_sets(resolve_set_paths(ROOT, set_ids))
    config = GeneratorConfig(
        max_height_units=args.max_height, footprint_cm=args.footprint,
        split_probability=args.split_probability, max_rails=args.max_rails,
        curve_ready_bias=args.curve_bias, max_exits=args.max_exits, exit_style=args.exit_style,
        twist_probability=args.twist_probability,
    )
    candidates = generate(catalog, budget, config=config, attempts=args.attempts,
                          seed=args.seed, keep=args.keep)
    if not candidates:
        raise SystemExit("No valid layout found; try more --attempts, a larger --footprint or more sets.")

    for rank, candidate in enumerate(candidates, 1):
        m = candidate.metrics
        print(f"#{rank} score={candidate.score:.1f} levels={m['levels']} rails={m['rails']} "
              f"rolling={m['rolling_length_cm']}cm shortest={m['min_exit_path_cm']}cm "
              f"exits={m['exits']} (levels {m['exit_levels']}) branches={m['random_branches']} "
              f"area={m['footprint_area_cm2']}cm2 "
              f"covers={m['covers']} curves={m.get('curved_rails', 0)} twists={m.get('twists', 0)}")
        if args.out_dir is None:
            continue
        args.out_dir.mkdir(parents=True, exist_ok=True)
        name = f"{args.name_prefix}-{args.seed}-{rank}"
        data = layout_to_yaml_dict(
            candidate, name=name,
            description=f"Generated cascade from sets {', '.join(set_ids)} (seed {args.seed}, rank {rank}).",
            generator_info={"sets": set_ids, "seed": args.seed, "attempts": args.attempts,
                            "max_height_units": args.max_height,
                            "footprint_cm": list(args.footprint), "max_exits": args.max_exits,
                            "exit_style": args.exit_style, "score": round(candidate.score, 1)},
        )
        path = args.out_dir / f"{name}.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"   wrote {path}")


if __name__ == "__main__":
    main()
