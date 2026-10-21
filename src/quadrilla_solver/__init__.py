from .catalog import RailSpec, SetInventory, load_rail_specs, load_set_inventory
from .geometry import (
    SupportPair,
    StackingOption,
    TriangleSolution,
    find_stacking_options,
    find_triangle,
    valid_support_pairs,
)
from .optimizer import HeightSolution, maximize_straight_tower
from .stability import StabilityResult, check_support_chain, check_triangle_vertex_supports

__all__ = [
    "RailSpec",
    "SetInventory",
    "SupportPair",
    "StackingOption",
    "TriangleSolution",
    "HeightSolution",
    "StabilityResult",
    "load_rail_specs",
    "load_set_inventory",
    "valid_support_pairs",
    "find_stacking_options",
    "find_triangle",
    "check_support_chain",
    "check_triangle_vertex_supports",
    "maximize_straight_tower",
    "GRAVITY_M_S2",
    "AppliedLoad",
    "GroundReaction",
    "PointMass",
    "RailBody",
    "RailStatics",
    "StructureStatics",
    "SupportConnection",
    "SupportReaction",
    "analyze_structure",
]

from .statics import (
    GRAVITY_M_S2,
    AppliedLoad,
    GroundReaction,
    PointMass,
    RailBody,
    RailStatics,
    StructureStatics,
    SupportConnection,
    SupportReaction,
    analyze_structure,
)
