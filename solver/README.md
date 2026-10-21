# Solver

The project should treat "solver" as two layers:

1. **validators/checkers** that answer whether a proposed layout is valid
2. **generators/optimizers** that search for layouts while using those validators as constraints

The validators are intentionally split into three independent concerns.

## 1. Assembly Validator — can it be built?

Checks geometric and inventory feasibility.

Typical checks:

- required part exists in the selected inventory/preset
- XY positions and rotations are legal
- rail-hole coordinates line up with the attached block/support
- discrete Z heights line up
- the requested rail/part variant actually has the required hole/mount
- parts do not occupy impossible overlapping geometry
- only legal part-to-part attachment types are used

Examples of questions:

- Can a short rail be placed on top of a long rail using matching holes?
- Can these three rails/blocks form a triangular arrangement?
- Does this layout require a center-hole rail variant?
- Is the layout possible with only the selected commercial set?

The assembly validator does **not** decide whether the structure will stand stably and does not care whether the marble route works.

## 2. Stability Validator — will it stand?

Checks the support structure independently of marble routing.

Initial conservative rules:

- a rail must have at least two support points
- support points should constrain both sides of the rail; accepted patterns include:
  - support near both ends
  - one end plus a center support when the geometry is known to be stable
- every support point must ultimately connect through stable supporting parts/rails to the ground
- a rail used as a support for another rail must itself already be stable
- unsupported chains, single-point balances, and circular support dependencies are invalid

This should be implemented as a support graph.

Each placed component has:

- support points it **requires**
- support points it **provides**

Validation follows support edges downward until ground.

The MVP now also includes a recursive quasi-static helper for straight rails.

### Recursive rail statics

Each rail is treated as a rigid 1D beam under vertical gravity loads.

Inputs per rail:

- rail mass and local center of mass
- optional point masses
- exactly two downward support locations
- optional lower-rail target for each support
- optional support-column mass

For each rail the helper computes:

- total vertical load
- effective center of mass including all upper structure
- left/right support reactions
- stability margin from the effective COM to the nearest support
- normalized balance margin
- downward reactions transmitted to lower rails

Upper-rail reactions are propagated recursively as point loads onto lower rails.

A rail is considered tipped when the solved reaction at either compression-only support is negative. This is equivalent, in the current 1D model, to the effective COM lying outside the support interval.

Current exclusions:

- lateral force
- 2D/3D global center of mass
- rail bending
- friction
- connection pull-out
- more than two supports
- exact mass values for real Quadrilla parts

Actual force values therefore require measured part masses; the solver does not invent them.

Later refinements may add:

- 2D global statics for non-parallel/triangular structures
- cantilever limits
- rail bending/compliance
- support capacity and connection strength
- tolerance/clearance

## 3. Connectivity Validator — does the marble route work?

Checks the directed routing graph.

Typical checks:

- every connected port is geometrically compatible
- block internal routes are respected
- rail-hole states are respected
- covers/pass-through parts close holes correctly
- random branches are represented as multiple reachable outputs
- a requested source can reach a requested sink
- optional stricter modes can reject dead ends or unintended drops

This validator does not need rigid-body physics.

For the initial version, routing is topological:

```text
source port
  -> block route
  -> rail segment
  -> hole / next part
  -> ...
  -> sink
```

## Combined result

A layout can therefore have separate results:

```yaml
assembly:
  valid: true

stability:
  valid: false
  reasons:
    - rail_R3_has_only_one_support

connectivity:
  valid: true
```

This separation is important: a route can be connected but physically unbuildable; a structure can be buildable but unstable; a stable structure can contain no valid marble path.

## Query-style use

The same validators should answer short engineering questions.

### "Can a short rail be stacked on a long rail?"

1. Assembly validator searches for matching hole-pair geometry.
2. Stability validator checks whether the resulting short rail has a valid two-point support pattern.
3. Connectivity is optional unless a marble route is also requested.

### "Can I build a triangular structure?"

1. Enumerate candidate rail/block placements forming the requested 2D shape.
2. Reject candidates whose holes/heights cannot mate.
3. Reject candidates whose support graph does not terminate stably at ground.
4. Optionally check marble routing afterward.

### "What is the maximum height from this set?"

This is an optimization problem over the same constraints:

```text
maximize highest_z(layout)
subject to:
  assembly_valid(layout)
  stability_valid(layout)
  inventory_within_preset(layout)
```

If the question asks for a functioning marble run, add:

```text
connectivity_valid(layout)
```

It is useful to expose both answers:

- maximum **structural** height
- maximum **routable** height

because they can differ.

## Initial implementation order

1. parse catalog / set preset / inventory / layout
2. implement Assembly Validator
3. implement Stability Validator with support graph
4. implement Connectivity Validator
5. add small query/search helpers
6. add DFS/backtracking generator
7. add optimization objectives such as maximum height or maximum route length

The solver must not depend on viewer meshes or a physics engine.
