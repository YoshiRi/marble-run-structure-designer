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

  // Rail spec by type: straight rails from catalog.rails, curved rails from
  // catalog.curved_rails presented with the same fields (positions along the
  // centerline) plus arc segments. Mirrors catalog.load_rail_specs.
  function railGeometry(catalog, type) {
    const straight = catalog.rails?.[type];
    if (straight) return { ...straight, shape: "straight" };
    const special = catalog.special_rails?.[type];
    if (special?.shape === "twist") {
      // Two-level rail from the chute tip (end A) to the funnel center.
      return {
        ...special, shape: "twist",
        length_cm: Number(special.centerline_length_cm),
        hole_positions_cm: special.hole_positions_cm || [],
        hole_levels: special.hole_mount_levels_units || [],
      };
    }
    const curved = catalog.curved_rails?.[type];
    if (!curved) return null;
    const radius = geometryValue(curved.hole_circle_radius_cm, 23);
    const length = Number(curved.centerline_length_cm);
    const segments = curved.segments?.length
      ? curved.segments.map(seg => ({ length: Number(seg.length_cm), sign: seg.turn === "opposite" ? -1 : 1 }))
      : [{ length, sign: 1 }];
    return {
      ...curved, shape: "arc", radius_cm: radius, segments,
      length_cm: length, hole_positions_cm: curved.hole_arc_positions_cm || [],
    };
  }

  // Mount level of a hole relative to rail.z_units (non-zero only on the twist).
  function holeLevel(spec, index) {
    return Number(spec?.hole_levels?.[index] || 0);
  }

  function endLevel(spec, port) {
    const levels = spec?.hole_levels || [];
    if (!levels.length) return 0;
    return Number(port === "end_a" ? levels[0] : levels[levels.length - 1]);
  }

  // [x, y, heading radians] on the centerline, s cm from end A. Mirrors
  // model.rail_pose (negative s extrapolates before end A).
  function railPose(catalog, rail, s) {
    const spec = railGeometry(catalog, rail.rail_type);
    let x = Number(rail.x_cm), y = Number(rail.y_cm);
    let heading = Number(rail.yaw_deg || 0) * Math.PI / 180;
    if (!spec || spec.shape !== "arc") {
      return [x + s * Math.cos(heading), y + s * Math.sin(heading), heading];
    }
    const railSign = rail.turn === "right" ? -1 : 1;
    let remaining = Number(s);
    for (let i = 0; i < spec.segments.length; i++) {
      const seg = spec.segments[i];
      const last = i === spec.segments.length - 1;
      const step = (last || remaining < 0) ? remaining : Math.min(remaining, seg.length);
      const sign = railSign * seg.sign;
      const r = spec.radius_cm;
      const cx = x - sign * r * Math.sin(heading);
      const cy = y + sign * r * Math.cos(heading);
      heading += sign * step / r;
      x = cx + sign * r * Math.sin(heading);
      y = cy - sign * r * Math.cos(heading);
      remaining -= step;
      if (remaining <= 1e-9) break;
    }
    return [x, y, heading];
  }

  // Physical surface positions, not the offset positions used to draw markers.
  // The returned position is [world x, world y, vertical z], all in centimeters.
  function portPose(layout, catalog, ref) {
    const scale = geometryValue(catalog.geometry_cm?.height_unit, 1.5);
    const rail = (layout.rails || []).find(r => r.id === ref.component_id);
    if (rail) {
      const spec = railGeometry(catalog, rail.rail_type);
      if (!spec || !["end_a", "end_b"].includes(ref.port)) return null;
      const dir = ref.port === "end_a" ? -1 : 1;
      const distance = ref.port === "end_a" ? 0 : Number(spec.length_cm);
      const [px, py, angle] = railPose(catalog, rail, distance);
      return {
        position: [px, py, (Number(rail.z_units) + endLevel(spec, ref.port) + Number(spec.height || 1)) * scale],
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

  // Mirror of _twist_entry_node: where a marble dropped into a twist's
  // chute hole (index 0) continues.
  function twistEntryNode(catalog, rail, hole) {
    if (!rail || Number(hole) !== 0) return null;
    const spec = railGeometry(catalog, rail.rail_type);
    if (!spec || spec.shape !== "twist") return null;
    if (rail.flow_direction === "b_to_a") return "end_a";
    return (spec.hole_positions_cm || []).length > 1 ? "hole:1" : "end_b";
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
      const spec = railGeometry(catalog, rail.rail_type);
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
      const railSpec = railGeometry(catalog, rail.rail_type);
      const partHeight = partSpec(catalog, part.part_type)?.height;
      const index = Number(support.upper_hole_index);
      if (!railSpec || partHeight == null ||
          !Number.isInteger(index) || index < 0 ||
          index >= (railSpec.hole_positions_cm || []).length) {
        reasons.push("block_connected_invalid_geometry:" + rail.id + ":" + index);
        continue;
      }
      const [holeX, holeY] = railPose(catalog, rail, Number(railSpec.hole_positions_cm[index]));
      if (Math.hypot(Number(part.x_cm) - holeX, Number(part.y_cm) - holeY) > 0.35 ||
          Math.abs(Number(part.z_units) + Number(partHeight) - Number(rail.z_units) - holeLevel(railSpec, index)) > 0.1) {
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

    // Mirror of the Python stack-drop rule: a block's bottom outlet drops
    // into the top of the part beneath it in the same stack, or through the
    // lower rail hole into the top of the column under that hole.
    const columnsByUpperHole = new Map();
    for (const support of layout.supports || []) {
      if (!support.stack_part_ids?.length) continue;
      columnsByUpperHole.set(support.upper_rail_id + ":" + support.upper_hole_index, support);
    }
    const hasPort = (partId, port) => Boolean(partPorts.get(partId)?.has(port));
    for (const support of layout.supports || []) {
      const ids = support.stack_part_ids || [];
      const stack = ids.filter(id => parts.has(id));
      if (stack.length !== ids.length) continue;
      for (let k = 1; k < stack.length; k++) {
        if (hasPort(stack[k], "bottom") && hasPort(stack[k - 1], "top")) {
          edge(stack[k] + ":bottom", stack[k - 1] + ":top");
        }
      }
      if (!stack.length || support.lower_rail_id == null) continue;
      // A block standing on a twist's chute hole drops into the chute.
      const entry = twistEntryNode(catalog, rails.get(support.lower_rail_id), support.lower_hole_index);
      if (entry) {
        if (hasPort(stack[0], "bottom")) edge(stack[0] + ":bottom", support.lower_rail_id + ":" + entry);
        continue;
      }
      const below = columnsByUpperHole.get(support.lower_rail_id + ":" + support.lower_hole_index);
      if (!below || !parts.has(below.stack_part_ids.at(-1))) continue;
      const belowTop = below.stack_part_ids.at(-1);
      if (hasPort(stack[0], "bottom") && hasPort(belowTop, "top")) {
        edge(stack[0] + ":bottom", belowTop + ":top");
      }
    }

    // Mirror of _landing_edges: a side outlet of a block standing directly on
    // a rail, facing along it in its flow direction, lands on that rail.
    const explicitSources = new Set((layout.route_links || []).map(link => refKey(link.source)));
    const unitCm = geometryValue(catalog.geometry_cm?.height_unit, 1.5);
    for (const support of layout.supports || []) {
      if (!support.stack_part_ids?.length || support.lower_rail_id == null) continue;
      const rail = rails.get(support.lower_rail_id);
      const part = parts.get(support.stack_part_ids[0]);
      const railSpec = rail && railGeometry(catalog, rail.rail_type);
      if (!rail || !part || !railSpec || railSpec.shape === "twist") continue;
      const hole = Number(support.lower_hole_index);
      if (!Number.isInteger(hole) || hole < 0 || hole >= (railSpec.hole_positions_cm || []).length) continue;
      // Direction of the rail where the block stands (tangent on a curve).
      const theta = railPose(catalog, rail, Number(railSpec.hole_positions_cm[hole]))[2];
      const axis = [Math.cos(theta), Math.sin(theta)];
      const railTopCm = (Number(rail.z_units) + holeLevel(railSpec, hole) + Number(railSpec.height || 1)) * unitCm;
      const outputs = new Set();
      for (const route of partSpec(catalog, part.part_type)?.routes || []) {
        if (route.from == null) continue;
        for (const target of [...(route.to == null ? [] : [route.to]), ...(route.to_any_of || [])]) {
          outputs.add(String(target));
        }
      }
      for (const port of ["front", "left", "rear", "right"].filter(p => outputs.has(p)).sort()) {
        if (explicitSources.has(part.id + ":" + port)) continue;
        const pose = portPose(layout, catalog, { component_id: part.id, port });
        if (!pose) continue;
        const along = pose.normal[0] * axis[0] + pose.normal[1] * axis[1];
        if (Math.abs(along) < 0.95 || Math.abs(pose.position[2] - (railTopCm + unitCm)) > 0.05) continue;
        // The marble lands just past the block face, half a block from the hole.
        const halfBlock = Math.abs((pose.position[0] - Number(part.x_cm)) * axis[0] +
          (pose.position[1] - Number(part.y_cm)) * axis[1]);
        const landing = Number(railSpec.hole_positions_cm[hole]) + (along > 0 ? halfBlock : -halfBlock);
        const stations = [["end_a", 0],
          ...(railSpec.hole_positions_cm || []).map((x, i) => ["hole:" + i, Number(x)]),
          ["end_b", Number(railSpec.length_cm)]];
        let next = null;
        if (along > 0 && rail.flow_direction !== "b_to_a") {
          next = stations.find(([, x]) => x > landing + 1e-6)?.[0] ?? null;
        } else if (along < 0 && rail.flow_direction === "b_to_a") {
          const ahead = stations.filter(([, x]) => x < landing - 1e-6);
          next = ahead.length ? ahead[ahead.length - 1][0] : null;
        }
        if (next) edge(part.id + ":" + port, rail.id + ":" + next);
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
      const spec = railGeometry(catalog, rail.rail_type);
      if (!spec) continue;
      for (let index = 0; index < (spec.hole_positions_cm || []).length; index++) {
        const state = rail.hole_states?.[index] ?? "open";
        const key = rail.id + ":hole:" + index;
        if (state !== "block_connected" || !(graph.edges[key] || []).length) continue;
        const level = Number(rail.z_units) + holeLevel(spec, index) + Number(spec.height || 1);
        candidates.push({
          key,
          rail_id: rail.id,
          hole_index: index,
          level_units: level,
          label: rail.id + " · hole " + index + " · level " + level + "u",
        });
      }
    }
    // The top of a free-standing stack (it holds up no rail) is an input too:
    // the marble can be put straight into the top block (generated layouts
    // have no input rail).
    const parts = new Map((layout.parts || []).map(part => [part.id, part]));
    for (const support of layout.supports || []) {
      if (support.upper_rail_id != null || !support.stack_part_ids?.length) continue;
      if (twistEntryNode(catalog, (layout.rails || []).find(r => r.id === support.lower_rail_id),
        support.lower_hole_index)) continue;  // a twist's entry block is fed from the side
      const part = parts.get(support.stack_part_ids.at(-1));
      const key = part && part.id + ":top";
      if (!part || !(graph.edges[key] || []).length) continue;
      const level = Number(part.z_units) + Number(partSpec(catalog, part.part_type)?.height || 0);
      candidates.push({
        key, part_id: part.id, level_units: level,
        rail_id: "", hole_index: -1,
        label: part.id + " · top · level " + level + "u",
      });
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

  // Roll one marble from `source`, choosing each random branch with the same
  // transition weights analyzeOutcomes uses. `random` returns [0, 1).
  // Stops at an exterior exit, an unmodeled branch, or a cycle guard.
  function sampleRun(layout, catalog, graph, source, random = Math.random, maxSteps = 1000) {
    if (!Object.prototype.hasOwnProperty.call(graph.edges, source)) {
      return { path: [], exit: null, complete: false, reason: "unknown_source:" + source };
    }
    const path = [source];
    let node = source;
    for (let step = 0; step < maxSteps; step++) {
      const targets = graph.edges[node] || [];
      if (!targets.length) {
        const exit = exteriorExitInfo(node, layout, catalog, graph);
        return exit
          ? { path, exit: exit.node, complete: true, reason: null }
          : { path, exit: null, complete: false, reason: "unclassified_terminal:" + node };
      }
      const weights = transitionWeights(node, targets, layout, catalog);
      if (!weights) {
        return { path, exit: null, complete: false, reason: "unmodeled_branch:" + node };
      }
      let draw = random();
      let next = weights.transitions[weights.transitions.length - 1].node;
      for (const transition of weights.transitions) {
        if (draw < transition.probability) { next = transition.node; break; }
        draw -= transition.probability;
      }
      node = next;
      path.push(node);
    }
    return { path, exit: null, complete: false, reason: "step_limit:" + node };
  }

  return { buildGraph, trace, portPose, listInputHoles, analyzeOutcomes, sampleRun, railGeometry, railPose, holeLevel };
});
