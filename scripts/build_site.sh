#!/usr/bin/env bash
# Assemble the static viewer site into OUT_DIR (default: _site).
# Used by both the production Pages deploy and the PR preview workflow,
# so a preview is exactly what main would publish.
set -euo pipefail

OUT_DIR="${1:-_site}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

node --check "$ROOT/viewer/app.js"
node --check "$ROOT/viewer/routing.js"
node --check "$ROOT/viewer/gallery.js"
node --check "$ROOT/viewer/assembly.js"
node --check "$ROOT/viewer/validation.js"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
cp "$ROOT/viewer/index.html" "$OUT_DIR/index.html"
cp "$ROOT/viewer/app.js" "$ROOT/viewer/routing.js" "$ROOT/viewer/assembly.js" "$ROOT/viewer/validation.js" "$ROOT/viewer/styles.css" "$OUT_DIR/"
cp "$ROOT/viewer/gallery.html" "$ROOT/viewer/gallery.js" "$OUT_DIR/"
cp -r "$ROOT/catalog" "$ROOT/examples" "$OUT_DIR/"
# Serve files as-is; skip Jekyll processing on the gh-pages branch.
touch "$OUT_DIR/.nojekyll"
echo "Site assembled in $OUT_DIR"
