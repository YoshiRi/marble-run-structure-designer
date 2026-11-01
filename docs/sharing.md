# Sharing layouts

User request (2026-11-01): register the layouts you made and share them.

## Now: my layouts and share links (viewer, no server)

- **My layouts** (menu: マイレイアウトに保存): the open layout is kept in this
  browser (localStorage, `marble-run-my-layouts-v1`) under a name and listed
  first in the layout picker. Saving under an existing name asks to overwrite;
  a saved one can be deleted from the menu.
- **Share link** (menu: 共有リンクを送る): the layout itself goes in the link,
  `viewer/index.html#v1=<code>`, where the code is URL-safe base64 of
  deflate-raw(JSON) (`z…`, or plain JSON `j…` where the browser has no
  CompressionStream). Only what draws and rolls the layout is kept (rails,
  parts, supports, route links, routing query, name); metrics are recomputed.
  About 2 KB for a 60-level build. The part after `#` never reaches a server.
  Phones open the system share sheet (LINE etc.); elsewhere a dialog shows the
  link with a copy button. Opening a link shows the layout as 共有 · name; it
  can then be saved to one's own layouts.

## Later (user, 2026-11-01)

- **Publish to the gallery**: a shared layout added to `examples/gallery/`
  (e.g. an issue or pull request carrying the share code, checked by the
  validators in CI).
- **Register good sub-structures for the generator**: a part of a layout
  (like the triangle base or the box ladder module) saved as a pattern the
  generator can place, the way `patterns.py` and `box_ladder.py` do by hand.
