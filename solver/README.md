# Solver

This module will contain layout validation and automatic generation.

Initial implementation order:

1. parse catalog/inventory/layout
2. validate ports, heights, and rail-hole connections
3. validate support and occupancy
4. validate inventory
5. add DFS/backtracking generation

The solver must not depend on viewer meshes or a physics engine.
