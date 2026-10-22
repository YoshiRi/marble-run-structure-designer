"""Build the review gallery: a diverse set of generated layouts with stable IDs.

Runs the generator under several configurations, removes duplicates by layout
ID, picks a diverse set (twists, curves, many exits, tall, heavily stacked, then
best score) and writes examples/gallery/<id>.yaml plus examples/gallery/index.json.

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
    Budget, GeneratorConfig, generate, layout_id, layout_to_yaml_dict, resolve_set_paths,
)

ROOT = Path(__file__).resolve().parents[1]
SETS = ["QD001", "QD003", "QD005", "QDE6008AB05"]

# (label, config overrides)
CONFIGS = [
    ("balanced", {}),
    ("more-splits", {"split_probability": 0.7}),
    ("more-curves", {"curve_ready_bias": 0.8}),
    ("more-twists", {"twist_probability": 0.9}),
    ("taller", {"max_height_units": 30, "max_rails": 14}),
    ("ground-drops", {"landing_probability": 0.3}),
]

# Feature buckets the selection tries to cover before filling by score.
BUCKETS = [
    ("twist", lambda m: m.get("twists", 0) >= 1),
    ("two twists", lambda m: m.get("twists", 0) >= 2),
    ("curves", lambda m: m.get("curved_rails", 0) >= 2),
    ("many exits", lambda m: m["exits"] >= 4),
    ("tall", lambda m: m["levels"] >= 6),
    ("stacked", lambda m: m["columns_on_rails"] >= 9),
    ("long roll", lambda m: m["rolling_length_cm"] >= 220),
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
        config = GeneratorConfig(**overrides)
        for seed in range(1, args.seeds + 1):
            for candidate in generate(catalog, budget, config=config, attempts=args.attempts,
                                      seed=seed, keep=3):
                lid = layout_id(candidate.layout)
                if lid not in pool or pool[lid][0].score < candidate.score:
                    pool[lid] = (candidate, label, seed)
            print(f"{label} seed {seed}: pool {len(pool)}")

    ranked = sorted(pool.items(), key=lambda kv: kv[1][0].score, reverse=True)
    chosen: dict[str, tuple] = {}
    for _, test in BUCKETS:
        for lid, entry in ranked:
            if lid not in chosen and test(entry[0].metrics):
                chosen[lid] = entry
                break
    # Fill by score, at most a few per configuration so the set stays varied.
    cap = max(2, -(-args.count // len(CONFIGS)) + 1)
    per_config = Counter(entry[1] for entry in chosen.values())
    for lid, entry in ranked:
        if len(chosen) >= args.count:
            break
        if lid in chosen or per_config[entry[1]] >= cap:
            continue
        chosen[lid] = entry
        per_config[entry[1]] += 1

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
            generator_info={"sets": SETS, "config": label, "seed": seed, "score": round(candidate.score, 1)},
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
                                          "rolling_length_cm", "columns_on_rails")}
                       | {"curves": m.get("curved_rails", 0), "twists": m.get("twists", 0),
                          "parts": len(candidate.layout.parts), "covers": candidate.usage.get("cover", 0)},
        })
        print(f"{lid} {label:12s} score={candidate.score:.1f} tags={','.join(tags)}")
    (out / "index.json").write_text(json.dumps({"sets": SETS, "layouts": index}, indent=2) + "\n",
                                    encoding="utf-8")


if __name__ == "__main__":
    main()
