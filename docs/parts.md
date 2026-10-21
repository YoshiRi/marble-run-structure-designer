# Part Notes

This document records currently known part behavior. Statements based on direct observation are kept separate from unresolved items.

Local direction convention:

- `FRONT` is the side used as the primary output direction for a block definition.
- `LEFT`, `RIGHT`, and `REAR` are relative to `FRONT`.
- rotating the physical block rotates all local ports together.

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

## Purple drop block

Height: **1 unit**.

Known role: a routing component used to drop a marble downward.

Exact input/output port geometry is not yet encoded.

## Wooden foundation block

Height: **1 unit**.

Structural role only:

- used as a foundation/base
- not treated as a general routing component
- not treated as an arbitrary spacer in the initial model

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

Current logical configurations:

- empty
- block
- cover (pass-through)
- covered accelerator / red diagonal accelerator

Some holes can also accept a seesaw mechanism; that is deferred.

## Spiral

Working height: **3 units**, currently tentative.

The exact footprint, entry location, exit location, and support points remain to be measured.

## Not yet specified

The catalog still needs exact definitions for:

- red/stateful routing blocks
- orange routing block
- other natural-wood routing blocks, if distinct from the foundation piece
- curved rails
- S-shaped rails
- spiral geometry
- seesaw mechanism
- exact support/stacking rules
