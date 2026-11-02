from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .assembly import AssemblyResult, validate_assembly
from .catalog import PartCatalog
from .collision import marble_clearance_conflicts
from .connectivity import ConnectivityResult, validate_connectivity
from .layout_stability import (
    GlobalStabilityResult,
    LayoutStaticsResult,
    analyze_global_stability,
    analyze_layout_statics,
)
from .inventory import Inventory, InventoryResult, validate_inventory
from .model import Layout, PortRef


@dataclass(frozen=True)
class LayoutValidationResult:
    valid: bool
    assembly: AssemblyResult
    global_stability: GlobalStabilityResult
    local_statics: LayoutStaticsResult
    connectivity: ConnectivityResult | None
    inventory: InventoryResult | None
    # Solids blocking a marble on rails it actually reaches (needs a source).
    marble_clearance: tuple[str, ...] = ()


def validate_layout(
    layout: Layout,
    catalog: PartCatalog,
    *,
    source: PortRef | None = None,
    sinks: Sequence[PortRef] = (),
    inventory: Inventory | None = None,
) -> LayoutValidationResult:
    """
    Run the common layout through the independent validators.

    Overall validity requires:
    - buildable assembly
    - evaluable and stable global COM/support polygon
    - evaluable and stable per-rail statics
    - connectivity, when a source/sink query is supplied
    """

    assembly = validate_assembly(layout, catalog)
    global_stability = analyze_global_stability(layout, catalog)
    local_statics = analyze_layout_statics(layout, catalog)

    connectivity: ConnectivityResult | None = None
    marble_clearance: tuple[str, ...] = ()
    inventory_result: InventoryResult | None = (
        validate_inventory(layout, inventory) if inventory is not None else None
    )
    if source is not None or sinks:
        if source is None or not sinks:
            raise ValueError(
                "connectivity validation requires both source and at least one sink"
            )
        connectivity = validate_connectivity(
            layout, catalog, source=source, sinks=sinks
        )
        marble_clearance = marble_clearance_conflicts(
            layout, catalog, connectivity.reachable_nodes
        )

    local_valid = (
        local_statics.evaluable
        and local_statics.statics is not None
        and local_statics.statics.valid
    )
    connectivity_valid = connectivity.valid if connectivity is not None else True
    inventory_valid = inventory_result.valid if inventory_result is not None else True

    return LayoutValidationResult(
        valid=(
            assembly.valid
            and global_stability.evaluable
            and global_stability.stable
            and local_valid
            and connectivity_valid
            and inventory_valid
            and not marble_clearance
        ),
        assembly=assembly,
        global_stability=global_stability,
        local_statics=local_statics,
        connectivity=connectivity,
        inventory=inventory_result,
        marble_clearance=marble_clearance,
    )
