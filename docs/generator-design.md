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
  plain rail and its center hole is the outlet. Rails have no direction of
  their own; each is labelled one way, or around a pivot hole: a collector
  (both ends into the hole) or outward (the rail under a seesaw).
- **statics**: per rail, its center of mass (with everything resting on it)
  must lie within its outermost supports, whatever their number; a global
  center of mass inside the ground support hull. On three or more columns the
  split of the load is undetermined, so every extreme split is checked (one
  bracketing pair carries the rail, the other columns only their own weight)
  and all must pass.
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
| max height, footprint, max rails | 30 levels (36 cm; up to 60 ≈ 10 blocks, user), 90x90 cm, 12 | setup |

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
| merges (route nodes reached from two or more places) | + | official builds (§6) |

The terms live in `SCORE_TERMS` (`scoring.py`) with their default weights
and sources. Scoring is expected to change often, so it is extended in one
place: register a metric measured on the final layout with
`@layout_metric("key")` (it gets the layout, catalog, input and routing
graph), add a term, done. The generator, gallery, browser and tunables pick
it up; a profile weight of 0 switches a term off. `scripts/eval_generator.py`
measures any change on fixed seeds. A user can change the weights (and some layer-3 rules) as a
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

## 6. Next: merges and patterns (from the official builds)

A comparison of two official Quadrilla builds (box-art photos) with our
gallery, 2026-10-24. The biggest gap is the shape of the flow, not parts or
rules. Our builds are one tree that splits downward from one input. The
official builds merge routes and hang them on a recognizable frame.

| # | Official builds | Ours | Decision |
| --- | --- | --- | --- |
| 1 | several inputs (purple tops) | one input | later |
| 2 | routes **merge**, e.g. both sides end on one bottom rail | never merge | **yes**: cohesion and complexity for few parts |
| 3 | **triangle** of rails at 60° (plan view) | only by chance (never) | **pattern**, invoked on purpose |
| 4 | **frame**: corner columns, rails as beams on every side at several levels | columns only where a route needs one | **pattern** |
| 5 | **switchback**: parallel rails stacked between two columns, back and forth | rare | **pattern**; helps cohesion |
| 6 | twist feeding a twist | single twists | later |
| 7 | symmetry | random | later (score or pattern property) |
| 8 | a collector rail at the bottom | scattered exits | follows from 2 |
| 9 | red slope covers in front of block outlets | not modeled (`covered_slope` semantics open) | parts work (layer 0–1), needs measuring |
| 10 | red seesaw | modeled (random distributor; docs/parts.md) | generator move: later |

### 6.1 Merge (join move)

A new layer-2 move, **join**: instead of new structure, a branch continues on
a rail another branch already uses.

- (a) A block's side outlet lands on an existing rail below, upstream of that
  rail's stop.
- (b) A rail's stop hole drops onto an existing rail below, upstream of its
  stop.
- (c) The collector: the last rails of two branches both land on one bottom
  rail. This is (a) or (b) aimed at the lowest rail.

Rules:

- **Physics decides the joint.** Construction proposes it; the routing layer
  answers whether the edge exists. This is the "joint check" from §4, built
  here for the first time.
- **No loops.** The joined rail must not be upstream of the joining branch.
- **Clearance.** The landing spot must be on the rail's rolled stretch or
  extend it; marble clearance is checked as for any move.
- **Score.** A new term, `merges` (+): the number of route nodes with two or
  more incoming edges. Source: official builds. Merges also lower the exit
  count, which `max_exits` already rewards indirectly.

Measured before building it (2026-10-24, `scripts/eval_generator.py`, seeds
1–5, 150 attempts, 10 kept per seed; 50 builds):

- Baseline: 1.16 exits per build on average, so almost every build is a single
  chain with nothing to merge. 0 merges. 79.5 % of attempts validate, 10 ms per
  attempt.
