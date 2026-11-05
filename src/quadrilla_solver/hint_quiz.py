"""Rebuild from hints by asking (user, 2026-11-05).

The hints (parts, towers, route, rails with their towers in order and axis)
leave many builds; this module lists them, picks the question that splits
them most evenly ("on this rail, which hole is tower B in, counting from the
end where tower A is?"), keeps the builds that agree with each answer, and
turns a build into a layout the viewer can show and roll.

    quiz = Quiz(hints, catalog)       # lists the candidate builds
    quiz.question()                   # the best question, or None when one build is left
    quiz.answer(qid, value)           # keeps the builds that agree
    quiz.layout(i)                    # build i as a layout dict
"""
from __future__ import annotations

from collections import Counter
from math import cos, log2, radians, sin
from typing import Any, Mapping

from .catalog import PartCatalog
from .hint_solver import RAIL, GeometrySolver, RouteChecker, parse_towers
from .model import Layout, PlacedPart, PlacedRail, PortRef, RouteLink, SupportLink


class Candidate:
    def __init__(self, state, route):
        self.state, self.route = state, route


def _canon(state, labels) -> tuple:
    pts = [(x, y, r.z) for r in state.rails for (x, y) in r.holes] + \
        [(p[0], p[1], 1000 + labels[t]) for t, p in state.pos.items()]
    best = None
    for q in range(4):
        for m in (1, -1):
            c, s = round(cos(radians(90 * q))), round(sin(radians(90 * q)))
            o = [(c * x - s * m * y, s * x + c * m * y, z) for x, y, z in pts]
            mx, my = min(a[0] for a in o), min(a[1] for a in o)
            key = tuple(sorted((round(x - mx), round(y - my), z) for x, y, z in o))
            best = key if best is None or key < best else best
    return best


