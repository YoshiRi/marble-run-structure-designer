"""Measure the generator on fixed seeds (baseline for generator changes).

    python scripts/eval_generator.py [--seeds 1-5] [--attempts 150] [--keep 10]
        [--set key=value ...]   # GeneratorConfig fields, e.g. --set twist_probability=0.8

Prints the mean of each metric over the kept candidates, plus how many builds
were tried, how many validated, and the time per attempt. `merges` counts
route nodes the marble can reach from two or more places (design doc §6.1).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quadrilla_solver import generator as g  # noqa: E402
from quadrilla_solver.catalog import load_catalog  # noqa: E402
from quadrilla_solver.connectivity import build_routing_graph  # noqa: E402

SETS = ["QD001", "QD003", "QD005", "QDE6008AB05"]
METRICS = ["levels", "rails", "parts", "exits", "rolling_length_cm", "footprint_area_cm2",
           "dead_area_cm2", "idle_rail_cm", "weak_towers", "braces", "twists", "curved_rails"]


def merges(candidate, catalog) -> int:
    """Nodes reachable from the source that have 2+ incoming reachable edges."""
    graph = build_routing_graph(candidate.layout, catalog)
    edges = graph.edges if hasattr(graph, "edges") else graph.graph
    start = candidate.source.key
    seen, stack = {start}, [start]
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    incoming: dict[str, int] = {}
    for node in seen:
        for nxt in edges.get(node, ()):
            incoming[nxt] = incoming.get(nxt, 0) + 1
    return sum(1 for n, k in incoming.items() if k >= 2)


def seeds(text: str) -> list[int]:
    a, _, b = text.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", default="1-5")
    ap.add_argument("--attempts", type=int, default=150)
    ap.add_argument("--keep", type=int, default=10)
    ap.add_argument("--set", action="append", default=[], help="GeneratorConfig field=value")
    args = ap.parse_args()
    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    budget = g.Budget.from_sets(g.resolve_set_paths(ROOT, SETS))
    fields: dict = {"exclude_parts": ("red_right_angle",)}
    for item in args.set:
        key, _, value = item.partition("=")
        fields[key] = json.loads(value) if value[:1] in "[{0123456789-tf" else value
    config = g.GeneratorConfig(**fields)
    rows, counts = [], {"attempts": 0, "valid": 0}
    t0 = time.time()
    for seed in seeds(args.seeds):
        stats: dict = {}
        for c in g.generate(catalog, budget, config=config, attempts=args.attempts, seed=seed,
                            keep=args.keep, stats=stats):
            rows.append({**{k: c.metrics.get(k, 0) for k in METRICS}, "score": c.score,
                         "merges": merges(c, catalog)})
        for k in counts:
            counts[k] += stats.get(k, 0)
    elapsed = time.time() - t0
    out = {k: round(statistics.mean(r[k] for r in rows), 2) for k in [*METRICS, "merges", "score"]} if rows else {}
    out["with_merge_share"] = round(sum(1 for r in rows if r["merges"]) / len(rows), 2) if rows else 0
    out.update(candidates=len(rows), attempts=counts["attempts"], valid=counts["valid"],
               valid_rate=round(counts["valid"] / max(1, counts["attempts"]), 3),
               ms_per_attempt=round(1000 * elapsed / max(1, counts["attempts"]), 1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
