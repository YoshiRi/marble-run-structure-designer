"""viewer/validation.js must agree with the Python validators.

Every gallery layout, sample and fixture, plus mutations that break each
validator, is validated by both; reasons must match exactly and numbers to
1e-6 (the browser editor relies on this to check edits live).
"""
import copy
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import layout_sinks, layout_source
from quadrilla_solver.model import load_layout
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog" / "parts.yaml"
CATALOG = load_catalog(CATALOG_PATH)
CATALOG_DATA = yaml.safe_load(CATALOG_PATH.read_text())

NODE = r"""
const fs = require("node:fs");
const V = require("./viewer/validation.js");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.items.map(c =>
  V.validateLayout(c.layout, cases.catalog, { source: c.source, sinks: c.sinks }))));
"""

LAYOUTS = (sorted((ROOT / "examples" / "gallery").glob("mr-*.yaml"))
           + sorted((ROOT / "examples" / "generated").glob("*.yaml"))
           + sorted((ROOT / "tests" / "fixtures").glob("*.yaml")))


def _query(data):
    query = data.get("routing_query") or {}
    if not query.get("source") or not query.get("sinks"):
        return None, []
    source = layout_source(data)
    return source, list(layout_sinks(data))


def _mutations(name, data):
    """A few broken variants per layout, each hitting a different validator."""
    out = [(name, data)]
    if data.get("parts"):
        m = copy.deepcopy(data)
        m["parts"][0]["z_units"] = float(m["parts"][0]["z_units"]) + 1  # stack mismatch
        out.append((name + "+zshift", m))
        m = copy.deepcopy(data)
        p = copy.deepcopy(m["parts"][-1])
        p["id"] = "intruder"
        p["x_cm"] = float(p["x_cm"]) + 1.0  # overlaps its neighbour
        m["parts"].append(p)
        out.append((name + "+intruder", m))
    if data.get("supports"):
        m = copy.deepcopy(data)
        m["supports"] = m["supports"][1:]  # a rail loses a support
        out.append((name + "+nosupport", m))
    if data.get("rails"):
        m = copy.deepcopy(data)
        m["rails"][0]["x_cm"] = float(m["rails"][0]["x_cm"]) + 0.7  # off its columns
        out.append((name + "+railshift", m))
    if data.get("rails"):
        out.append((name + "+rot60", _rotated(data, 60.0)))  # off the 90-degree grid (triangles)
    if any(p["part_type"] == "seesaw" for p in data.get("parts", [])):
        out.extend(_seesaw_mutations(name, data))
    third = _third_support(data)
    if third is not None:
        out.append((name + "+thirdsupport", third))
    return out


def _third_support(data):
    """A third ground column under a rail's free hole (statics: outer two)."""
    import math
    for rail in data.get("rails", []):
        if rail["rail_type"] != "straight_long_center":
            continue
        used = {s["upper_hole_index"] for s in data["supports"] if s.get("upper_rail_id") == rail["id"]}
        if len(used) != 2 or 2 in used:
            continue
        m = copy.deepcopy(data)
        yaw = math.radians(float(rail.get("yaw_deg", 0)))
        x = float(rail["x_cm"]) + 25.0 * math.cos(yaw)
        y = float(rail["y_cm"]) + 25.0 * math.sin(yaw)
        ids = ["third_f"] + [f"third_p{i}" for i in range(int(rail["z_units"]) - 1)]
        m["parts"] += [{"id": ids[0], "part_type": "wooden_foundation", "x_cm": x, "y_cm": y, "z_units": 0}]
        m["parts"] += [{"id": pid, "part_type": "purple_drop", "x_cm": x, "y_cm": y, "z_units": i + 1}
                       for i, pid in enumerate(ids[1:])]
        m["supports"].append({"name": "third", "upper_rail_id": rail["id"], "upper_hole_index": 2,
                              "stack_part_ids": ids})
        return m
    return None


def _rotated(data, deg):
    """The whole layout turned about the origin: rails and parts at angles
    that are not multiples of 90 degrees."""
    import math
    m = copy.deepcopy(data)
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    for item in m.get("rails", []) + m.get("parts", []):
        x, y = float(item["x_cm"]), float(item["y_cm"])
        item["x_cm"], item["y_cm"] = x * c - y * s, x * s + y * c
        key = "yaw_deg" if item in m.get("rails", []) else "rotation_deg"
        item[key] = (float(item.get(key, 0)) + deg) % 360
    return m


def _seesaw_mutations(name, data):
    """Seesaw and pivot-rail rules: mount, alignment, flow, feed height."""
    def variant(tag, fn):
        m = copy.deepcopy(data)
        fn(m)
        return (f"{name}+{tag}", m)

    def seesaw(m):
        return next(p for p in m["parts"] if p["part_type"] == "seesaw")

    def host(m):
        sid = seesaw(m)["id"]
        rid = next(s["lower_rail_id"] for s in m["supports"] if sid in s["stack_part_ids"])
        return next(r for r in m["rails"] if r["id"] == rid)

    def others(m):
        return [r for r in m["rails"] if r["id"] != host(m)["id"]]

    return [
        variant("turned", lambda m: seesaw(m).update(rotation_deg=90)),
        variant("hostflow", lambda m: host(m).update(flow_direction="a_to_b")),
        variant("nopivot", lambda m: host(m).update(flow_hole=None)),
        variant("collector", lambda m: host(m).update(flow_direction="to_hole")),
        variant("toohigh", lambda m: [r.update(z_units=float(r["z_units"]) + 8) for r in others(m)]),
        variant("covered", lambda m: [r.setdefault("hole_states", {}).update({i: "covered" for i in range(4)})
                                      for r in others(m)]),
    ]


