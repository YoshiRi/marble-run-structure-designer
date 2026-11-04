import sys, time, json
from pathlib import Path
sys.path.insert(0, '/home/claude/marble-run-structure-designer/src')
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, GeneratorConfig, generate, resolve_set_paths
from quadrilla_solver.hints import extract_hints
from quadrilla_solver.hint_solver import parse_towers, GeometrySolver, RouteChecker
from quadrilla_solver.model import rail_hole_world
from math import cos, sin, radians
ROOT = Path('/home/claude/marble-run-structure-designer')
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
    if len(gt_pts)!=len(pts): return False
    g=sorted((round(x-min(a[0] for a in gt_pts),1),round(y-min(a[1] for a in gt_pts),1),z) for x,y,z in gt_pts)
    for v in variants(pts):
        if all(abs(a[0]-b[0])<0.6 and abs(a[1]-b[1])<0.6 and a[2]==b[2] for a,b in zip(g,v)): return True
    return False
def canon_holes(pts):
    return min(tuple((round(x),round(y),z) for x,y,z in v) for v in variants(pts))
def gt_holes(layout):
    return [ (x,y,z) for r in layout.rails if r.rail_type in ("straight_long","straight_long_center","straight_short")
             for k in range(len(CAT.rails[r.rail_type].holes_cm)) for (x,y,z) in [rail_hole_world(r,CAT,k)]]
def sol_holes(st):
    return [(x,y,r.z) for r in st.rails for (x,y) in r.holes]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
WITH_RAILS = len(sys.argv) > 3 and sys.argv[3] == 'rails'
for base in sys.argv[1].split(","):
    for seed in (11,12,13,14,15):
        gt = generate(CAT, owned, config=GeneratorConfig(**CASES[base]), attempts=60, seed=seed, keep=1)
        if not gt: print(base, seed, "no GT"); continue
        L = gt[0].layout
        if any(r.rail_type not in ("straight_long","straight_long_center","straight_short") for r in L.rails):
            print(base, seed, "skip (curves/twists)"); continue
        h = extract_hints(L, CAT, base)
        towers = parse_towers(h["towers"], CAT)
        solver = GeometrySolver(towers, h["parts"], CAT, max_nodes=100000, rail_towers=h["rails"] if WITH_RAILS else None)
        t = time.time(); gt_pts = gt_holes(L)
        n = found = 0; first_match = None; distinct = set(); routed = set(); gt_routed = False
        covers = h["parts"].get("cover", 0)
        for st in solver.solve():
            n += 1
            c = canon_holes(sol_holes(st))
            new = c not in distinct
            distinct.add(c)
            is_gt = match(gt_pts, sol_holes(st))
            if is_gt:
                found += 1
                first_match = first_match or len(distinct)
            if c not in routed and RouteChecker(st, towers, CAT, covers).valid():
                routed.add(c)
                gt_routed = gt_routed or is_gt
            if n >= LIMIT: break
        print(json.dumps({"base": base, "seed": seed, "rails": len(L.rails), "towers": len(towers),
                          "solutions": n, "distinct": len(distinct), "route_ok": len(routed), "gt_route_ok": gt_routed, "matching": found, "first_match_at": first_match,
                          "nodes": solver.nodes, "secs": round(time.time()-t,1)}))
