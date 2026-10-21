from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from quadrilla_solver.catalog import load_catalog
from quadrilla_solver.model import PortRef, load_layout
from quadrilla_solver.validation import validate_layout


def _port(text: str) -> PortRef:
    component, sep, port = text.partition(":")
    if not sep or not component or not port:
        raise argparse.ArgumentTypeError(
            "port must be COMPONENT:PORT, e.g. upper:end_a"
        )
    return PortRef(component, port)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a Quadrilla layout YAML."
    )
    parser.add_argument("layout", type=Path)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("catalog/parts.yaml"),
    )
    parser.add_argument("--source", type=_port)
    parser.add_argument("--sink", action="append", type=_port, default=[])
    args = parser.parse_args()

    if (args.source is None) != (not args.sink):
        parser.error("--source and at least one --sink must be supplied together")

    catalog = load_catalog(args.catalog)
    layout = load_layout(args.layout)
    result = validate_layout(
        layout,
        catalog,
        source=args.source,
        sinks=tuple(args.sink),
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))

    raise SystemExit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
