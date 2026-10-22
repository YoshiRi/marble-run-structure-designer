# Marble Run Structure Designer

An independent, unofficial design and validation tool for modular marble-run structures, currently modeling compatibility with Hape Quadrilla parts distributed by Hape/BorneLund.

This project is not affiliated with, sponsored by, or endorsed by Hape, BorneLund, or any other manufacturer, distributor, or rights holder referenced by the project. Product and company names are used descriptively; see [TRADEMARKS.md](TRADEMARKS.md).

The project focuses on **automatic layout generation**, a **layout/routing viewer**, and a **construction-assist UI**. It models modular marble runs as discrete routing/construction systems rather than full rigid-body physics simulations.

## Project goals

1. **Automatic Design**
   - Generate buildable layouts from available parts, footprint/height constraints, and routing goals.
   - Treat the owned inventory as a constraint rather than hard-coding one commercial set.

2. **Viewer**
   - Visualize the generated layout and marble routes.
   - Start with 2.5D/discrete geometry; simple marble animation may be added later.
   - Full physics simulation is not a primary goal.

3. **Construction Assist UI**
   - Turn a generated layout into practical build instructions.
   - Show level-by-level placement, part orientation, rail-hole usage, and remaining inventory.

## Core modeling idea

The supported marble-run construction system is represented as a **2.5D discrete model**:

- planar placement in \(x, y\)
- discrete height \(z\)
- orientation (normally 0/90/180/270 degrees)
- routing represented as connections between ports
- rendering geometry kept separate from solver geometry

The current working height units are:

| Part | Height units | Status |
| --- | ---: | --- |
| rail | 1 | working model |
| standard routing block | 4 | working model |
| spiral | 3 | tentative |
| purple drop block | 1 | observed |
| wooden foundation block | 1 | observed |

See [docs/model.md](docs/model.md) and [docs/parts.md](docs/parts.md) for the current specification.

## Repository layout

```text
.
├── catalog/
│   ├── inventory.yaml
│   └── parts.yaml
├── docs/
│   ├── decisions/
│   │   └── 0001-use-2.5d-discrete-model.md
│   ├── model.md
│   ├── open-questions.md
│   ├── parts.md
│   └── project-goal.md
├── examples/
│   └── four-level-zigzag.yaml
├── solver/
├── viewer/
└── ui/
```

The repository includes a Python layout validator and a schematic browser viewer. The generator, construction-assist UI, and full browser-side solver are planned. Part definitions distinguish measured observations from provisional assumptions.


## Viewer

Run the static viewer locally with `python -m http.server 8000` from the repository root, then open `http://localhost:8000/viewer/`. See [viewer/README.md](viewer/README.md). The published site is hosted on GitHub Pages.

Deployment uses the `gh-pages` branch:

- pushes to `main` publish the site root (`.github/workflows/pages.yml`)
- every pull request that touches the viewer, catalog or examples gets a preview at `https://yoshiri.github.io/marble-run-structure-designer/pr-preview/pr-<number>/`, linked in a PR comment and removed when the PR closes (`.github/workflows/pr-preview.yml`)

Both build with `scripts/build_site.sh`, so a preview matches what `main` would publish. GitHub Pages must be set to **Deploy from a branch → `gh-pages` / root** (Settings → Pages).

## Licensing

- Software: [Apache License 2.0](LICENSE)
- Project-authored documentation, examples, and copyrightable original catalog/measurement content: [CC BY-SA 4.0](CONTENT_LICENSE.md)
- Third-party components retain their own licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

The project also maintains a [defensive publication policy](docs/defensive-publication.md) for algorithmic milestones that are later made public.