- Opportunities in finished builds, i.e. a block outlet that could reach a free
  side inlet of another column (upper bound, no collision check):
  - with one straight rail: 0 of 50 builds. Only 17 outlet/inlet pairs even
    face each other on a line, and their distance misses a rail length by a
    median of 8.5 cm;
  - with rail, drop column, rail: 8 of 50 geometrically, 4 of 50 once the
    heights work.

So merges will not come from searching locally toward the existing
structure (the "target-driven routing" idea). The lengths are fixed and the
grid is orthogonal, so routes coincide by luck only. A merge has to be
**planned**: decide where the routes meet first, then build both routes so
they arrive there. One way to make them meet by construction is **mirror
symmetry**: build one branch after a splitter, mirror it to make the
other, and join both on the mirror plane at a block with two inlets
(natural_drop: front and rear both lead to bottom). That is also the shape
of the official triangle build (two mirrored sides ending on one bottom
rail).

**First merge move: the seesaw diamond** (implemented). A branch that would
dive through a rail hole may instead drop onto a seesaw (`seesaw_probability`,
a search bias). The diamond is built as one unit:

```text
   rail R ── open hole ──┐  drop 6..12 levels (8 first)
                         ▼
   H  ──[blk]────◇seesaw◇────[blk]──   center-hole long rail, flows outward
          │ yellow, front inward │      blocks hold H at holes 0 and 4
   C  ──[ ▶ ]──────►●◄──────[ ◀ ]──   collector: both ends into the center hole
                    │                   (the merge)
          drop column (or a dive)
```

The two arms are mirror images, so they meet by construction. Measured
(`scripts/eval_generator.py`, default weights): 6 % of kept builds have a
merge (0 before). With the merge weight at 25: 24 %, and the footprint shrinks
(2528 vs 2866 cm² without seesaws). Valid rate and time are unchanged. A
diamond uses about 14 levels of height for one split and merge, so with
today's weights it competes with chains of more drop stages.

### 6.2 Patterns

A **pattern** is a template in local coordinates:

- columns (position, base, the levels they hold);
- rails (type, the holes they sit on, level, flow);
- **ports**, where the marble enters it and where it leaves.

Patterns are data (one YAML file each under `catalog/patterns/`) so the user
can teach new ones. Placing one takes an origin, a rotation and a top level.
The parts go through the same per-move checks (inventory, footprint,
collisions, clearance). The route is then built through its ports, and the
whole build is validated as usual.

Two ways to use a pattern:

- **Skeleton first.** Pick the pattern when a build starts, then run the
  cascade from its ports and let other routes join it (§6.1). This suits
  frame and triangle, which shape the whole build. It is the "propose a
  footprint first" search from §4, limited to known skeletons.
- **Macro move.** Place the pattern where an outlet already is, mid-cascade.
  This suits the switchback, which is a route segment.

| Pattern | Shape | Parameters | Geometry known? |
| --- | --- | --- | --- |
| switchback | two columns one rail apart; rails stacked at steps of k levels with alternating flow; at each end a drop block in the column turns the marble back onto the next rail down | turns, rail kind, k | yes (straight rails, drop blocks) |
| frame | four corner columns on a rectangle sized by rail hole spacing; one rail per side, each side lower than the last, so the marble circles the frame downward | rail kinds per side, step | yes (rectangle); spacing to choose |
| triangle, isosceles | base: a center-hole long rail, corners on its end holes (46 cm apart). Two long side rails: 2nd hole on a base corner, end hole at the apex (41 cm). At the apex a 3-hole plate takes both side ends on its outer holes; on its middle hole a median long rail (holes 2 and 4 from the end, 36 cm) runs to the base's center hole | — | yes (user, 2026-10-25); see below |
| triangle, equilateral | three equal sides at 60°; the three sides end up at three different levels, so the corners need many purples | side length | possible in theory, never built (user); later |

