import json
import subprocess
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.assembly_plan import bill_of_materials, build_plan, check_inventory
from quadrilla_solver.generator import layout_usage
from quadrilla_solver.model import load_layout

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = sorted((ROOT / "examples" / "gallery").glob("mr-*.yaml")) + [
    ROOT / "tests" / "fixtures" / name
    for name in ("twist-drop.yaml", "landing-tower.yaml", "stack-drop.yaml", "three-level-physically-connected.yaml")
]

NODE = """
const fs = require("fs");
const A = require("./viewer/assembly.js");
const layout = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({plan: A.buildPlan(layout), bom: A.billOfMaterials(layout)}));
"""


@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.stem)
def test_plan_places_everything_once_bottom_up(path):
    layout = load_layout(path)
    plan = build_plan(layout)
    assert plan[0]["kind"] == "parts" and plan[-1]["kind"] == "check"
    seen = [c for step in plan for c in step["components"]]
    assert sorted(seen) == sorted([r.id for r in layout.rails] + [p.id for p in layout.parts])
    placed: set[str] = set()
    for step in plan[1:-1]:
        for column in step["columns"]:
            if column["base"] != "ground":
                assert column["base"]["rail"] in placed, (step["rail"], column)
        placed.add(step["rail"])
        for free in step["free"]:
            assert step["rail"] in placed
    covers = sum(len(step.get("covers", ())) for step in plan)
    assert bill_of_materials(layout).get("cover", 0) == covers
    usage = {k: v for k, v in layout_usage(layout).items() if v}
    assert bill_of_materials(layout) == usage


@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.stem)
def test_browser_plan_matches_python(path):
    data = yaml.safe_load(path.read_text())
    out = subprocess.run(["node", "-e", NODE], input=json.dumps(data), cwd=ROOT,
                         capture_output=True, text=True, check=True)
    browser = json.loads(out.stdout)
    python = json.loads(json.dumps(build_plan(load_layout(path))))
    assert browser["plan"] == python
    assert browser["bom"] == bill_of_materials(load_layout(path))


def test_inventory_check_pools_long_rails_and_uses_wildcards():
    rows = {r["part"]: r for r in check_inventory(
        {"straight_long": 2, "straight_long_center": 2, "straight_short": 5, "blue": 4, "cover": 3},
        {"straight_long": 3, "straight_short": 4, "straight_unspecified": 1, "blue": 2, "cover": 9})}
    assert rows["straight_long"]["needed"] == 4 and rows["straight_long"]["available"] == 3
    shorts = rows["straight_long"]["short"] + rows["straight_short"]["short"]
    assert shorts == 1  # two missing straights, one wildcard
    assert rows["blue"]["short"] == 2 and rows["cover"]["short"] == 0
