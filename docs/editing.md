# Editing: rebuilding a stretch (window rebuild)

User direction (2026-11-02/03): block-level edits are too limited; adding a
rail on top adds unwanted structure. Instead give an intent ("add a split
here", "add a rail here") as a constraint and search for a solution, by
separating the build at a level, rebuilding there, and putting the part above
back on it.

## How it works (`src/quadrilla_solver/rebuild.py`)

The user picks a route rail R and an intent. The layout is cut in three:

- **lower**: rails at R's level and below, fixed with all their columns;
- **window**: R, removed and grown again bottom-up by the generator's own
  step (`_grow_up`), from the block R dropped into, under the intent:
  `rebuild` (1–2 rails, another way), `add_rail` (2 rails), `split` (2–3
  rails with a red splitter whose second branch merges hole to hole or exits);
- **upper**: rails above R, one rigid piece. It is moved (up, and sideways
  if the new route lands elsewhere) so its drop lands in a block on the
  window's top rail. Its internal columns move with it.

Then every support outside the lower part is solved again
(`resolve_supports`, lower rails fixed) and the result validated. Candidates
are ranked: the upper part moved least, few new ground columns and weak
towers, few parts. The lower part's marble paths are obstacles for the new
columns.

Parts: the sets in the request, else the layout's generator sets, else the
owned parts; the viewer's "may use more parts than owned" passes every set.

## Refused, with a reason (`RebuildRefused.code`)

`not_on_route`, `drops` (R drops in more than one place, e.g. a split rail),
`multi_in`, `no_in`, `cross_link` / `cross_fall` (the upper part also
reaches the lower part other than through R: a box ladder, a merge across
the cut), `no_parts`, `no_candidates`.

## Viewer

Edit → tap a rail → 作り直し: 別の形に / 分岐を入れる / レールを足す. The
first candidate is applied (one undo step); 別の案 flips through the others.
Runs in the browser worker (`web.edit_json`, op `rebuild`).

## Measured (examples/box_base/mr-5be5ce26, rails above the box)

About 1 s per request. With the owned parts only, `add_rail` and `split`
find nothing on this build (it uses all the long rails); with one more
basic set, 3 candidates each on every rail above the box. Box rails are
refused (`cross_link`).

## Next

- A window of several rails (rebuild a range of levels, not one rail).
- Cuts across a box ladder or a merge (both sides reconnected).
- Intent at a block (split exactly here) rather than at a rail.