**Isosceles triangle, geometry check.** Plate hole pitch p, assumed
4.5 cm (the user says the 2- and 3-hole plates share it). The apex is
h = √(41² − (23 − p)²) from the base: 36.59 cm for p = 4.5 (36.33 for 4.0,
36.84 for 5.0). The median spans 36 cm, so it is 0.6 cm short, which the
1.8 cm holes can absorb at two joints ("it fits by a miracle", user). The
apex angle is 54°, the base angles 63°. The side rails and the median
all rest on the base rail, one level up, and the plate ties their apex ends.

How it stands (user, 2026-10-25), fixture `triangle-isosceles.yaml`
(`scripts/make_triangle_fixture.py`):

| where | from the ground up |
| --- | --- |
| base corners (2) | foundation + block (6) → side rail (z 6, 2nd hole) → block → base rail (z 12, end hole) |
| apex side ends (2) | foundation + block (6) → side rail (z 6, end hole) → 3-hole plate (z 7, outer hole) |
| base center | base (z 12) → red splitter (13–18) → median (z 18, hole 1) |
| apex middle | plate (z 7) → two blocks (8–18) → median (z 18, hole 2) |

Rails are not laid straight on rails: a marble would only drop through the
hole, so a block stands between (user). The red splitter belongs at the
base end; at the apex its two sides are weak (user).

Route (fixture): the marble enters at the median's apex end, rolls to the
base end and drops into the red splitter, whose outlets face the base's two
ends (user). Each half rolls along the base (holes 1 and 3 covered) into a
corner block that sends it down the side rail toward the apex. The plate
lies on the side's end hole, so the marble drops through hole 2 just before
it. This build is one of the official examples (user).

**As a generator pattern** (`patterns.isosceles_triangle`,
`GeneratorConfig.triangle_probability`, built 2026-10-26). At a drop high
enough (25 levels or more), the drop block lands on the median's apex end,
with pass-through parts above it, and the whole triangle is placed below,
turned to one of four directions. It ends the branch with two exits (both
sides). The triangle keeps its own supports: the support solver skips such
builds, and curve swaps leave its rails alone. Its structural rails do not
count as idle rail. The score term `triangles` (+20) recognizes the
structure in any layout (a plate on two rails carrying a column on its
middle hole).

Measured (owned inventory, 3 seeds, kept builds with a triangle):

| | 30 levels | 45 levels |
| --- | --- | --- |
| p 0.3 | 2 / 30 | 7 / 30 (best 147) |
| p 1 | 12 / 30 | 17 / 30 (best 141; mean score 129.8 vs 126.9 at p 0.3) |

Gallery configuration `triangles` and bucket "triangle".

**Base lottery** (user, 2026-10-26; `GeneratorConfig.bases`, default
`{triangle: 1, diamond: 1, free: 1}`). Each attempt draws one base design
by weight and the build must end on it, else the attempt is dropped:
triangle (the triangle at a drop with room), diamond (the seesaw split and
merge, §6.1) or free (the plain search). A weight of 0 leaves a base out,
e.g. to explore without triangles. The viewer's dialog has one weight per
base. A placed pattern keeps its own supports while the support solver
re-solves the rest (no more greedy braces left over the pattern).

Measured (owned inventory, 5 seeds, 150 attempts, 50 kept builds):

| | valid / attempt | kept: triangle / diamond / free | score | parts | ms / attempt |
| --- | --- | --- | --- | --- | --- |
| 30 levels, plain | 0.79 | 0 / 13 / 37 | 105.8 | 27.9 | 17 |
| 30 levels, lottery | 0.29 | 9 / 19 / 22 | 105.2 | 27.4 | 8 |
| 45 levels, plain | 0.83 | 0 / 3 / 47 | 133.2 | 51.0 | 49 |
| 45 levels, lottery | 0.38 | 17 / 5 / 28 | 127.7 | 44.4 | 25 |

Attempts whose base is not reached are dropped early, so they cost little.
More base designs are wanted (user examples, as with the triangle).

Extensions (user, 2026-10-25), next:
- **double sides** (official): one more level of rails and blocks under
  each side;
