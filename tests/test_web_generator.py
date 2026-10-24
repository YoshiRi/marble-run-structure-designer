"""The browser generator (Pyodide) runs quadrilla_solver.web unchanged."""
import json
from pathlib import Path

from quadrilla_solver.generator import layout_id, layout_sinks, layout_source
from quadrilla_solver.validation import validate_layout
from quadrilla_solver.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_py_manifest_lists_every_file_the_worker_needs():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_py_manifest", ROOT / "scripts" / "make_py_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = json.loads((ROOT / "viewer" / "py-manifest.json").read_text())
    assert committed == module.manifest(), "run scripts/make_py_manifest.py"
    assert all((ROOT / f).exists() for f in committed["files"])


def test_generate_json_returns_valid_layouts(tmp_path):
    from quadrilla_solver.web import generate_json
    import yaml

    seen = []
    out = json.loads(generate_json(json.dumps({
        "sets": ["QD001", "QD003", "QD005", "QDE6008AB05"], "exclude": ["red_right_angle"],
        "attempts": 50, "seed": 3, "keep": 3}), str(ROOT), lambda done, total: seen.append((done, total))))
    assert out and len(out) <= 3
    assert seen[-1] == (50, 50)
    catalog = load_catalog(ROOT / "catalog" / "parts.yaml")
    for data in out:
        path = tmp_path / "l.yaml"
        path.write_text(yaml.safe_dump(data))
        from quadrilla_solver.model import load_layout
        layout = load_layout(path)
        assert layout_id(layout) == data["layout_id"]
        assert validate_layout(layout, catalog, source=layout_source(data), sinks=layout_sinks(data)).valid
        assert data["bill_of_materials"]["check"]
        assert all(p["part_type"] != "red_right_angle" for p in data["parts"])
    # Same options, same layouts (the browser gets what the CLI would).
    again = json.loads(generate_json(json.dumps({
        "sets": ["QD001", "QD003", "QD005", "QDE6008AB05"], "exclude": ["red_right_angle"],
        "attempts": 50, "seed": 3, "keep": 3}), str(ROOT)))
    assert [d["layout_id"] for d in again] == [d["layout_id"] for d in out]
