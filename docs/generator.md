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

```text
10 x levels + 0.1 x rolling length (cm) + 6 x rail exits + 4 x random branches
+ 2 x columns standing on rails - 8 x outlets left without a rail
```

## Results (QD001+QD003+QD005)

The first version (ground columns only) stopped at 6 rails because of covers.
With landing drops and stacked columns, candidates reach 8-12 rails, 3-4 exits
and up to 11 columns standing on rails, typically 6 levels within 24 units.

## Known limits

- Covers are counted for every covered hole, including holes resting on a
  column; if a column's peg already closes the hole, this is conservative.
- An outlet facing against a rail's flow is not modeled as landing.
- Long curves, the twist (spiral), seesaws and covered slopes are not generated yet.
- Filler blocks are routing blocks used purely as structure.
