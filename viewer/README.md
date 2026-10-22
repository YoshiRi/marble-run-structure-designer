# Viewer

Static Babylon.js viewer for the project's common marble-run `Layout` schema.

## Current MVP

- schematic 3D rails and blocks
- arbitrary rail yaw
- visible rail-hole cutouts (Babylon.js CSG, with surface-marker fallback) and color-coded hole states
- support links
- route direction / explicit route links
- global center of mass
- ground support polygon
- click-to-inspect part/rail metadata
- load a local Layout YAML file
- no build step

The viewer deliberately uses schematic boxes rather than realistic meshes. Detailed collision geometry is deferred.

## Dimension provenance

The viewer reads rail lengths and hole positions from `catalog/parts.yaml`.
Long-rail length (50 cm) and hole positions (2, 7, 43, 48 cm) are measured.
Short-rail length (27 cm) is measured; some short-rail hole positions are inferred.
The center-hole rail includes a cataloged center position at 25 cm.

**Provisional rendering dimensions (not physical measurements):**

- 1 height unit = 3 cm
- rail width = 3 cm
- block footprint = 5 × 5 cm
- hole diameter = 1.5 cm

The solver stores vertical positions in abstract height units. Do not treat the
viewer as a dimensional CAD model until these dimensions are measured and
recorded with provenance.

The colored rings distinguish open, covered, block-connected, and slope-covered
rail holes. Covered holes are shown with caps. CSG creates real through-holes
where available; otherwise the viewer uses dark surface markers as a fallback.

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

The viewer is fully static.

The canonical solver currently remains Python. A fully static hosted application has two viable paths:

1. **Port the solver core to TypeScript/JavaScript** and execute it directly in the browser. This is the preferred long-term path because the solver is mostly deterministic graph/geometry/statics logic.
2. Run the existing Python solver through **Pyodide**. This minimizes code duplication but adds a large browser runtime and slower startup.

The Layout YAML and catalog YAML remain the shared interface either way.

## Deferred

- realistic meshes
- collision detection
- browser-side full Assembly / local statics / Connectivity / Inventory validation
- construction-assist overlays
- marble animation
