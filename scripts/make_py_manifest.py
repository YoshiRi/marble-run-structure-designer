"""Write viewer/py-manifest.json: the files the browser generator loads into
Pyodide (the solver package, the catalog and the set files), as paths
relative to the repository root (the site keeps the same layout); and
viewer/generator-tunables.json: the score weights and style rules the
Generate dialog offers, taken from the Python source.

    python scripts/make_py_manifest.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def manifest() -> dict:
    files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "src" / "quadrilla_solver").glob("*.py"))
    files += ["catalog/parts.yaml", "catalog/sets/index.yaml"]
    files += sorted(str(p.relative_to(ROOT)) for p in (ROOT / "catalog" / "sets").rglob("*.yaml")
                    if p.name != "index.yaml")
    return {"files": files}


def tunables() -> dict:
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from quadrilla_solver.web import describe_tunables
    return describe_tunables()


if __name__ == "__main__":
    (ROOT / "viewer" / "py-manifest.json").write_text(json.dumps(manifest(), indent=2) + "\n")
    (ROOT / "viewer" / "generator-tunables.json").write_text(json.dumps(tunables(), indent=2) + "\n")
    print("wrote viewer/py-manifest.json and viewer/generator-tunables.json")
