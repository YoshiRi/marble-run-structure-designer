# Layout Generator (M2, first version)

`scripts/generate_layout.py` searches for buildable layouts from the combined
contents of one or more commercial sets and writes the best ones as Layout YAML
that the viewer can open.

```bash
python scripts/generate_layout.py --sets QD001,QD003,QD005 --attempts 800 \
    --seed 6 --keep 3 --out-dir examples/generated
```

Options: `--max-height` (top rail level, units of 1.5 cm), `--footprint WxD`
(cm), `--max-rails`, `--split-probability`, `--seed`, `--attempts`, `--keep`.

## What it builds

A descending cascade grown from a top rail:

```text
rail --(block-connected hole)--> drop column --(side outlet)--> rail --> ...
```

- Rails are straight and axis-aligned (0/90/180/270 deg). Each rests on two
  ground columns: a plain column under hole 1, and at the far end (hole 2 or 3)
  either a drop column or, for a leaf rail that ends the run, another plain
  column.
- A drop column is a foundation, filler blocks/purple drop blocks, a routing
  block whose top opening leads to side outlets (yellow, blue, green, cyan,
  red splitters) and optionally pass-through parts above it (purple drop or
  orange vertical) that lengthen the fall.
- A side outlet feeds a new rail starting at the block face, either at the
  outlet floor or one unit lower (drop-one).
- Red splitters fork the cascade into two branches.

## Constraints checked while building

- inventory: the summed contents of the chosen sets, including covers (one per
  covered hole) and wildcard `straight_unspecified` rails
- footprint and maximum height
- solid collisions and marble clearance above every rolling segment
- a lookahead that only turns an outlet toward directions with room for a rail

Every finished candidate must then pass the full `validate_layout` (assembly,
global stability, rail statics, connectivity, marble clearance).

## Scoring

```text
10 x levels + 0.1 x rolling length (cm) + 6 x rail exits
+ 4 x random branches - 8 x outlets left without a rail
```

Levels/length and branches/exits are the current priorities.

## Known limits

- **Covers bind first.** With QD001+QD003+QD005 (18 covers) candidates stop at
  6 rails. Covers are counted for every covered hole, including holes resting
  on a support column; if a column's peg already closes the hole, the count is
  conservative.
- **Foundations bind next** (16): every column currently stands on the ground.
  Columns standing on lower rails would remove that limit.
- No curved/spiral rails, seesaws or covered slopes.
- Filler blocks are routing blocks used purely as structure.
