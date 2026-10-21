# Layout Model

A `Layout` is the common input shared by assembly, stability, and connectivity validation.

## Coordinate convention

- `x_cm, y_cm`: world-plan coordinates in centimeters
- `z_units`: discrete Quadrilla height units
- rail `x_cm, y_cm`: world position of rail end A
- rail `yaw_deg`: plan-view orientation; arbitrary angles are allowed
- part `x_cm, y_cm`: center/support-axis position
- part `z_units`: bottom elevation

For a rail, `z_units` is its bottom/support-plane elevation.

## Structural support

A `SupportLink` describes one vertical support column under a rail hole.

```text
upper rail hole
      |
 [stack parts]
      |
lower rail hole
      |
     ...
```

or:

```text
upper rail hole
      |
 [stack parts]
      |
    ground
```

`stack_part_ids` are ordered bottom-to-top.

The Assembly Validator checks:

- both rail-hole references exist
- upper/lower rail-hole XY positions coincide
- stack parts are on the same support axis
- the discrete Z stack closes exactly
- a physical part is not reused in two support columns
- foundations are only used at the bottom of ground support columns
- every rail has a geometrically acceptable pair of support holes

## Ground support and global stability

Ground-ending `SupportLink` positions define the ground support set.

The global stability validator:

1. computes each part/rail world COM
2. combines them using catalog masses
3. computes the convex hull of ground support points
4. projects the total COM onto XY
5. checks whether it lies in the support hull

For two ground contacts the hull degenerates to a line segment. Such a structure can pass the idealized model with zero lateral margin; real transverse width is not yet represented.

## Local rail statics

The same support links are converted into the 1D recursive beam model when each rail has exactly two supports.

For every rail:

- self weight is applied at its center
- upper-rail reactions arrive as point loads
- support-column masses are added at their lower contact
- left/right reactions are solved by moment equilibrium
- negative support reaction means tipping

## Routing

Each straight rail has nodes:

```text
end_a -> hole:0 -> hole:1 -> ... -> end_b
```

or the reverse order when `flow_direction: b_to_a`.

Hole behavior in the MVP:

- `covered`: marble continues along the rail
- `open`: route stops at the hole
- `block_connected`: route stops on the rail and may drop into the top routing block in that support column
- `covered_slope`: currently unresolved and therefore reported as unsupported

Routing-block internal edges are loaded from `catalog/parts.yaml`.

`RouteLink` explicitly connects transitions whose exact physical port offset is not yet modeled, such as a horizontal block exit into another rail.

## Example

See:

```text
examples/two-level-supported.yaml
```

That example is a full golden test for:

- assembly
- ground/global stability
- recursive local rail statics
- routing reachability
