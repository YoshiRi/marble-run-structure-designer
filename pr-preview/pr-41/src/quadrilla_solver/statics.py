from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

GRAVITY_M_S2 = 9.80665


@dataclass(frozen=True)
class PointMass:
    """A mass attached to a rail at a local x-coordinate."""

    name: str
    x_cm: float
    mass_g: float


@dataclass(frozen=True)
class SupportConnection:
    """
    One downward support of a rail.

    x_cm:
        Support location on the child rail.
    target_id:
        ID of the lower rail receiving the reaction, or None for ground.
    target_x_cm:
        Local coordinate on the lower rail where the reaction is applied.
        Must be provided when target_id is not None.
    transfer_mass_g:
        Optional mass of the support column/block stack between the two rails.
        That mass is below the child rail, so it does not affect the child
        equilibrium, but it does add load to the lower rail.
    """

    x_cm: float
    target_id: str | None
    target_x_cm: float | None = None
    transfer_mass_g: float = 0.0
    name: str = ""


@dataclass(frozen=True)
class RailBody:
    """
    A straight rail represented as a rigid 1D beam under vertical gravity load,
    on two or more downward supports (columns).
    """

    id: str
    length_cm: float
    mass_g: float
    supports: tuple[SupportConnection, ...]
    com_cm: float | None = None
    point_masses: tuple[PointMass, ...] = ()


@dataclass(frozen=True)
class AppliedLoad:
    source: str
    x_cm: float
    force_n: float


@dataclass(frozen=True)
class SupportReaction:
    support: SupportConnection
    force_n: float
    transmitted_force_n: float


@dataclass(frozen=True)
class RailStatics:
    rail_id: str
    total_force_n: float
    equivalent_mass_g: float
    effective_com_cm: float
    support_span_cm: float
    stability_margin_cm: float
    normalized_margin: float
    stable: bool
    reactions: tuple[SupportReaction, ...]
    applied_loads: tuple[AppliedLoad, ...]
    # Reactions of the outermost two supports carrying everything (the tipping
    # case; on two supports the same as `reactions`). The 20 g rule uses them.
    outer_reactions_n: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class GroundReaction:
    source_rail_id: str
    support_name: str
    force_n: float


@dataclass(frozen=True)
class StructureStatics:
    valid: bool
    rails: Mapping[str, RailStatics]
    ground_reactions: tuple[GroundReaction, ...]
    total_ground_force_n: float
    reasons: tuple[str, ...]


def _weight_n(mass_g: float) -> float:
    return mass_g / 1000.0 * GRAVITY_M_S2


def _validate_rail(rail: RailBody) -> None:
    if not rail.id:
        raise ValueError("rail id must be non-empty")
    if not isfinite(rail.length_cm) or rail.length_cm <= 0:
        raise ValueError(f"{rail.id}: length_cm must be positive")
    if not isfinite(rail.mass_g) or rail.mass_g < 0:
        raise ValueError(f"{rail.id}: mass_g must be non-negative")

    com = rail.length_cm / 2.0 if rail.com_cm is None else rail.com_cm
    if not (0.0 <= com <= rail.length_cm):
        raise ValueError(f"{rail.id}: com_cm outside rail")

    xs = [s.x_cm for s in rail.supports]
    if len(xs) < 2:
        raise ValueError(f"{rail.id}: at least two supports needed")
    if not all(0.0 <= x <= rail.length_cm for x in xs):
        raise ValueError(f"{rail.id}: support outside rail")
    if max(xs) - min(xs) <= 1e-12:
        raise ValueError(f"{rail.id}: supports must be at distinct positions")

    for p in rail.point_masses:
        if p.mass_g < 0:
            raise ValueError(f"{rail.id}: negative point mass {p.name}")
        if not (0.0 <= p.x_cm <= rail.length_cm):
            raise ValueError(f"{rail.id}: point mass {p.name} outside rail")

    for support in rail.supports:
        if support.transfer_mass_g < 0:
            raise ValueError(f"{rail.id}: negative transfer mass")
        if support.target_id is not None and support.target_x_cm is None:
            raise ValueError(
                f"{rail.id}: target_x_cm required for target {support.target_id}"
            )


