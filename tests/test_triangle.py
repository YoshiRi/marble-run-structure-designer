"""The user's isosceles triangle base (design doc §6.2)."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.connectivity import build_routing_graph
from quadrilla_solver.model import layout_from_dict
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
DATA = yaml.safe_load((ROOT / "tests" / "fixtures" / "triangle-isosceles.yaml").read_text())


def _validate(data):
    return validate_layout(layout_from_dict(data), CATALOG)


def test_the_triangle_stands():
    result = _validate(DATA)
    assert result.valid, result


def test_the_median_fits_only_with_its_declared_play():
    for name in ("median_on_base", "median_on_plate"):
        data = copy.deepcopy(DATA)
        next(s for s in data["supports"] if s["name"] == name)["play_cm"] = 0.0
        reasons = _validate(data).assembly.reasons
        assert any(r.startswith(f"support_xy_mismatch:{name}") for r in reasons), reasons


def test_play_is_capped_by_the_catalog():
    data = copy.deepcopy(DATA)
    next(s for s in data["supports"] if s["name"] == "median_on_base")["play_cm"] = 0.8
    assert any(r.startswith("support_play_too_large:median_on_base") for r in _validate(data).assembly.reasons)


def test_nothing_rolls_on_the_plate():
    graph = build_routing_graph(layout_from_dict(DATA), CATALOG)
    assert not any(n.startswith("apex_plate:") and targets for n, targets in graph.edges.items())


def test_without_the_apex_columns_the_sides_tip():
    data = copy.deepcopy(DATA)
    data["supports"] = [s for s in data["supports"] if s["name"] not in ("col_left_3", "col_right_3")]
    assert not _validate(data).valid