def _python(data, source, sinks, tmp_path):
    path = tmp_path / "layout.yaml"
    path.write_text(yaml.safe_dump(data))
    try:
        result = validate_layout(load_layout(path), CATALOG, source=source, sinks=sinks)
    except Exception as error:  # noqa: BLE001 - statics raise on impossible input
        return {"error": str(error)}
    statics = result.local_statics
    return {
        "valid": result.valid,
        "assembly": {"valid": result.assembly.valid, "reasons": list(result.assembly.reasons),
                     "warnings": list(result.assembly.warnings)},
        "global": {"evaluable": result.global_stability.evaluable, "stable": result.global_stability.stable,
                   "mass": result.global_stability.total_mass_g, "com": result.global_stability.com_xyz_cm,
                   "margin": result.global_stability.margin_cm,
                   "reasons": list(result.global_stability.reasons)},
        "statics": {"evaluable": statics.evaluable, "reasons": list(statics.reasons),
                    "valid": statics.statics.valid if statics.statics else None,
                    "struct_reasons": list(statics.statics.reasons) if statics.statics else None,
                    "reactions": {k: [r.force_n for r in v.reactions] for k, v in statics.statics.rails.items()}
                    if statics.statics else None},
        "connectivity": None if result.connectivity is None else {
            "valid": result.connectivity.valid, "reached": list(result.connectivity.reached_sinks),
            "nodes": list(result.connectivity.reachable_nodes), "dead": list(result.connectivity.dead_ends),
            "reasons": list(result.connectivity.reasons),
            "paths": {k: list(v) for k, v in result.connectivity.paths.items()}},
        "clearance": list(result.marble_clearance),
    }


def _browser_view(b):
    st = b["local_statics"]
    return {
        "valid": b["valid"],
        "assembly": b["assembly"],
        "global": {"evaluable": b["global_stability"]["evaluable"], "stable": b["global_stability"]["stable"],
                   "mass": b["global_stability"]["total_mass_g"], "com": b["global_stability"]["com_xyz_cm"],
                   "margin": b["global_stability"]["margin_cm"], "reasons": b["global_stability"]["reasons"]},
        "statics": {"evaluable": st["evaluable"], "reasons": st["reasons"],
                    "valid": st["statics"]["valid"] if st["statics"] else None,
                    "struct_reasons": st["statics"]["reasons"] if st["statics"] else None,
                    "reactions": {k: [r["force_n"] for r in v["reactions"]] for k, v in st["statics"]["rails"].items()}
                    if st["statics"] else None},
        "connectivity": None if b["connectivity"] is None else {
            "valid": b["connectivity"]["valid"], "reached": b["connectivity"]["reached_sinks"],
            "nodes": b["connectivity"]["reachable_nodes"], "dead": b["connectivity"]["dead_ends"],
            "reasons": b["connectivity"]["reasons"], "paths": b["connectivity"]["paths"]},
        "clearance": b["marble_clearance"],
    }


def _close(a, b, where="root"):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), (where, set(a) ^ set(b))
        for k in a:
            _close(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert len(a) == len(b), (where, a, b)
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{where}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            assert a == b, (where, a, b)
        elif math.isinf(a) or math.isinf(b):
            assert a == b, (where, a, b)
        else:
            assert abs(a - b) <= 1e-6 * max(1.0, abs(a)), (where, a, b)
    else:
        assert a == b, (where, a, b)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for parity check")
@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.stem)
def test_browser_validators_match_python(path, tmp_path):
    data = yaml.safe_load(path.read_text())
    source, sinks = _query(data)
    items, expected = [], []
    for name, variant in _mutations(path.stem, data):
        py = _python(variant, source, sinks, tmp_path)
        if "error" in py:
            continue  # Python raises on impossible statics; the browser reports instead
        items.append({"layout": variant, "source": source.key if source else None,
                      "sinks": [s.key for s in sinks]})
        expected.append((name, py))
    out = subprocess.run(["node", "-e", NODE], input=json.dumps({"catalog": CATALOG_DATA, "items": items}),
                         cwd=ROOT, capture_output=True, text=True, check=True)
    browser = json.loads(out.stdout)
    assert len(browser) == len(expected)
    for (name, py), b in zip(expected, browser):
        js = _browser_view(b)
        # JSON turns Python tuples into lists; com/margin are numbers or None.
        try:
            _close(json.loads(json.dumps(py)), js)
        except AssertionError as error:
            raise AssertionError(f"{name}: {error}") from None
    # The mutations really exercise the validators.
    assert any(not py["valid"] for _, py in expected[1:]) or len(expected) == 1


def test_g6_matches_python_format():
    values = [0.0, -0.0, 1.0, 12.5, -3.25, 1e-5, 0.0001234, 123456.0, 1234567.0, 8.695291777188329, 2.4492935982947064e-16]
    out = subprocess.run(["node", "-e", "const V=require('./viewer/validation.js');"
                          "process.stdout.write(JSON.stringify(" + json.dumps(values) + ".map(V.g6)))"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [format(v, ".6g") for v in values]
