# Layout Generator (M2)

The layered design behind this (physics, construction, style rules,
preferences, selection) is in `generator-design.md`; start there before
adding a rule.

`scripts/generate_layout.py` searches for buildable layouts from the combined
contents of one or more commercial sets and writes the best ones as Layout YAML
that the viewer can open.

The default inventory is `OWNED`, the user's counted collection
(`catalog/inventory.yaml`, 2026-10-25). It counts the center-hole long rails
(seesaw mount) apart from the plain ones; set presets do not, so there both
draw from one long-rail pool. Set presets can still be named with `--sets`.

```bash
python scripts/generate_layout.py --sets OWNED --attempts 600 \
    --seed 1 --keep 3 --out-dir examples/generated
```

Options: `--max-height` (top rail level, levels of 1.2 cm; default 30 = 36 cm), `--footprint WxD`
(cm), `--max-rails`, `--split-probability`, `--seed`, `--attempts`, `--keep`.

## What it builds

A descending cascade grown from a top rail (`rail0`, marble enters at end A).
Each rail carries the marble to a block-connected **stop hole**, where it drops
into a **drop block** (a routing block whose top opening leads to side outlets:
yellow, blue, green, cyan, red splitters), optionally under pass-through parts
(purple drop, orange vertical) that lengthen the fall. Two drop modes:

- **Landing drop**: the drop block stands on a new rail beneath it and lands the
  marble on that rail just past its face (see `docs/layout.md`). The block both
  holds up the upper rail and routes onto the lower one. Long rails may be the
  center-hole variant, so a rail can drop at its center and leave the other half
  free.
- **Ground drop**: the drop block tops a ground column; each side outlet feeds a
  new rail starting at the block face, at the outlet floor or one unit lower.

Red splitters fork the cascade.

## Curved rails (substitution)

With curves in the inventory (add the older Twist set: `--sets
QD001,QD003,QD005,QDE6008AB05`), each valid candidate is post-processed: a short
straight becomes a short curve, and a center-hole long rail an S-curve, when
the curve's holes coincide with every hole the straight uses (holes 0/3 and
0/2/4), the marble does not enter it through an explicit link at its end, and
blocks standing on it only land the marble on it. Those blocks turn with the
curve's tangent (+-30 deg); everything below the rail is unchanged. Every swap
is re-validated; short and long curves also need a block standing on them.

While building, `--curve-bias` (default 0.5) is the chance to prefer these
"curve-ready" holes. At 0.5 the best scores are essentially unchanged and kept
layouts carry about one curve each; higher values add curves at some cost in
score. Curves also save covers: a curve has no holes between its end holes.

## Twist

