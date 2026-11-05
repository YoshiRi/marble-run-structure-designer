# Rebuild from hints

Goal (user, 2026-11-04): reproduce a build from what a person can tell by
looking at it, kept apart from photo detection. Status: straight rails only
(no curves, twists, seesaws); merges are not solved yet.

## Hints

`hints.extract_hints(layout, catalog, base, source)` reads them off a known
layout (the test oracle):

| hint | what a person says |
|---|---|
| `parts` | how many of each part, covers included |
| `towers` | for every spot, the parts bottom to top, `R` where a rail lies across; `>` / `<` mark a block side that feeds / takes a rail end |
| `rails` | per rail: type, the towers it lies on **in order** along it, and `axis` (rails with the same axis are parallel, the others at a right angle) |
| `route` | the marble's steps: `[a, b]` = rolls from tower a to tower b, `[a, -1]` = leaves the run at a |

`spots`, `answers`, `tower_parts` and `rail_ids` are the answer key (for tests
and the viewer), not hints.

## Solver (`hint_solver.py`)

1. **Geometry** (`GeometrySolver`): depth-first over rail placements, tower to
   hole incidences, rail clearance; pruned by the hints (rail towers, order,
   axis), by steadiness (a rail's middle lies between its outermost holding
   columns) and by the covers the hinted route steps need.
2. **Route** (`RouteChecker`): the marble from the route's first tower; a
   block sends it either way along its rail (a red splitter both ways); it
   drops at the first uncovered hole into the column below; a stack standing
   in the way = stuck, a fall from above the lowest level = flies out; the
   steps must equal the route hint and the covers the cover count.

On the generated test builds (grid, 7–9 towers) the full search ends in
seconds to ~1.5 min (CPython) and leaves a few hundred to a few thousand
builds, the original always among them.

## Asking (`hint_quiz.py`)

What is left differs in which hole each tower is in (rails slide along their
towers) and which way parallel rails run. `Quiz` asks the question whose
answer splits the remaining builds most evenly (entropy):

* "On this rail, which hole is tower F in, counting from the end at tower D?"
* "Seen from above, do A→B and C→D point the same way?"

On the four test builds 6–13 answers leave exactly the original.

## Viewer

Debug mode → menu → **Rebuild from hints (test)**. It reads the hints off the
layout on show, lists the builds (Python in the worker, `web.quiz_json`),
labels the towers A, B, … and colors the ones a question is about. Answer, or
let it answer from the original ("Answer all from the original"); "Original"
/ "Candidate" switch the 3D view. Test layouts: `examples/hint_quiz/`
(`?debug=1&layout=examples/hint_quiz/seed14.yaml`).
