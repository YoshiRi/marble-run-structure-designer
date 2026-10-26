"""Preferences (generator-design.md, layer 4): metrics and the one score.

Scoring changes often (every review adds or retunes something), so it is
built to be extended in one place:

* A **metric** is a number measured on a finished build. Metrics measured on
  the final layout are registered here with `@layout_metric("key")`: a
  function of a `MetricContext` (layout, catalog, the marble's input, the
  routing graph). Construction-time metrics (levels, rolled length, ...) are
  still supplied by the generator (design doc §4: to be moved here).
* A **term** turns a metric into points: an entry in `SCORE_TERMS` with a
  sign, a default weight, a label, a help text and its source (review or
  goal). Terms are what the viewer's Generate dialog lists; a user's profile
  overrides weights by key. A weight of 0 switches a term off.

To add a preference: register a metric (if new) and add a term. Nothing else
changes: the generator, the gallery, the browser and the tunables file
(`scripts/make_py_manifest.py`) pick it up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .catalog import PartCatalog
from .connectivity import RoutingGraph, build_routing_graph
from .model import Layout, PortRef


@dataclass
class MetricContext:
    layout: Layout
    catalog: PartCatalog
    source: PortRef
    _graph: RoutingGraph | None = field(default=None, repr=False)

    @property
    def graph(self) -> RoutingGraph:
        if self._graph is None:
            self._graph = build_routing_graph(self.layout, self.catalog)
        return self._graph

    def reachable(self) -> set[str]:
        """Route nodes the marble can reach from the input."""
        edges = self.graph.edges
        seen, stack = {self.source.key}, [self.source.key]
        while stack:
            for nxt in edges.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen


LAYOUT_METRICS: dict[str, Callable[[MetricContext], float]] = {}


def layout_metric(key: str) -> Callable[[Callable[[MetricContext], float]], Callable[[MetricContext], float]]:
    """Register a metric measured on the final layout under `key`."""
    def register(fn: Callable[[MetricContext], float]) -> Callable[[MetricContext], float]:
        LAYOUT_METRICS[key] = fn
        return fn
    return register


def layout_metrics(layout: Layout, catalog: PartCatalog, source: PortRef) -> dict[str, float]:
    ctx = MetricContext(layout, catalog, source)
    return {key: fn(ctx) for key, fn in LAYOUT_METRICS.items()}


@layout_metric("merges")
def _merges(ctx: MetricContext) -> float:
    """Route nodes reached from two or more places (design doc §6.1)."""
    seen = ctx.reachable()
    incoming: dict[str, int] = {}
    for node in seen:
        for nxt in ctx.graph.edges.get(node, ()):
            incoming[nxt] = incoming.get(nxt, 0) + 1
    return float(sum(1 for k in incoming.values() if k >= 2))


@layout_metric("shared_towers")
def _shared_towers(ctx: MetricContext) -> float:
    """Spots (top view) where columns holding two or more different rails
    stand on top of each other: a tower through several rails (user idea,
    2026-10-25). Distances are 2D, so this works on any lattice."""
    spots: list[tuple[float, float, set[str]]] = []
    parts = ctx.layout.part_map()
    for s in ctx.layout.supports:
        if s.upper_rail_id is None or not s.stack_part_ids:
            continue
        p = parts.get(s.stack_part_ids[0])
        if p is None:
            continue
        for x, y, rails in spots:
            if (x - p.x_cm) ** 2 + (y - p.y_cm) ** 2 < 0.35 ** 2:
                rails.add(s.upper_rail_id)
                break
        else:
            spots.append((p.x_cm, p.y_cm, {s.upper_rail_id}))
    return float(sum(1 for _, _, rails in spots if len(rails) >= 2))


@layout_metric("switchbacks")
def _switchbacks(ctx: MetricContext) -> float:
    """Route rails lying right under another route rail of the same type,
    reversed (end A under end B): one step of a switchback (back and forth
    between two towers)."""
    from .model import rail_pose
    reached = {n.split(":", 1)[0] for n in ctx.reachable()}
    rails = [r for r in ctx.layout.rails if r.id in reached
             and ctx.catalog.rails[r.rail_type].shape not in ("arc", "twist")]

    def ends(r):
        spec = ctx.catalog.rails[r.rail_type]
        return rail_pose(r, spec, 0.0)[:2], rail_pose(r, spec, spec.length_cm)[:2]

    def near(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 < 0.35 ** 2

    count = 0
    for upper in rails:
        ua, ub = ends(upper)
        for lower in rails:
            if lower is upper or lower.rail_type != upper.rail_type or lower.z_units >= upper.z_units:
                continue
            la, lb = ends(lower)
            if near(ua, lb) and near(ub, la):
                count += 1
                break
    return float(count)


@layout_metric("triangles")
def _triangles(ctx: MetricContext) -> float:
    """Triangle bases (design doc §6.2): a hole plate resting on two rails
    that carries a column on its middle hole, as at the apex of the user's
    isosceles triangle. Recognized in any layout, placed or not."""
    rails = {r.id: r for r in ctx.layout.rails}
    count = 0
    for plate in ctx.layout.rails:
        if ctx.catalog.rails[plate.rail_type].shape != "plate":
            continue
        below = {s.lower_rail_id for s in ctx.layout.supports
                 if s.upper_rail_id == plate.id and s.lower_rail_id in rails}
        middle = len(ctx.catalog.rails[plate.rail_type].holes_cm) // 2
        carries = any(s.lower_rail_id == plate.id and s.lower_hole_index == middle and s.upper_rail_id
                      for s in ctx.layout.supports)
        if len(below) >= 2 and carries:
            count += 1
    return float(count)


@layout_metric("frame_turns")
def _frame_turns(ctx: MetricContext) -> float:
    """Longest run of drops along the route that each turn the marble 90
    degrees the same way (left, left, left...): the marble circling a frame
    (design doc §6.2). Three turns close a rectangle."""
    from math import cos, radians, sin
    seen = ctx.reachable()
    rails = {r.id: r for r in ctx.layout.rails}

    def rail_of(node: str) -> str | None:
        rid = node.split(":", 1)[0]
        return rid if rid in rails and ":hole:" in node else None

    nxt: dict[str, set[str]] = {}   # rail -> rails the marble drops onto next
    for node in seen:
        rid = rail_of(node)
        if rid is None:
            continue
        stack, done = list(ctx.graph.edges.get(node, ())), set()
        while stack:
            n = stack.pop()
            if n in done:
                continue
            done.add(n)
            other = rail_of(n)
            if other == rid:
                continue
            if other is not None:
                nxt.setdefault(rid, set()).add(other)
            else:
                stack.extend(ctx.graph.edges.get(n, ()))

    def heading(rid: str) -> tuple[float, float] | None:
        r = rails[rid]
        if ctx.catalog.rails[r.rail_type].shape in ("arc", "twist"):
            return None
        flip = {"a_to_b": 0.0, "b_to_a": 180.0}.get(r.flow_direction)
        if flip is None:
            return None
        a = radians(r.yaw_deg + flip)
        return cos(a), sin(a)

    def turn(a: str, b: str) -> int:
        ha, hb = heading(a), heading(b)
        if ha is None or hb is None or abs(ha[0] * hb[0] + ha[1] * hb[1]) > 0.1:
            return 0
        return 1 if ha[0] * hb[1] - ha[1] * hb[0] > 0 else -1

    best: dict[tuple[str, int], int] = {}

    def run(rid: str, sign: int) -> int:   # turns of `sign` in a row from rid
        key = (rid, sign)
        if key not in best:
            best[key] = 0
            best[key] = max((1 + run(o, sign) for o in nxt.get(rid, ()) if turn(rid, o) == sign), default=0)
        return best[key]

    return float(max((run(r, s) for r in rails for s in (1, -1)), default=0))


# One linear score. Each term: sign (+ reward, - penalty), default weight,
# label and help for the viewer, and where it came from.
SCORE_TERMS: tuple[dict[str, Any], ...] = (
    {"key": "levels", "sign": 1, "weight": 10.0, "label": "Levels",
     "help": "per level of drops", "source": "goal"},
    {"key": "rolling_length_cm", "sign": 1, "weight": 0.2, "label": "Total roll",
     "help": "per cm the marble rolls, all branches", "source": "review 1"},
    {"key": "min_exit_path_cm", "sign": 1, "weight": 0.15, "label": "Shortest branch",
     "help": "per cm of roll on the shortest start-to-exit path", "source": "review 1"},
    {"key": "random_branches", "sign": 1, "weight": 4.0, "label": "Branches",
     "help": "per random splitter", "source": "goal"},
    {"key": "merges", "sign": 1, "weight": 8.0, "label": "Merges",
     "help": "per place two routes join", "source": "official builds"},
    {"key": "switchbacks", "sign": 1, "weight": 4.0, "label": "Switchbacks",
     "help": "per rail lying right under a route rail of the same type, reversed",
     "source": "official builds (switchback pattern)"},
    {"key": "triangles", "sign": 1, "weight": 20.0, "label": "Triangle bases",
     "help": "per triangle base (a plate tying two side rails, carrying the median)",
     "source": "official builds; user (efficient structure, 2026-10-26)"},
    {"key": "frame_turns", "sign": 1, "weight": 2.0, "label": "Frame turns",
     "help": "per drop in the longest run turning the same way (the marble circling a frame)",
     "source": "official builds (design doc §6.2)"},
    {"key": "shared_towers", "sign": 1, "weight": 3.0, "label": "Shared towers",
     "help": "per spot where columns hold two or more rails one above the other",
     "source": "user idea (cohesion)"},
    {"key": "columns_on_rails", "sign": 1, "weight": 2.0, "label": "Stacked columns",
     "help": "per column standing on a rail", "source": "goal"},
    {"key": "curved_rails", "sign": 1, "weight": 3.0, "label": "Curves",
     "help": "per curved rail", "source": "variety"},
    {"key": "twists", "sign": 1, "weight": 5.0, "label": "Twists",
     "help": "per twist", "source": "variety"},
    {"key": "exit_height", "sign": -1, "weight": 1.5, "label": "High exits",
     "help": "per unit of height the marble leaves from (all exits)", "source": "review 1"},
    {"key": "weak_towers", "sign": -1, "weight": 15.0, "label": "Weak towers",
     "help": "per stack of 5+ blocks braced along one axis", "source": "reviews 2, 3"},
    {"key": "idle_rail_cm", "sign": -1, "weight": 0.2, "label": "Idle rail",
     "help": "per cm of rail the marble never rolls on (braces excluded)",
     "source": "reviews 3, dense-stack, layered-tower"},
    {"key": "dead_area_cm2", "sign": -1, "weight": 0.02, "label": "Unused area",
     "help": "per cm2 of top view taken by parts no marble rolls on", "source": "review 3"},
    {"key": "footprint_area_cm2", "sign": -1, "weight": 0.002, "label": "Footprint",
     "help": "per cm2 of the bounding box in top view", "source": "review 1"},
)
DEFAULT_WEIGHTS: dict[str, float] = {t["key"]: t["weight"] for t in SCORE_TERMS}

# Terms whose value is derived from other metrics rather than read directly.
DERIVED: dict[str, Callable[[Mapping[str, Any]], float]] = {
    "exit_height": lambda m: float(sum(m.get("exit_levels", ()))),
}


def term_value(key: str, metrics: Mapping[str, Any]) -> float:
    if key in DERIVED:
        return DERIVED[key](metrics)
    return float(metrics.get(key, 0) or 0)


def score(metrics: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> float:
    """Sum of sign x weight x value over SCORE_TERMS. `weights` overrides the
    default weight (magnitude) of any term by key; unknown keys are ignored."""
    chosen = {**DEFAULT_WEIGHTS, **{k: v for k, v in (weights or {}).items() if k in DEFAULT_WEIGHTS}}
    return sum(t["sign"] * float(chosen[t["key"]]) * term_value(t["key"], metrics) for t in SCORE_TERMS)


def score_breakdown(metrics: Mapping[str, Any], weights: Mapping[str, float] | None = None) -> dict[str, float]:
    """Points per term (for reports and the viewer)."""
    chosen = {**DEFAULT_WEIGHTS, **{k: v for k, v in (weights or {}).items() if k in DEFAULT_WEIGHTS}}
    return {t["key"]: round(t["sign"] * float(chosen[t["key"]]) * term_value(t["key"], metrics), 2)
            for t in SCORE_TERMS}
