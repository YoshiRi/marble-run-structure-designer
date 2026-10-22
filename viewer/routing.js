/* Browser-side port of src/quadrilla_solver/connectivity.py.
 * Keep routing semantics in sync; pytest compares both graph and traces.
 * Pure JS: no Babylon.js or DOM dependencies.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MarbleRouting = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function buildGraph(layout, catalog) {
    const graph = new Map();
    const reasons = [];
    const rails = new Map((layout.rails || []).map(rail => [rail.id, rail]));
    const parts = new Map((layout.parts || []).map(part => [part.id, part]));
    const knownComponents = new Set([...rails.keys(), ...parts.keys()]);
    const partPorts = new Map();

    function ensure(node) {
      if (!graph.has(node)) graph.set(node, new Set());
    }
    function edge(source, target) {
      ensure(source);
      ensure(target);
      graph.get(source).add(target);
    }
    function partSpec(type) {
      for (const group of [
        catalog.routing_blocks,
        catalog.structural_parts,
        catalog.special_parts,
        catalog.accessories?.routing_affecting,
        catalog.accessories?.non_routing,
      ]) {
        if (group && Object.prototype.hasOwnProperty.call(group, type)) return group[type];
      }
      return null;
    }
    function refKey(ref) {
      return ref.component_id + ":" + ref.port;
    }

    // Directed internal routes, including all possible random branches.
    for (const part of layout.parts || []) {
      const spec = partSpec(part.part_type);
      if (!spec) continue;
      const ports = new Set();
      for (const route of spec.routes || []) {
        if (route.from == null) continue;
        const targets = [
          ...(route.to == null ? [] : [route.to]),
          ...(route.to_any_of || []),
        ];
        for (const target of targets) {
          edge(part.id + ":" + route.from, part.id + ":" + target);
          ports.add(String(route.from));
          ports.add(String(target));
        }
      }
      partPorts.set(part.id, ports);
    }

    // Rails are directed chains, stopped by open/connected holes.
    for (const rail of layout.rails || []) {
      const spec = catalog.rails?.[rail.rail_type];
      if (!spec) continue;
      const sequence = [
        "end_a",
        ...(spec.hole_positions_cm || []).map((_, index) => "hole:" + index),
        "end_b",
      ];
      if (rail.flow_direction === "b_to_a") sequence.reverse();
      for (const port of sequence) ensure(rail.id + ":" + port);
      for (let i = 0; i + 1 < sequence.length; i++) {
        const current = sequence[i];
        const next = sequence[i + 1];
        if (current.startsWith("hole:")) {
          const index = Number(current.slice(5));
          const state = rail.hole_states?.[index] ?? "open";
          if (state === "covered") edge(rail.id + ":" + current, rail.id + ":" + next);
          else if (state === "covered_slope") {
            reasons.push("unsupported_covered_slope_semantics:" + rail.id + ":" + index);
          }
        } else {
          edge(rail.id + ":" + current, rail.id + ":" + next);
        }
      }
    }

    // A connected upper hole drops into the top routing block of its support.
    for (const support of layout.supports || []) {
      if (!support.stack_part_ids?.length) continue;
      const rail = rails.get(support.upper_rail_id);
      if (!rail || (rail.hole_states?.[support.upper_hole_index] ?? "open") !== "block_connected") continue;
      const part = parts.get(support.stack_part_ids.at(-1));
      if (!part) continue;
      if (!partPorts.get(part.id)?.has("top")) {
        reasons.push("block_connected_without_top_port:" + rail.id + ":" +
          support.upper_hole_index + ":" + part.id);
        continue;
      }
      edge(rail.id + ":hole:" + support.upper_hole_index, part.id + ":top");
    }

    // Explicit links represent transitions whose geometry is not yet modeled.
    for (const link of layout.route_links || []) {
      if (!knownComponents.has(link.source.component_id)) {
        reasons.push("route_link_unknown_component:" + link.source.component_id);
        continue;
      }
      if (!knownComponents.has(link.target.component_id)) {
        reasons.push("route_link_unknown_component:" + link.target.component_id);
        continue;
      }
      const source = refKey(link.source);
      const target = refKey(link.target);
      edge(source, target);
      if (link.bidirectional) edge(target, source);
    }

    const edges = Object.fromEntries([...graph.entries()]
      .sort(([a], [b]) => a.localeCompare(b, "en"))
      .map(([node, targets]) => [node, [...targets].sort()]));
    return { edges, nodes: Object.keys(edges), reasons: [...new Set(reasons)] };
  }

  function trace(graph, source, sink) {
    const edges = graph.edges;
    const reasons = [...graph.reasons];
    if (!Object.prototype.hasOwnProperty.call(edges, source)) {
      reasons.push("unknown_source:" + source);
      return {
        source, sink, valid: false, reachable: false,
        path: [], reachableNodes: [], reachableEdges: [],
        deadEnds: [], reasons: [...new Set(reasons)],
      };
    }
    const unknownSink = !Object.prototype.hasOwnProperty.call(edges, sink);
    if (unknownSink) reasons.push("unknown_sink:" + sink);
    const visited = new Set([source]);
    const previous = new Map();
    const queue = [source];
    for (let i = 0; i < queue.length; i++) {
      const node = queue[i];
      for (const target of edges[node] || []) {
        if (visited.has(target)) continue;
        visited.add(target);
        previous.set(target, node);
        queue.push(target);
      }
    }
    const reachable = visited.has(sink);
    const path = [];
    if (reachable) {
      let node = sink;
      while (node !== undefined) {
        path.push(node);
        node = previous.get(node);
      }
      path.reverse();
    } else {
      reasons.push("no_requested_sink_reachable");
    }
    const reachableNodes = [...visited].sort();
    const deadEnds = reachableNodes.filter(node =>
      !(edges[node] || []).length && node !== sink);
    const reachableEdges = [];
    for (const node of reachableNodes) {
      for (const target of edges[node] || []) {
        if (visited.has(target)) reachableEdges.push([node, target]);
      }
    }
    return {
      source, sink,
      valid: reachable && !unknownSink && !reasons.some(r => r.startsWith("unsupported_")),
      reachable, path, reachableNodes, reachableEdges,
      deadEnds, reasons: [...new Set(reasons)],
    };
  }

  return { buildGraph, trace };
});
