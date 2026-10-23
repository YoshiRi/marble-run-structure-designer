"""Browser entry point: run the generator under Pyodide.

The viewer's generator worker (`viewer/generator-worker.js`) copies the
package, the catalog and the set files into Pyodide's file system and calls
`generate_json`. Nothing here re-implements generation: it is the same
`generate()` the CLI and the gallery use, run in chunks so the page can show
progress.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .catalog import load_catalog
from .generator import Budget, GeneratorConfig, generate, layout_id, layout_to_yaml_dict, resolve_set_paths


def generate_layouts(options: Mapping[str, Any], root: str | Path,
                     progress: Callable[[int, int], Any] | None = None) -> list[dict[str, Any]]:
    """Generate layouts from simple options (all optional):

    sets, exclude, max_height, footprint [w, d], max_exits, max_rails,
    twist_probability, curve_bias, split_probability, attempts, seed, keep.
    Returns layout YAML mappings (as written by the CLI), best score first.
    """
    root = Path(root)
    catalog = load_catalog(root / "catalog" / "parts.yaml")
    sets = list(options.get("sets") or ["QD001", "QD003", "QD005"])
    exclude = tuple(options.get("exclude") or ())
    budget = Budget.from_sets(resolve_set_paths(root, sets))
    footprint = options.get("footprint") or (90.0, 90.0)
    config = GeneratorConfig(
        max_height_units=int(options.get("max_height", 24)),
        footprint_cm=(float(footprint[0]), float(footprint[1])),
        max_exits=int(options.get("max_exits", 2)),
        max_rails=int(options.get("max_rails", 12)),
        twist_probability=float(options.get("twist_probability", 0.5)),
        curve_ready_bias=float(options.get("curve_bias", 0.5)),
        split_probability=float(options.get("split_probability", 0.45)),
        exclude_parts=exclude,
    )
    attempts = int(options.get("attempts", 200))
    seed = int(options.get("seed", 1))
    keep = int(options.get("keep", 6))
    chunk = 25
    best: dict[str, Any] = {}
    done = 0
    while done < attempts:
        n = min(chunk, attempts - done)
        for candidate in generate(catalog, budget, config=config, attempts=n,
                                  seed=seed * 100003 + done, keep=keep):
            lid = layout_id(candidate.layout)
            if lid not in best or best[lid].score < candidate.score:
                best[lid] = candidate
        done += n
        if progress is not None:
            progress(done, attempts)
    available = {k: (0 if k in exclude else v) for k, v in budget.counts.items()}
    out = []
    for candidate in sorted(best.values(), key=lambda c: -c.score)[:keep]:
        lid = layout_id(candidate.layout)
        out.append(layout_to_yaml_dict(
            candidate, name=lid,
            description=f"Generated in the browser from sets {', '.join(sets)} (seed {seed}).",
            generator_info={"sets": sets, "exclude": list(exclude), "seed": seed, "attempts": attempts,
                            "score": round(candidate.score, 1)},
            available=available,
        ))
    return out


def generate_json(options_json: str, root: str, progress: Callable[[int, int], Any] | None = None) -> str:
    """JSON in, JSON out (keeps Pyodide conversions out of the way)."""
    return json.dumps(generate_layouts(json.loads(options_json), root, progress))
