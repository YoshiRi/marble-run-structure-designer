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
    // Centered side holes: floor at installation level +1 unit (the groove of
    // a rail laid at the same level). Side-entry notches: installation level.
    const sideZ = (spec.port_visualization?.side_entry_notches || []).includes(ref.port)
      ? 0 : Math.min(scale, height);
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

  function allowsSideEntryPlusOne(layout, catalog, source, target, a, b) {
    if (!layout.routing_options?.allow_side_entry_plus_one) return false;
    const rail = (layout.rails || []).find(r => r.id === source.component_id);
    if (!rail || !["end_a", "end_b"].includes(source.port)) return false;
    const part = (layout.parts || []).find(p => p.id === target.component_id);
    if (!part) return false;
    const spec = partSpec(catalog, part.part_type);
    if (!(spec?.port_visualization?.side_entry_notches || []).includes(target.port)) {
      return false;
    }

    const heightUnitCm = geometryValue(catalog.geometry_cm?.height_unit, 1.5);
    const dx = a.position[0] - b.position[0];
    const dy = a.position[1] - b.position[1];
    const verticalGap = a.position[2] - b.position[2];
    const horizontalDistance = Math.hypot(dx, dy);
    const dot = a.normal.reduce((sum, x, i) => sum + x * b.normal[i], 0);
    return horizontalDistance <= 0.35 &&
      Math.abs(verticalGap - heightUnitCm) <= 0.35 &&
      dot <= -0.95;
  }

  // Mirror of _allows_side_exit_drop_one: a centered side outlet may also
  // drop one unit onto a rail whose groove is at the installation level.
  function allowsSideExitDropOne(layout, catalog, source, target, a, b) {
    if (!["front", "rear", "left", "right"].includes(source.port)) return false;
    const part = (layout.parts || []).find(p => p.id === source.component_id);
    if (!part) return false;
    const spec = partSpec(catalog, part.part_type);
    if (!spec) return false;
    if ((spec.port_visualization?.side_entry_notches || []).includes(source.port)) return false;
    const rail = (layout.rails || []).find(r => r.id === target.component_id);
    if (!rail || !["end_a", "end_b"].includes(target.port)) return false;

    const heightUnitCm = geometryValue(catalog.geometry_cm?.height_unit, 1.5);
    const horizontalDistance = Math.hypot(a.position[0] - b.position[0], a.position[1] - b.position[1]);
    const drop = a.position[2] - b.position[2];
    const dot = a.normal.reduce((sum, x, i) => sum + x * b.normal[i], 0);
    return horizontalDistance <= 0.35 &&
      Math.abs(drop - heightUnitCm) <= 0.35 &&
      dot <= -0.95;
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
      if (!allowsSideEntryPlusOne(layout, catalog, source, target, a, b) &&
          !allowsSideExitDropOne(layout, catalog, source, target, a, b)) {
        return "route_link_geometry_mismatch:" + label;
      }
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

  function splitNodeKey(node) {
    const separator = node.indexOf(":");
    if (separator < 0) return { componentId: node, port: "" };
    return { componentId: node.slice(0, separator), port: node.slice(separator + 1) };
  }

  function listInputHoles(layout, catalog, graph) {
    const candidates = [];
    for (const rail of layout.rails || []) {
      const spec = catalog.rails?.[rail.rail_type];
      if (!spec) continue;
      for (let index = 0; index < (spec.hole_positions_cm || []).length; index++) {
        const state = rail.hole_states?.[index] ?? "open";
        const key = rail.id + ":hole:" + index;
        if (state !== "block_connected" || !(graph.edges[key] || []).length) continue;
        candidates.push({
          key,
          rail_id: rail.id,
          hole_index: index,
          level_units: Number(rail.z_units) + Number(spec.height || 1),
          label: rail.id + " · hole " + index + " · level " +
            (Number(rail.z_units) + Number(spec.height || 1)) + "u",
        });
      }
    }
    return candidates.sort((a, b) =>
      b.level_units - a.level_units ||
      a.rail_id.localeCompare(b.rail_id, "en") ||
      a.hole_index - b.hole_index);
  }

  function exteriorExitInfo(node, layout, catalog, graph) {
    if ((graph.edges[node] || []).length) return null;
    const { componentId, port } = splitNodeKey(node);
    const rail = (layout.rails || []).find(item => item.id === componentId);
    if (rail) {
      if (port === "end_a" || port === "end_b") {
        return {
          node, kind: "rail_end",
          label: rail.id + " · end " + (port === "end_a" ? "A" : "B") + " (rail exit)",
        };
      }
      const match = /^hole:(\d+)$/.exec(port);
      if (match && (rail.hole_states?.[Number(match[1])] ?? "open") === "open") {
        return {
          node, kind: "open_hole",
          label: rail.id + " · hole " + Number(match[1]) + " (open hole)",
        };
      }
      return null;
    }

    const part = (layout.parts || []).find(item => item.id === componentId);
    if (!part) return null;
    const spec = partSpec(catalog, part.part_type);
    const outputPorts = new Set((spec?.routes || []).flatMap(route => [
      ...(route.to == null ? [] : [route.to]),
      ...(route.to_any_of || []),
    ]));
    if (!outputPorts.has(port)) return null;
    return { node, kind: "block_outlet", label: part.id + " · " + port + " (block outlet)" };
  }

  function transitionWeights(node, targets, layout, catalog) {
    if (targets.length === 1) return { transitions: [{ node: targets[0], probability: 1 }], estimated: false };
    if (targets.length < 1) return { transitions: [], estimated: false };

    const { componentId, port } = splitNodeKey(node);
    const part = (layout.parts || []).find(item => item.id === componentId);
    const spec = part ? partSpec(catalog, part.part_type) : null;
    const routes = (spec?.routes || []).filter(route => route.from === port);
    if (routes.length === 1 && routes[0].selection === "random") {
      const route = routes[0];
      const choices = [
        ...(route.to == null ? [] : [route.to]),
        ...(route.to_any_of || []),
      ].map(target => componentId + ":" + target);
      if (choices.length === targets.length && choices.every(target => targets.includes(target))) {
        const probability = 1 / choices.length;
        return {
          transitions: choices.map(target => ({ node: target, probability })),
          estimated: choices.length > 1,
        };
      }
    }
    return null;
  }

  function analyzeOutcomes(layout, catalog, graph, source) {
    if (!Object.prototype.hasOwnProperty.call(graph.edges, source)) {
      return {
        source, complete: false, estimated: false, exits: [],
        reasons: ["unknown_source:" + source],
      };
    }

    const reachable = new Set([source]);
    const queue = [source];
    for (let i = 0; i < queue.length; i++) {
      for (const target of graph.edges[queue[i]] || []) {
        if (reachable.has(target)) continue;
        reachable.add(target);
        queue.push(target);
      }
    }
    const exits = [...reachable]
      .map(node => exteriorExitInfo(node, layout, catalog, graph))
      .filter(Boolean)
      .sort((a, b) => a.node.localeCompare(b.node, "en"));

    const memo = new Map();
    const active = new Set();
    const assumptions = new Set();
    const issues = new Set();
    function visit(node) {
      if (active.has(node)) {
        issues.add("cycle_detected:" + node);
        return { probabilities: new Map(), complete: false };
      }
      if (memo.has(node)) return memo.get(node);
      const targets = graph.edges[node] || [];
      if (!targets.length) {
        const exit = exteriorExitInfo(node, layout, catalog, graph);
        if (!exit) {
          issues.add("unclassified_terminal:" + node);
          return { probabilities: new Map(), complete: false };
        }
        const result = { probabilities: new Map([[node, 1]]), complete: true };
        memo.set(node, result);
        return result;
      }

      const weights = transitionWeights(node, targets, layout, catalog);
      if (!weights) {
        issues.add("unmodeled_branch:" + node);
        return { probabilities: new Map(), complete: false };
      }
      if (weights.estimated) assumptions.add("uniform_random_branch:" + node);
      active.add(node);
      const probabilities = new Map();
      let complete = true;
      for (const transition of weights.transitions) {
        const child = visit(transition.node);
        complete = complete && child.complete;
        for (const [exit, probability] of child.probabilities) {
          probabilities.set(exit, (probabilities.get(exit) || 0) +
            transition.probability * probability);
        }
      }
      active.delete(node);
      const result = { probabilities, complete };
      memo.set(node, result);
      return result;
    }

    const computed = visit(source);
    const reasons = [...new Set([...graph.reasons, ...issues])];
    const totalProbability = exits.reduce((sum, exit) =>
      sum + (computed.probabilities.get(exit.node) || 0), 0);
    const complete = computed.complete && reasons.length === 0 &&
      exits.length > 0 && Math.abs(totalProbability - 1) < 1e-6;
    return {
      source,
      complete,
      estimated: assumptions.size > 0,
      assumptions: [...assumptions].sort(),
      exits: exits.map(exit => ({
        ...exit,
        probability: complete ? (computed.probabilities.get(exit.node) || 0) : null,
      })),
      reasons,
    };
  }

  return { buildGraph, trace, portPose, listInputHoles, analyzeOutcomes };
});
