# Assembly assist (design)

Goal: take a generated layout from the gallery to a physical build without
reading YAML. Decisions from the user:

- steps are **one rail at a time**, bottom up
- it is a **Build mode inside the 3D viewer**, not a separate page
- the bill of materials is **checked against the sets** the layout was
  generated from

## Entry points

- Viewer toolbar: a `Build` toggle next to `Roll`. The URL keeps it:
  `index.html?layout=examples/gallery/<id>.yaml&mode=build&step=3`.
- Gallery cards: `Build` link beside `Open in viewer`.

## Step plan (shared logic, `viewer/assembly.js`, mirrored in Python)

Input: the layout. Output: an ordered list of steps.

1. **Step 0: parts** — bill of materials (see below), nothing placed.
2. One step per rail, in increasing `z_units` (ties: rails another rail
   stands on first, then by id). A rail's step contains:
   1. **Columns**, one per support whose `upper_rail_id` is this rail, each
      listed bottom to top: on the ground (foundation first) or "on
      rail N, hole i". Parts are grouped (`natural x2, purple x3`). Routing
      blocks get a facing hint (below).
   2. **The rail** itself, saying which hole rests on which column ("hole 0
      on column A, hole 3 on column B"), its kind, and for curves the turn.
   3. **Hole fittings**: covers to insert (covered holes), holes left open on
      purpose (a dive exit: "keep empty below"), holes a column passes
      through.
   4. **Free-standing blocks on this rail** (input block, twist entry block,
      counterweights), with their facing.
   A brace rail is a normal step labelled "brace (no marble)".
3. **Last step: check** — roll the marble from the input; the existing roll
   animation runs, with the exit tally.

Dependencies hold by construction: a column only stands on lower rails, so
z order places them first. A rail at the same level as one it touches (e.g.
the twist feed) is ordered after it by id; the plan check below reports any
column that would be placed before the rail it stands on.

## Facing hints

Routing blocks rotate freely, so each block in a step gets:

- in 3D, arrows on the block from each outlet port (front/rear/left/right),
  colored like the route, plus the inlet notch for side-entry blocks;
- in text, where the outlet points: the rail it feeds ("front toward rail 4")
  when a route link or landing exists, otherwise a compass word relative to
  the build's first rail (along / against / left / right of rail 1).

## 3D view in Build mode

- Components of earlier steps: dark gray (user request after the first try).
- Components of the current step: in color, outlined, with facing arrows.
- The camera is framed once when Build mode opens, then kept between steps
  (user request).
- Later steps: hidden (toggle: ghosted at 15 % opacity).
- Holes, support lines and the route overlay follow the existing toggles;
  the route is shown only on placed rails.

## Sidebar in Build mode

- Step header: `Step 3 / 9 · rail 2 (short, level 14)`, Prev / Next, a
  "done" checkbox per step (stored per layout ID in localStorage).
- The step's checklist (columns, rail, fittings, free blocks) as rows; hovering
  a row highlights the parts in 3D.
- Step 0 shows the bill of materials.

## Bill of materials and set check

Counts per part type (rails by kind, blocks by color, purple, foundations,
covers), with color swatches. Compared with the sets in the layout's
`generator.sets` (summed set files, same pooling as the generator: long rails
with and without the center hole share a pool, `straight_unspecified` is a
wildcard straight, twists pool across sizes, `exclude` parts count as zero).
Each row: needed, available, and OK / short by n. Layouts without
`generator.sets` show counts only.

## Out of scope for the first version

- Physical coordinates on a mat; positions are given by connections (which
  hole on which column) plus a top-view minimap of the current step.
- Choosing a different, easier build order; the plan is fixed bottom up.
- Printing; possible later as a "print all steps" view.

## Tests

- Python mirror of the step plan: every component appears in exactly one
  step; no column is placed before the rail it stands on; covers in the
  steps equal the layout's covered holes; the BOM equals `layout_usage`.
- Browser/Python parity of the plan on the gallery layouts (node, like the
  routing parity tests).
- Headless check: Build mode steps through a gallery layout, the number of
  visible meshes grows monotonically, and the last step rolls the marble.