def _pair_reactions(loads, left_x: float, right_x: float, total: float) -> tuple[float, float]:
    """Reactions of two supports at left_x < right_x carrying all loads."""
    if total <= 0:
        return 0.0, 0.0
    right = sum(load.force_n * (load.x_cm - left_x) for load in loads) / (right_x - left_x)
    return total - right, right


def analyze_structure(
    bodies: Mapping[str, RailBody],
    *,
    reaction_tolerance_n: float = 1e-9,
    max_scenarios: int = 64,
) -> StructureStatics:
    """
    Propagate gravity loads from upper rails to lower rails.

    Assumptions:
    - vertical quasi-static loads only
    - each rail is a rigid 1D beam on two or more supports (compression only)
    - no friction, lateral force, rail bending, or joint pull-out
    - a support column's own mass may be represented by transfer_mass_g

    A rail is stable when its effective center of mass lies within its
    outermost supports (moments about each support: the side it would tip to
    has a support), whatever the number of supports.

    On two supports the reactions follow from equilibrium. On more, the
    split is not determined (statically indeterminate: it depends on tiny
    height differences). Every extreme split is checked: the load carried by
    one pair of supports that brackets the center of mass, the others
    passing on only their own column's weight. The structure is valid only if
    the whole structure is stable in every such scenario (conservative).
    The rails reported are those of the first failing scenario, else of the
    first scenario (each rail on its first bracketing pair).

    The support graph must be acyclic.
    """
    if not bodies:
        return StructureStatics(
            valid=True,
            rails={},
            ground_reactions=(),
            total_ground_force_n=0.0,
            reasons=(),
        )
    for key, rail in bodies.items():
        if key != rail.id:
            raise ValueError(f"mapping key {key!r} != RailBody.id {rail.id!r}")
        _validate_rail(rail)

    results: list[StructureStatics] = []

    def explore(assign: dict[str, int]) -> None:
        if len(results) >= max_scenarios:
            return
        result, branch, options = _solve_scenario(bodies, assign, reaction_tolerance_n)
        if branch is None:
            results.append(result)
            return
        for i in range(options):
            explore({**assign, branch: i})

    explore({})
    failing = next((r for r in results if not r.valid), None)
    return failing or results[0]


