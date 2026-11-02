(() => {
  "use strict";
  const T = (key, vars) => window.MarbleI18n.t(key, vars);

  const DATA_ROOT = window.location.pathname.includes("/viewer/") ? "../" : "./";
  const STORE_KEY = "marble-run-gallery-review-v1";
  const MARKS = [
    { key: "buildable", label: "Buildable" },
    { key: "doubtful", label: "Doubtful" },
    { key: "interesting", label: "Interesting" },
  ];
  const METRICS = [
    ["levels", "Levels"], ["rails", "Rails"], ["exits", "Exits"], ["random_branches", "Branches"],
    ["rolling_length_cm", "Roll cm"], ["min_exit_path_cm", "Shortest"], ["highest_exit", "Exit lvl"],
    ["footprint_area_cm2", "Area cm²"], ["dead_area_cm2", "Unused cm²"], ["braces", "Braces"],
    ["curves", "Curves"], ["twists", "Twists"], ["columns_on_rails", "On rails"], ["parts", "Parts"],
  ];

  let reviews = {};
  try { reviews = JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}") || {}; } catch (error) { reviews = {}; }

  function save() {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(reviews)); } catch (error) { /* storage unavailable */ }
  }

  function review(id) {
    if (!reviews[id]) reviews[id] = { marks: [], note: "" };
    return reviews[id];
  }

  function summaryLines(layouts) {
    return layouts
      .filter(entry => reviews[entry.id] && (reviews[entry.id].marks.length || reviews[entry.id].note.trim()))
      .map(entry => {
        const r = reviews[entry.id];
        const marks = MARKS.filter(m => r.marks.includes(m.key)).map(m => m.label).join(", ") || "-";
        return entry.id + ": " + marks + (r.note.trim() ? " — " + r.note.trim() : "");
      });
  }

  function refreshSummary(layouts) {
    const lines = summaryLines(layouts);
    document.getElementById("summary").value = lines.join("\n");
    document.getElementById("status").textContent = lines.length
      ? T("gal.reviewed", { n: lines.length, m: layouts.length })
      : T("gal.noReviews");
  }

  async function copyText(text, fallback) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      if (fallback) { fallback.focus(); fallback.select(); }
      return false;
    }
  }

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function stat(key, value) {
    const span = el("span");
    span.append(T(key) + " ", el("b", "", String(value ?? "—")));
    return span;
  }

  function card(entry, layouts) {
    const r = review(entry.id);
    const box = el("article", "card" + (r.marks.length || r.note ? " reviewed" : ""));
    box.id = entry.id;

    const link = "./index.html?layout=" + encodeURIComponent(entry.file).replace(/%2F/g, "/");
    const main = el("a", "card-main");
    main.href = link;
    const img = el("img", "thumb");
    img.loading = "lazy";
    img.alt = entry.id;
    img.src = DATA_ROOT + entry.thumbnail;
    img.addEventListener("error", () => { img.replaceWith(el("div", "thumb thumb-empty", "◎")); });
    const m = entry.metrics || {};
    const stats = el("div", "card-stats");
    stats.append(stat("gal.levels", m.levels), stat("gal.exitsShort", m.exits),
      stat("gal.branchesShort", m.random_branches), stat("gal.partsShort", m.parts));
    main.append(img, el("div", "card-title layout-id", entry.id), stats);

    const links = el("div", "card-links");
    const open = el("a", "", T("gal.open"));
    open.href = link;
    const buildLink = el("a", "", T("gal.build"));
    buildLink.href = link + "&mode=build&step=0";
    links.append(open, buildLink);

    // Review tools (debug only): the ID, tags, all metrics, marks and a note.
    const tools = el("div", "review-tools debug-only");
    const idRow = el("div", "id-row");
    const copy = el("button", "copy-id", T("gal.copyId"));
    copy.type = "button";
    copy.addEventListener("click", async () => {
      const ok = await copyText(entry.id);
      copy.textContent = T(ok ? "gal.copiedId" : "gal.selectId");
      setTimeout(() => { copy.textContent = T("gal.copyId"); }, 1400);
    });
    idRow.append(el("span", "layout-id", entry.id), copy);
    const tags = el("div", "tags");
    for (const tag of [entry.config, ...(entry.tags || [])]) tags.appendChild(el("span", "tag", tag));
    const metrics = el("dl", "metrics");
    for (const [key] of METRICS) {
      const wrap = el("div");
      wrap.append(el("dt", "", T("gal.m." + key)), el("dd", "", String(m[key] ?? "—")));
      metrics.appendChild(wrap);
    }
    const marks = el("div", "marks");
    marks.setAttribute("role", "group");
    marks.setAttribute("aria-label", "Review marks for " + entry.id);
    for (const mark of MARKS) {
      const b = el("button", "mark", T("gal.mark." + mark.key));
      b.type = "button";
      b.id = entry.id + "-" + mark.key;
      b.setAttribute("aria-pressed", String(r.marks.includes(mark.key)));
      b.addEventListener("click", () => {
        const current = review(entry.id);
        current.marks = current.marks.includes(mark.key)
          ? current.marks.filter(k => k !== mark.key)
          : [...current.marks, mark.key];
        b.setAttribute("aria-pressed", String(current.marks.includes(mark.key)));
        box.classList.toggle("reviewed", Boolean(current.marks.length || current.note));
        save();
        refreshSummary(layouts);
      });
      marks.appendChild(b);
    }
    const note = el("input", "note");
    note.id = entry.id + "-note";
    note.type = "text";
    note.placeholder = T("gal.note");
    note.setAttribute("aria-label", "Note for " + entry.id);
    note.value = r.note;
    note.addEventListener("input", () => {
      review(entry.id).note = note.value;
      box.classList.toggle("reviewed", Boolean(review(entry.id).marks.length || note.value));
      save();
      refreshSummary(layouts);
    });
    tools.append(idRow, tags, metrics, marks, note);

    box.append(main, links, tools);
    return box;
  }

  // My layouts (saved in the viewer, this browser): open, build or delete.
  const MINE_STORE = "marble-run-my-layouts-v1";

  function loadMine() {
    try { return JSON.parse(localStorage.getItem(MINE_STORE) || "[]"); } catch (error) { return []; }
  }

  function renderMine() {
    const mine = loadMine();
    const section = document.getElementById("mineSection");
    section.hidden = !mine.length;
    document.getElementById("mineGrid").replaceChildren(...mine.map(entry => {
      const box = el("article", "card");
      const link = "./index.html?mine=" + encodeURIComponent(entry.id);
      const main = el("a", "card-main");
      main.href = link;
      const rails = entry.data?.rails || [];
      const stats = el("div", "card-stats");
      stats.append(stat("gal.railsShort", rails.length), stat("gal.partsShort", (entry.data?.parts || []).length),
        stat("gal.saved", new Date(entry.savedAt).toLocaleDateString(window.MarbleI18n.lang)));
      main.append(el("div", "thumb thumb-empty", "★"), el("div", "card-title", entry.name), stats);
      const links = el("div", "card-links");
      const open = el("a", "", T("gal.open"));
      open.href = link;
      const buildLink = el("a", "", T("gal.build"));
      buildLink.href = link + "&mode=build&step=0";
      const del = el("button", "danger", T("menu.delete"));
      del.type = "button";
      del.addEventListener("click", () => {
        if (!confirm(T("mine.deleteConfirm", { name: entry.name }))) return;
        try { localStorage.setItem(MINE_STORE, JSON.stringify(loadMine().filter(e => e.id !== entry.id))); } catch (error) { /* ignore */ }
        renderMine();
      });
      links.append(open, buildLink, del);
      box.append(main, links);
      return box;
    }));
  }

  let debug = false;
  try { debug = localStorage.getItem("marble-run-debug-v1") === "on"; } catch (error) { /* private mode */ }
  const asked = new URLSearchParams(window.location.search).get("debug");
  if (asked !== null) debug = asked !== "0";
  document.body.classList.toggle("debug", debug);
  renderMine();

  async function init() {
    const grid = document.getElementById("grid");
    try {
      const response = await fetch(DATA_ROOT + "examples/gallery/index.json");
      if (!response.ok) throw new Error("index.json: HTTP " + response.status);
      const index = await response.json();
      const layouts = index.layouts || [];
      grid.replaceChildren(...layouts.map(entry => card(entry, layouts)));
      refreshSummary(layouts);
      document.getElementById("copySummary").addEventListener("click", async () => {
        const text = document.getElementById("summary").value;
        if (!text) {
          document.getElementById("status").textContent = T("gal.nothing");
          return;
        }
        const ok = await copyText(text, document.getElementById("summary"));
        document.getElementById("status").textContent = ok
          ? T("gal.copied", { n: text.split("\n").length })
          : T("gal.blocked");
      });
      if (window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    } catch (error) {
      grid.replaceChildren(Object.assign(document.createElement("p"), {
        className: "status",
        textContent: T("gal.indexFailed", { error: error.message }),
      }));
    }
  }

  init();
})();