The twist (QD005 lists 3; the user's two are the same size) has two chute
holes and a funnel center hole; its chute is a plain rail. The generator
feeds it like one:

- **landing**: a drop block stands on a chute hole and lands the marble along
  the chute (also the input block)
- **tip**: a block outlet feeds the chute's tip

The funnel then drops the marble through its center hole into a new drop
column. `twist_probability` (default 0.5) is the chance to try a twist first.
An earlier "hook" entry (a rail into a blue/green/natural block on a chute
hole, dropping from its bottom) was removed: the marble falls straight through
the chute hole into the block below (user review of mr-c61a3513).

## Input and towers

The marble is put straight into the top block (user review 2: an input rail
only wastes columns). The build still starts from a top rail with a drop
column under it, but the first drop must land on a lower rail; then the top
rail and the columns that only held it are removed, and the drop column stays
as a free-standing stack on its rail. Its top part is the source
(`routing_query.source`, e.g. `c1_0_blue:top`); the viewer lists it as an
input. `trim_input_rail: false` keeps the old input rail.

A **weak tower** is a stack at one spot with 5 or more blocks (5-level parts;
purple 1u pieces and foundations not counted) whose upper half is braced in
one direction only: every rail touching it at or above half its height runs
along one axis (a rail near the ground hardly braces the top). It topples
easily (user reviews 2 and 3). This is one rule and a penalty, -15 points each
(user decision, `generator-design.md`); an earlier "thin tower" filter was
merged into it.

Review 3 refinements:

- **support reactions**: the statics take moments about each rail's two
  supports with everything resting on it, now including free-standing stacks
  (input block, twist entry block). A rail carrying a load **outside** its
  supports must keep its lighter support pressing with at least
  `min_support_reaction_g` (20 g); `balance()` adds counterweight blocks on
  free holes the marble does not roll over (user idea), or the candidate is
  dropped. A rail resting with its own center of mass on one support (center
  hole plus an end) is accepted: review 3 rated such builds buildable.
- **brace rails** (`brace_towers`, user's choice after review 3): for each
  weak tower, a straight rail carrying no marble is laid across it in its
  upper half, at right angles to the rails it holds; the tower's column is
  split at one of the brace's holes and the other support is another crossed
  column or a new short one. Bracing roughly tripled the candidates that
  passed the former thin-tower filter. Brace rails stay straight (no curve substitution).
- **unused area** (`dead_area_cm2`, user definition): top-view area taken by
  rails and columns where no marble rolls (1 cm grid; rolled rail stretches
  at full rail width and twist funnels count as used); 0.02 point per cm2.
- **shorter rails** (`shorten_rails`, review of the dense-stack sample): a
  long straight is swapped for a short one laid along the same line when every
  hole in use and every linked end lands on the short rail's matching hole or
  end and the marble's stretch fits; holes it now rolls over get covers. Each
  swap is validated. About a quarter of long rails shrink; the dense-stack
  sample lost two (rail6, rail7).
  A long straight's holes sit only near its ends (2, 7, 43, 48 cm), so a rail
  whose marble rolls a few cm at one end but whose other support is a ground
  column at the far end cannot shrink in place. Then (`move_columns`, review
  of generated-layered-tower) such a column, if it holds only this rail, moves
  along the rail onto the short rail's free hole nearest to where it stood;
  the swap is validated like any other (collisions, statics, routing). The
  dense-stack sample loses a third long rail (rail8) this way.
- **idle rail**: rail length the marble never rolls on costs 0.2 point per cm
  (a long rail held up by an extra column for a 3 cm roll). Brace rails are
  idle on purpose and are not counted.
- **exclude_parts** (`--exclude`): parts the user does not have; the gallery
  excludes the right-angle splitter (`red_right_angle`).

Effect: with two exits, no right-angle splitter and no thin towers, builds are
small (4-6 rails, mostly one exit). Growing them needs bracing (perpendicular
rails at tall stacks) and longer horizontal runs per level.

## Seesaw diamond (split and merge)

`CascadeGenerator._seesaw_diamond`: instead of ending a branch with a dive,
the marble falls (6–12 levels, 8 tried first) onto a seesaw on the center hole
of a center-hole long rail H (`from_hole`). At H's holes 0 and 4 a yellow block
stands on a collector rail C directly below (`to_hole`), holding H and facing
inward. The seesaw sends the marble to either end of H. That end's block takes
it from H's hole and drops it onto C, and both routes merge at C's center hole.
From there the branch continues with a normal drop column (C is then held at
hole 0 and the center), or it dives (C is held at both ends). Holes 1 and 3 of
both rails are covered. The diamond is placed only if it fits the footprint and
hits nothing. Its rolled stretches count toward the rolled length. Pivot rails
are never swapped for curves.

## Exits

`exit_style: contained` (default, user rule) ends a branch only where a marble
can be caught: at a block's centered side outlet (`block_exit_probability`
for low outlets, or when no rail fits), or by diving through an open rail hole
with nothing below it (the farthest holes first). Rails never just roll off
their end; `exit_style: any` (`--exit-style any`) allows that again.
`max_exits` (default 2, `--max-exits`) caps the branch outputs: a splitter is
only placed while the extra outlets fit under the cap.

## Columns

Columns are abstract while building: a base (ground or a rail hole), the rail
hole they hold up, and the routing parts at their top. When a new lower rail
passes exactly through an existing column at one of its holes, the column is
**split**: the lower half supports the new rail, the upper half stands on it.
That is how upper columns come to stand on lower rails, on holes the marble does
not roll over. Every rail keeps exactly two supports with an accepted hole pair.
Fillers (foundation on the ground, 5-level blocks, 1-level purple drop blocks) are
composed at the end; their feasibility is checked at every step.

## Constraints checked while building

- inventory: summed contents of the chosen sets, including covers (one per
  covered hole), foundations, and long rails shared by the plain and center-hole
  variants; `straight_unspecified` rails are a wildcard
- footprint and maximum height
- solid collisions and marble clearance above every rolling segment
- a lookahead that only turns an outlet toward directions with room for a rail

Every finished candidate must also pass `validate_layout` (assembly, global
stability, rail statics, connectivity, marble clearance) and reach every exit.

## Scoring

From the first gallery review (all candidates looked buildable; long rolls
were valued; high drops, very short branches and sprawling builds were not):

```text
10 x levels + 0.2 x rolling length (cm) + 0.15 x shortest start-to-exit roll (cm)
+ 4 x random branches + 2 x columns standing on rails + 3 x curves + 5 x twists
- 1.5 x sum of exit levels (units) - 0.002 x footprint bounding-box area (cm2)
- 15 x weak towers - 0.2 x idle rail length (cm, braces excluded)
- 0.02 x unused top-view area (cm2)
```

A twist counts as 60 cm of rolling (chute plus about 1.75 turns; estimate).
To confine a build to a table area use `--footprint WIDTHxDEPTH`.

## Results (QD001+QD003+QD005+QDE6008AB05)

With two exits and contained exits, the best candidates have 6-8 levels and
150-300 cm of rolling per branch, exits 2-3 units above the ground.

## Known limits

- Covers are counted for every covered hole, including holes resting on a
  column; if a column's peg already closes the hole, this is conservative.
- An outlet facing against a rail's flow is not modeled as landing.
- The entry block on a twist is not part of the rail statics (it sits right
  above the chute's own support column).
- Long curves, seesaws and covered slopes are not generated yet.
- Filler blocks are routing blocks used purely as structure.

## Review gallery

`scripts/build_gallery.py` runs the generator under several configurations
(balanced, more twists, no twists, more curves, three exits, taller, compact),
drops duplicates by layout ID and picks a varied set: one per feature bucket
(no twist, twist, two twists, curves, branched, tall, stacked, long roll,
compact), then round-robin over configurations by score, at most a few each. Output: `examples/gallery/<id>.yaml` and `index.json`.
Reviews reported by ID feed the scoring and future pattern weights.


### Review log

- Review 1 (gallery from commit 3a638d2, old twist model and rail-end exits):
  11 of 12 Buildable (mr-9bb890c9 and mr-358199f1 also Interesting),
  mr-e5fedfc0 Doubtful. Feedback: long rolling routes are what count; drops
  from high up, very short branches and sprawling builds should lose points;
  exits should be block outlets or dives through rail holes, not rail ends; cap
  the branch outputs (default 2) because each exit needs a catcher. Led to the
  contained exits, `max_exits` and the current scoring. Those layouts remain in
  git history at that commit.
- Review 2 (gallery from commit d8ae75c, contained exits): 7 Buildable
  (mr-b5d3fba6 also Interesting), 2 Doubtful (mr-c3ebf4ad, mr-d503eaf0), 3
  Buildable but Doubtful (mr-f243c530, mr-f6d7cc83, mr-99f6f75f). Feedback:
  the top input rail is unnecessary and wastes columns; stacks of 5+ blocks
  braced along one direction only are doubtful. Led to the trimmed input and
  the thin-tower filter.
- Review 3 (gallery from commit cd9f871, no input rails or thin towers):
  mostly Buildable; mr-dab9cd16 Interesting. Doubtful: mr-831dc67a (no
  right-angle splitter at hand), mr-32de2d10 (S-curve balance), mr-d758cb5d
  (block on the overhanging end of the top rail). Notes: a column only holding
  the top block's rail (mr-dab9cd16), tower shape fragile (mr-aef20353), a
  long rail where a short one would do (mr-58269e6d), space-inefficient
  (mr-a86b7d93, mr-9554bf4c); compact is good (mr-2724d8e4).
- Review of generated-layered-tower (2026-10-24, viewer Review mode; an
  example from the v2 generator): verdict Bad. rail10, rail6 and rail1 are long
  rails the marble barely uses ("too long", "takes too much area"). Each is
  long only because one support is a ground column at the far end. Classified
  Taste. Led to shortening with column moves (`move_columns`), idle rail
  excluding braces at 0.2 per cm, and replacing the viewer's default examples
  (all from the v2 generator) with current gallery layouts.

- Annealing reviews, 2026-10-26 (triangle base builds, `examples/anneal/`):
  - mr-00051d41: the input column could stand on the triangle (over the red
    splitter, held by rails) instead of on the ground.
  - mr-a5c66ca1: turn the four-corner frame above by 90 degrees to share
    columns and add a switchback.
  - mr-7e0a3f49: lay the beam (rail3) over the median line; the column c6
    can sit on the base center, and the twist's hole on the base's end.
  - mr-5119dc15 (the reworked build): "columns can stand on the triangle's
    corners and beams" in general. Put a ground column on a triangle end;
    extend toward the apex for area efficiency; make the base-center pass
    block a natural-wood merge taking marbles from above and the side; route
    through the apex column and switch back there.
  Led to: a score term for columns standing on a pattern, layout-level
  moves in the annealer (turn above a drop; next: snap a hole onto a
  pattern hole, merge at the base center, switchback through the apex).
