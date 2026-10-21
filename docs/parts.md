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

## Standard block height

Working height: **4 units**.

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

The output is selected randomly between the two opposite horizontal exits.

This should be modeled as a probabilistic branch, not as an alternating/stateful switch unless later physical testing shows otherwise. The exact probability distribution is not yet specified.

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

Some holes can also accept special mechanisms such as a seesaw; that is deferred.

## Accessories

### Routing-affecting

- **Cover** — changes an open hole into a rail pass-through.
- **Covered slope** — affects the marble route/behavior; exact routing semantics and orientation still need to be encoded.

### Non-routing

- **Accelerator plate** — affects motion but not graph connectivity, so it can be ignored by the initial solver and retained only for viewer/construction-assist purposes.

## Spiral

Working height: **3 units**, currently tentative.

The exact footprint, entry location, exit location, and support points remain to be measured.

## Not yet specified

The catalog still needs exact definitions for:

- curved rails
- S-shaped rails
- spiral geometry
- seesaw mechanism
- covered-slope routing semantics
- exact support/stacking rules
- any unobserved ports/routes on the natural-wood block