- **apex tray**: a catcher at the apex takes the marbles from both sides
  (the large trays are counted but not modeled yet).

Four columns. Routes from the base down to the side rails that also keep it
stable are few (user).

Modeling: a hole plate laid across rails is a short rail without a groove
(catalog `beam`, shape `plate`; nothing rolls on it). The median's two
joints declare `play_cm` 0.3 each, capped by `geometry_cm.max_joint_play_cm`
(0.35, provisional until the peg diameter is measured); without it the
assembly check reports `support_xy_mismatch`.

The viewer and the validators already handle any angle: every gallery
layout turned by 30° or 60° stays valid, and Python and the browser agree
(`+rot60` in the parity test). Only the generator's moves are on the
90° grid; the triangle would be a placed skeleton.

### 6.3 Route first, supports after (two phases)

Proposal (user, 2026-10-24): lay the route first while ignoring
buildability, then add supports. **The vertical joints of the route cannot
be deferred.** In Quadrilla the drop from one rail to the next *is* a block
column, quantized in 5-level blocks and 1-level purples. So the route phase
keeps the joint geometry exact. What can be deferred is everything the marble
never touches: the second support of each rail, plain columns, braces and
counterweights. In the gallery that is 77 % of the parts (9 of about 15
columns per build).

**Support phase** (`supports.py`, first step built). It strips the columns
the marble never touches, then solves the supports for all rails at once
(depth-first, branch-and-bound):

- each rail gets exactly two supports on a valid hole pair;
- a column stands on the ground or on a lower rail's aligned hole (a tower);
- columns stay out of the marble's path and falls;
- the solver keeps parts minimal and prefers shared spots;
- the best few solutions are validated and ranked with weak towers.

Measured (`scripts/eval_supports.py`, `scripts/eval_generator.py` with
`solve_supports`):

| | parts | footprint cm² | unused area | weak towers | valid | ms/try |
| --- | --- | --- | --- | --- | --- | --- |
| 30 levels, greedy | 32.6 | 2840 | 156 | 0 | 78 % | 14 |
| 30 levels, solved | 28.6 | 2506 | 68 | 0.02 | 68 % | 36 |
| 45 levels, greedy | 59.7 | 3803 | 225 | 1.1 | 70 % | 42 |
| 45 levels, solved | 49.8 | 3052 | 138 | 1.2 | 74 % | 108 |

The gain comes from shorter columns standing on lower rails, and from
dropping the greedy braces. Keeping the braces and re-solving changes
nothing. Shared spots (towers and frames) hardly appear, because the route
rarely puts holes of different rails above each other. So **frames have to
be planned in the route phase** (patterns: switchback, frame), and the
support phase then turns the aligned holes into towers. `solve_supports` is
on by default since 2026-10-25 (user decision). Measured on the owned
inventory, 30 levels, 5 seeds: parts 32.6 → 27.9 (−14 %), footprint
2797 → 2280 cm² (−18 %), merges 0.16 → 0.28, score 105.5 → 105.3,
valid 84 → 80 %, 11 → 30 ms per attempt.

**Search schedule** (user idea, 2026-10-25): branch early, align later.
`align_weight` makes later placements try rails whose holes lie over or
under existing holes first (2D distances, ready for a triangular lattice);
`early_split_boost` raises the splitter chance near the top. The score gains
`shared_towers` (+3 per spot where columns hold two or more rails one above
the other). Measured: the bias barely changes alignment (4.6 aligned hole
pairs per build at weight 8 vs 3.9 at 0) and the towers stay around 2. The
moves leave too few choices: the rail type, a hole and the direction. With
fixed rail lengths, a rail's other holes rarely land over earlier holes. Off
by default. Alignment has to come from moves that create it: patterns.

