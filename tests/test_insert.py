from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.generator import Budget, resolve_set_paths
from quadrilla_solver.insert import EditRefused, LIFT, insert_switchback, split_at
from quadrilla_solver.model import PortRef, layout_from_dict
from quadrilla_solver.validation import validate_layout

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog(ROOT / "catalog" / "parts.yaml")
COUNTS = Budget.from_sets(resolve_set_paths(ROOT, ["OWNED"])).counts


def _load(name):
    data = yaml.safe_load((ROOT / "examples" / name).read_text())
    q = data["routing_query"]
    return (layout_from_dict(data), PortRef(q["source"]["component_id"], q["source"]["port"]),
            tuple(PortRef(s["component_id"], s["port"]) for s in q["sinks"]))


def test_a_switchback_goes_in_low_in_a_box_and_everything_above_rises():
    layout, source, sinks = _load("box_base/mr-5be5ce26.yaml")
    part = layout.part_map()["c6_0_green"]           # a drop block inside the box
    level = part.z_units + 5
    found = insert_switchback(layout, CATALOG, COUNTS, source, sinks, "c6_0_green")
    assert found
    best = found[0]
    assert validate_layout(best["layout"], CATALOG, source=best["source"], sinks=best["sinks"]).valid
    new = best["layout"].rail_map()
    for r in layout.rails:
        assert new[r.id].z_units == r.z_units + (LIFT if r.z_units >= level else 0)
        assert (new[r.id].x_cm, new[r.id].y_cm) == (r.x_cm, r.y_cm)
    assert len(best["layout"].rails) == len(layout.rails) + 2


def test_split_here_turns_the_block_red_and_adds_an_exit():
    layout, source, sinks = _load("gallery/mr-52360cae.yaml")
    best = split_at(layout, CATALOG, source, sinks, "c6_0_yellow")[0]
    assert best["layout"].part_map()["c6_0_yellow"].part_type == "red_random_split"
    assert len(best["sinks"]) == len(sinks) + 1
    assert validate_layout(best["layout"], CATALOG, source=best["source"], sinks=best["sinks"]).valid


def test_split_needs_a_free_hole_behind():
    layout, source, sinks = _load("ladder/mr-cee16024.yaml")
    with pytest.raises(EditRefused) as refused:
        split_at(layout, CATALOG, source, sinks, "c7_0_green")
    assert refused.value.code == "no_back_hole"
