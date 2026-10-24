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
- exit probabilities also shown as labels at each exit in the 3D view
- marble rolling: **Roll a marble** (top toolbar and sidebar) animates one marble along a sampled route
  (random branches chosen with the same weights as the probability table);
  **Roll 100** samples instantly. The **Rolled** column tallies where sampled
  marbles ended, so it can be compared with the computed probabilities.
  Marble diameter is 1.6 cm (official 16 mm); motion is schematic, not physics.
- optional side-drop inlet rule allowing a rail groove one height unit above the notch
- global center of mass
- ground support polygon and optional visible ground-level grid (z=0)
- click-to-inspect part/rail metadata, including each part's bottom/top levels and elevations
- load a local Layout YAML file
- no build step

The example menu lists layouts produced by the generator
(`examples/generated/`, see [docs/generator.md](../docs/generator.md)). Any
other Layout YAML can be opened with **Load YAML**; hand-built layouts used
by the tests live in `tests/fixtures/`. Centered side holes are drawn with
their floor at installation level +1, where they physically open.

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

- 1 level = **1.2 cm** (user measurement, 2026-10-24); a standard block is
  5 levels (6 cm), rails and purple blocks 1 level each
- rail height: **1.2 cm (1 level)**, user-confirmed
- purple thin/drop block height: **1.2 cm (1 level)**, user-confirmed and rendered from an explicit catalog dimension
- wooden foundation height: **1 level (1.2 cm)**, user-confirmed
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
checkbox optionally permits a +1-level (1.2 cm) vertical offset, while retaining
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

## Curved rails and twist (viewer only)

The viewer draws `curved_short` / `curved_long` rails (catalog `curved_rails`) and
the twist (`special_parts.spiral`) schematically from estimated geometry. A curved
rail is placed like a straight one (`x_cm`/`y_cm` = end A, `yaw_deg` = travel
direction at end A) plus `turn: left|right`. The solver and the routing graph do
not model these parts yet. Preview: load `tests/fixtures/curves-and-twist-preview.yaml`
with **Load YAML**.

## Gallery and layout IDs

`gallery.html` lists generated review candidates (`examples/gallery/`, built by
`scripts/build_gallery.py`). Every generated layout carries a `layout_id` such
as `mr-9bb890c9`: a short hash of its rails, parts, supports and links, so the
same build always has the same ID. The viewer shows it in the header and opens a
layout directly with `index.html?layout=examples/gallery/<id>.yaml`.

Each gallery card has Buildable / Doubtful / Interesting marks and a note, kept
in the browser (localStorage). **Copy review summary** produces lines such as
`mr-9bb890c9: Buildable, Interesting — note` to paste into a chat or issue.
Thumbnails are rendered with `scripts/render_gallery_thumbnails.js` (dev tool).


## Build mode (assembly assist)

`Build` in the toolbar (or `?mode=build&step=N`, or a gallery card's Build
link) turns the viewer into step-by-step instructions, one rail per step from
the bottom (`viewer/assembly.js`, mirrored by `quadrilla_solver.assembly_plan`):

- step navigation (← Step n / N →) sits in the toolbar next to Build
- step 0: a parts board over the 3D view (icon × count per part, shortfalls
  in red) and the bill of materials, checked against the sets in the layout's
  `bill_of_materials.check` (written by the generator; long rails with and
  without the center hole share a count, wildcard straights fill shortfalls)