**Switchback** (implemented as a landing preference, `switchback_probability`).
When a drop lands on a new rail, try first a rail of the same type lying right
under the rail above, reversed: its block hole is the mirror of the upper
stop hole (holes[k] = length - holes[stop]), so every hole lines up with the
one above. The drop column at each end is the support of the rail above, so
the ends become towers through the whole run. The switchback uses the
alignment schedule (`align_start_depth`).

Two physics changes came with it:

- Statics accepts a rail on any number of columns (two or more). Tipping is
  checked on the outermost pair; the load sent down is checked for every
  extreme split (each pair of columns bracketing the center of mass carrying
  it). The 20 g rule uses the outer pair. Of 199 layouts (gallery, fixtures,
  generated), 58 have a rail on 3+ columns and 2 became invalid, both the same
  case: a long rail balanced on its center column, which stands on the
  overhang of a lower rail (mr-f66be837, dropped from the gallery). The seesaw diamond's collector now keeps both end columns when the
  branch continues under its center.
- The support solver applies the overhang style rule (≥ 20 g on the lighter
  support) when choosing among its solutions.

Measured (30 levels; switchbacks allowed from the top, supports solved):

| | switchbacks | footprint cm² | shared towers | merges | valid | score |
| --- | --- | --- | --- | --- | --- | --- |
| default | 0.06 | 2677 | 2.7 | 0.14 | 84 % | 108.3 |
| supports solved | 0.10 | 2622 | 2.2 | 0.14 | 79 % | 108.1 |
| switchbacks + solved | 1.88 | 2265 | 2.9 | 0.94 | 59 % | 105.3 |

Switchbacks make the build about 15 % smaller in top view, with more towers
and, through more dives, more seesaw diamonds. They trade some rolled length
and twists, so they lose a few points under today's weights. The gallery has
a `switchbacks` configuration and bucket. The defaults are unchanged until
the user reviews them.

**Frame** (`frame_probability`, `frame_min_height_units` 45, `frame_sides` 6, `frame_min_side_cm` 18;
built 2026-10-25). A run of drops that each turn the marble 90° the same
way. The first two sides are free (at least 18 cm); the third fixes the
rectangle, so later rails must stop exactly on its corners. It is a macro
move that continues across drops (`_State.frames`), started with the
alignment schedule. The metric `frame_turns` (longest run of same-way turns
along the route, score +2 each) and the gallery bucket "frame" (≥ 3 turns)
measure it. Measured (owned inventory, 3 seeds):

| | parts | footprint cm² | shared towers | merges | score | valid |
| --- | --- | --- | --- | --- | --- | --- |
| 30 levels, off | 28.8 | 2283 | 2.3 | 0.33 | 107.2 | 82 % |
| 30 levels, p 0.5 | 27.0 | 2618 | 2.4 | 0.07 | 111.9 | 84 % |
| 30 levels, p 1 | 26.7 | 2829 | 2.5 | 0 | 113.7 | 85 % |
| 45 levels, off | 49.5 | 3572 | 3.6 | 0.10 | 116.8 | 80 % |
| 45 levels, p 1 | 49.8 | 3531 | 4.2 | 0.03 | 129.4 | 82 % |

At p 1 and 45 levels, 30 % of the kept builds have three or more turns in a
row. A frame takes over the drops, so merges and switchbacks almost vanish.
A twist breaks the run. Default (user, 2026-10-25): on (p 1) only in tall
builds, `max_height_units` ≥ `frame_min_height_units` (45).

### 6.5 Annealing (polish a build)

User idea (2026-10-26): improve a random build by local changes, as in
simulated annealing: move columns, swap blocks, re-attach rails, add a
switchback. First version (`anneal.py`, `scripts/anneal_layout.py`): the
generator's random decisions are recorded as a tape; a neighbour re-rolls the
tape from a point (re-grows everything after it), changes one decision, or
nudges one. Every neighbour is grown by the generator and goes through the
same validation and post-passes, so each step is buildable; the score is the
generator's. Worse neighbours are accepted with exp(Δ/T).

Measured (triangle base, 45 levels, 300 neighbours, 4 seeds):

