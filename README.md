# Quadrilla Designer

An independent, unofficial design-assistance project for studying and building compatible Hape/BorneLund Quadrilla marble-run structures.

This project is not affiliated with, sponsored by, or endorsed by Hape, BorneLund, or any other manufacturer, distributor, or rights holder referenced by the project. Product and company names are used descriptively; see [TRADEMARKS.md](TRADEMARKS.md).

The project focuses on **automatic layout generation**, a **layout/routing viewer**, and a **construction-assist UI**. It intentionally models Quadrilla as a discrete routing/construction system rather than as a full rigid-body physics simulation.

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

Quadrilla is represented as a **2.5D discrete construction system**:

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

The repository is currently in the **specification / catalog-building phase**. Part definitions are being separated into confirmed observations and tentative assumptions so the solver can be built on explicit data rather than implicit knowledge.


## Licensing

- Software: [Apache License 2.0](LICENSE)
- Project-authored documentation, examples, and copyrightable original catalog/measurement content: [CC BY-SA 4.0](CONTENT_LICENSE.md)
- Third-party components retain their own licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

The project also maintains a [defensive publication policy](docs/defensive-publication.md) for algorithmic milestones that are later made public.