def _solve_scenario(
    bodies: Mapping[str, RailBody],
    assign: Mapping[str, int],
    reaction_tolerance_n: float,
) -> tuple[StructureStatics, str | None, int]:
    """One load-propagation pass. A rail with 3+ supports uses the bracketing
    pair `assign[rail]`; the first such rail without a choice is returned with
    its number of options (and the pass uses option 0 for it)."""
    # Dependency direction is upper child -> lower target. A lower rail cannot
    # be solved until all rails loading it have been solved.
    parents_by_child: dict[str, set[str]] = {k: set() for k in bodies}
    children_by_parent: dict[str, set[str]] = {k: set() for k in bodies}

    for rail in bodies.values():
        for support in rail.supports:
            target = support.target_id
            if target is None:
                continue
            if target not in bodies:
                raise ValueError(f"{rail.id}: unknown support target {target}")
            target_rail = bodies[target]
            assert support.target_x_cm is not None
            if not (0.0 <= support.target_x_cm <= target_rail.length_cm):
                raise ValueError(
                    f"{rail.id}: target coordinate {support.target_x_cm} "
                    f"outside {target}"
                )
            parents_by_child[rail.id].add(target)
            children_by_parent[target].add(rail.id)

    # Number of distinct upper rails that must be solved before each lower rail.
    remaining_children = {
        rail_id: len(children_by_parent[rail_id]) for rail_id in bodies
    }
    ready = sorted(
        rail_id for rail_id, count in remaining_children.items() if count == 0
    )

    incoming: dict[str, list[AppliedLoad]] = {k: [] for k in bodies}
    solved: dict[str, RailStatics] = {}
    ground: list[GroundReaction] = []
    reasons: list[str] = []
    branch: str | None = None
    options = 0

    while ready:
        rail_id = ready.pop(0)
        rail = bodies[rail_id]

        loads: list[AppliedLoad] = []
        com = rail.length_cm / 2.0 if rail.com_cm is None else rail.com_cm
        self_force = _weight_n(rail.mass_g)
        if self_force > 0:
            loads.append(AppliedLoad(f"{rail_id}:self", com, self_force))

        for point in rail.point_masses:
            force = _weight_n(point.mass_g)
            if force > 0:
                loads.append(
                    AppliedLoad(
                        source=f"{rail_id}:point:{point.name}",
                        x_cm=point.x_cm,
                        force_n=force,
                    )
                )

        loads.extend(incoming[rail_id])
        total_force = sum(load.force_n for load in loads)

        if total_force <= 0:
            effective_com = com
        else:
            effective_com = (
                sum(load.force_n * load.x_cm for load in loads) / total_force
            )

        ordered = sorted(rail.supports, key=lambda s: s.x_cm)
        left, right = ordered[0], ordered[-1]
        span = right.x_cm - left.x_cm
        outer = _pair_reactions(loads, left.x_cm, right.x_cm, total_force)

        margin = min(
            effective_com - left.x_cm,
            right.x_cm - effective_com,
        )
        normalized = margin / (span / 2.0)
        stable = (
            outer[0] >= -reaction_tolerance_n
            and outer[1] >= -reaction_tolerance_n
        )

        if not stable:
            reasons.append(
                f"tipping:{rail_id}:com={effective_com:.6g}:"
                f"supports={left.x_cm:.6g},{right.x_cm:.6g}"
            )

        # Which pair carries the load: on two supports, both; on more, the
        # pairs that bracket the center of mass (or the outer pair if none).
        if len(ordered) == 2:
            pair = (0, 1)
        else:
            pairs = [
                (i, j)
                for i in range(len(ordered))
                for j in range(i + 1, len(ordered))
                if ordered[i].x_cm - 1e-9 <= effective_com <= ordered[j].x_cm + 1e-9
                and ordered[j].x_cm - ordered[i].x_cm > 1e-12
            ] or [(0, len(ordered) - 1)]
            if rail_id in assign:
                pair = pairs[min(assign[rail_id], len(pairs) - 1)]
            else:
                if branch is None and len(pairs) > 1:
                    branch, options = rail_id, len(pairs)
                pair = pairs[0]
        carried = dict(zip(pair, _pair_reactions(loads, ordered[pair[0]].x_cm, ordered[pair[1]].x_cm,
                                                  total_force)))
        reactions_raw = tuple((support, carried.get(i, 0.0)) for i, support in enumerate(ordered))
        reactions: list[SupportReaction] = []

        for support, reaction in reactions_raw:
            # A compression-only support cannot physically transmit a negative
            # solved reaction. Keep the mathematical result for diagnostics,
            # but never propagate tensile load into the lower structure.
            propagated_reaction = max(0.0, reaction)
            transferred = propagated_reaction + _weight_n(support.transfer_mass_g)

            reactions.append(
                SupportReaction(
                    support=support,
                    force_n=reaction,
                    transmitted_force_n=transferred,
                )
            )

            if support.target_id is None:
                ground.append(
                    GroundReaction(
                        source_rail_id=rail_id,
                        support_name=support.name,
                        force_n=transferred,
                    )
                )
            else:
                assert support.target_x_cm is not None
                incoming[support.target_id].append(
                    AppliedLoad(
                        source=f"{rail_id}:{support.name or 'support'}",
                        x_cm=support.target_x_cm,
                        force_n=transferred,
                    )
                )

        solved[rail_id] = RailStatics(
            rail_id=rail_id,
            total_force_n=total_force,
            equivalent_mass_g=total_force / GRAVITY_M_S2 * 1000.0,
            effective_com_cm=effective_com,
            support_span_cm=span,
            stability_margin_cm=margin,
            normalized_margin=normalized,
            stable=stable,
            reactions=tuple(reactions),
            applied_loads=tuple(loads),
            outer_reactions_n=outer,
        )

        for parent in parents_by_child[rail_id]:
            remaining_children[parent] -= 1
            if remaining_children[parent] == 0:
                ready.append(parent)
                ready.sort()

    if len(solved) != len(bodies):
        unresolved = sorted(set(bodies) - set(solved))
        reasons.append("support_cycle:" + ",".join(unresolved))

    return StructureStatics(
        valid=len(solved) == len(bodies) and all(x.stable for x in solved.values()),
        rails=solved,
        ground_reactions=tuple(ground),
        total_ground_force_n=sum(x.force_n for x in ground),
        reasons=tuple(reasons),
    ), branch, options