class Quiz:
    def __init__(self, hints: Mapping[str, Any], catalog: PartCatalog, max_nodes: int = 300000,
                 limit: int = 20000):
        self.hints, self.catalog = hints, catalog
        self.towers = parse_towers(hints["towers"], catalog)
        covers = hints["parts"].get("cover")
        self.solver = GeometrySolver(self.towers, hints["parts"], catalog, max_nodes=max_nodes,
                                     rail_towers=hints.get("rails"), route=hints.get("route"), covers=covers)
        kinds: dict = {}
        labels = [kinds.setdefault(tuple(t), len(kinds)) for t in hints["towers"]]
        seen, self.cands = set(), []
        for st in self.solver.solve():
            key = _canon(st, labels)
            if key in seen:
                continue
            seen.add(key)
            res = RouteChecker(st, self.towers, catalog, covers, route=hints.get("route")).valid()
            if res:
                self.cands.append(Candidate(st, res[0]))
                if len(self.cands) >= limit:
                    break
        self.complete = self.solver.nodes <= self.solver.max_nodes and len(self.cands) < limit
        self.asked: list[tuple[str, Any]] = []

    # ---- questions ------------------------------------------------------------

    def _rail_of(self, c: Candidate, i: int):
        """The candidate's rail for hinted rail i (same type and towers)."""
        want = self.hints["rails"][i]
        towers = set(want["towers"])
        for ri, r in enumerate(c.state.rails):
            mine = set(r.taken.values()) | ({r.end_tower} if r.end_tower is not None else set())
            if r.kind == want["type"] and mine == towers:
                return ri, r
        return None, None

    def features(self, c: Candidate) -> dict[str, Any]:
        """Answers this build gives to every question: for each hinted rail and
        each tower on it, the hole number counted from the end where the
        rail's first tower (in the hinted order) is."""
        out = {}
        for i, want in enumerate(self.hints.get("rails") or []):
            ri, r = self._rail_of(c, i)
            if r is None:
                continue
            n = len(r.holes)
            seq = ([r.end_tower] if r.end_tower is not None else []) + [r.taken[h] for h in sorted(r.taken)]
            forward = not want.get("order") or seq[0] == want["order"][0]
            for h, t in r.taken.items():
                out[f"hole:{i}:{t}"] = h + 1 if forward else n - h
        # parallel rails: does rail k run the same way as rail i (from the
        # first tower of its order to the last)?
        rails = self.hints.get("rails") or []
        vec = {}
        for i, want in enumerate(rails):
            order = want.get("order") or []
            if len(order) >= 2 and order[0] in c.state.pos and order[-1] in c.state.pos:
                a, b = c.state.pos[order[0]], c.state.pos[order[-1]]
                vec[i] = (b[0] - a[0], b[1] - a[1])
        for i in vec:
            for k in vec:
                if i < k and rails[i].get("axis") is not None and rails[i].get("axis") == rails[k].get("axis"):
                    dot = vec[i][0] * vec[k][0] + vec[i][1] * vec[k][1]
                    out[f"dir:{i}:{k}"] = "same" if dot > 0 else "opposite"
        return out

    def question(self) -> dict[str, Any] | None:
        if len(self.cands) <= 1:
            return None
        asked = {q for q, _ in self.asked}      # answered or skipped
        tallies: dict[str, Counter] = {}
        for c in self.cands:
            for q, v in self.features(c).items():
                if q not in asked:
                    tallies.setdefault(q, Counter())[v] += 1
        best, best_gain = None, 0.0
        n = len(self.cands)
        for q, tally in tallies.items():
            if len(tally) < 2:
                continue
            gain = -sum(k / n * log2(k / n) for k in tally.values())    # entropy of the answer
            if gain > best_gain + 1e-9:
                best, best_gain = q, gain
        if best is None:
            return None
        kind, i, t = best.split(":")
        i, t = int(i), int(t)
        options = [{"value": v, "count": k} for v, k in sorted(tallies[best].items())]
        if kind == "dir":
            return {"id": best, "kind": "dir", "rail": i, "other": t, "options": options,
                    "order": self.hints["rails"][i].get("order"), "other_order": self.hints["rails"][t].get("order")}
        rail = self.hints["rails"][i]
        order = rail.get("order") or rail["towers"]
        holes = len(self.catalog.rails[rail["type"]].holes_cm)
        return {"id": best, "kind": "hole", "rail": i, "rail_type": rail["type"], "tower": t, "from_tower": order[0],
                "order": order, "holes": holes, "options": options}

    def answer(self, qid: str, value: Any) -> int:
        self.asked.append((qid, value))
        self.cands = [c for c in self.cands if self.features(c).get(qid) == value]
        return len(self.cands)

    # ---- a build as a layout ----------------------------------------------------

    def layout(self, index: int = 0, name: str = "hint rebuild") -> dict[str, Any]:
        from .generator import layout_to_dict
        layout, source, sinks = self.to_layout(self.cands[index], name)
        out = layout_to_dict(layout, source, sinks)
        out["name"] = name
        return out

    def to_layout(self, c: Candidate, name: str):
        st, route, cat = c.state, c.route, self.catalog
        rails, rail_at = [], {}
        for ri, r in enumerate(st.rails):
            cm = cat.rails[r.kind].holes_cm
            d = (cos(radians(r.yaw)), sin(radians(r.yaw)))
            x0, y0 = r.holes[0][0] - cm[0] * d[0], r.holes[0][1] - cm[0] * d[1]
            flow = route["flow"].get(ri, 1)
            states = {}
            for (rj, h) in route["covered"]:
                if rj == ri:
                    states[h] = "covered"
            for (rj, h), what in route["stops"].items():
                if rj == ri:
                    states[h] = "block_connected" if what == "block" else "open"
            kw = {}
            if isinstance(flow, tuple):
                kw = {"flow_direction": "from_hole", "flow_hole": flow[1]}
            else:
                kw = {"flow_direction": "a_to_b" if flow > 0 else "b_to_a"}
            rails.append(PlacedRail(f"rail{ri}", r.kind, round(x0, 4), round(y0, 4), r.z, round(r.yaw % 360, 4),
                                    hole_states=states, **kw))
            for h, t in r.taken.items():
                rail_at[(t, r.z)] = (ri, h)
        parts, supports, links = [], [], []
        part_id: dict[tuple[int, int], str] = {}
        for tw in self.towers:
            t = tw.index
            if t not in st.base:
                continue
            x, y = st.pos[t]
            z = st.base[t]
            seg, lower = [], None
            for j, tok in enumerate(tw.tokens + [None]):
                if tok is None or tok == RAIL:
                    upper = rail_at.get((t, z)) if tok == RAIL else None
                    if seg:
                        supports.append(SupportLink(
                            f"rail{upper[0]}" if upper else None, upper[1] if upper else None, tuple(seg),
                            f"rail{lower[0]}" if lower else None, lower[1] if lower else None, name=f"t{t}_{j}"))
                    seg, lower = [], (upper if tok == RAIL else None)
                    if tok == RAIL:
                        z += 1
                    continue
                kind = tok.rstrip("<>")
                heading = None
                if (t, j) in route["turn"]:
                    ri = (lower or rail_at.get((t, z)))[0] if (lower or rail_at.get((t, z))) else None
                    if ri is not None:
                        yaw = st.rails[ri].yaw
                        heading = yaw if route["turn"][(t, j)] > 0 else yaw + 180
                if tok.endswith(">"):
                    for ri, r in enumerate(st.rails):
                        if r.end_tower == t and r.z in (z, z - 1):
                            heading = r.yaw
                            links.append(RouteLink(PortRef(f"t{t}_{j}_{kind}", "front"), PortRef(f"rail{ri}", "end_a")))
                rot = int(round((heading - 90) % 360)) if heading is not None else 0
                pid = f"t{t}_{j}_{kind}"
                parts.append(PlacedPart(pid, kind, round(x, 4), round(y, 4), z, rot))
                part_id[(t, j)] = pid
                seg.append(pid)
                z += cat.height_units(kind)
        layout = Layout(name, rails=tuple(rails), parts=tuple(parts), supports=tuple(supports),
                        route_links=tuple(links))
        t0, j0 = route["start"]
        source = PortRef(part_id[(t0, j0)], "top")
        sinks = []
        for ri, h in route["exits"]:
            if h == "end":
                flow = route["flow"].get(ri, 1)
                sinks.append(PortRef(f"rail{ri}", "end_b" if flow == 1 else "end_a"))
            else:
                sinks.append(PortRef(f"rail{ri}", f"hole:{h}"))
        return layout, source, tuple(sinks)
