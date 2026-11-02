from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, resolve_set_paths
from quadrilla_solver.model import PortRef, layout_from_dict
from quadrilla_solver.rebuild import RebuildRefused, rebuild
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
EXAMPLE = ROOT / "examples" / "box_base" / "mr-5be5ce26.yaml"


def _load():
    data = yaml.safe_load(EXAMPLE.read_text())
    q = data["routing_query"]
    source = PortRef(q["source"]["component_id"], q["source"]["port"])
    sinks = tuple(PortRef(s["component_id"], s["port"]) for s in q["sinks"])
    return layout_from_dict(data), source, sinks


def _counts(*sets):
    return Budget.from_sets(resolve_set_paths(ROOT, list(sets))).counts


def test_a_split_is_added_and_the_part_above_kept():
    layout, source, sinks = _load()
    found = rebuild(layout, CATALOG, _counts("OWNED", "QD001"), source, sinks, "rail11", "split", attempts=30)
    assert found
    best = found[0]
    reds = lambda lay: Counter(p.part_type for p in lay.parts)["red_random_split"]
    assert reds(best["layout"]) > reds(layout)
    result = validate_layout(best["layout"], CATALOG, source=best["source"], sinks=best["sinks"])
    assert result.valid
    # the rails above rail11 are still there, moved as one piece
    above = [r for r in layout.rails if r.z_units > 54]
    moved = best["layout"].rail_map()
    dx, dy, dz = best["shift"]
    for r in above:
        m = moved[r.id]
        assert (m.x_cm - r.x_cm, m.y_cm - r.y_cm, m.z_units - r.z_units) == pytest.approx((dx, dy, dz))


def test_the_lower_part_stays_fixed():
    layout, source, sinks = _load()
    found = rebuild(layout, CATALOG, _counts("OWNED", "QD001"), source, sinks, "rail10", "add_rail", attempts=30)
    assert found
    new = found[0]["layout"].rail_map()
    for r in layout.rails:
        if r.z_units <= 48 and r.id != "rail10":
            assert new[r.id] == r


def test_a_rail_of_the_box_is_refused_with_a_reason():
    layout, source, sinks = _load()
    with pytest.raises(RebuildRefused) as refused:
        rebuild(layout, CATALOG, _counts("OWNED"), source, sinks, "rail5", "rebuild")
    assert refused.value.code == "cross_link"
