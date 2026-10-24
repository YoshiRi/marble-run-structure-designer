# Generator design

High-level design of how the generator builds a marble-run tower, and where
each kind of rule belongs. This is the reference for future changes: a new
review comment or idea is first placed in one of the layers below, then
implemented there. The goal is to stop the generator turning into a pile of
ad-hoc special cases.

`docs/generator.md` describes the current implementation in detail;
`docs/layout.md` and `docs/parts.md` describe the model. This document is the
map that connects them.

## 1. Goals

In priority order (from the user's reviews):

1. **Buildable**: it stands up with real parts, and the marble really runs
   the route the tool claims.
2. **Fun to watch**: many levels, a long roll on every branch, a few branches,
   twists and curves.
3. **Tidy**: compact, few parts that only hold other parts up, no long rails
   doing nothing, no marble leaving from high up.
4. **Within the owned parts**.

Non-goals: realistic rigid-body physics, arbitrary angles (the build is on an
orthogonal grid plus the curves' fixed geometry).

## 2. Layers

Every rule lives in exactly one layer. Higher layers may use lower ones, never
re-implement them.

```text
 5  Selection      which candidates to show (gallery diversity)
 4  Preferences    score terms: what makes a build better
 3  Style rules    hard filters chosen by the user (could be different for
                   another user or another table)
 2  Construction   how candidate builds are proposed and repaired
 1  Physics        what is true about parts: geometry, routing, statics
 0  Catalog/model  part data, the layout format
```

| Layer | Question it answers | Lives in |
| --- | --- | --- |
| 0 Catalog / model | What parts exist and how are they described? | `catalog/parts.yaml`, `model.py` |
| 1 Physics | Is this layout physically possible, and where does the marble go? | validators: `assembly`, `collision`, `layout_stability`, `connectivity`, `routing_geometry` (+ `viewer/routing.js` mirror) |
| 2 Construction | How do we propose a build, and how do we improve one? | `generator.py` (moves), rewrite passes (`substitution.py`, `balance`, `brace`); runs in the browser unchanged via Pyodide (`web.py`) |
| 3 Style rules | Which valid builds does this user accept at all? | `GeneratorConfig` hard limits |
| 4 Preferences | Among accepted builds, which is better? | `score()` |
| 5 Selection | Which few builds go to the gallery? | `scripts/build_gallery.py` |

### Layer 0–1: Physics is the single source of truth

The validators decide, for any layout:

- **assembly**: every stack closes exactly between ground or a rail hole and
  the rail it holds; foundations only on the ground; parts do not
  interpenetrate; free-standing stacks sit on their hole.
- **routing**: the directed port graph. It uses block internal routes and
  rail chains, where open and block-connected holes interrupt the chain and
  covered holes carry it on. Joints are real port contacts: a side outlet
  lands on a rail beneath, a bottom outlet drops through a hole into the
  column below, and a side exit can drop one unit. The twist's chute is a
  plain rail and its center hole is the outlet.
- **statics**: per rail, moments about its two supports with everything resting
  on it; a global center of mass inside the ground support hull.
- **clearance**: nothing stands where the marble rolls.

A physics fact the user corrects (e.g. "the twist's chute holes drop the
marble through") is changed **here and only here**: in the catalog or a
validator. Construction must never encode its own version of a physics fact,
because the two drift apart. When construction needs physics, it calls the
layer below (e.g. it asks the routing graph whether the marble reaches the
exits).

### Layer 2: Construction = propose, then repair

The generator produces candidate builds in two stages.

**Propose (top-down cascade).** The build grows downward from the input:

```text
input block on a rail
  -> marble lands on the rail, rolls to a stop
       -> drop: a block column under the stop hole
            -> landing: the block stands on a new lower rail (stacked)
            -> ground: the block tops a column from the ground
            -> each other outlet of the block starts a new branch
  -> a branch ends: dive through an open hole, or leave a low block outlet
```

The state is abstract: rails plus **columns** (a base, the hole they hold,
the routing blocks on top). Filler parts are chosen at the end. When a new
lower rail passes through a column at one of its holes, the column is split
(lower part holds the new rail, upper part stands on it). Every move checks
the inventory, the footprint, collisions and marble clearance, so dead ends
are cut early. Randomness picks among the allowed moves; many builds are tried.

The moves, i.e. the grammar of the generator:

| Move | Effect |
| --- | --- |
| place rail | a rail whose marble enters at a point and stops at a hole (or dives) |
| landing drop | drop block on a new lower rail; the marble lands on it |
| ground drop | drop block on a ground column |
| grow outlet | a rail from a block's side outlet (same level or one lower) |
| twist | a twist fed like a rail: landing on its chute, or at its tip |
| end branch | dive through an open hole / leave a low block outlet |

**Moves and patterns.** A *move* is one construction step: one rail or one
block column added, as in the table. A *pattern* is a known combination of
several moves that a person would recognize and reuse, e.g. the triangle
layout on the 23 cm lattice or a brace across a tall column. Patterns are hard
to stumble on by random single moves, so they are added as macro moves: one
step of the search places the whole pattern, which is then checked like any
other move. Patterns come from the user (decision: learn a few known patterns
rather than hope the search finds them).

**Repair (rewrite passes).** A proposed build then goes through a list of
local rewrites. Each pass is named and has one purpose. Trim and brace work on
the abstract state under the same per-move checks, and the build is
validated afterwards. Shorten, curves and balance keep a change only if the
whole build still validates.

| Pass | Purpose | Origin |
| --- | --- | --- |
| trim input | remove the input rail and its columns; marble goes into the top block | review 2 |
| brace | lay a marble-free rail across a weak tower | review 3 |
| shorten | long straight -> short straight when nothing changes; else move a far ground column that holds only this rail along it | dense-stack, layered-tower reviews |
| curves | straight -> curve on the same holes | user idea |
| balance | counterweight blocks for overhanging loads | review 3 |

The order is fixed: trim, brace, shorten, curves, balance.

### Layer 3: Style rules (hard filters)

They are not physics: they say what this user accepts. Each is a config
field with a default, and the source of the default is recorded.

| Rule | Default | Source |
| --- | --- | --- |
| exits are block outlets or dives (`exit_style`) | contained | review 1 |
| at most n exits (`max_exits`) | 2 | review 1 (catching marbles) |
| overhanging load keeps >= 20 g on the lighter support | 20 g | review 3 |
| parts not owned (`exclude_parts`) | right-angle splitter (gallery) | review 3 |
| max height, footprint, max rails | 24 u, 90x90 cm, 12 | setup |

### Layer 4: Preferences (one score)

All "better/worse" judgments are terms of one linear score, each with a
weight and a source. No preference is hidden inside construction moves.

| Term | Sign | Source |
| --- | --- | --- |
| levels | + | goal |
| rolling length (total) | + | review 1 |
| shortest start-to-exit roll | + | review 1 (short branches) |
| random branches, twists, curves, columns on rails | + | goal / variety |
| exit height | - | review 1 (marble from high up) |
| unused top-view area, footprint, idle rail length (braces excluded) | - | reviews 1, 3, layered-tower |
| weak towers (5+ blocks, upper half braced along one axis) | - | reviews 2, 3; one rule, a penalty (decision) |

The terms live in `SCORE_TERMS` (`generator.py`) with their default weights
and sources. A user can change the weights (and some layer-3 rules) as a
**profile** in the viewer's Generate dialog; the layout records the profile
it was made with. Taste goes into a profile, not into code.

Construction biases (probabilities like `twist_probability`) only change
*how often* a move is tried. They are search tuning, not preferences, and
should not be used to express taste.

### Layer 5: Selection

The gallery runs several configurations, removes duplicates by layout ID, and
covers feature buckets (twist, curves, braced, compact, ...) before filling
by score. It never changes a build.

## 3. How a review comment becomes a change

Reviews come in from the gallery (verdict per layout ID) or from the viewer's
Review mode, which pins notes to components (rail, hole, block, port or a
point) with a kind: Physics, Taste, Good, Idea. The kind is the user's first
guess at the layer; step 1 confirms it.

1. **Classify** the comment:
   - a physics fact → layer 0–1
   - "never like this" → layer 3
   - "this is better or worse" → layer 4
   - "the generator never makes X" → layer 2: a new move or pass
   - "the gallery shows too much of Y" → layer 5
2. **Write it down** in the table of that layer with its source (review and
   layout ID).
3. **Test it** at that layer: a validator test with a small fixture, a pass
   test before/after, or a score test.
4. Avoid fixing a physics fact by steering construction (e.g. "never place X
   there") or a style rule by a score weight that is large enough to act as a
   filter.

## 4. Current debt (where the code does not follow this design yet)

- **Physics leaks into construction.**
  - The generator computes hole levels, landing positions and twist stops
    itself instead of asking the routing layer whether a joint works. The
    twist bugs came from exactly this.
  - Target: moves propose; a small "joint check" query (one edge of the
    routing graph) decides.
- **Bracing is a repair, not a move.** Tall builds depend on a pass patching
  towers after the fact. A brace pattern placed when a column grows tall
  would be more natural.
- **Metrics are mixed**: some come from the abstract state (rolled length),
  some from the final layout (area, idle rail). All should come from the final
  layout plus the routing graph.
- **Dead options**:
  - `min_roll_cm` is effectively off.
  - The rail-to-block feed links that only the removed hook entry used are
    still in the code.
- **The search is top-down and greedy.** Builds tend to be one chain per exit;
  with two exits and no right-angle splitter, they are small. A different
  search (bottom-up, or proposing a footprint pattern first) is a layer-2
  change and does not touch the other layers.

## 5. Edit mode (viewer)

The editor is a person doing layer-2 work by hand; it uses the same layers.

| Edit | Where it runs | Notes |
| --- | --- | --- |
| block rotate, block swap (same height) | viewer (field change) | same height keeps every stack closed |
| cover / uncover an open hole | viewer | block-connected holes are left alone |
| remove a free-standing stack | viewer | not the one holding the input |
| curve left/right, shorten | Python passes `substitute`, `shorten` via the worker (`web.edit_json`) | one geometry implementation |

After every edit the routing query's exits are recomputed from the same
input, then `viewer/validation.js` (layer 1) checks the result. Invalid
results are kept and explained; undo goes back. The panel also shows the
layer-3 checks (exit count and kind, parts within the sets). A saved edit
records `edited_from` and a fresh bill of materials; stale metrics are
dropped.

## 6. Decisions

| Question | Decision |
| --- | --- |
| Thin vs weak towers | one rule (weak towers), a **penalty**, not a filter |
| Known layouts (triangle, ...) | add as **patterns** (macro moves) taught by the user |
| Edit mode | port the validators to **JavaScript** with Python parity tests, like routing |
| Learning from review marks | **not yet** |

## 7. Open questions

- Which patterns first, and their exact geometry (the triangle: rail ends on
  the triangle's sides, the middle hole on the perpendicular).
- Bracing: keep as a pass, or turn into a pattern?
- Search: stay top-down, or propose a footprint pattern first?
