import sys, time, json
from pathlib import Path
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'src'))
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
from quadrilla_solver.hints import extract_hints
from quadrilla_solver.hint_solver import parse_towers, GeometrySolver, RouteChecker, rank_key, balance
from quadrilla_solver.model import rail_hole_world
from math import cos, sin, radians
ROOT = Path(__file__).resolve().parents[1]
CAT = load_catalog(ROOT / 'catalog/parts.yaml')
owned = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"]))
PLAIN = dict(twist_probability=0, curve_ready_bias=0, seesaw_probability=0, frame_probability=0)
CASES = {
  "grid": dict(bases={"free": 1.0}, triangle_probability=0.0, max_height_units=30, max_rails=8, **PLAIN),
  "grid45": dict(bases={"free": 1.0}, triangle_probability=0.0, max_height_units=45, max_rails=12, **PLAIN),
  "ladder": dict(strategy="bottom_up", up_base="ladder", max_height_units=45, max_rails=12),
  "box": dict(strategy="bottom_up", up_base="box", max_height_units=60, max_rails=16),
}
def variants(pts):
    out=[]
    for q in range(4):
        for m in (1,-1):
            c,s_=round(cos(radians(90*q))),round(sin(radians(90*q)))
            o=[(c*x - s_*(m*y), s_*x + c*(m*y), z) for x,y,z in pts]
            mx=min(a[0] for a in o); my=min(a[1] for a in o)
            out.append(sorted((round(x-mx,1),round(y-my,1),z) for x,y,z in o))
    return out
def match(gt_pts, pts):
    """Same points (with the same labels) up to a turn, a mirror and a shift."""
    if len(gt_pts)!=len(pts): return False
    mx=min(a[0] for a in gt_pts); my=min(a[1] for a in gt_pts)
    g=[(x-mx,y-my,z) for x,y,z in gt_pts]
    for v in variants(pts):
        pool=list(v); ok=True
        for x,y,z in g:
            i=next((i for i,(a,b,c) in enumerate(pool) if c==z and abs(a-x)<0.6 and abs(b-y)<0.6), None)
            if i is None: ok=False; break
            pool.pop(i)
        if ok: return True
    return False
def canon_holes(pts):
    return min(tuple((round(x),round(y),z) for x,y,z in v) for v in variants(pts))
def gt_holes(layout):
    return [ (x,y,z) for r in layout.rails if r.rail_type in ("straight_long","straight_long_center","straight_short")
             for k in range(len(CAT.rails[r.rail_type].holes_cm)) for (x,y,z) in [rail_hole_world(r,CAT,k)]]
def sol_holes(st):
    # rail holes, and each tower's spot (labelled by its index) so that the
    # same holes with towers in other holes do not count as the answer
    return [(x,y,r.z) for r in st.rails for (x,y) in r.holes] + [(p[0], p[1], LABEL[t]) for t, p in st.pos.items()]
LABEL = []
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
OPTS = set(sys.argv[3].split(',')) if len(sys.argv) > 3 else set()
WITH_RAILS = 'rails' in OPTS
WITH_ROUTE = 'route' in OPTS
for base in sys.argv[1].split(","):
    for seed in [int(x) for x in __import__("os").environ.get("SEEDS","11,12,13,14,15").split(",")]:
        gt = generate(CAT, owned, config=GeneratorConfig(**CASES[base]), attempts=60, seed=seed, keep=1)
        if not gt: print(base, seed, "no GT"); continue
        L = gt[0].layout
        if any(r.rail_type not in ("straight_long","straight_long_center","straight_short") for r in L.rails):
            print(base, seed, "skip (curves/twists)"); continue
        h = extract_hints(L, CAT, base, gt[0].source)
        towers = parse_towers(h["towers"], CAT)
        solver = GeometrySolver(towers, h["parts"], CAT, max_nodes=int(__import__("os").environ.get("NODES","100000")), rail_towers=[{k: v for k, v in r.items() if not (k == "axis" and 'noaxis' in OPTS) and not (k == "order" and 'noorder' in OPTS)} for r in h["rails"]] if WITH_RAILS else None,
                                route=h["route"] if WITH_ROUTE else None, covers=None if 'nocovers' in OPTS else h["parts"].get("cover", 0))
        covers = None if 'nocovers' in OPTS else h["parts"].get("cover", 0)
        ranked = {}; gt_keys = set()
        kinds = {}; LABEL[:] = [1000 + kinds.setdefault(tuple(tw), len(kinds)) for tw in h['towers']]   # same-looking towers are interchangeable
        t = time.time(); gt_pts = gt_holes(L) + [(x, y, LABEL[i]) for i, (x, y) in enumerate(h['spots'])]
        n = found = 0; first_match = None; distinct = set(); routed = set(); gt_routed = False

        SAMPLE = 'sample' in OPTS
        it = solver.sample(int(__import__('os').environ.get('RESTARTS', '300')), int(__import__('os').environ.get('EACH', '3000'))) if SAMPLE else solver.solve()
        for st in it:
            n += 1
            c = canon_holes(sol_holes(st))
            new = c not in distinct
            distinct.add(c)
            is_gt = match(gt_pts, sol_holes(st))
            if is_gt:
                found += 1
                first_match = first_match or len(distinct)
            if c not in routed:
                res = RouteChecker(st, towers, CAT, covers, route=h['route'] if WITH_ROUTE else None).valid()
                if res:
                    routed.add(c)
                    gt_routed = gt_routed or is_gt
                    ranked[c] = rank_key(st, towers, CAT, res[0])
                    if is_gt: gt_keys.add(c)
            if n >= LIMIT: break
        order = sorted(ranked, key=ranked.get)
        balanced = sum(1 for k in ranked.values() if not k[0])
        gt_rank = min((order.index(k) + 1 for k in gt_keys), default=None)
        gt_key = ranked[min(gt_keys, key=order.index)] if gt_keys else None
        ties = sum(1 for k in ranked.values() if gt_key and k <= gt_key)
        print(json.dumps({"rank": gt_rank, "ties_upto_gt": ties, "balanced": balanced, "gt_key": gt_key}))
        print(json.dumps({"base": base, "seed": seed, "rails": len(L.rails), "towers": len(towers),
                          "solutions": n, "distinct": len(distinct), "route_ok": len(routed), "gt_route_ok": gt_routed, "matching": found, "first_match_at": first_match,
                          "nodes": solver.nodes, "secs": round(time.time()-t,1)}))
