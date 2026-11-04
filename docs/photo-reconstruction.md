# Building a layout from photos (plan, 2026-11-04)

Goal (user): from photos of a real build, recover its structure as a layout,
even with imperfect detection, by combining hints (use case C; A = attach
photos, B = read the parts list, are steps on the way).

## What a photo gives, and what it does not

Tried on one real photo (a living room, ~10 rails, ~35 blocks) and one
official example image:

- Open-vocabulary detection (YOLOE, no training): 4 rails, 2 trays, almost no
  blocks. Not usable as is.
- Segment everything (SAM2) + color: blocks come out one by one (blue,
  yellow, green, cyan, orange, purple, red); background furniture too; rails
  are not separated from the wooden background.
- A vision-language model reading the photo: levels (~8–9), rails (~10),
  blocks (~30+), special parts present; not exact counts, not which hole.
- The real build uses things the model cannot express yet: the large green
  seesaw (a part not in the catalog yet; the user will add it), catch trays,
  accelerators on rails. (A rail that looked tilted in the photo is level:
  user, 2026-11-04 — perspective.) The official examples use large chutes.

## Idea: hints, then a solver

Quadrilla is very constrained, so weak evidence can fix a lot:

| constraint | what it pins down |
| --- | --- |
| levels are 1.2 cm; blocks 5 levels, purple 1, rails 1 | a column's color sequence gives every rail height along it, with no camera calibration |
| columns are vertical stacks at a hole | blocks in a vertical image run = one tower |
| rail holes are 5/13/18/23/36/41/46 cm apart | tower-to-tower distances along a rail |
| a rail rests on two or more columns | which towers a rail joins |
| the marble must route and the build must stand | prunes candidates |

Pipeline:

1. **2D evidence** per photo: block masks with color (SAM2 or a trained
   YOLO-seg), rails as line segments, holes as ellipses, special parts.
2. **Towers**: group blocks into vertical runs; read each run bottom to top
   (e.g. green, purple, yellow, green, purple, cyan) → rail levels at that
   tower.
3. **Incidence**: which rail ends sit on which towers (image proximity).
4. **Solve**: discrete search for tower positions (x, y) so rail spans match
   hole distances, heights match the color sequences, the route runs and the
   build stands (the existing validators); rank by agreement with the masks
   (render each candidate from the estimated camera, compare).
5. **User hints** where the solver is unsure: tap "this is the same tower in
   both photos", "this rail is a short one", the number of levels, a second
   photo from the side. Then solve again.

Training data for step 1 can come from this project: the generator and the
3D viewer render any number of layouts with every part's pose known, so
masks and boxes label themselves; a few dozen hand-labelled real photos close
the gap between renders and photos. Runs in the browser (ONNX / WebGPU).

## Model work needed first

- The large green seesaw (user to describe), large chutes, catch trays,
  accelerators in the catalog.

## Direction (user, 2026-11-04)

Solving from hints is developed and tested apart from detection: given the
parts used, the order they stack in, and the base shape (square grid,
triangle...), can the solver rebuild the same structure? See
`src/quadrilla_solver/hints.py` and `hint_solver.py`.

## Discovery steps

1. **Hints by hand → solver** (no ML): write down the towers' color
   sequences and the rail-tower incidences of one photo by hand and see
   whether a solver recovers a valid layout. Tests the core idea.
2. **Synthetic renders**: render generated layouts with random cameras,
   lights and backgrounds, with masks; check that they look close enough to
   photos.
3. **Small detector**: train YOLO-seg on the renders (+ a few real photos);
   measure block detection on real photos.

## Official example images

Product photos and instruction images belong to their publisher. This
repository is public under Apache-2.0, so committing them would republish
them under a license we cannot grant. Keep instead: a link to the source and
our own description of the build (a layout YAML recreating it, our own render).
Our own photos can be committed (crop out people and the room).
