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

`validate_connectivity()` also returns `paths`, mapping each reached sink to
its shortest directed sequence of graph-node keys. The browser Viewer traces
the same port graph in `viewer/routing.js` and overlays the selected route
and alternative reachable branches. It does not simulate ball dynamics.

`RouteLink` normally connects **catalogued openings at the same physical
position** within 0.35 cm, with outward normals facing in opposite directions
and source/target roles consistent with the directed routes and rail flow.
Misaligned links are rejected with a `route_link_geometry_mismatch` diagnostic,
not drawn as teleporting lines. Rail holes cannot be used as arbitrary explicit
link endpoints. A `block_connected` hole feeds a top port only when the
support-column block top matches the hole's XY and the rail underside height.

Side-entry notches that feed a downward route (blue rear, green left, and
natural-drop front/rear) have a specific optional allowance. By default, the
rail groove must meet the notch at the part's installation level. Set
`routing_options.allow_side_entry_plus_one: true` to also accept the rail
groove exactly one height unit (1.5 cm) above that level. This exception still
requires matching XY, opposite-facing normals, and a valid directed connection;
it models the open-bottom drop inlet rather than claiming the port centers are
at the same height. The Viewer has a checkbox for this option; its toggle is
session-only unless saved in the layout YAML.

These tests are based on provisional schematic opening positions from the
catalog. They do not certify collision clearance, internal channels, or
real-world marble motion.

## Example

See:

```text
examples/three-level-physically-connected.yaml

# Structural example that ends at an unmatched block outlet:
examples/two-level-supported.yaml
```

That example is a full golden test for:

- assembly
- ground/global stability
- recursive local rail statics
- routing reachability

## Routing options and Viewer query

A layout may configure the optional side-drop connection rule:

```yaml
routing_options:
  allow_side_entry_plus_one: false
```

The default is `false`. The Viewer checkbox can override it for the current
session; set it in YAML to choose the initial state.

A layout may also specify a default source and sink for the browser routing inspector:

```yaml
routing_query:
  source: { component_id: upper, port: end_a }
  sinks:
    - { component_id: exit, port: end_b }
```

The Python CLI still accepts explicit `--source` and `--sink` arguments;
`routing_query` is currently viewer metadata rather than part of the Python
`Layout` dataclass. The Viewer supports selecting any other graph node.
