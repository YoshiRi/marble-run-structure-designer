# Viewer

Static Babylon.js viewer for the project's common marble-run `Layout` schema.

## Current MVP

- schematic 3D rails and blocks
- arbitrary rail yaw
- rail-hole markers and hole states
- support links
- route direction / explicit route links
- global center of mass
- ground support polygon
- click-to-inspect part/rail metadata
- load a local Layout YAML file
- no build step

The viewer deliberately uses schematic boxes rather than realistic meshes. Detailed collision geometry is deferred.

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
