# Project Goal

Quadrilla Designer is intended to help design and physically build Quadrilla marble-run layouts.

## 1. Automatic Design

Generate valid layouts from constraints such as:

- available/owned parts
- allowed footprint
- maximum height
- desired route length
- number of turns, branches, or drops
- desired use of specific parts

The generator should work on an abstract discrete model. It must not depend on realistic 3D meshes or rigid-body physics.

## 2. Viewer

Visualize:

- part placement
- discrete height levels
- part orientation
- rail holes and their states
- the resulting marble routing graph

A simple marble animation is useful, but full physical simulation is explicitly secondary.

## 3. Construction Assist UI

Convert a generated layout into instructions that are convenient while building the physical toy.

Expected functions include:

- level-by-level build steps
- highlighting the next part to place
- showing part orientation
- identifying which rail hole is used
- showing required hole state/modifier
- tracking remaining inventory

## Non-goals for the initial implementation

- accurate rigid-body marble physics
- photorealistic rendering
- exact CAD reproduction of every part
- automatic recognition of a physical build from a camera

These can be added later if they directly improve design or construction assistance.

## Initial milestones

### M0 — Digital representation

- machine-readable part catalog
- machine-readable inventory
- layout format
- route representation
- validator for hand-authored layouts

### M1 — Viewer

- render a valid hand-authored layout
- show route direction and level transitions
- inspect rail-hole states

### M2 — Generator

- generate valid layouts under inventory and footprint constraints
- initially use simple search/backtracking
- introduce CP-SAT/WFC/etc. only if the problem requires them

### M3 — Construction Assist

- transform a layout into ordered build steps
- show orientation and hole placement clearly enough to reproduce the build
