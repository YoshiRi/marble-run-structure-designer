"""Layer 4: the score is extended in one place (scoring.py)."""
from pathlib import Path

import yaml

from quadrilla_solver import scoring
from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import layout_source
from quadrilla_solver.model import load_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")


def test_a_registered_metric_is_measured_and_scored(monkeypatch):
    monkeypatch.setitem(scoring.LAYOUT_METRICS, "rails_seen", lambda ctx: float(len(ctx.layout.rails)))
    term = {"key": "rails_seen", "sign": 1, "weight": 2.0, "label": "x", "help": "x", "source": "test"}
    monkeypatch.setattr(scoring, "SCORE_TERMS", scoring.SCORE_TERMS + (term,))
    monkeypatch.setitem(scoring.DEFAULT_WEIGHTS, "rails_seen", 2.0)
    path = sorted((ROOT / "examples" / "gallery").glob("mr-*.yaml"))[0]
    layout = load_layout(path)
    metrics = scoring.layout_metrics(layout, CATALOG, layout_source(yaml.safe_load(path.read_text())))
    assert metrics["rails_seen"] == len(layout.rails)
    assert scoring.score_breakdown(metrics)["rails_seen"] == 2.0 * len(layout.rails)
    assert scoring.score(metrics, {"rails_seen": 0}) == scoring.score(metrics) - 2.0 * len(layout.rails)


def test_score_is_the_sum_of_its_breakdown_and_ignores_unknown_weights():
    metrics = {"levels": 4, "rolling_length_cm": 100, "exit_levels": [2, 3], "merges": 1}
    assert abs(sum(scoring.score_breakdown(metrics).values()) - scoring.score(metrics)) < 1e-6
    assert scoring.score(metrics, {"no_such_term": 99}) == scoring.score(metrics)


def test_gallery_builds_have_no_merges_yet():
    for path in sorted((ROOT / "examples" / "gallery").glob("mr-*.yaml"))[:4]:
        data = yaml.safe_load(path.read_text())
        assert scoring.layout_metrics(load_layout(path), CATALOG, layout_source(data))["merges"] == 0
