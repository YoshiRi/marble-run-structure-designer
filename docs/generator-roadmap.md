# Generator Roadmap: Curves, Lattice and Patterns

Notes from design discussions with the user. Not implemented yet unless stated.

## All rail holes lie on one triangular lattice (23 cm)

Every rail's holes fall on a triangular lattice with 23 cm spacing:

| Part | Holes used on the lattice |
| --- | --- |
| short straight | holes 0 and 3: one step |
| long center-hole straight | holes 0, 2, 4: two steps in a line |
| short curve | end holes: one step (arc bulges 3.1 cm) |
| S-curve | end and middle holes: two steps in a line (equivalent to the long rail's 0, 2, 4) |
| long curve | three consecutive hexagon corners: two steps turning 60 deg at the middle point |

So the long curve is a 60-degree corner piece on this lattice. A lattice-based
generator (columns on lattice points, parts as lattice edges) would handle all
straight and curved parts in one framework.

Constraint from the user: blocks stand on one peg and can be rotated to 30/60
deg, but some blocks turn the marble by 90 deg (e.g. red right-angle, side
inlets), so on a 60-degree lattice fewer block/direction combinations work.

## Curve stability

- Short and long curves tip on their own; they are stable once a block stands
  on them (user-confirmed).
- The S-curve's center of mass lies on its middle hole (point symmetry), so it is
  expected to be self-stable.
- Long curve: a column standing on the middle hole without a support below it
  is a balance risk. Score it as a penalty (risk), not as invalid.

## Substituting curves for straights

Because end-hole positions coincide, a short straight can become a short curve,
and a long center-hole rail used only at holes 0, 2, 4 can become an S-curve,
without changing any column or block.

Measured on 200 v2 layouts (QD001+QD003+QD005): no rail is support-only (every
rail carries the marble), and no short rail has blocks standing on both end
holes. Substitution therefore only pays off on rails the marble rolls along,
where the curve's end tangents are turned 30 deg from the straight's direction
(the outlet that feeds it, or the block it lands from, is aligned with the old
straight). Whether marbles still enter and leave cleanly is a physical question
to confirm before allowing it. 64 long center-hole rails used only holes 0, 2, 4
in those layouts, so S-curve substitution would trigger often once allowed.

## Search heuristics and known patterns

- The generator is a randomized constructive search with validation as a
  filter (not exhaustive DFS). Bonuses for preferred patterns, or biased choices
  toward them, can raise the hit rate.
- Pattern library: humans build fast by recalling known sub-structures. Example
  from the user, a near-triangular frame on one plane:

  ```text
  o--o--o
        |
        o
  ```

  A center-hole long rail ([o o o]) whose two ends rest on two sides of a
  triangle and whose center meets the perpendicular. Such patterns could be
  offered to the search as ready-made building steps ("macros").
