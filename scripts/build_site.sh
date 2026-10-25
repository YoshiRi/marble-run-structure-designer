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
node --check "$ROOT/viewer/sound.js"
node --check "$ROOT/viewer/generator-worker.js"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
cp "$ROOT/viewer/index.html" "$OUT_DIR/index.html"
cp "$ROOT/viewer/app.js" "$ROOT/viewer/routing.js" "$ROOT/viewer/assembly.js" "$ROOT/viewer/validation.js" "$ROOT/viewer/sound.js" "$ROOT/viewer/styles.css" "$OUT_DIR/"
cp "$ROOT/viewer/gallery.html" "$ROOT/viewer/gallery.js" "$ROOT/viewer/manifest.webmanifest" "$OUT_DIR/"
cp -r "$ROOT/viewer/icons" "$ROOT/viewer/sounds" "$OUT_DIR/"
# Browser generator: worker, file manifest and the Python solver it loads.
cp "$ROOT/viewer/generator-worker.js" "$ROOT/viewer/py-manifest.json" "$ROOT/viewer/generator-tunables.json" "$OUT_DIR/"
mkdir -p "$OUT_DIR/src/quadrilla_solver"
cp "$ROOT"/src/quadrilla_solver/*.py "$OUT_DIR/src/quadrilla_solver/"
cp -r "$ROOT/catalog" "$ROOT/examples" "$OUT_DIR/"
# Serve files as-is; skip Jekyll processing on the gh-pages branch.
touch "$OUT_DIR/.nojekyll"
echo "Site assembled in $OUT_DIR"
