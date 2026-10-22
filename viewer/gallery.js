(() => {
  "use strict";

  const DATA_ROOT = window.location.pathname.includes("/viewer/") ? "../" : "./";
  const STORE_KEY = "marble-run-gallery-review-v1";
  const MARKS = [
    { key: "buildable", label: "Buildable" },
    { key: "doubtful", label: "Doubtful" },
    { key: "interesting", label: "Interesting" },
  ];
  const METRICS = [
    ["levels", "Levels"], ["rails", "Rails"], ["exits", "Exits"], ["random_branches", "Branches"],
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
      ? lines.length + " of " + layouts.length + " reviewed"
      : "No reviews yet: mark a layout or add a note.";
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

  function card(entry, layouts) {
    const r = review(entry.id);
    const el = document.createElement("article");
    el.className = "card" + (r.marks.length || r.note ? " reviewed" : "");
    el.id = entry.id;

    const link = "./index.html?layout=" + encodeURIComponent(entry.file).replace(/%2F/g, "/");
    const img = document.createElement("img");
    img.className = "thumb";
    img.loading = "lazy";
    img.alt = "3D view of layout " + entry.id;
    img.src = DATA_ROOT + entry.thumbnail;
    img.addEventListener("error", () => { img.replaceWith(document.createTextNode("")); });
    const imgLink = document.createElement("a");
    imgLink.href = link;
    imgLink.appendChild(img);

    const idRow = document.createElement("div");
    idRow.className = "id-row";
    const id = document.createElement("span");
    id.className = "layout-id";
    id.textContent = entry.id;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "copy-id";
    copy.textContent = "Copy ID";
    copy.addEventListener("click", async () => {
      const ok = await copyText(entry.id);
      copy.textContent = ok ? "Copied" : "Select ID";
      setTimeout(() => { copy.textContent = "Copy ID"; }, 1400);
    });
    idRow.append(id, copy);

    const tags = document.createElement("div");
    tags.className = "tags";
    for (const tag of [entry.config, ...(entry.tags || [])]) {
      const t = document.createElement("span");
      t.className = "tag";
      t.textContent = tag;
      tags.appendChild(t);
    }

    const metrics = document.createElement("dl");
    metrics.className = "metrics";
    for (const [key, label] of METRICS) {
      const wrap = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = entry.metrics?.[key] ?? "—";
      wrap.append(dt, dd);
      metrics.appendChild(wrap);
    }

    const marks = document.createElement("div");
    marks.className = "marks";
    marks.setAttribute("role", "group");
    marks.setAttribute("aria-label", "Review marks for " + entry.id);
    for (const mark of MARKS) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "mark";
      b.id = entry.id + "-" + mark.key;
      b.textContent = mark.label;
      b.setAttribute("aria-pressed", String(r.marks.includes(mark.key)));
      b.addEventListener("click", () => {
        const current = review(entry.id);
        current.marks = current.marks.includes(mark.key)
          ? current.marks.filter(k => k !== mark.key)
          : [...current.marks, mark.key];
        b.setAttribute("aria-pressed", String(current.marks.includes(mark.key)));
        el.classList.toggle("reviewed", Boolean(current.marks.length || current.note));
        save();
        refreshSummary(layouts);
      });
      marks.appendChild(b);
    }

    const note = document.createElement("input");
    note.className = "note";
    note.id = entry.id + "-note";
    note.type = "text";
    note.placeholder = "Note (e.g. what looks wrong or fun)";
    note.setAttribute("aria-label", "Note for " + entry.id);
    note.value = r.note;
    note.addEventListener("input", () => {
      review(entry.id).note = note.value;
      el.classList.toggle("reviewed", Boolean(review(entry.id).marks.length || note.value));
      save();
      refreshSummary(layouts);
    });

    const open = document.createElement("a");
    open.className = "open";
    open.href = link;
    open.textContent = "Open in viewer";

    el.append(imgLink, idRow, tags, metrics, marks, note, open);
    return el;
  }

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
          document.getElementById("status").textContent = "Nothing to copy yet: mark a layout or add a note first.";
          return;
        }
        const ok = await copyText(text, document.getElementById("summary"));
        document.getElementById("status").textContent = ok
          ? "Copied " + text.split("\n").length + " lines. Paste them into the chat."
          : "Copy was blocked: the summary is selected, copy it manually.";
      });
      if (window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    } catch (error) {
      grid.replaceChildren(Object.assign(document.createElement("p"), {
        className: "status",
        textContent: "Could not load the gallery index (" + error.message + "). Run scripts/build_gallery.py.",
      }));
    }
  }

  init();
})();
