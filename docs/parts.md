# Part Notes

This document records currently known part behavior. Statements based on direct observation are kept separate from unresolved items.

Local direction convention:

- `FRONT` is the side used as the primary output direction for a block definition.
- `LEFT`, `RIGHT`, and `REAR` are relative to `FRONT`.
- rotating the physical block rotates all local ports together.

## Part categories

The working catalog separates physical parts into:

- **Block**
  - standard routing block
  - thin routing block
  - foundation block
- **Rail**
- **Special**
  - e.g. seesaw
- **Routing-affecting accessory**
  - cover
  - covered slope
- **Non-routing accessory**
  - accelerator plate

A rail hole has a resulting logical state, but the physical accessory that creates that state is modeled separately.

## Measured masses

User-measured values currently available:

| Part | Mass |
| --- | ---: |
| Blue routing block | 53 g |
| Orange routing block | 58 g |
| Purple thin/drop block | 12 g |
| Wooden foundation block | 12 g |
| Accelerator plate | 2.5 g |
| Short straight rail | 74 g |
| Long straight rail | 135 g |

These values are used as direct statics inputs where the exact part type is known.

Until additional measurements are available, every **unmeasured standard-height (height 4) routing block** uses a provisional mass of **55 g**. Measured values override this fallback, so blue remains 53 g and orange remains 58 g. The fallback does not apply to thin blocks, rails, accessories, foundations, spirals, or special parts. The wooden foundation is measured at 12 g. Because it is ground-only in the current model, its mass affects total mass / ground reaction accounting but not upper-rail tipping calculations.

## Standard block height

Working height: **4 units = 6 cm effective stacked height** (user measurement).

The standard routing block has a **4.5 × 4.5 cm** footprint and a **1 cm
connector protrusion** that inserts into the mating piece. The protrusion
does **not** add 1 cm to the assembled stack height; one stacked standard block
contributes 6 cm, not 7 cm.

The rail width is **4.5 cm**. Rail holes are approximately **1.8 cm** in
diameter. The rail's physical thickness is not yet measured; its current
1-unit height maps to a provisional 1.5 cm in the viewer.

## Yellow routing block

Confirmed behavior:

```text
TOP -> FRONT
```

In a stacked layout this naturally acts as a level transition / turnaround: a marble drops from a rail into the top of the yellow block and exits sideways onto the rail below.

## Blue routing block

Confirmed behavior:

```text
TOP  -> FRONT
REAR -> BOTTOM
```

The horizontal input that drops downward is opposite the side used by the top-input output.

## Green routing block

Confirmed behavior:

```text
TOP  -> FRONT
LEFT -> BOTTOM
```

Relative to the top-input output side, the horizontal input that drops downward is 90 degrees to the left.

## Cyan routing block

Confirmed behavior:

```text
TOP   -> FRONT
LEFT  <-> RIGHT
```

The horizontal pass-through line is perpendicular to the output used by a marble entering from the top.

## Natural-wood routing block

Confirmed behavior:

```text
FRONT -> BOTTOM
REAR  -> BOTTOM
```

This is a standard-height routing block and is distinct from the thin wooden foundation piece.

Other possible ports/routes are currently left unspecified rather than inferred.

## Red routing block

Confirmed behavior:

```text
TOP -> FRONT or REAR
```

The output is randomly distributed between the two opposite horizontal exits.

## Red right-angle variant

Confirmed behavior:

```text
TOP -> FRONT or RIGHT
```

This is also a random distributor, but its two horizontal exits are arranged at 90 degrees instead of opposite each other.

The exact probability distribution is not needed for initial reachability solving.

## Orange routing block

Confirmed behavior:

```text
TOP -> BOTTOM
```

Horizontal directions are blocked; no horizontal route is currently modeled.

## Purple drop block

Height: **1 unit**.

Confirmed behavior:

```text
TOP -> BOTTOM
```

It is therefore a thin vertical pass-through routing block.

## Wooden foundation block

Height: **1 unit**.

Structural role only:

- used as a foundation/base
- not treated as a routing component
- not treated as an arbitrary spacer in the initial model

This is distinct from the standard-height natural-wood routing block.

## Straight rails

### Long rail

Measured length: **50 cm**

Measured hole positions from one end:

```text
2, 7, 43, 48 cm
```

### Long rail with center hole

Measured length: **50 cm**

Hole positions:

```text
2, 7, 25, 43, 48 cm
```

Some rail variants additionally have a center groove/mount used by the seesaw. Do not assume every center-hole rail has this feature until checked physically.

### Short rail

Measured length: **27 cm**

The end-hole spacing follows the same pattern as the long rail, giving the current model:

```text
2, 7, 20, 25 cm
```

## Rail-hole behavior

A hole can be used for block insertion and can also act as a marble opening.

Current logical configurations include:

- empty/open
- block-connected
- covered/pass-through
- covered-slope

Some rail variants also provide a dedicated center mount for a seesaw.

## Accessories

### Routing-affecting

- **Cover** — changes an open hole into a rail pass-through.
- **Covered slope / covered accelerator (フタ付加速パーツ)** — affects the marble route/behavior; exact routing semantics and orientation still need to be encoded.

### Non-routing

- **Accelerator plate** — affects motion but not graph connectivity, so it can be ignored by the initial solver and retained only for viewer/construction-assist purposes.

## Seesaw special part

Implementation is **deferred for the MVP**, but its observed behavior is recorded so the model can accommodate it later.

Mounting:

- installed at the center of compatible rail variants
- the compatible rail has a center hole plus a groove/mount for the seesaw

Routing:

```text
TOP -> LEFT_END
TOP -> RIGHT_END
```

Behavior:

- stateful distributor
- marbles dropped from above are sent toward one end of the rail or the other
- the direction has hysteresis; the observed switching scale is approximately **4-5 marbles**
- exact state-transition mechanics and exact threshold are intentionally left unspecified for now

For initial reachability-only solving, this can eventually be approximated as a branch to either rail end. A later viewer/simulation layer can model the hysteretic switching state.

## Spiral

Working height: **3 units**, currently tentative.

The exact footprint, entry location, exit location, and support points remain to be measured.

## Deferred / out of initial scope

The initial solver may ignore:

- curved rails
- S-shaped rails
- seesaw state transitions
- detailed seesaw geometry
- Funny Function special-part geometry

Still unresolved for the parts that remain in the MVP path:

- spiral geometry
- covered-slope routing semantics
- exact support/stacking rules
- any unobserved ports/routes on the natural-wood block
