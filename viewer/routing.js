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

  function geometryValue(raw, fallback) {
    const value = Number(raw && typeof raw === "object" && "value" in raw ? raw.value : raw);
    return Number.isFinite(value) ? value : fallback;
  }

  function partSpec(catalog, type) {
    for (const group of [
      catalog.routing_blocks, catalog.structural_parts, catalog.special_parts,
      catalog.accessories?.routing_affecting, catalog.accessories?.non_routing,
    ]) {
      if (group && Object.prototype.hasOwnProperty.call(group, type)) return group[type];
    }
    return null;
  }

  // Physical surface positions, not the offset positions used to draw markers.
  // The returned position is [world x, world y, vertical z], all in centimeters.
  function portPose(layout, catalog, ref) {
    const scale = geometryValue(catalog.geometry_cm?.height_unit, 1.5);
    const rail = (layout.rails || []).find(r => r.id === ref.component_id);
    if (rail) {
      const spec = catalog.rails?.[rail.rail_type];
      if (!spec || !["end_a", "end_b"].includes(ref.port)) return null;
      const angle = Number(rail.yaw_deg || 0) * Math.PI / 180;
      const dir = ref.port === "end_a" ? -1 : 1;
      const distance = ref.port === "end_a" ? 0 : Number(spec.length_cm);
      return {
        position: [
          Number(rail.x_cm) + distance * Math.cos(angle),
          Number(rail.y_cm) + distance * Math.sin(angle),
          (Number(rail.z_units) + Number(spec.height || 1)) * scale,
        ],
        normal: [dir * Math.cos(angle), dir * Math.sin(angle), 0],
      };
    }

    const part = (layout.parts || []).find(p => p.id === ref.component_id);
    if (!part) return null;
    const spec = partSpec(catalog, part.part_type);
    if (!spec || !(spec.ports || []).includes(ref.port)) return null;
    if (spec.height == null) return null;
    const footprint = catalog.geometry_cm?.standard_block_footprint || {};
    const width = Number(footprint.width_cm ?? 4.5);
    const depth = Number(footprint.depth_cm ?? 4.5);
    const height = geometryValue(spec.body_height_cm, Number(spec.height) * scale);
    const sideZ = (spec.port_visualization?.side_entry_notches || []).includes(ref.port)
      ? 0 : height / 2;
    const local = {
      top: [0, 0, height, [0, 0, 1]],
      bottom: [0, 0, 0, [0, 0, -1]],
      front: [0, depth / 2, sideZ, [0, 1, 0]],
      rear: [0, -depth / 2, sideZ, [0, -1, 0]],
      right: [width / 2, 0, sideZ, [1, 0, 0]],
      left: [-width / 2, 0, sideZ, [-1, 0, 0]],
    }[ref.port];
    if (!local) return null;
    const [lx, ly, lz, normal] = local;
    const angle = Number(part.rotation_deg || 0) * Math.PI / 180;
    const c = Math.cos(angle), sn = Math.sin(angle);
    return {
      position: [
        Number(part.x_cm) + lx * c - ly * sn,
        Number(part.y_cm) + lx * sn + ly * c,
        Number(part.z_units) * scale + lz,
      ],
      normal: [normal[0] * c - normal[1] * sn,
               normal[0] * sn + normal[1] * c, normal[2]],
    };
  }

  function supportsFlow(layout, catalog, ref, output) {
    const rail = (layout.rails || []).find(r => r.id === ref.component_id);
    if (rail) {
      const downstream = rail.flow_direction === "b_to_a" ? "end_a" : "end_b";
      const upstream = rail.flow_direction === "b_to_a" ? "end_b" : "end_a";
      return ref.port === (output ? downstream : upstream);
    }
    const part = (layout.parts || []).find(p => p.id === ref.component_id);
    if (!part) return false;
    const spec = partSpec(catalog, part.part_type);
    if (!spec) return false;
    return (spec.routes || []).some(route => output
      ? [...(route.to == null ? [] : [route.to]), ...(route.to_any_of || [])].includes(ref.port)
      : route.from === ref.port);
  }

  function routeLinkError(layout, catalog, link) {
    const source = link.source, target = link.target;
    const label = source.component_id + ":" + source.port + ":" +
      target.component_id + ":" + target.port;
    const a = portPose(layout, catalog, source);
    const b = portPose(layout, catalog, target);
    if (!a || !b) return "route_link_unsupported_port:" + label;
    const validDirection = (s, t) =>
      supportsFlow(layout, catalog, s, true) &&
      supportsFlow(layout, catalog, t, false);
    if (!validDirection(source, target) ||
        (link.bidirectional && !validDirection(target, source))) {
      return "route_link_invalid_direction:" + label;
    }
    const distance = Math.hypot(...a.position.map((x, i) => x - b.position[i]));
    const dot = a.normal.reduce((sum, x, i) => sum + x * b.normal[i], 0);
    if (distance > 0.35 || dot > -0.95) {
      return "route_link_geometry_mismatch:" + label;
    }
    return null;
  }

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
    function refKey(ref) {
      return ref.component_id + ":" + ref.port;
    }

    // Directed internal routes, including all possible random branches.
    for (const part of layout.parts || []) {
      const spec = partSpec(catalog, part.part_type);
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

    // Only a geometrically aligned, real hole can feed the top of a block.
    const validConnectedHoles = new Set();
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
      const railSpec = catalog.rails?.[rail.rail_type];
      const partHeight = partSpec(catalog, part.part_type)?.height;
      const index = Number(support.upper_hole_index);
      if (!railSpec || partHeight == null ||
          !Number.isInteger(index) || index < 0 ||
          index >= (railSpec.hole_positions_cm || []).length) {
        reasons.push("block_connected_invalid_geometry:" + rail.id + ":" + index);
        continue;
      }
      const yaw = Number(rail.yaw_deg || 0) * Math.PI / 180;
      const holeX = Number(rail.x_cm) + Number(railSpec.hole_positions_cm[index]) * Math.cos(yaw);
      const holeY = Number(rail.y_cm) + Number(railSpec.hole_positions_cm[index]) * Math.sin(yaw);
      if (Math.hypot(Number(part.x_cm) - holeX, Number(part.y_cm) - holeY) > 0.35 ||
          Math.abs(Number(part.z_units) + Number(partHeight) - Number(rail.z_units)) > 0.1) {
        reasons.push("block_connected_geometry_mismatch:" + rail.id + ":" + index + ":" + part.id);
        continue;
      }
      validConnectedHoles.add(rail.id + ":" + index);
      edge(rail.id + ":hole:" + index, part.id + ":top");
    }
    for (const rail of layout.rails || []) {
      for (const [index, state] of Object.entries(rail.hole_states || {})) {
        if (state === "block_connected" && !validConnectedHoles.has(rail.id + ":" + index)) {
          reasons.push("block_connected_without_valid_support:" + rail.id + ":" + index);
        }
      }
    }

    // Explicit links must mate actual aligned openings. No teleport edges.
    for (const link of layout.route_links || []) {
      if (!knownComponents.has(link.source.component_id)) {
        reasons.push("route_link_unknown_component:" + link.source.component_id);
        continue;
      }
      if (!knownComponents.has(link.target.component_id)) {
        reasons.push("route_link_unknown_component:" + link.target.component_id);
        continue;
      }
      const error = routeLinkError(layout, catalog, link);
      if (error) {
        reasons.push(error);
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
      valid: reachable && reasons.length === 0,
      reachable, path, reachableNodes, reachableEdges,
      deadEnds, reasons: [...new Set(reasons)],
    };
  }

  return { buildGraph, trace, portPose };
});
