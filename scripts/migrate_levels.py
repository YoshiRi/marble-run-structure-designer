"""Recompute the heights of layout files after a change of the level scale.

2026-10-24: one level is 1.2 cm and a standard block 5 levels (it was taken
as 1.5 cm and 4 levels). A layout's z values follow from its structure:

* a stack starts on the ground (z 0) or on the top of its lower rail
  (rail z + hole level + 1) and its parts follow each other with their
  catalog heights;
* a rail sits on its supporting stacks (stack top - hole level).

The script recomputes every z from the ground up. When the stacks under one
rail now end at different heights, purple drop blocks are added to the
shorter ones (just above their bottom part) so the rail lies level again.
Route links and other relations are not changed; validate afterwards.

    python scripts/migrate_levels.py FILE.yaml [...]   # rewrites in place
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quadrilla_solver.catalog import load_catalog  # noqa: E402

CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")


def hole_level(rail: dict, index: int | None) -> int:
    if index is None:
        return 0
    return CATALOG.rails[rail["rail_type"]].hole_level(int(index))


def migrate(data: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    rails = {r["id"]: r for r in data.get("rails", [])}
    parts = {p["id"]: p for p in data.get("parts", [])}
    supports = data.get("supports", [])
    known: dict[str, float] = {}       # rail id -> new z
    placed: set[str] = set()            # parts with their new z
    # A block outlet feeding a rail end (route link) keeps its height offset
    # to that rail, in levels: the rail rises (on padded supports) if needed.
    link_offsets: dict[str, list[tuple[str, float]]] = {}
    for link in data.get("route_links", []) or []:
        src, dst = link["source"]["component_id"], link["target"]["component_id"]
        if src in parts and dst in rails:
            link_offsets.setdefault(dst, []).append((src, rails[dst]["z_units"] - parts[src]["z_units"]))
    pending = list(range(len(supports)))
    tops: dict[int, float] = {}        # support index -> stack top (new)

    def base_of(s: dict) -> float | None:
        if s.get("lower_rail_id") is None:
            return 0.0
        lower = s["lower_rail_id"]
        if lower not in known:
            return None
        return known[lower] + hole_level(rails[lower], s.get("lower_hole_index")) + 1

    def stack(i: int, base: float) -> float:
        z = base
        for pid in supports[i]["stack_part_ids"]:
            parts[pid]["z_units"] = z
            placed.add(pid)
            z += CATALOG.height_units(parts[pid]["part_type"])
        return z

    def refill(i: int, top: float) -> bool:
        """Rebuild a ground stack's filler (below a routing top part, if its
        hole drops into it) to end exactly at `top`."""
        sup = supports[i]
        if sup.get("lower_rail_id") is not None:
            return False
        ids = list(sup["stack_part_ids"])
        upper = rails[sup["upper_rail_id"]]
        states = upper.get("hole_states") or {}
        connected = states.get(sup["upper_hole_index"], states.get(str(sup["upper_hole_index"]))) == "block_connected"
        keep_top = [ids[-1]] if connected else []
        body = ids[:-1] if connected else ids
        if not body or parts[body[0]]["part_type"] != "wooden_foundation":
            return False
        height = top - sum(CATALOG.height_units(parts[p]["part_type"]) for p in keep_top) - 1
        block = CATALOG.standard_block_units()
        fillers = [p for p in body[1:] if CATALOG.height_units(parts[p]["part_type"]) == block]
        n_blocks = min(len(fillers), int(height // block))
        new_body = [body[0], *fillers[:n_blocks]]
        for k in range(int(round(height - n_blocks * block))):
            pid = f"{sup.get('name') or body[0]}_fill{k}"
            parts[pid] = {"id": pid, "part_type": "purple_drop", "x_cm": parts[body[0]]["x_cm"],
                          "y_cm": parts[body[0]]["y_cm"], "z_units": 0}
            new_body.append(pid)
        for p in body:
            if p not in new_body:
                del parts[p]
        sup["stack_part_ids"] = [*new_body, *keep_top]
        tops[i] = stack(i, 0.0)
        return abs(tops[i] - top) < 1e-6

    for _ in range(len(supports) + len(rails) + 2):
        progressed = False
        for i in list(pending):
            base = base_of(supports[i])
            if base is None:
                continue
            tops[i] = stack(i, base)
            pending.remove(i)
            progressed = True
        # Rails whose supports all have their stacks.
        for rid, rail in rails.items():
            if rid in known:
                continue
            mine = [i for i, s in enumerate(supports) if s.get("upper_rail_id") == rid]
            if not mine:  # a free-floating preview rail: nothing to derive from
                known[rid] = rail["z_units"]
                progressed = True
                continue
            feeders = link_offsets.get(rid, [])
            if any(i in pending for i in mine) or any(src not in placed for src, _ in feeders):
                continue
            levels = {i: tops[i] - hole_level(rail, supports[i]["upper_hole_index"]) for i in mine}
            if feeders:
                # The feeding outlet fixes the rail's height; supports that
                # came out too tall are rebuilt to fit (ground stacks only).
                z = max(parts[src]["z_units"] + off for src, off in feeders)
                for i, at in list(levels.items()):
                    if at > z and refill(i, z + hole_level(rail, supports[i]["upper_hole_index"])):
                        levels[i] = z
                        notes.append(f"{rid}: column under hole {supports[i]['upper_hole_index']} refilled")
                z = max([z, *levels.values()])
            else:
                z = max(levels.values())
            for i, at in levels.items():
                short = round(z - at)
                if short <= 0:
                    continue
                ids = supports[i]["stack_part_ids"]
                first = parts[ids[0]]
                new = []
                for k in range(short):
                    pid = f"{supports[i].get('name') or ids[0]}_lvl{k}"
                    parts[pid] = {"id": pid, "part_type": "purple_drop", "x_cm": first["x_cm"],
                                  "y_cm": first["y_cm"], "z_units": 0}
                    new.append(pid)
                supports[i]["stack_part_ids"] = [ids[0], *new, *ids[1:]]
                base = base_of(supports[i])
                tops[i] = stack(i, base)
                notes.append(f"{rid}: +{short} purple under hole {supports[i]['upper_hole_index']}")
            rail["z_units"] = z
            known[rid] = z
            progressed = True
        if not progressed:
            break
    unresolved = [r for r in rails if r not in known]
    if unresolved or pending:
        raise ValueError(f"cannot place rails {unresolved} / supports {pending}")
    data["parts"] = list(parts.values())
    return data, notes


def main(paths: list[str]) -> None:
    for path in map(Path, paths):
        data = yaml.safe_load(path.read_text())
        data, notes = migrate(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        print(path, "; ".join(notes) or "heights recomputed")


if __name__ == "__main__":
    main(sys.argv[1:])