| start | start score | after annealing |
| --- | --- | --- |
| first valid random build | 131.0 | 143.8–146.1 (T from 3–8 down) |
| best of 150 random builds | 153.7 | 157.9 (+15.9 on one seed, +0.7 on one, 0 on two) |
| (best of 300 random builds, no annealing) | | 158.4 |

So far the tape is a weak neighbourhood: a change early in the tape reshapes
everything after it, so annealing behaves much like re-sampling the lower
part. It helps a weak start, barely a good one. Next: layout-level moves
that keep the rest in place (move a column onto an aligned hole, swap a
drop block for the merge block where a rail ends against it, re-attach a
rail end, insert a switchback), with the tape re-roll kept as the large
move.

**Layout-level move: turn the part above a drop** (user review of
mr-a5c66ca1, 2026-10-26: "turn this four-corner frame by 90 degrees; columns
would be shared and a switchback could be added"). `rotate_above` turns
every rail upstream of a drop column, with their drop columns and marble
corridors, by 90/180/270 degrees about that column's axis; the column stays
and its lower rail does not move. Plain supports of the turned part are
dropped and solved again. The footprint is checked as a size, not a place.
On mr-a5c66ca1 (165.6 through the same passes): of the 9 turns, 5 hit the
rest of the build, 2 had no valid supports, and the valid ones scored lower
(upper part 180° about the drop onto the median: 159.2, larger footprint,
the frame's same-way turns broken; the twist 90°: 150.6). The turn that
opens a switchback needs the switchback inserted too: a move to combine.

**Score term `pattern_columns`** (+4, user review of mr-5119dc15): columns
of the build that stand on a triangle base's rails (corners, beams) rather
than on the ground. **Annealing with moves** (`anneal_with_moves`): the
state is (tape, list of turns); a step changes the tape (the turns are
dropped) or adds, removes or changes a turn. On mr-a5c66ca1 no turn improves
the score: what the reviews ask for (a merge block at the base center fed
from above and the side, a switchback through the apex column, ground
columns moved onto the triangle's ends) changes the route, not just its
orientation. Those route-level moves are next.

### 6.6 Generation strategies (switchable)

User decision (2026-10-27): several generation patterns to switch between
(`GeneratorConfig.strategy`, the viewer's "Generation" choice).

- `top_down` (default): the cascade from the input down; a base is drawn
  by the lottery (§6.2).
- `bottom_up`: the triangle base is placed first, centered, in one of four
  directions. The route then grows upward from its entry (the median's apex
  end): each step puts a rail above whose stop hole drops the marble,
  through a block, onto the rail below. Rails whose holes lie over existing
  holes (the base's corners and beams, other rails) and reversed rails right
  above (switchbacks) are tried first, with some randomness. The supports
  must bracket the hole the next block stands on. A free-standing input
  block tops the last rail. Reviews of the annealed builds asked for this:
  the route should be chosen knowing the base.

Measured (owned inventory, 3 seeds, 100 attempts, 30 kept):

| | valid / attempt | mean score | rails | parts | shared towers |
| --- | --- | --- | --- | --- | --- |
| 30 levels, top_down (lottery) | 0.29 | 105.2 | | 27.4 | |
| 30 levels, bottom_up | 1.00 | 115.4 | 8.0 | 34.0 | 3.0 |
| 45 levels, top_down (lottery) | 0.38 | 127.7 | | 44.4 | |
| 45 levels, bottom_up | 1.00 | 149.6 | 10.5 | 50.6 | 4.7 |

The bottom-up builds stack a compact zigzag tower over the apex. Still
missing: switchbacks are rare (0 kept), and only the feed column stands on
the base (pattern_columns 1). Next: the merge at the base center fed from
above and the side, and supports preferring the base's holes.

**Experiment: fewer new columns, stay over the base** (user, 2026-10-27).
`ground_column_penalty` (the support solver's extra cost per ground column),
the score term `ground_columns` (off by default) and `up_within_base` (rails
grown bottom-up keep both ends inside the base's top-view box, 5 cm margin).
45 levels, bottom-up, 3 seeds × 100 attempts, 30 kept; score without the
new term:

| | score | ground columns | columns on the base | rails | parts | footprint cm² | levels |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 149.6 | 3.4 | 1.0 | 10.5 | 50.6 | 4814 | 8.0 |
| ground penalty (6, term 8) | 146.6 | 2.4 | 1.0 | 10.4 | 40.8 | 4679 | 7.6 |
| within base | 158.9 | 4.0 | 1.0 | 10.8 | 55.9 | 3275 | 8.0 |
| both | 158.3 | 3.8 | 1.0 | 10.7 | 54.0 | 3248 | 7.9 |
| both, strong (15, term 20) | 130.6 | 2.0 | 1.0 | 9.2 | 36.2 | 2971 | 6.9 |

Staying over the base shrinks the footprint by a third and raises the score,
but the rails over the base's open middle need ground columns there. The
ground penalty cuts parts by a fifth; strong, it also cuts the route (fewer
rails and levels). No setting puts more columns on the base itself: its
holes rarely line up with the grid of the rails above (the sides are at
63°; the base center holds the red splitter). That needs placement that
aims at the base's free holes (corners, side holes, plate ends).

**Experiment: rails at any angle** (`up_free_angles`, off). Holes are round,
so a column joins rails at any angle (user). Bottom-up growth also tried
every angle that puts another hole of the new rail over a base hole. 45
levels: valid 52 % (100 % on the grid), score 102.8 alone and 149.9 within
the base (grid: 163.3), columns on the base 1.1. The aimed angles win the
ordering, then dead-end. Not kept. User's next idea: keep a 2D map of hole
sites for the whole build (the base's holes first) and make columns stand
only on those sites, a new site costing extra.

### 6.4 Order of work

1. The join move and the `merges` term, in the current generator. A
   gallery bucket "merged".
2. The pattern format, placement and checks, with the switchback as the
   first pattern (a macro move). A bucket "switchback".
3. The frame (built as a macro move, 2026-10-25; a skeleton-first variant is open).
4. The triangle, once its geometry is fixed.

Each step adds a fixture and a test at its layer (§3).

## 7. Decisions

| Question | Decision |
| --- | --- |
| Thin vs weak towers | one rule (weak towers), a **penalty**, not a filter |
| Known layouts (triangle, ...) | add as **patterns** (macro moves) taught by the user |
| Edit mode | port the validators to **JavaScript** with Python parity tests, like routing |
| Learning from review marks | **not yet** |
| Several inputs | **later** (official builds have them; low value now) |
| Merging routes | **yes**, a join move (§6.1) |
| First patterns | **switchback, frame, triangle** (§6.2) |

## 8. Open questions

- TODO (user, 2026-10-24): register several **good-design combinations** as
  patterns (§6.2). Waiting for the user's examples.
- TODO (user, 2026-10-25), at a good stopping point: make **efficient
  structures like the isosceles triangle** (official builds) usable in two
  ways, to raise the human score:
  - **call them as one large pattern** (a skeleton the generator places
    first, then grows routes and towers from its ports: here the median's
    apex end in, the two side drops out, the red splitter's column up);
  - **score them**: a term that recognizes the structure in any layout
    (e.g. a triangle of rails sharing corner columns, a tower standing on a
    plate), so builds that reach it on their own also gain.
  Both need a pattern format with ports and a recognizer per pattern; the
  triangle is the first entry (placed and recognized, §6.2, 2026-10-26). Next for the triangle itself: double
  sides (official) and an apex tray (needs the tray measured).
- The triangle's exact geometry: settled for the isosceles type (§6.2,
  fixture `triangle-isosceles.yaml`); the equilateral type is later.
- Bracing: keep as a pass, or turn into a pattern?
- Search: stay top-down, or propose a footprint pattern first?
