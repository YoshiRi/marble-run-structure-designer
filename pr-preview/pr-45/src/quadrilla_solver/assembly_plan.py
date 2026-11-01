"""Bottom-up build plan for a layout: one step per rail (user decision).

Mirrored in viewer/assembly.js (Build mode); tests compare the two.

Step 0 lists the parts; then each rail gets a step, lowest first: the columns
that hold it up (bottom to top, on the ground or on a lower rail's hole),
the rail itself (which hole rests on which column), its hole fittings
(covers, holes left open, holes dropping into a column) and the
free-standing blocks that stand on it (input block, twist entry block,
counterweights). A final step rolls the marble.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .model import Layout


def _rail_order(layout: Layout) -> list[str]:
    """Rails by level; a rail that another stands on (via a column) first."""
    rails = layout.rail_map()
    needs: dict[str, set[str]] = {r.id: set() for r in layout.rails}
    for s in layout.supports:
        if s.upper_rail_id in needs and s.lower_rail_id in rails and s.lower_rail_id != s.upper_rail_id:
            needs[s.upper_rail_id].add(s.lower_rail_id)
    order: list[str] = []
    placed: set[str] = set()
    while len(order) < len(rails):
        ready = [rid for rid in rails if rid not in placed and needs[rid] <= placed]
        if not ready:  # a cycle cannot be built bottom up; fall back to level order
            ready = [rid for rid in rails if rid not in placed]
        nxt = min(ready, key=lambda rid: (rails[rid].z_units, rid))
        order.append(nxt)
        placed.add(nxt)
    return order


def build_plan(layout: Layout) -> list[dict[str, Any]]:
    linked = {l.source.component_id for l in layout.route_links} | \
        {l.target.component_id for l in layout.route_links}
    steps: list[dict[str, Any]] = [{"kind": "parts", "components": []}]
    for rid in _rail_order(layout):
        rail = layout.rail_map()[rid]
        columns = [
            {"support": s.name, "parts": list(s.stack_part_ids),
             "base": ({"rail": s.lower_rail_id, "hole": s.lower_hole_index}
                      if s.lower_rail_id is not None else "ground"),
             "hole": s.upper_hole_index}
            for s in layout.supports if s.upper_rail_id == rid
        ]
        columns.sort(key=lambda c: c["hole"])
        free = [{"support": s.name, "parts": list(s.stack_part_ids), "hole": s.lower_hole_index}
                for s in layout.supports if s.upper_rail_id is None and s.lower_rail_id == rid]
        free.sort(key=lambda f: (f["hole"], f["support"]))
        states = {int(k): v for k, v in rail.hole_states.items()}
        steps.append({
            "kind": "rail",
            "rail": rid,
            "rail_type": rail.rail_type,
            "z_units": rail.z_units,
            "brace": not states and rid not in linked,
            "columns": columns,
            "rests": sorted([c["hole"], c["support"]] for c in columns),
            "covers": sorted(i for i, v in states.items() if v == "covered"),
            "open": sorted(i for i, v in states.items() if v == "open"),
            "drops": sorted(i for i, v in states.items() if v == "block_connected"),
            "free": free,
            "components": [pid for c in columns for pid in c["parts"]] + [rid]
                          + [pid for f in free for pid in f["parts"]],
        })
    steps.append({"kind": "check", "components": []})
    return steps


def bill_of_materials(layout: Layout) -> dict[str, int]:
    used = Counter(r.rail_type for r in layout.rails) + Counter(p.part_type for p in layout.parts)
    covers = sum(1 for r in layout.rails for v in r.hole_states.values() if v == "covered")
    if covers:
        used["cover"] = covers
    return dict(sorted(used.items()))


# Inventory pools, as in the generator: long rails with and without the center
# hole share the long-rail count; twists pool across sizes; any shortfall of
# straights may be met by `straight_unspecified` wildcards.
_POOL = {"straight_long_center": "straight_long", "spiral_large": "spiral", "spiral_small": "spiral"}


def check_inventory(used: Mapping[str, int], available: Mapping[str, int]) -> list[dict[str, Any]]:
    """Rows of needed / available / short per pooled part, plus a wildcard row."""
    needed: Counter = Counter()
    for part, n in used.items():
        needed[_POOL.get(part, part)] += n
    avail: Counter = Counter()
    for part, n in available.items():
        if isinstance(n, int):
            avail[_POOL.get(part, part)] += n
    rows = []
    straight_short = 0
    for part in sorted(needed):
        short = max(0, needed[part] - avail[part])
        if part in ("straight_short", "straight_long"):
            straight_short += short
        rows.append({"part": part, "needed": needed[part], "available": avail[part], "short": short})
    wild = avail["straight_unspecified"]
    if straight_short and wild:
        covered = min(wild, straight_short)
        for row in rows:
            if row["part"] in ("straight_short", "straight_long") and row["short"] and covered:
                take = min(row["short"], covered)
                row["short"] -= take
                row["wildcard"] = take
                covered -= take
    return rows
