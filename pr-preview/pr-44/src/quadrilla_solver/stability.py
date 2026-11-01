from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class StabilityResult:
    valid: bool
    reasons: tuple[str, ...] = ()


def check_support_chain(
    support_graph: Mapping[str, Sequence[str]],
    grounded: set[str],
    roots: Sequence[str],
) -> StabilityResult:
    """
    Verify that every requested root has at least two downward support branches
    and that those branches recursively terminate at ground.

    This is a conservative graph check, not force/center-of-mass simulation.
    """

    memo: dict[str, bool] = {}
    visiting: set[str] = set()
    reasons: list[str] = []

    def stable(node: str) -> bool:
        if node in grounded:
            return True
        if node in memo:
            return memo[node]
        if node in visiting:
            reasons.append(f"support_cycle:{node}")
            memo[node] = False
            return False

        children = tuple(support_graph.get(node, ()))
        if len(children) < 2:
            reasons.append(f"insufficient_supports:{node}:{len(children)}")
            memo[node] = False
            return False

        visiting.add(node)
        good = all(stable(child) for child in children)
        visiting.remove(node)
        memo[node] = good
        return good

    ok = all(stable(root) for root in roots)
    return StabilityResult(valid=ok, reasons=tuple(dict.fromkeys(reasons)))


def check_triangle_vertex_supports(
    grounded_or_stable_vertices: Sequence[bool],
) -> StabilityResult:
    """
    Initial triangle-frame stability rule: all three vertices must have a stable
    downward support chain. This deliberately avoids claiming force-level proof.
    """
    if len(grounded_or_stable_vertices) != 3:
        return StabilityResult(False, ("triangle_requires_three_vertices",))
    missing = tuple(
        f"triangle_vertex_{i}_unsupported"
        for i, supported in enumerate(grounded_or_stable_vertices)
        if not supported
    )
    return StabilityResult(valid=not missing, reasons=missing)
