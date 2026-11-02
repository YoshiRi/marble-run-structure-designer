from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import sqrt

from .catalog import RailSpec


@dataclass(frozen=True)
class SupportPair:
    hole_a_cm: float
    hole_b_cm: float
    span_cm: float
    kind: str


@dataclass(frozen=True)
class StackingOption:
    top: SupportPair
    bottom: SupportPair
    span_cm: float


@dataclass(frozen=True)
class TriangleSolution:
    side_spans_cm: tuple[float, float, float]
    support_pairs: tuple[SupportPair, SupportPair, SupportPair]
    vertices_cm: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


def _hole_zone(x: float, length: float) -> str:
    # Initial stability geometry policy:
    # - the outer 30% on each side counts as an end region
    # - a +/-10% band around the midpoint counts as center
    if abs(x - length / 2.0) <= 0.10 * length:
        return "center"
    if x <= 0.30 * length:
        return "left"
    if x >= 0.70 * length:
        return "right"
    return "interior"


def valid_support_pairs(rail: RailSpec) -> tuple[SupportPair, ...]:
    """
    Return hole pairs that satisfy the current *geometric* support policy.

    Accepted patterns:
    - left end + right end
    - either end + center

    This says nothing about whether the supporting objects below those holes are
    themselves stable; that belongs to the Stability Validator.
    """
    out: list[SupportPair] = []
    holes = rail.holes_cm
    for i, a in enumerate(holes):
        for b in holes[i + 1 :]:
            za = _hole_zone(a, rail.length_cm)
            zb = _hole_zone(b, rail.length_cm)
            zones = {za, zb}
            kind: str | None = None
            if zones == {"left", "right"}:
                kind = "end_to_end"
            elif "center" in zones and ("left" in zones or "right" in zones):
                kind = "end_to_center"
            if kind is not None:
                out.append(
                    SupportPair(
                        hole_a_cm=a,
                        hole_b_cm=b,
                        span_cm=round(abs(b - a), 9),
                        kind=kind,
                    )
                )
    return tuple(out)


def find_stacking_options(
    top: RailSpec,
    bottom: RailSpec,
    tolerance_cm: float = 1e-6,
) -> tuple[StackingOption, ...]:
    """
    Find parallel placements where a stable support-hole pair on the top rail
    can be vertically aligned with a valid pair on the bottom rail.

    Translation and 180-degree reversal are allowed. Stability of the bottom
    rail itself is checked separately.
    """
    out: list[StackingOption] = []
    for tp, bp in product(valid_support_pairs(top), valid_support_pairs(bottom)):
        if abs(tp.span_cm - bp.span_cm) <= tolerance_cm:
            out.append(StackingOption(top=tp, bottom=bp, span_cm=tp.span_cm))
    return tuple(out)


def find_triangle(
    rails: tuple[RailSpec, RailSpec, RailSpec],
    prefer_largest: bool = True,
) -> TriangleSolution | None:
    """
    Find a plan-view triangle whose side endpoints coincide with valid support
    holes on each rail.

    Rail yaw is continuous in this query. This is intentional: Quadrilla rail
    holes are treated as round support/connection sites, while block routing
    orientation remains discrete.

    Stability in Z is separate: the three triangle vertices still need stable
    support chains to ground (or to an already-stable lower structure).
    """
    pair_sets = [valid_support_pairs(r) for r in rails]
    candidates: list[TriangleSolution] = []

    for p0, p1, p2 in product(*pair_sets):
        a, b, c = p0.span_cm, p1.span_cm, p2.span_cm
        if not (a + b > c and a + c > b and b + c > a):
            continue

        # A=(0,0), B=(a,0), C determined from sides AC=c and BC=b.
        x = (a * a + c * c - b * b) / (2.0 * a)
        y2 = c * c - x * x
        if y2 <= 0:
            continue
        y = sqrt(y2)
        candidates.append(
            TriangleSolution(
                side_spans_cm=(a, b, c),
                support_pairs=(p0, p1, p2),
                vertices_cm=((0.0, 0.0), (a, 0.0), (x, y)),
            )
        )

    if not candidates:
        return None

    key = lambda s: sum(s.side_spans_cm)
    return max(candidates, key=key) if prefer_largest else min(candidates, key=key)
