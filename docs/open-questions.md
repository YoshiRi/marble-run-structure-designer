# Open Questions

Items here should be resolved by measurement, photographs, manuals, or repeatable physical tests.

## Current MVP priority

- Confirm whether spiral height is exactly 3 discrete units.
- Define the covered-slope accessory's exact routing effect and orientation.
- Check whether the natural-wood routing block has any additional routes beyond FRONT/REAR -> BOTTOM.
- Formalize the minimum support/stacking rules needed by the validator.

Curved/S-shaped rails and detailed seesaw behavior are intentionally **out of the initial solver scope**.

## Rail geometry

- Confirm short-rail hole positions numerically rather than only by repeated end spacing.
- Measure rail width and hole center coordinates in the transverse direction if needed by the solver.
- Determine which rail variants have center holes.
- Determine which center-hole rail variants also have the groove/mount required by the seesaw.
- Determine whether every ordinary hole has identical structural constraints.

## Structural rules

- Formalize when a rail hole needs support from below.
- Formalize legal stacking combinations.
- Determine whether the wooden foundation block must touch ground or may also be used on an elevated structural surface.
- Determine the minimum collision geometry needed to reject impossible layouts.

## Routing accessories

- Define the covered-slope accessory's exact route/behavior and orientation.
- Confirm whether cover behavior is always a pure pass-through.

## Probabilistic / stateful routing

### Red blocks

- ordinary red: `TOP -> {FRONT, REAR}`, random
- right-angle red: `TOP -> {FRONT, RIGHT}`, random
- exact probability distributions are not needed for reachability

### Seesaw — deferred

Known enough to reserve the model shape:

- mounts at the center of compatible rails with a center hole and groove/mount
- accepts a marble from above
- routes toward the left or right rail end
- switching has approximately 4-5 marbles of hysteresis

Still intentionally unresolved:

- exact state-transition rule
- exact threshold
- initial state
- whether the 4-5 marble value is fixed or only approximate
- exact set of compatible rail variants

## Curved rails

- Confirm the end overhang beyond the end holes (assumed 2 cm, as on straight rails).
- Support: does a curve stand on its two end holes (the arc's center of mass
  lies off the line between them), or does it need a third support / the
  middle hole?
- Owned counts and which sets include short and long curves.

## Deferred geometry

- curved rails
- S-shaped rails
- detailed seesaw geometry
- Funny Function special-part geometry

## Inventory

The owned collection combines multiple sets and has missing pieces.

Inventory counts will therefore be entered from a manual count rather than copied from product-box specifications.
