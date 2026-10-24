# Design Model

## Overview

The working model is **2.5D** rather than continuous 3D.

A placed component is represented conceptually by:

```text
(x, y, z, rotation)
```

where:

- `x, y` describe planar placement
- `z` is a discrete height
- `rotation` is normally one of 0, 90, 180, or 270 degrees

The solver should use only the geometry needed for placement and routing. Viewer meshes are a separate concern.

## Separation of concerns

The system keeps the following data separate:

### Part Catalog

Intrinsic properties of a part type:

- height
- footprint
- ports
- internal routes
- allowed rotations
- rail length / hole positions
- structural role

### Inventory

How many physical pieces are currently available.

Inventory is intentionally separate because the owned sets have missing pieces and counts will be measured later.

### Layout

A concrete arrangement of parts:

- part type
- position
- orientation
- rail placement
- hole configuration
- connections

### Routing Graph

Derived from the layout.

It represents where a marble can travel without requiring a physics simulation.

### Viewer Representation

Optional geometry used only for visualization.

The solver must not require detailed meshes.

## Working height units

Current observations / assumptions:

| Component | Height | Confidence |
| --- | ---: | --- |
| rail | 1 | user-confirmed model height |
| normal routing block | 4 | working model |
| spiral | 3 | tentative; must be confirmed |
| purple drop block | 1 | observed |
| wooden foundation block | 1 | observed |

The discrete model uses integer height units (**levels**). **One level is
1.2 cm** (user measurement, 2026-10-24): five rails or five purple blocks stack
to the height of one standard block, which occupies **5 levels = 6 cm** when
assembled. (Until 2026-10-24 the model used 1.5 cm and 4 levels per block, a
measurement mistake; `scripts/migrate_levels.py` converted the layout files.)
The block's **1 cm connector protrusion** inserts into the mating piece and is
not added to the effective stacked height.

The rail height of **1 level (1.2 cm)** is confirmed by the user. The twist
still spans 3 levels from its chute to its center hole.
Thin/foundation pieces are also modeled as 1 unit, but their physical heights
have not been directly verified. The catalog records this distinction in
`geometry_cm`.

## Ports and routes

A routing block has named ports such as:

```text
TOP
BOTTOM
FRONT
REAR
LEFT
RIGHT
```

A part orientation maps these local directions into world directions.

An internal route is represented independently of the part's physical appearance:

```text
TOP -> FRONT
REAR -> BOTTOM
```

This makes block rotation a simple transformation of the local port graph.

The viewer depicts side exits as **face-centered circular recesses** and side
inlets to downward routes as **bottom-edge semicircular recesses**. The catalog
lists these inlet ports explicitly in `port_visualization.side_entry_notches`,
keeping appearance separate from routing. Actual opening diameters and internal
channel geometry remain unmeasured.

## Rails

A rail is modeled by:

- total length
- ordered hole positions
- a centered longitudinal groove (1 cm wide; depth/profile not yet measured)
- planar placement
- height
- route direction along the rail

Measured straight rails currently include:

```text
long:        length 50 cm, holes at 2, 7, 43, 48 cm
long-center: length 50 cm, holes at 2, 7, 25, 43, 48 cm
short:       length 27 cm, holes at 2, 7, 20, 25 cm
```

The short-rail hole coordinates assume the same end spacing observed on the long rail.

## Rail holes

A rail hole is a connection/routing site. The same physical opening can participate in structure and routing.

Current logical hole states are:

- `empty`
- `block`
- `cover`
- `accelerator`

A future seesaw state/attachment is intentionally deferred.

Implementation should avoid conflating:

1. **structural attachment** — what is above/below the hole
2. **routing modifier** — whether the opening is passed over, used for a drop, accelerated, etc.

A possible representation is:

```text
RailHole
  position
  attachment_above?
  support_below?
  modifier?
```

The final routing behavior is derived from these fields.

## Validation layers

Layout validity is deliberately split into three independent checks.

### Assembly / buildability

Answers **"can these physical parts be assembled in this arrangement?"**

Checks:

- compatible XY placement
- compatible Z levels
- matching rail-hole / part connection locations
- legal part orientation and attachment type
- correct rail variant / mount availability
- no impossible solid overlap
- inventory count not exceeded

### Stability

Answers **"will the assembled structure stand?"**

This is represented as a downward support graph.

Initial rail rule:

- each rail requires at least two effective support points
- normally these should support the two sides/ends of the rail
- an end-plus-center support pattern may also be valid
- every support must ultimately reach ground through already-stable components
- a rail cannot be considered a valid support until that rail itself is stable

This permits real constructions where rails support other rails, including non-rectangular/triangular arrangements, without requiring full rigid-body simulation.

#### Quasi-static force model

For straight-rail stacks, a second stability layer treats each rail as a rigid 1D beam with exactly two compression-only supports.

For each rail, the model recursively aggregates:

- the rail's own weight
- attached point masses
- support reactions transmitted from upper rails

It then computes the effective center of mass and the two support reactions from force/moment equilibrium. Reactions are propagated downward to lower rails until ground.

If either solved support reaction is negative, the configuration would require a support to pull downward/upward rather than merely carry compression, so the rail is classified as tipping/unstable.

The helper also reports a stability margin: the distance from the effective COM to the nearest support. A normalized margin of 1 means the COM is centered between supports; 0 means it lies on a support boundary; negative means tipping in the current model.

Physical force values require actual component masses. Until masses are measured, this helper is used with explicit synthetic/test masses rather than guessed catalog values.

### Connectivity

Answers **"does a valid marble path exist?"**

Checks the directed routing graph independently from the support graph:

- internal block routes
- rail direction and hole state
- routing accessories
- branching/random outputs
- source-to-sink reachability
- optional dead-end detection

A layout can therefore be buildable but unstable, stable but unroutable, or routable in graph terms but physically unbuildable.

### Overall validity

For a complete playable construction:

```text
valid = assembly_valid
     && stability_valid
     && connectivity_valid
```

Individual validators can also be queried independently.

## Generation strategy

The initial generator should favor simple incremental search:

1. place a start routing part
2. enumerate compatible outgoing connections
3. place a rail / next routing part
4. check height, footprint, support, and inventory constraints
5. continue recursively
6. backtrack when no valid continuation exists

The abstract model should later be usable by CP-SAT, WFC, or other search methods without changing viewer code.
