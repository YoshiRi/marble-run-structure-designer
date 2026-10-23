from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import hypot

from .catalog import PartCatalog
from .collision import solid_collisions
from .geometry import valid_support_pairs
from .model import Layout, rail_hole_world


@dataclass(frozen=True)
class AssemblyResult:
    valid: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def validate_assembly(
    layout: Layout,
    catalog: PartCatalog,
    *,
    xy_tolerance_cm: float = 1e-3,  # 0.01 mm: absorbs float/YAML rounding on curves
    z_tolerance_units: float = 1e-6,
) -> AssemblyResult:
    reasons: list[str] = []
    warnings: list[str] = []

    ids = [x.id for x in layout.rails] + [x.id for x in layout.parts]
    if len(ids) != len(set(ids)):
        reasons.append("duplicate_component_id")

    rails = layout.rail_map()
    parts = layout.part_map()

    for rail in layout.rails:
        if rail.rail_type not in catalog.rails:
            reasons.append(f"unknown_rail_type:{rail.id}:{rail.rail_type}")
            continue
        if rail.flow_direction not in {"a_to_b", "b_to_a"}:
            reasons.append(
                f"invalid_flow_direction:{rail.id}:{rail.flow_direction}"
            )
        spec = catalog.rails[rail.rail_type]
        for idx, state in rail.hole_states.items():
            if not 0 <= idx < len(spec.holes_cm):
                reasons.append(f"invalid_hole_index:{rail.id}:{idx}")
            if state not in {"open", "block_connected", "covered", "covered_slope"}:
                reasons.append(f"invalid_hole_state:{rail.id}:{idx}:{state}")

    for part in layout.parts:
        if not catalog.has_part(part.part_type):
            reasons.append(f"unknown_part_type:{part.id}:{part.part_type}")
            continue
        rotations = catalog.allowed_rotations(part.part_type)
        if rotations is not None and part.rotation_deg % 360 not in rotations:
            reasons.append(
                f"invalid_rotation:{part.id}:{part.rotation_deg}"
            )

    used_stack_parts: dict[str, str] = {}
    supports_by_upper: dict[str, list[int]] = {x.id: [] for x in layout.rails}
    foundation_usage: dict[str, tuple[bool, int]] = {}

    for i, support in enumerate(layout.supports):
        label = support.name or f"support_{i}"
        if support.upper_rail_id is None:
            # Free-standing stack on a rail hole (e.g. a twist's entry block).
            reasons.extend(_free_stack_reasons(support, label, layout, catalog, used_stack_parts,
                                               xy_tolerance_cm, z_tolerance_units))
            continue
        upper = rails.get(support.upper_rail_id)
        if upper is None:
            reasons.append(f"unknown_upper_rail:{label}:{support.upper_rail_id}")
            continue
        upper_spec = catalog.rails.get(upper.rail_type)
        if upper_spec is None:
            continue
        if not 0 <= support.upper_hole_index < len(upper_spec.holes_cm):
            reasons.append(
                f"invalid_upper_hole:{label}:{support.upper_hole_index}"
            )
            continue

        supports_by_upper[upper.id].append(support.upper_hole_index)
        ux, uy, _ = rail_hole_world(
            upper, catalog, support.upper_hole_index
        )

        if support.lower_rail_id is None:
            if support.lower_hole_index is not None:
                reasons.append(f"ground_support_has_lower_hole:{label}")
            base_z = 0.0
            lower_xy = (ux, uy)
            is_ground = True
        else:
            lower = rails.get(support.lower_rail_id)
            if lower is None:
                reasons.append(
                    f"unknown_lower_rail:{label}:{support.lower_rail_id}"
                )
                continue
            if support.lower_hole_index is None:
                reasons.append(f"missing_lower_hole:{label}")
                continue
            lower_spec = catalog.rails[lower.rail_type]
            if not 0 <= support.lower_hole_index < len(lower_spec.holes_cm):
                reasons.append(
                    f"invalid_lower_hole:{label}:{support.lower_hole_index}"
                )
                continue

            lx, ly, _ = rail_hole_world(
                lower, catalog, support.lower_hole_index
            )
            if hypot(ux - lx, uy - ly) > xy_tolerance_cm:
                reasons.append(
                    f"support_xy_mismatch:{label}:"
                    f"upper=({ux:.6g},{uy:.6g}):"
                    f"lower=({lx:.6g},{ly:.6g})"
                )
            lower_xy = (lx, ly)
            base_z = (lower.z_units + lower_spec.hole_level(support.lower_hole_index)
                      + lower_spec.height_units)
            is_ground = False

        expected_z = base_z
        for stack_index, part_id in enumerate(support.stack_part_ids):
            part = parts.get(part_id)
            if part is None:
                reasons.append(f"unknown_stack_part:{label}:{part_id}")
                continue

            if part_id in used_stack_parts:
                reasons.append(
                    f"stack_part_reused:{part_id}:"
                    f"{used_stack_parts[part_id]}:{label}"
                )
            else:
                used_stack_parts[part_id] = label

            height = catalog.height_units(part.part_type)
            if height is None:
                reasons.append(
                    f"unknown_stack_height:{label}:{part_id}:{part.part_type}"
                )
                continue

            if hypot(part.x_cm - ux, part.y_cm - uy) > xy_tolerance_cm:
                reasons.append(
                    f"stack_xy_mismatch:{label}:{part_id}"
                )
            if abs(part.z_units - expected_z) > z_tolerance_units:
                reasons.append(
                    f"stack_z_mismatch:{label}:{part_id}:"
                    f"expected={expected_z:.6g}:actual={part.z_units:.6g}"
                )

            if part.part_type == "wooden_foundation":
                foundation_usage[part_id] = (is_ground, stack_index)
                if not is_ground or stack_index != 0:
                    reasons.append(
                        f"foundation_not_ground_base:{label}:{part_id}"
                    )

            expected_z += height

        upper_z = upper.z_units + upper_spec.hole_level(support.upper_hole_index)
        if abs(upper_z - expected_z) > z_tolerance_units:
            reasons.append(
                f"upper_rail_z_mismatch:{label}:{upper.id}:"
                f"expected={expected_z:.6g}:actual={upper_z:.6g}"
            )

        # A ground support with no column means the rail itself lies on ground.
        # This is allowed geometrically but called out because normal Quadrilla
        # builds usually use a foundation/block column.
        if is_ground and not support.stack_part_ids:
            warnings.append(f"rail_directly_on_ground:{label}:{upper.id}")

    for rail_id, hole_indices in supports_by_upper.items():
        unique = sorted(set(hole_indices))
        if len(unique) < 2:
            reasons.append(
                f"insufficient_support_points:{rail_id}:{len(unique)}"
            )
            continue

        rail = rails[rail_id]
        spec = catalog.rails[rail.rail_type]
        accepted = {
            tuple(sorted((p.hole_a_cm, p.hole_b_cm)))
            for p in valid_support_pairs(spec)
        }
        local_holes = [spec.holes_cm[i] for i in unique]
        if not any(
            tuple(sorted(pair)) in accepted
            for pair in combinations(local_holes, 2)
        ):
            reasons.append(f"no_stable_support_pair:{rail_id}")

    # A free-standing stack has no load above to hold it down: it must stand
    # between its rail's two supports, not on the overhanging end (user review 3).
    span: dict[str, list[float]] = {}
    for support in layout.supports:
        rail = rails.get(support.upper_rail_id) if support.upper_rail_id is not None else None
        spec = catalog.rails.get(rail.rail_type) if rail is not None else None
        if spec is not None and 0 <= support.upper_hole_index < len(spec.holes_cm):
            span.setdefault(rail.id, []).append(spec.holes_cm[support.upper_hole_index])
    for i, support in enumerate(layout.supports):
        if support.upper_rail_id is not None or support.lower_rail_id not in span:
            continue
        spec = catalog.rails[rails[support.lower_rail_id].rail_type]
        hole = support.lower_hole_index
        if hole is None or not 0 <= hole < len(spec.holes_cm):
            continue
        xs = span[support.lower_rail_id]
        if not min(xs) - 1e-6 <= spec.holes_cm[hole] <= max(xs) + 1e-6:
            reasons.append(f"free_stack_cantilevered:{support.name or f'support_{i}'}")

    # The twist's funnel always empties through its center hole.
    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is not None and spec.shape == "twist":
            if rail.hole_states.get(len(spec.holes_cm) - 1, "open") == "covered":
                reasons.append(f"twist_center_hole_covered:{rail.id}")

    # Curved rails tip on their own: they are stable only with load above,
    # i.e. at least one column standing on them (user-confirmed).
    loaded = {s.lower_rail_id for s in layout.supports if s.lower_rail_id and s.stack_part_ids}
    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is not None and spec.needs_load_above and rail.id not in loaded:
            reasons.append(f"curve_needs_load_above:{rail.id}")

    # Foundation is ground-only. A placed foundation that is not used as the
    # base of a ground support is therefore not a valid assembly.
    for part in layout.parts:
        if part.part_type == "wooden_foundation" and part.id not in foundation_usage:
            reasons.append(f"unused_or_elevated_foundation:{part.id}")

    # Coarse bounding-box check: bodies may touch but not interpenetrate.
    reasons.extend(solid_collisions(layout, catalog))

    return AssemblyResult(
        valid=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _free_stack_reasons(support, label, layout, catalog, used_stack_parts,
                        xy_tolerance_cm, z_tolerance_units) -> list[str]:
    """A stack that holds up no rail: it must stand on a real rail hole."""
    reasons: list[str] = []
    rails, parts = layout.rail_map(), layout.part_map()
    lower = rails.get(support.lower_rail_id) if support.lower_rail_id is not None else None
    if lower is None or not support.stack_part_ids:
        return [f"free_stack_needs_lower_rail:{label}"]
    spec = catalog.rails.get(lower.rail_type)
    hole = support.lower_hole_index
    if spec is None or hole is None or not 0 <= hole < len(spec.holes_cm):
        return [f"invalid_lower_hole:{label}:{hole}"]
    x, y, _ = rail_hole_world(lower, catalog, hole)
    expected_z = lower.z_units + spec.hole_level(hole) + spec.height_units
    for part_id in support.stack_part_ids:
        part = parts.get(part_id)
        if part is None:
            reasons.append(f"unknown_stack_part:{label}:{part_id}")
            continue
        if part_id in used_stack_parts:
            reasons.append(f"stack_part_reused:{part_id}:{used_stack_parts[part_id]}:{label}")
        else:
            used_stack_parts[part_id] = label
        height = catalog.height_units(part.part_type)
        if height is None:
            reasons.append(f"unknown_stack_height:{label}:{part_id}:{part.part_type}")
            continue
        if hypot(part.x_cm - x, part.y_cm - y) > xy_tolerance_cm:
            reasons.append(f"stack_xy_mismatch:{label}:{part_id}")
        if abs(part.z_units - expected_z) > z_tolerance_units:
            reasons.append(f"stack_z_mismatch:{label}:{part_id}:"
                           f"expected={expected_z:.6g}:actual={part.z_units:.6g}")
        if part.part_type == "wooden_foundation":
            reasons.append(f"foundation_not_ground_base:{label}:{part_id}")
        expected_z += height
    return reasons