- each rail step: the columns that hold it up (bottom to top, on the ground or
  on a lower rail's hole), the rail with its covers / open dive holes / drop
  holes, then blocks standing alone on it (input, twist entry, counterweights)
- last step: everything placed; roll the marble

The 3D view shows what is placed so far: the current step in color, parts
placed in earlier steps dark gray (user request); it outlines the current step and draws
arrows on blocks the marble passes through (green: outlets, blue: fed side
notches); facing is also given in words relative to the step's rail. Blocks
used only as structure are marked "any way round". Done ticks are kept per
layout ID in the browser. The camera is framed once when Build mode opens and
then stays where you leave it between steps (Reset camera reframes).

## Validation in the browser

`viewer/validation.js` (`MarbleValidation.validateLayout`) ports the Python
validators: assembly (stacks, supports, foundations, rotations, curve load,
twist center hole), solid collisions, global stability (COM in the ground
support hull), per-rail statics (moments about each rail's supports, loads
passed down to lower rails, free-standing stacks as point loads), routing
connectivity (via `routing.js`) and marble clearance. Reason strings are the
same as in Python. `tests/test_validation_browser_parity.py` validates every
gallery layout, sample and fixture plus broken variants of each (moved parts,
intruding blocks, missing supports, shifted rails) with both and requires
identical reasons and numbers to 1e-6. One validation of a gallery layout
takes about 1.5 ms, fast enough to re-check on every edit.

The sidebar's Validation box shows the result for the loaded layout (in Build
mode: what is placed so far, without the route).

## Generate in the browser

`Generate` in the toolbar opens a dialog (sets you have, right-angle splitter
or not, max height, area, exits, twists, curves, effort, seed) and runs the
**same Python generator** as `scripts/generate_layout.py`, in the browser:
`viewer/generator-worker.js` loads Pyodide 0.28.3 from jsDelivr in a Web
Worker, copies the files listed in `viewer/py-manifest.json` (the
`quadrilla_solver` package, the catalog and the set files) into its file
system, stands in js-yaml for PyYAML, and calls `quadrilla_solver.web`.
Nothing is re-implemented in JavaScript, so generation rules stay in one place.

The first run downloads Pyodide (about 10 MB); later runs reuse it (about 4 s
for 100 tries in a test browser). Results can be opened in the viewer (and its
Build mode) or downloaded as YAML. After changing the package's file list, run
`python scripts/make_py_manifest.py` (a test checks it).

### Preferences (profiles)

The Generate dialog's **Preferences** section lists every score term (reward
+ / penalty −, with its default weight, meaning and source) and the style
rules that can be changed (max rails, overhang margin, highest block exit,
bracing, exit style). Both lists come from the Python source
(`SCORE_TERMS` in `generator.py`, `STYLE_TUNABLES` in `web.py`) through
`viewer/generator-tunables.json`, so the dialog never drifts from the solver.
Settings can be saved as named profiles in the browser, reset to the defaults,
and exported/imported as JSON. A generated layout records the weights and rules
it was made with under `generator`.

## Edit mode

**Edit** in the toolbar turns the viewer into a small editor. Click a rail or a
block, then:

- block: rotate 90° (keys `R` / `Shift+R`), swap to another block of the same
  height, or remove a free-standing stack (counterweight);
- rail: curve left/right or shorten (the generator's own Python passes, run in
  the worker; the first use loads Python), and cover/uncover open holes.

Every change re-derives the exits from the same input and is validated live
(`validation.js`); the panel shows validity, the exit count and kind, and
parts beyond the sets. Undo/redo (`Ctrl+Z` / `Ctrl+Shift+Z`) and **Save YAML**
are in the toolbar; a saved file records `edited_from`. See
`docs/generator-design.md` §5.

## Review mode

**Review** pins notes to the build. Click a part, a rail hole, a block port or
an empty spot (e.g. unused area), choose a kind and write the note:

| Kind | Meaning | Usually becomes (generator design) |
| --- | --- | --- |
| Physics | would not stand or roll like this | layer 0–1: catalog or validator fix |
| Taste | works, but not wanted | layer 3 rule or layer 4 score term |
| Good | keep doing this | layer 4 / patterns |
| Idea | try something here | layer 2 move or pattern |

Notes, an overall verdict (Good / Doubtful / Bad) and a layout comment are kept
per layout in this browser. **Copy for Claude** puts them on the clipboard as
YAML (component IDs, hole and port, position in cm, the text); paste that into
the chat. Layouts that exist only in the browser (generated, loaded from a
file, or edited) are included in full. **Download** saves the same YAML.
