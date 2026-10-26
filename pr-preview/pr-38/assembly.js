/* Bottom-up build plan for Build mode: one step per rail (user decision).
 * Mirror of src/quadrilla_solver/assembly_plan.py; tests compare the two.
 */
(function (root) {
  "use strict";

  function railOrder(layout) {
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const needs = new Map([...rails.keys()].map(id => [id, new Set()]));
    for (const s of layout.supports || []) {
      if (needs.has(s.upper_rail_id) && rails.has(s.lower_rail_id) && s.lower_rail_id !== s.upper_rail_id) {
        needs.get(s.upper_rail_id).add(s.lower_rail_id);
      }
    }
    const order = [];
    const placed = new Set();
    const key = id => [Number(rails.get(id).z_units), id];
    const less = (a, b) => {
      const [za, ia] = key(a), [zb, ib] = key(b);
      return za !== zb ? za < zb : ia < ib;
    };
    while (order.length < rails.size) {
      let ready = [...rails.keys()].filter(id => !placed.has(id) && [...needs.get(id)].every(n => placed.has(n)));
      if (!ready.length) ready = [...rails.keys()].filter(id => !placed.has(id));
      const next = ready.reduce((best, id) => (best === null || less(id, best) ? id : best), null);
      order.push(next);
      placed.add(next);
    }
    return order;
  }

  function sortedNumbers(values) {
    return values.map(Number).sort((a, b) => a - b);
  }

  function buildPlan(layout) {
    const linked = new Set();
    for (const l of layout.route_links || []) {
      linked.add(l.source.component_id);
      linked.add(l.target.component_id);
    }
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const steps = [{ kind: "parts", components: [] }];
    for (const rid of railOrder(layout)) {
      const rail = rails.get(rid);
      const columns = (layout.supports || [])
        .filter(s => s.upper_rail_id === rid)
        .map(s => ({
          support: s.name || "",
          parts: [...(s.stack_part_ids || [])],
          base: s.lower_rail_id != null ? { rail: s.lower_rail_id, hole: Number(s.lower_hole_index) } : "ground",
          hole: Number(s.upper_hole_index),
        }))
        .sort((a, b) => a.hole - b.hole);
      const free = (layout.supports || [])
        .filter(s => s.upper_rail_id == null && s.lower_rail_id === rid)
        .map(s => ({ support: s.name || "", parts: [...(s.stack_part_ids || [])], hole: Number(s.lower_hole_index) }))
        .sort((a, b) => a.hole - b.hole || (a.support < b.support ? -1 : a.support > b.support ? 1 : 0));
      const states = Object.entries(rail.hole_states || {}).map(([k, v]) => [Number(k), v]);
      const holesIn = state => sortedNumbers(states.filter(([, v]) => v === state).map(([k]) => k));
      steps.push({
        kind: "rail",
        rail: rid,
        rail_type: rail.rail_type,
        z_units: Number(rail.z_units),
        brace: states.length === 0 && !linked.has(rid),
        columns,
        rests: columns.map(c => [c.hole, c.support])
          .sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0)),
        covers: holesIn("covered"),
        open: holesIn("open"),
        drops: holesIn("block_connected"),
        free,
        components: [...columns.flatMap(c => c.parts), rid, ...free.flatMap(f => f.parts)],
      });
    }
    steps.push({ kind: "check", components: [] });
    return steps;
  }

  function billOfMaterials(layout) {
    const used = {};
    const add = (k, n = 1) => { used[k] = (used[k] || 0) + n; };
    for (const r of layout.rails || []) add(r.rail_type);
    for (const p of layout.parts || []) add(p.part_type);
    const covers = (layout.rails || []).reduce(
      (n, r) => n + Object.values(r.hole_states || {}).filter(v => v === "covered").length, 0);
    if (covers) add("cover", covers);
    return Object.fromEntries(Object.entries(used).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
  }

  const api = { buildPlan, billOfMaterials, railOrder };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MarbleAssembly = api;
})(typeof window !== "undefined" ? window : globalThis);
