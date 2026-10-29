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
from .generator import (
    SCORE_TERMS, Budget, GeneratorConfig, generate, layout_id, layout_to_dict, layout_to_yaml_dict,
    resolve_set_paths,
)
from .model import layout_from_dict
from .substitution import eligible_rails, shorten, substitute

# Style rules (generator-design.md, layer 3) the Generate dialog may change,
# with the GeneratorConfig field each sets. Limits keep the search sane.
STYLE_TUNABLES: tuple[dict[str, Any], ...] = (
    {"key": "max_rails", "label": "Max rails", "type": "int", "min": 4, "max": 20, "step": 1,
     "default": GeneratorConfig().max_rails, "help": "rails in one build, braces included", "source": "setup"},
    {"key": "min_support_reaction_g", "label": "Overhang margin (g)", "type": "float", "min": 0, "max": 80,
     "step": 5, "default": GeneratorConfig().min_support_reaction_g,
     "help": "a rail with a load outside its supports keeps at least this on the lighter support",
     "source": "review 3"},
    {"key": "block_exit_max_level", "label": "Highest block exit (u)", "type": "int", "min": 2, "max": 16,
     "step": 1, "default": GeneratorConfig().block_exit_max_level,
     "help": "a branch may end at a block outlet only this low", "source": "review 1"},
    {"key": "brace_towers", "label": "Brace weak towers", "type": "bool",
     "default": GeneratorConfig().brace_towers, "help": "lay marble-free rails across weak towers",
     "source": "review 3"},
    {"key": "seesaw_probability", "label": "Seesaw diamonds", "type": "float", "min": 0, "max": 1,
     "step": 0.1, "default": GeneratorConfig().seesaw_probability,
     "help": "chance to end a dive on a seesaw whose arms merge on a collector rail (search bias)",
     "source": "official builds"},
    *({"key": f"base_{name}", "label": label, "type": "float", "min": 0, "max": 5, "step": 0.5,
       "default": float((GeneratorConfig().bases or {}).get(name, 0.0)), "help": help_, "source": "user (base lottery)"}
      for name, label, help_ in (
          ("triangle", "Base: triangle", "weight of the isosceles triangle base in the draw (0: never)"),
          ("diamond", "Base: seesaw diamond", "weight of the seesaw split-and-merge base in the draw"),
          ("free", "Base: none", "weight of builds without a base design (the plain search)"))),
    {"key": "frame_probability", "label": "Frames", "type": "float", "min": 0, "max": 1,
     "step": 0.1, "default": GeneratorConfig().frame_probability,
     "help": "chance to start a frame (the marble circling a rectangle); only from 45 levels",
     "source": "official builds"},
    {"key": "switchback_probability", "label": "Switchbacks", "type": "float", "min": 0, "max": 1,
     "step": 0.1, "default": GeneratorConfig().switchback_probability,
     "help": "chance to land on a reversed rail right under the one above (back and forth between two towers)",
     "source": "official builds"},
    {"key": "align_start_depth", "label": "Align from depth", "type": "int", "min": 0, "max": 8, "step": 1,
     "default": GeneratorConfig().align_start_depth,
     "help": "switchbacks and alignment start below this many drops (branch first above it)",
     "source": "user idea"},
    {"key": "solve_supports", "label": "Solve supports", "type": "bool",
     "default": GeneratorConfig().solve_supports,
     "help": "re-solve the columns the marble never touches for all rails at once (fewer parts, slower)",
     "source": "two-phase design"},
    {"key": "strategy", "label": "Generation", "type": "choice", "choices": ["top_down", "bottom_up"],
     "default": GeneratorConfig().strategy,
     "help": "top_down: grow the route down from the input (base drawn by lottery); "
             "bottom_up: place the triangle base first and grow the route up from it",
     "source": "user (2026-10-27)"},
    {"key": "up_base", "label": "Bottom-up base", "type": "choice", "choices": ["triangle", "ladder"],
     "default": GeneratorConfig().up_base,
     "help": "what a bottom-up build grows from: the triangle base, or a ladder between two towers",
     "source": "user (2026-10-28)"},
    {"key": "exit_style", "label": "Exits", "type": "choice", "choices": ["contained", "any"],
     "default": GeneratorConfig().exit_style,
     "help": "contained: block outlets or dives only; any: rails may also roll off their end",
     "source": "review 1"},
)


def describe_tunables() -> dict[str, Any]:
    """What the Generate dialog can tune: score weights and style rules."""
    return {"weights": [dict(t) for t in SCORE_TERMS], "style": [dict(t) for t in STYLE_TUNABLES]}


