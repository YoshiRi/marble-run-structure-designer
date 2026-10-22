/* Render gallery thumbnails by opening each layout in the viewer.
 *
 * Dev tool (not run in CI). Needs playwright-core and a Chromium binary:
 *   CHROMIUM_PATH=/path/to/chromium node scripts/render_gallery_thumbnails.js
 * (or with @sparticuz/chromium installed, which supplies binary and flags)
 * Serves the repository with a small static server on a free port (or BASE_URL).
 * Thumbnails are JPEG; the committed ones were downscaled to 480 px wide.
 */
"use strict";
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".yaml": "text/plain", ".json": "application/json", ".png": "image/png" };

function serve() {
  const server = http.createServer((req, res) => {
    const file = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end(); return;
    }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(resolve => server.listen(0, () => resolve(server)));
}

(async () => {
  const index = JSON.parse(fs.readFileSync(path.join(ROOT, "examples/gallery/index.json"), "utf8"));
  // BASE_URL points at an already running static server (e.g. python -m
  // http.server from the repository root); otherwise serve the repo here.
  const server = process.env.BASE_URL ? null : await serve();
  const base = process.env.BASE_URL || `http://localhost:${server.address().port}`;
  // Prefer @sparticuz/chromium (binary + flags) when installed; otherwise
  // CHROMIUM_PATH (or Playwright's default) with software WebGL flags.
  let launch = {
    executablePath: process.env.CHROMIUM_PATH,
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"],
  };
  try {
    const sparticuz = require("@sparticuz/chromium").default;
    launch = { executablePath: await sparticuz.executablePath(), args: sparticuz.args };
  } catch (error) { /* not installed */ }
  const browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport: { width: 1180, height: 820 } });
  // Optional local copies of the CDN scripts (BABYLON_JS, JS_YAML) for offline use.
  if (process.env.BABYLON_JS) {
    await page.route("https://cdn.jsdelivr.net/npm/babylonjs*/**", r => r.fulfill({ path: process.env.BABYLON_JS }));
  }
  if (process.env.JS_YAML) {
    await page.route("https://cdn.jsdelivr.net/npm/js-yaml*/**", r => r.fulfill({ path: process.env.JS_YAML }));
  }
  for (const entry of index.layouts) {
    await page.goto(`${base}/viewer/index.html?layout=${entry.file}`);
    await page.waitForFunction(() => document.getElementById("layoutMeta").textContent.startsWith("mr-"),
      null, { timeout: 30000 });
    await page.evaluate(() => {
      for (const id of ["toggleCom", "togglePolygon", "toggleSupports"]) {
        const box = document.getElementById(id);
        if (box.checked) box.click();
      }
    });
    await page.waitForTimeout(800);
    const canvas = await page.$("#renderCanvas");
    const box = await canvas.boundingBox();
    const out = path.join(ROOT, entry.thumbnail);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    // Software WebGL can take tens of seconds per capture.
    await page.screenshot({ path: out, timeout: 180000, type: "jpeg", quality: 82,
      clip: { x: box.x + 90, y: box.y + 60, width: box.width - 180, height: box.height - 120 } });
    console.log("wrote", entry.thumbnail);
  }
  await browser.close();
  if (server) server.close();
})().catch(error => { console.error(error); process.exit(1); });
