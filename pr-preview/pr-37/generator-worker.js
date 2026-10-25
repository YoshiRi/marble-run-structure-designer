/* Runs the Python generator (src/quadrilla_solver) in the browser with
 * Pyodide, in a worker so the page stays responsive. The generation logic is
 * not re-implemented here: this loads the same package the CLI uses.
 *
 * Messages in:  {type: "generate", id, base, options}
 *               {type: "edit", id, base, request}   (rail rewrites, web.edit_json)
 *   base: URL of the site root (where src/, catalog/ live)
 * Messages out: {type: "status", text} | {type: "progress", id, done, total}
 *               {type: "result", id, layouts} | {type: "edited", id, response}
 *               {type: "error", id, message}
 */
/* global loadPyodide, jsyaml */
"use strict";

const PYODIDE_VERSION = "0.28.3";
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/";
const JS_YAML_URL = "https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js";

let ready = null;

async function boot(base) {
  self.postMessage({ type: "status", text: "Loading Python (first time only)…" });
  importScripts(JS_YAML_URL, PYODIDE_URL + "pyodide.js");
  const py = await loadPyodide({ indexURL: PYODIDE_URL });
  self.postMessage({ type: "status", text: "Loading the solver…" });
  // The manifest sits next to this worker (in the site root, or viewer/ in dev).
  const manifest = await (await fetch("py-manifest.json")).json();
  await Promise.all(manifest.files.map(async rel => {
    const response = await fetch(base + rel);
    if (!response.ok) throw new Error("Failed to load " + rel + " (HTTP " + response.status + ")");
    const text = await response.text();
    const dir = "/repo/" + rel.slice(0, rel.lastIndexOf("/"));
    py.FS.mkdirTree(dir);
    py.FS.writeFile("/repo/" + rel, text);
  }));
  // PyYAML is the solver's only dependency: stand in with js-yaml.
  py.registerJsModule("_jsyaml", { load: text => jsyaml.load(text) });
  py.runPython(`
import sys, types, _jsyaml
def _safe_load(src):
    text = src.read() if hasattr(src, "read") else src
    obj = _jsyaml.load(text)
    return obj.to_py() if hasattr(obj, "to_py") else obj
_yaml = types.ModuleType("yaml")
_yaml.safe_load = _safe_load
sys.modules["yaml"] = _yaml
sys.path.insert(0, "/repo/src")
from quadrilla_solver.web import generate_json, edit_json
`);
  return { generateJson: py.globals.get("generate_json"), editJson: py.globals.get("edit_json") };
}

self.onmessage = async event => {
  const { type, id, base, options, request } = event.data || {};
  if (type !== "generate" && type !== "edit") return;
  try {
    if (!ready) ready = boot(base);
    const { generateJson, editJson } = await ready;
    if (type === "edit") {
      self.postMessage({ type: "edited", id, response: JSON.parse(editJson(JSON.stringify(request), "/repo")) });
      return;
    }
    self.postMessage({ type: "status", text: "Generating…" });
    const out = generateJson(JSON.stringify(options), "/repo",
      (done, total) => self.postMessage({ type: "progress", id, done, total }));
    self.postMessage({ type: "result", id, layouts: JSON.parse(out) });
  } catch (error) {
    ready = null;
    self.postMessage({ type: "error", id, message: String(error && error.message || error) });
  }
};