def _style(options: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for t in STYLE_TUNABLES:
        if t["key"] not in (options.get("style") or {}):
            continue
        raw = options["style"][t["key"]]
        if t["type"] == "int":
            out[t["key"]] = max(t["min"], min(t["max"], int(raw)))
        elif t["type"] == "float":
            out[t["key"]] = max(t["min"], min(t["max"], float(raw)))
        elif t["type"] == "bool":
            out[t["key"]] = bool(raw)
        elif raw in t["choices"]:
            out[t["key"]] = raw
    return out


def generate_layouts(options: Mapping[str, Any], root: str | Path,
                     progress: Callable[[int, int], Any] | None = None) -> list[dict[str, Any]]:
    """Generate layouts from simple options (all optional):

    sets, exclude, max_height, footprint [w, d], max_exits, max_rails,
    twist_probability, curve_bias, split_probability, attempts, seed, keep,
    weights {term: weight} (see SCORE_TERMS), style {key: value} (STYLE_TUNABLES).
    Returns layout YAML mappings (as written by the CLI), best score first.
    """
    root = Path(root)
    catalog = load_catalog(root / "catalog" / "parts.yaml")
    sets = list(options.get("sets") or ["OWNED"])
    exclude = tuple(options.get("exclude") or ())
    budget = Budget.from_sets(resolve_set_paths(root, sets))
    footprint = options.get("footprint") or (90.0, 90.0)
    fields = dict(
        max_height_units=max(10, min(60, int(options.get("max_height", 30)))),
        footprint_cm=(float(footprint[0]), float(footprint[1])),
        max_exits=int(options.get("max_exits", 2)),
        max_rails=int(options.get("max_rails", 12)),
        twist_probability=float(options.get("twist_probability", 0.5)),
        curve_ready_bias=float(options.get("curve_bias", 0.5)),
        split_probability=float(options.get("split_probability", 0.45)),
        exclude_parts=exclude,
        weights={k: float(v) for k, v in (options.get("weights") or {}).items()} or None,
    )
    style = _style(options)
    bases = {k[5:]: style.pop(k) for k in list(style) if k.startswith("base_")}
    if bases:
        fields["bases"] = {**(GeneratorConfig().bases or {}), **bases}
    fields.update(style)
    config = GeneratorConfig(**fields)
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
                            "score": round(candidate.score, 1),
                            **({"weights": dict(config.weights)} if config.weights else {}),
                            **({"style": _style(options)} if _style(options) else {})},
            available=available,
        ))
    return out


def generate_json(options_json: str, root: str, progress: Callable[[int, int], Any] | None = None) -> str:
    """JSON in, JSON out (keeps Pyodide conversions out of the way)."""
    return json.dumps(generate_layouts(json.loads(options_json), root, progress))


# ---------------------------------------------------------------------------
# Edit mode: rail rewrites (layer 2) run here so the browser does not keep a
# second copy of the geometry. Block edits (type, rotation) are plain field
# changes and happen in the viewer. The viewer validates every result.

_STRUCTURE = ("rails", "parts", "supports", "route_links")


def rail_edits(data: Mapping[str, Any], root: str | Path) -> dict[str, list[str]]:
    """Which rail rewrites apply to each rail: {"rail id": ["curve", "shorten"]}."""
    catalog = load_catalog(Path(root) / "catalog" / "parts.yaml")
    layout = layout_from_dict(dict(data))
    curves = set(eligible_rails(layout))
    out: dict[str, list[str]] = {}
    for rail in layout.rails:
        ops = []
        if rail.id in curves:
            ops.append("curve")
        if shorten(layout, catalog, rail.id) or shorten(layout, catalog, rail.id, move_columns=True):
            ops.append("shorten")
        out[rail.id] = ops
    return out


def edit_layout(data: Mapping[str, Any], op: Mapping[str, Any], root: str | Path) -> list[dict[str, Any]]:
    """Apply one rail rewrite. op: {"op": "curve", "rail": id, "turn": "left"|"right"}
    or {"op": "shorten", "rail": id}. Returns candidate structures (rails,
    parts, supports, route_links), most natural first; the caller validates
    them and keeps the first that passes. Raises ValueError if the rewrite
    does not apply to that rail."""
    catalog = load_catalog(Path(root) / "catalog" / "parts.yaml")
    layout = layout_from_dict(dict(data))
    rail_id = str(op.get("rail"))
    if rail_id not in layout.rail_map():
        raise ValueError(f"no rail {rail_id}")
    kind = op.get("op")
    if kind == "curve":
        if rail_id not in eligible_rails(layout):
            raise ValueError(f"{rail_id} cannot become a curve: a linked end or a hole in use has no curve match")
        turn = "right" if op.get("turn") == "right" else "left"
        candidates = [substitute(layout, catalog, rail_id, turn)]
    elif kind == "shorten":
        # In place first; else moving a ground column along the rail.
        candidates = shorten(layout, catalog, rail_id) + shorten(layout, catalog, rail_id, move_columns=True)
        if not candidates:
            raise ValueError(f"{rail_id} cannot be shortened: its holes in use do not fit a short rail")
    else:
        raise ValueError(f"unknown edit {kind!r}")
    return [{k: v for k, v in layout_to_dict(c).items() if k in _STRUCTURE} for c in candidates]


def edit_json(request_json: str, root: str) -> str:
    """{"layout": ..., "op": ...} -> {"candidates": [...]} | {"error": "..."};
    {"layout": ..., "op": {"op": "options"}} -> {"options": {rail: [ops]}}."""
    request = json.loads(request_json)
    try:
        if (request.get("op") or {}).get("op") == "options":
            return json.dumps({"options": rail_edits(request["layout"], root)})
        return json.dumps({"candidates": edit_layout(request["layout"], request["op"], root)})
    except ValueError as error:
        return json.dumps({"error": str(error)})
