# Viewer

Static Babylon.js viewer for the project's common marble-run `Layout` schema.

## Current MVP

- schematic 3D rails and blocks
- arbitrary rail yaw
- visible rail-hole cutouts (Babylon.js CSG, with surface-marker fallback) and color-coded hole states
- block side exits as centered circular recesses; side-to-bottom inlets as
  bottom-edge semicircular notches (catalog-driven)
- support links
- actual graph reachability and shortest directed source-to-sink path highlighting
- reachable branches, dead-end markers, and invalid/unsupported routing diagnostics
- marble input-hole selector (valid `block_connected` rail holes)
- click-to-select input holes in the 3D view: every valid candidate shows a
  teal drop marker; clicking a marker or the hole itself selects it (green)
- external exit list and topology-based exit probabilities
- optional side-drop inlet rule allowing a rail groove one height unit above the notch
- global center of mass
- ground support polygon and optional visible ground-level grid (z=0)
- click-to-inspect part/rail metadata, including each part's bottom/top levels and elevations
- load a local Layout YAML file
- no build step

The default `three-level-physically-connected.yaml` example includes a
blue-block front outlet dropping one unit onto an exit rail that rests on plain
ground foundations (no pedestal blocks needed). Centered side holes are drawn
with their floor at installation level +1, where they physically open.
`two-level-supported.yaml` has no downstream connection from its blue
block, so the trace ends at the real front opening rather than jumping to
an unrelated lower rail.

Vertically stacked pieces of the same type have a subtle joint line so multiple
1-unit purple drop blocks are not mistaken for one taller part.

The viewer deliberately uses schematic boxes rather than realistic meshes. Detailed collision geometry is deferred.

## Dimension provenance

The viewer reads rail lengths and hole positions from `catalog/parts.yaml`.
Long-rail length (50 cm) and hole positions (2, 7, 43, 48 cm) are measured.
Short-rail length (27 cm) is measured; some short-rail hole positions are inferred.
The center-hole rail includes a cataloged center position at 25 cm.

**Measured or reported physical dimensions:**

- standard routing-block footprint: **4.5 × 4.5 cm**
- standard routing-block effective stacked height: **6 cm** (4 height units)
- rail width: **4.5 cm**
- straight rail center groove width: **1.0 cm**, longitudinal along the rail
- standard block connector protrusion: **1 cm**, inserted into the mating part;
  it does **not** increase the assembled stack height
- rail-hole diameter: **approximately 1.8 cm** (not a precision measurement)

**Derived and provisional dimensions:**

- 1 height unit = **1.5 cm**, derived from the standard block's 6 cm / 4 units
- rail height is **1 unit**, explicitly confirmed by the user; this renders
  as **1.5 cm** from the derived scale (not a separate caliper measurement)
- purple thin/drop block height: **1.5 cm (1 unit)**, user-confirmed and rendered from an explicit catalog dimension
- wooden foundation height remains unverified in centimeters
- block port diameter = **1.8 cm provisional**, borrowed from the approximate
  rail-hole diameter; actual block port diameters have not been measured
- block side exit placement = **face center**, as specified by the user
- block side inlets leading to a downward drop = **bottom-edge semicircular notches**,
  as specified by the user; catalog `port_visualization.side_entry_notches` lists
  which ports use this shape
- rail groove depth = **0.3 cm provisional**; its profile is rendered as a
  rectangular recess, pending measurements of depth and cross-section
- block port CSG cavities = **shallow blind recesses**, not modeled internal channels

These parameters are stored with provenance in `catalog/parts.yaml` under
`geometry_cm`. The viewer reads them from the catalog, while the solver keeps
its discrete height units. Protrusions are currently omitted from meshes because
the viewer depicts assembled, engaged blocks. This is still schematic geometry,
not a dimensionally verified CAD model.

The colored rings distinguish open, covered, block-connected, and slope-covered
rail holes. Covered holes are shown with caps. CSG creates real through-holes
where available; otherwise the viewer uses dark surface markers as a fallback.

Block openings follow each routing block's `ports` field. For example, a
yellow block has top and front openings; blue has top, front, rear, and bottom.
The blue block's rear inlet is a bottom-edge semicircle; its front outlet is
centered. Green has a left-side bottom-edge inlet; natural-wood drop has front
and rear bottom-edge inlets. Block holes are rendered as shallow CSG recesses,
not through-passages: actual internal routing geometry remains unmeasured.
The Holes toggle controls hole markers and outlines, not the underlying CSG
cutout geometry.

## Local run

The viewer uses `fetch()` for YAML data, so serve the repository over HTTP:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/viewer/
```

For the GitHub Pages artifact, `viewer/index.html` is copied to the site root together with `catalog/` and `examples/`.

## Solver / static hosting

The viewer is fully static. `viewer/routing.js` is a dependency-free port of
`src/quadrilla_solver/connectivity.py` and traces the directed port graph.
The green path is the **shortest topological path** to the selected sink, not a
physical marble trajectory or travel-time estimate. Overlay segments on rails
follow their center grooves; a vertical drop is shown only through a real
block-connected hole. Cross-component links are drawn only when actual
catalogued openings are aligned and face each other. **Inside blocks, only
the existing entry/exit ports and the block outline are highlighted**:
internal channel geometry is not known, so no fabricated 3D arc is drawn
through solid wood. Cyan branches show other
reachable graph edges, including possible random routes. Open holes interrupt
rail traversal; covered holes preserve it; block-connected holes can drop into
a supporting routing block. Unsupported covered-slope semantics are reported.

The exit table lists reachable open rail holes, downstream rail ends, and
unconnected block outlets. Deterministic paths show their topology-model
probability; random branches are temporarily assumed equiprobable and displayed
as estimates. Unsupported graph behavior, cycles, or unmodeled branches cause
probabilities to be withheld rather than guessed.

Side-entry notches that route downwards normally connect at the part's
installation level. The **Allow rail groove one level above a side-drop inlet**
checkbox optionally permits a +1-unit (1.5 cm) vertical offset, while retaining
XY alignment, facing-direction, and flow-direction checks. The option is off
by default and can also be configured in YAML with
`routing_options.allow_side_entry_plus_one: true`.

For local Layout YAML files, the optional `routing_query` field specifies the
initial source and destination:

```yaml
routing_query:
  source: { component_id: upper, port: end_a }
  sinks:
    - { component_id: exit, port: end_b }
```

The dropdowns can select other graph nodes without editing the YAML.

The canonical solver currently remains Python. A fully static hosted application has two viable paths:

1. **Port the solver core to TypeScript/JavaScript** and execute it directly in the browser. This is the preferred long-term path because the solver is mostly deterministic graph/geometry/statics logic.
2. Run the existing Python solver through **Pyodide**. This minimizes code duplication but adds a large browser runtime and slower startup.

The Layout YAML and catalog YAML remain the shared interface either way.

## Deferred

- realistic meshes
- collision detection
- browser-side full Assembly / local statics / Inventory validation
- full physical marble dynamics and exact internal block channels
- construction-assist overlays
- marble animation
