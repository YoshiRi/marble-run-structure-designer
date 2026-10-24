"""Build the review gallery: a diverse set of generated layouts with stable IDs.

Runs the generator under several configurations, removes duplicates by layout
ID, picks a diverse set (twists, curves, branches, tall, stacked, long roll,
compact, then best score) and writes examples/gallery/<id>.yaml plus examples/gallery/index.json.

    python scripts/build_gallery.py --count 12 --seeds 3 --attempts 300
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import (
    Budget, GeneratorConfig, generate, layout_id, layout_to_yaml_dict, resolve_set_paths, score,
)

ROOT = Path(__file__).resolve().parents[1]
SETS = ["QD001", "QD003", "QD005", "QDE6008AB05"]
# Parts the user does not have at the moment (review 3: no right-angle splitter).
EXCLUDE = ("red_right_angle",)

# (label, config overrides)
CONFIGS = [
    ("balanced", {}),
    ("more-twists", {"twist_probability": 0.9}),
    ("no-twists", {"twist_probability": 0.0}),
    ("more-curves", {"curve_ready_bias": 0.8}),
    ("three-exits", {"max_exits": 3, "split_probability": 0.7}),
    ("taller", {"max_height_units": 45, "max_rails": 14}),
    # Official builds stack close to 10 blocks (user): up to 60 levels.
    ("tallest", {"max_height_units": 60, "max_rails": 16}),
    ("compact", {"footprint_cm": (60.0, 60.0)}),
    # Seesaw diamonds (split and merge, design doc §6.1) on purpose.
    ("merges", {"seesaw_probability": 1.0, "weights": {"merges": 25.0}}),
]

# Feature buckets the selection tries to cover before filling by score.
BUCKETS = [
    ("no twist", lambda m: m.get("twists", 0) == 0),
    ("twist", lambda m: m.get("twists", 0) >= 1),
    ("two twists", lambda m: m.get("twists", 0) >= 2),
    ("curves", lambda m: m.get("curved_rails", 0) >= 2),
    ("branched", lambda m: m["random_branches"] >= 1),
    ("tall", lambda m: m["levels"] >= 7),
    ("stacked", lambda m: m["columns_on_rails"] >= 6),
    ("long roll", lambda m: m["min_exit_path_cm"] >= 200),
    ("compact", lambda m: m["footprint_area_cm2"] <= 2500),
    ("braced", lambda m: m.get("braces", 0) >= 1),
    ("merged", lambda m: m.get("merges", 0) >= 1),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--attempts", type=int, default=300)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "examples" / "gallery")
    args = parser.parse_args()

    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    budget = Budget.from_sets(resolve_set_paths(ROOT, SETS))
    pool: dict[str, tuple] = {}
    for label, overrides in CONFIGS:
        config = GeneratorConfig(exclude_parts=EXCLUDE, **overrides)
        for seed in range(1, args.seeds + 1):
            for candidate in generate(catalog, budget, config=config, attempts=args.attempts,
                                      seed=seed, keep=3):
                lid = layout_id(candidate.layout)
                if lid not in pool or pool[lid][0].score < candidate.score:
                    pool[lid] = (candidate, label, seed)
            print(f"{label} seed {seed}: pool {len(pool)}")
    # The same build turned, mirrored or with other filler blocks gets another
    # layout ID: keep one per shape (rails and rotation-invariant metrics).
    seen: dict[tuple, str] = {}
    for lid, (candidate, _, _) in sorted(pool.items(), key=lambda kv: -score(kv[1][0].metrics)):
        m = candidate.metrics
        signature = (tuple(sorted(Counter(r.rail_type for r in candidate.layout.rails).items())),
                     m["levels"], m["exits"], round(m["rolling_length_cm"]), round(m["footprint_area_cm2"]))
        if signature in seen:
            del pool[lid]
        else:
            seen[signature] = lid
    print(f"pool after removing turned/mirrored copies: {len(pool)}")

    # Rank by the default score: configurations may use their own weights.
    ranked = sorted(pool.items(), key=lambda kv: score(kv[1][0].metrics), reverse=True)
    chosen: dict[str, tuple] = {}
    # At most a few per configuration so the set stays varied.
    cap = max(2, -(-args.count // len(CONFIGS)) + 1)
    per_config: Counter = Counter()
    for _, test in BUCKETS:
        for lid, entry in ranked:
            if lid not in chosen and per_config[entry[1]] < cap and test(entry[0].metrics):
                chosen[lid] = entry
                per_config[entry[1]] += 1
                break
    # Fill round-robin over configurations, best score first within each.
    by_config = {label: [(lid, e) for lid, e in ranked if e[1] == label] for label, _ in CONFIGS}
    while len(chosen) < args.count and any(by_config.values()):
        for label in sorted(by_config, key=lambda k: per_config[k]):
            while by_config[label] and by_config[label][0][0] in chosen:
                by_config[label].pop(0)
            if by_config[label] and len(chosen) < args.count:
                lid, entry = by_config[label].pop(0)
                chosen[lid] = entry
                per_config[label] += 1

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    keep = set(chosen)
    for old in out.glob("mr-*.yaml"):
        if old.stem not in keep:
            old.unlink()
    index = []
    for lid, (candidate, label, seed) in sorted(chosen.items(), key=lambda kv: -kv[1][0].score):
        m = candidate.metrics
        tags = [name for name, test in BUCKETS if test(m)]
        data = layout_to_yaml_dict(
            candidate, name=lid,
            description=f"Gallery candidate ({label}, seed {seed}).",
            generator_info={"sets": SETS, "exclude": list(EXCLUDE), "config": label, "seed": seed, "score": round(candidate.score, 1)},
            available={k: (0 if k in EXCLUDE else v) for k, v in budget.counts.items()},
        )
        assert data["layout_id"] == lid
        (out / f"{lid}.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                                          encoding="utf-8")
        parts = Counter()
        for k, v in candidate.usage.items():
            parts[k] = v
        index.append({
            "id": lid,
            "file": f"examples/gallery/{lid}.yaml",
            "thumbnail": f"examples/gallery/thumbs/{lid}.jpg",
            "config": label,
            "seed": seed,
            "score": round(candidate.score, 1),
            "tags": tags,
            "metrics": {k: m[k] for k in ("levels", "rails", "exits", "random_branches",
                                          "rolling_length_cm", "min_exit_path_cm", "columns_on_rails",
                                          "footprint_area_cm2", "dead_area_cm2", "braces")}
                       | {"curves": m.get("curved_rails", 0), "twists": m.get("twists", 0),
                          "highest_exit": max(m["exit_levels"], default=0),
                          "parts": len(candidate.layout.parts), "covers": candidate.usage.get("cover", 0)},
        })
        print(f"{lid} {label:12s} score={candidate.score:.1f} tags={','.join(tags)}")
    (out / "index.json").write_text(json.dumps({"sets": SETS, "layouts": index}, indent=2) + "\n",
                                    encoding="utf-8")


if __name__ == "__main__":
    main()
