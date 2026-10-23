# Layout Generator (M2)

`scripts/generate_layout.py` searches for buildable layouts from the combined
contents of one or more commercial sets and writes the best ones as Layout YAML
that the viewer can open.

```bash
python scripts/generate_layout.py --sets QD001,QD003,QD005 --attempts 600 \
    --seed 1 --keep 3 --out-dir examples/generated
```

Options: `--max-height` (top rail level, units of 1.5 cm), `--footprint WxD`
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

The twist (QD005 lists 3; the user's two are the same size) is entered with a
hook (user-described): a rail runs into the side inlet of an entry block
standing on the twist's chute hole (blue rear, green left or natural front/rear
notch, facing back up the rail), the block drops the marble from its bottom
into the chute, and the twist heads to the **right** of the incoming rail, so
the marble arrives from the twist's right side. It rolls down the chute,
circles the funnel and drops through the center hole into a new drop column.
Side outlets do not land on the chute. The chute hole mounts 3 units above the
center hole, so the feeding rail sits at the chute's level and the entry block
is free-standing (a support with no upper rail). `twist_probability` (default
0.5) is the chance to try a twist first, mid-cascade or at a branch end; about
a third of builds with the default sets contain one, two thirds at 0.9.

## Input and thin towers

The marble is put straight into the top block (user review 2: an input rail
only wastes columns). The build still starts from a top rail with a drop
column under it, but the first drop must land on a lower rail; then the top
rail and the columns that only held it are removed, and the drop column stays
as a free-standing stack on its rail. Its top part is the source
(`routing_query.source`, e.g. `c1_0_blue:top`); the viewer lists it as an
input. `trim_input_rail: false` keeps the old input rail.

A **thin tower** is a stack at one spot with 5 or more blocks (4u parts;
purple 1u pieces and foundations not counted) whose rails all run along one
axis: braced in one direction only, it topples easily (user review 2).
Candidates with more than `max_thin_towers` (default 0) are dropped, and each
one costs 12 points when allowed. This shrinks the builds: the best now have
5-10 rails and 30-80 parts, where tall towers were the easy way up.

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
Fillers (foundation on the ground, 4u blocks, 1u purple drop blocks) are
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
- 1.5 x sum of exit levels (units) - 0.005 x footprint bounding-box area (cm2)
- 12 x thin towers
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
