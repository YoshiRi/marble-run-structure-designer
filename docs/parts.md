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
diameter. The rail height is **1 unit** as confirmed by the user, which maps
to **1.5 cm** under the derived scale; this is not a separate thickness
measurement. The purple thin/drop block is also **1 unit = 1.5 cm** tall,
matching the rail thickness (user-confirmed); its catalog records this physical
height explicitly. Straight rails have a **1 cm wide longitudinal groove in the
center** (user measurement). Groove depth and cross-section remain unknown;
the viewer currently renders a provisional 0.3 cm deep rectangular groove.

The Viewer now displays openings on the faces named in each routing block's
`ports` list. Side exits are **horizontally centered circular openings** whose
floor is **one height unit above the installation level** (user-confirmed), so a
rail laid at the block's own level meets them; an outlet can also drop one unit
onto a rail whose groove is at the installation level. Side inlets
leading to downward routes are **semicircular openings at the bottom edge**.
For the current catalog this applies to blue rear, green left, and natural-drop
front/rear ports. Port diameters and internal channel shapes remain unmeasured;
the viewer shows shallow recesses rather than complete channels.

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

## Spiral (twist)

Natural wood. A chute (about 12 cm) joined to a funnel with a 23 cm rim, about
36 cm overall (user estimates). Its two mount holes are 23 cm apart, matching a
short straight rail's end holes, and the chute-end mount sits **3 units** above
the funnel-center mount. The marble enters at the chute, circles the funnel and
drops through the center outlet.

The historical Twist set lists a large and a small spiral, but the user's two
pieces are the same size, so all twists are treated as this size for now.

The viewer draws it schematically (`special_parts.spiral`, placement: funnel
center, outlet level, direction toward the chute). Funnel depth and the exact
inlet position are not measured; the solver does not model it yet.

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

## Curved rails

Same width (4.5 cm) and thickness (1 unit) as the straight rails. Geometry is
**derived** from user observations, not yet measured.

Observations:

- Short curve: a hole at each end. Six short curves overlapped at their holes
  close a circle, so the end holes are **60 deg** apart around the center. The
  two end holes line up with the outer holes of a short straight rail
  (hole 0 and hole 3, 23 cm apart).
- Long curve: holes at both ends and in the middle; a short curve overlaps it
  hole to hole. Three long curves overlapped close a circle, so its end holes
  are **120 deg** apart, with the middle hole at 60 deg.

Derivation:

```text
end-hole chord 23 cm, 60 deg apart  ->  hole-circle radius R = 23 / (2 sin 30 deg) = 23.0 cm
end overhang 2 cm (as on straight rails) = 4.98 deg at R
short curve: 60 + 2 x 4.98  = 70 deg of arc, 28.1 cm along the centerline
long curve:  120 + 2 x 4.98 = 130 deg of arc, 52.2 cm along the centerline
edges: inner radius 20.75 cm, outer 25.25 cm
```

The 70 deg and 130 deg totals match the user's visual estimates, which
supports the 2 cm overhang assumption.

Confirmed by the user against the drawn model:

- The shape matches the derived drawing.
- A short curve and a short straight overlap exactly hole on hole (end holes
  of the curve over holes 0 and 3 of the straight). They must be on different
  levels, at least one unit apart.
- The long curve's end holes do not coincide with any convenient hole of
  another rail, consistent with its derived 39.8 cm end-hole chord.
- A curve is not stable on its own (its center of mass lies outside the line
  between its end supports); it becomes stable once a block stands on it.
  The stability rule for curves must therefore require load above. Because every curve shares R = 23 cm
and 60 deg hole spacing, curve holes always fall on a hexagonal pattern around
the circle's center.

Not yet modeled: the solver, generator and viewer still handle straight rails
only (`curved_rails:` in `catalog/parts.yaml`, `solver_support: not_yet`).
Open questions are listed in `docs/open-questions.md`.

## S-curve

Two short-curve arcs bending in opposite directions, with holes at both ends and
in the middle (user-confirmed). Each half spans 60 deg between holes on the
23 cm circle, so the three holes are **collinear and 23 cm apart** (46 cm end to
end): for connections the S-curve is equivalent to a center-hole long rail's
holes 0, 2 and 4 (user-confirmed). Derived: 52.2 cm along the centerline; the end
tangents are parallel to each other and turned 30 deg from the line of holes.
By point symmetry its center of mass sits on the middle hole, on the line between
the end holes. Viewer-only for now.

## Hole plates

Flat boards with rail-style holes, user-reported: two holes in a row, three
holes in a row, and four holes at the corners (`structural_parts.plate_*`).
Hole pitch, outline, thickness and typical use are not measured yet; owned
counts are still to be found. The solver ignores them.

