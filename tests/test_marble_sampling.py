"""Sampled marble runs in the browser engine agree with the analysis."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import validate_connectivity
from quadrilla_solver.model import PortRef, load_layout
from quadrilla_solver.validation import validate_layout


ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")

# Seeded PRNG (mulberry32) so the frequency check is reproducible.
NODE_SCRIPT = r"""
const fs = require("node:fs");
const {buildGraph, analyzeOutcomes, sampleRun} = require("./viewer/routing.js");
const {layout, catalog, source, runs} = JSON.parse(fs.readFileSync(0, "utf8"));
let seed = 12345;
const random = () => {
  seed |= 0; seed = seed + 0x6D2B79F5 | 0;
  let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
  return ((t ^ t >>> 14) >>> 0) / 4294967296;
};
const graph = buildGraph(layout, catalog);
const counts = {};
let firstPath = null;
for (let i = 0; i < runs; i++) {
  const run = sampleRun(layout, catalog, graph, source, random);
  if (!firstPath) firstPath = run.path;
  const key = run.complete ? run.exit : "incomplete:" + run.reason;
  counts[key] = (counts[key] || 0) + 1;
}
process.stdout.write(JSON.stringify({
  counts, firstPath, outcomes: analyzeOutcomes(layout, catalog, graph, source),
}));
"""


def _run(example: str, source: str, runs: int) -> dict:
    layout_data = yaml.safe_load((ROOT / "tests" / "fixtures" / example).read_text())
    completed = subprocess.run(
        ["node", "-e", NODE_SCRIPT],
        input=json.dumps({
            "layout": layout_data, "catalog": CATALOG.raw,
            "source": source, "runs": runs,
        }),
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


def test_random_split_example_is_a_valid_buildable_layout():
    layout = load_layout(ROOT / "tests" / "fixtures" / "random-split.yaml")
    result = validate_layout(
        layout, CATALOG, source=PortRef("upper", "end_a"),
        sinks=(PortRef("exit_front", "end_b"), PortRef("exit_rear", "end_b")),
    )
    assert result.valid, result


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_sampled_split_frequencies_match_analysis():
    data = _run("random-split.yaml", "upper:hole:0", 2000)
    probabilities = {e["node"]: e["probability"] for e in data["outcomes"]["exits"]}
    assert probabilities == {"exit_front:end_b": 0.5, "exit_rear:end_b": 0.5}
    assert set(data["counts"]) == set(probabilities)
    for node, count in data["counts"].items():
        # 2000 fair draws: well inside +/- 5 standard deviations (~112).
        assert abs(count - 1000) < 112, (node, count)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_sampled_deterministic_run_follows_solver_path():
    data = _run("three-level-physically-connected.yaml", "upper:end_a", 50)
    assert data["counts"] == {"exit:end_b": 50}
    layout = load_layout(ROOT / "tests" / "fixtures" / "three-level-physically-connected.yaml")
    solver = validate_connectivity(
        layout, CATALOG, PortRef("upper", "end_a"), (PortRef("exit", "end_b"),)
    )
    assert data["firstPath"] == list(solver.paths["exit:end_b"])
