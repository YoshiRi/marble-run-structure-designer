from __future__ import annotations

import json
from pathlib import Path

from quadrilla_solver.queries import (
    max_height_for_preset,
    short_on_long,
    triangle_with_long_rails,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    result = {
        "short_on_long": short_on_long(ROOT),
        "triangle": triangle_with_long_rails(ROOT),
        "max_height": {
            "QD001": max_height_for_preset(
                ROOT, "catalog/sets/basic-qd001.yaml"
            ),
            "QD003": max_height_for_preset(
                ROOT, "catalog/sets/funny-function-qd003.yaml"
            ),
            "QD005": max_height_for_preset(
                ROOT, "catalog/sets/twist-and-rail-qd005.yaml"
            ),
            "QD101": max_height_for_preset(
                ROOT, "catalog/sets/speedway-qd101.yaml"
            ),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
