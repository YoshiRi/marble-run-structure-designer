/* Browser-side port of the Python layout validators:
 *   assembly.py, collision.py, layout_stability.py, statics.py,
 *   validation.py (validate_layout) and connectivity.validate_connectivity.
 * Keep semantics and reason strings in sync; pytest compares both
 * (tests/test_validation_browser_parity.py). Pure JS, no DOM.
 * Routing (the port graph) comes from routing.js.
 */
(function (root, factory) {
  "use strict";
  const routing = (typeof module === "object" && module.exports) ? require("./routing.js") : root.MarbleRouting;
  const api = factory(routing);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MarbleValidation = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (R) {
  "use strict";

  const GRAVITY = 9.80665;
  const HOLE_STATES = new Set(["open", "block_connected", "covered", "covered_slope"]);

  // ---- helpers ---------------------------------------------------------------

  // Python's format(x, ".6g").
  function g6(x) {
    x = Number(x);
    if (Object.is(x, -0)) return "-0";
    if (x === 0) return "0";
    if (!Number.isFinite(x)) return x > 0 ? "inf" : x < 0 ? "-inf" : "nan";
    const [mant, expStr] = x.toExponential(5).split("e");
    const exp = Number(expStr);
    const strip = s => (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s);
    if (exp < -4 || exp >= 6) {
      return strip(mant) + "e" + (exp < 0 ? "-" : "+") + String(Math.abs(exp)).padStart(2, "0");
    }
    return strip(x.toFixed(Math.max(0, 5 - exp)));
  }

  function unique(list) { return [...new Set(list)]; }

  function value(raw) {
    if (raw == null) return null;
    if (typeof raw === "number") return raw;
    if (typeof raw === "object" && raw.value != null) return Number(raw.value);
    return null;
  }

  function geometry(catalog, key, fallback) {
    const v = catalog.geometry_cm?.[key];
    if (v == null) return fallback;
    return Number(typeof v === "object" ? (v.value ?? fallback) : v);
  }

  function findPart(catalog, type) {
    for (const category of ["routing_blocks", "structural_parts", "special_parts"]) {
      const group = catalog[category];
      if (group && Object.prototype.hasOwnProperty.call(group, type) && group[type] && typeof group[type] === "object") {
        return [category, group[type]];
      }
    }
    for (const sub of ["routing_affecting", "non_routing"]) {
      const group = catalog.accessories?.[sub];
      if (group && Object.prototype.hasOwnProperty.call(group, type)) return ["accessories." + sub, group[type]];
    }
    return null;
  }

  // RailSpec as in catalog.load_rail_specs (null for unknown types).
  function railSpec(catalog, type) {
    const geo = R.railGeometry(catalog, type);
    if (!geo) return null;
    if (geo.shape === "straight" && (geo.length_cm == null || geo.hole_positions_cm == null)) return null;
    return {
      length_cm: Number(geo.length_cm),
      holes_cm: (geo.hole_positions_cm || []).map(Number),
      height_units: Number(geo.height ?? 1),
      mass_g: value(geo.mass_g),
      shape: geo.shape,
      hole_levels: (geo.hole_levels || []).map(Number),
      com_cm: geo.shape === "twist" && geo.com_cm != null ? Number(geo.com_cm) : null,
      needs_load_above: geo.shape === "arc" && geo.stability === "needs_load_above",
      radius_cm: geo.radius_cm ?? null,
    };
  }

  function holeLevel(spec, i) { return spec.hole_levels.length ? spec.hole_levels[i] : 0; }

  function heightUnits(catalog, type) {
    const rail = railSpec(catalog, type);
    if (rail) return rail.height_units;
    const found = findPart(catalog, type);
    if (!found) return null;
    const h = found[1].height;
    return h == null ? null : Math.trunc(Number(h));
  }

  function massG(catalog, type) {
    const rail = railSpec(catalog, type);
    if (rail) return rail.mass_g;
    const found = findPart(catalog, type);
    if (!found) return null;
    const [category, spec] = found;
    const measured = value(spec.mass_g);
    if (measured != null) return measured;
    if (category === "routing_blocks" && Math.trunc(Number(spec.height || 0)) === standardBlockUnits(catalog)) {
      return value(catalog.mass_defaults?.standard_routing_block_g);
    }
    return null;
  }

  function standardBlockUnits(catalog) {
    const v = catalog.height_units?.standard_block ?? 5;
    return Math.trunc(Number(typeof v === "object" ? v.value : v));
  }

  function hasPart(catalog, type) { return Boolean(railSpec(catalog, type) || findPart(catalog, type)); }

  function allowedRotations(catalog, type) {
    const found = findPart(catalog, type);
    if (!found) return null;
    const rot = found[1].rotations_deg;
    if (rot == null || rot === "any") return null;
    return rot.map(v => ((Math.trunc(Number(v)) % 360) + 360) % 360);
  }

  function pose(catalog, rail, s) { return R.railPose(catalog, rail, s); }

  function railHoleWorld(catalog, rail, i) {
    const spec = railSpec(catalog, rail.rail_type);
    if (!(i >= 0 && i < spec.holes_cm.length)) throw new RangeError(rail.id + ": hole index " + i);
    const [x, y] = pose(catalog, rail, spec.holes_cm[i]);
    return [x, y, Number(rail.z_units) + holeLevel(spec, i)];
  }

  function holeState(rail, i) { return rail.hole_states?.[i] ?? rail.hole_states?.[String(i)]; }

  function holeEntries(rail) {
    return Object.entries(rail.hole_states || {}).map(([k, v]) => [Number(k), v]);
  }

  // geometry.valid_support_pairs: end+end or end+center hole pairs.
  function zone(x, length) {
    if (Math.abs(x - length / 2) <= 0.10 * length) return "center";
    if (x <= 0.30 * length) return "left";
    if (x >= 0.70 * length) return "right";
    return "interior";
  }

  function supportPairs(spec) {
    const out = [];
    const h = spec.holes_cm;
    for (let i = 0; i < h.length; i++) {
      for (let j = i + 1; j < h.length; j++) {
        const zs = new Set([zone(h[i], spec.length_cm), zone(h[j], spec.length_cm)]);
        const endToEnd = zs.has("left") && zs.has("right") && zs.size === 2;
        const endToCenter = zs.has("center") && (zs.has("left") || zs.has("right"));
        if (endToEnd || endToCenter) out.push([Math.min(h[i], h[j]), Math.max(h[i], h[j])]);
      }
    }
    return out;
  }

  // ---- collision.py ------------------------------------------------------------

  function solid(id, cx, cy, hx, hy, angle, zMin, zMax) {
    return { id, cx, cy, hx, hy, angle, zMin, zMax };
  }

  function stripSolids(catalog, rail, spec, start, end, halfWidth, zMin, zMax, id) {
    if (end - start <= 0) return [];
    const pieces = spec.shape !== "arc" ? 1 : Math.max(1, Math.trunc((end - start) / 3.0 + 0.999));
    const out = [];
    const step = (end - start) / pieces;
    for (let i = 0; i < pieces; i++) {
      const a = pose(catalog, rail, start + i * step);
      const b = pose(catalog, rail, start + (i + 1) * step);
      const chord = Math.hypot(b[0] - a[0], b[1] - a[1]);
      let sagitta = 0;
      if (spec.shape === "arc" && spec.radius_cm) {
        sagitta = spec.radius_cm - Math.sqrt(spec.radius_cm ** 2 - (chord / 2) ** 2);
      }
      out.push(solid(id, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, chord / 2, halfWidth + sagitta,
        Math.atan2(b[1] - a[1], b[0] - a[0]), zMin, zMax));
    }
    return out;
  }

  function twistSolids(catalog, rail, spec, unit, width) {
    const raw = catalog.special_rails?.[rail.rail_type] || {};
    const rimRaw = raw.funnel_rim_diameter_cm ?? 23;
    const rim = Number(typeof rimRaw === "object" ? (rimRaw.value ?? 23) : rimRaw);
    const center = spec.holes_cm[spec.holes_cm.length - 1];
    const chuteEnd = center - rim / 2;
    const z0 = Number(rail.z_units) * unit;
    const top = spec.hole_levels.length ? spec.hole_levels[0] : 3;
    const flatEnd = spec.holes_cm[spec.holes_cm.length - 2] + width / 2;
    let out = stripSolids(catalog, rail, spec, 0, flatEnd, width / 2, z0 + top * unit, z0 + (top + 1) * unit, rail.id);
    const pieces = 4;
    for (let i = 0; i < pieces; i++) {
      const s0 = flatEnd + (chuteEnd - flatEnd) * i / pieces;
      const s1 = flatEnd + (chuteEnd - flatEnd) * (i + 1) / pieces;
      const dropHi = (s1 - flatEnd) / (chuteEnd - flatEnd);
      const dropLo = (s0 - flatEnd) / (chuteEnd - flatEnd);
      out = out.concat(stripSolids(catalog, rail, spec, s0, s1, width / 2,
        z0 + (top - dropHi) * unit, z0 + (top + 1 - dropLo) * unit, rail.id));
    }
    const [cx, cy, heading] = pose(catalog, rail, center);
    out.push(solid(rail.id, cx, cy, rim / 2, rim / 2, heading, z0, z0 + top * unit));
    return out;
  }

  function railSolids(catalog, rail) {
    const spec = railSpec(catalog, rail.rail_type);
    if (!spec) return [];
    const unit = geometry(catalog, "height_unit", 1.5);
    const width = geometry(catalog, "rail_width_cm", 4.5);
    if (spec.shape === "twist") return twistSolids(catalog, rail, spec, unit, width);
    const z = Number(rail.z_units);
    return stripSolids(catalog, rail, spec, 0, spec.length_cm, width / 2, z * unit, (z + spec.height_units) * unit, rail.id);
  }

  function partBodyHeightCm(catalog, type, unit) {
    const found = findPart(catalog, type);
    if (found) {
      const body = value(found[1].body_height_cm);
      if (body != null) return body;
    }
    const h = heightUnits(catalog, type);
    return h == null ? null : h * unit;
  }

  function componentSolids(layout, catalog) {
    const unit = geometry(catalog, "height_unit", 1.5);
    const fp = catalog.geometry_cm?.standard_block_footprint;
    const width = fp && typeof fp === "object" ? Number(fp.width_cm ?? 4.5) : 4.5;
    const depth = fp && typeof fp === "object" ? Number(fp.depth_cm ?? 4.5) : 4.5;
    let out = [];
    for (const rail of layout.rails || []) out = out.concat(railSolids(catalog, rail));
    for (const part of layout.parts || []) {
      const h = partBodyHeightCm(catalog, part.part_type, unit);
      if (h == null) continue;
      const z = Number(part.z_units) * unit;
      const fpPart = findPart(catalog, part.part_type)?.[1]?.footprint_cm;
      const [hx, hy] = fpPart && fpPart.length != null
        ? [Number(fpPart.length) / 2, Number(fpPart.width) / 2] : [width / 2, depth / 2];
      out.push(solid(part.id, Number(part.x_cm), Number(part.y_cm), hx, hy,
        Number(part.rotation_deg || 0) * Math.PI / 180, z, z + h));
    }
    return out;
  }

  function axes(s) {
    const c = Math.cos(s.angle), n = Math.sin(s.angle);
    return [[c, n], [-n, c]];
  }

  function projectionRadius(s, axis) {
    const [[ux, uy], [vx, vy]] = axes(s);
    return s.hx * Math.abs(ux * axis[0] + uy * axis[1]) + s.hy * Math.abs(vx * axis[0] + vy * axis[1]);
  }

  function penetration(a, b) {
    const zOverlap = Math.min(a.zMax, b.zMax) - Math.max(a.zMin, b.zMin);
    if (zOverlap <= 0) return zOverlap;
    const dx = b.cx - a.cx, dy = b.cy - a.cy;
    let smallest = zOverlap;
    for (const axis of [...axes(a), ...axes(b)]) {
      const distance = Math.abs(dx * axis[0] + dy * axis[1]);
      smallest = Math.min(smallest, projectionRadius(a, axis) + projectionRadius(b, axis) - distance);
      if (smallest <= 0) return smallest;
    }
    return smallest;
  }

  function solidCollisions(layout, catalog, tolerance = 0.05) {
    const solids = componentSolids(layout, catalog);
    const reasons = new Set();
    for (let i = 0; i < solids.length; i++) {
      for (let j = i + 1; j < solids.length; j++) {
        const a = solids[i], b = solids[j];
        if (a.id === b.id) continue;
        if (penetration(a, b) > tolerance) {
          const [first, second] = [a.id, b.id].sort();
          reasons.add("solid_collision:" + first + ":" + second);
        }
      }
    }
    return [...reasons].sort();
  }

  function railNodeLocalX(port, spec) {
    if (port === "end_a") return 0;
    if (port === "end_b") return spec.length_cm;
    if (port.startsWith("hole:")) {
      const i = Number(port.slice(5));
      if (i >= 0 && i < spec.holes_cm.length) return spec.holes_cm[i];
    }
    return null;
  }

  function marbleClearanceConflicts(layout, catalog, reachableNodes, marble = 1.6, tolerance = 0.05) {
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const reached = new Map();
    for (const node of reachableNodes) {
      const colon = node.indexOf(":");
      const rail = rails.get(colon < 0 ? node : node.slice(0, colon));
      if (!rail) continue;
      const spec = railSpec(catalog, rail.rail_type);
      if (!spec) continue;
      const x = railNodeLocalX(colon < 0 ? "" : node.slice(colon + 1), spec);
      if (x == null) continue;
      // Per stretch: a pivot rail (collector or seesaw) has one on each side.
      let sides = [0];
      const k = rail.flow_hole;
      if ((rail.flow_direction === "to_hole" || rail.flow_direction === "from_hole") && k != null &&
          Number(k) >= 0 && Number(k) < spec.holes_cm.length) {
        const pivot = spec.holes_cm[Number(k)];
        sides = [[-1, x <= pivot + 1e-6], [1, x >= pivot - 1e-6]].filter(([, keep]) => keep).map(([s]) => s);
      }
      for (const side of sides) {
        const key = rail.id + "\u0000" + side;
        if (!reached.has(key)) reached.set(key, []);
        reached.get(key).push(x);
      }
    }
    const solids = componentSolids(layout, catalog);
    const unit = geometry(catalog, "height_unit", 1.5);
    const reasons = [];
    // Python sorts (rail_id, side) tuples.
    const keys = [...reached.keys()].sort((a, b) => {
      const [ra, sa] = a.split("\u0000"), [rb, sb] = b.split("\u0000");
      return ra < rb ? -1 : ra > rb ? 1 : Number(sa) - Number(sb);
    });
    for (const key of keys) {
      const railId = key.split("\u0000")[0];
      const xs = reached.get(key);
      const start = Math.min(...xs), end = Math.max(...xs);
      const rail = rails.get(railId);
      const spec = railSpec(catalog, rail.rail_type);
      if (end - start <= 0 || spec.shape === "twist") continue;
      const top = (Number(rail.z_units) + spec.height_units) * unit;
      const corridor = stripSolids(catalog, rail, spec, start, end, marble / 2, top, top + marble, railId + "#marble");
      for (const s of solids) {
        if (s.id === railId) continue;
        if (corridor.some(piece => penetration(piece, s) > tolerance)) {
          reasons.push("marble_path_blocked:" + railId + ":" + s.id);
        }
      }
    }
    return unique(reasons);
  }

  // ---- assembly.py --------------------------------------------------------------

  function validateAssembly(layout, catalog, xyTol = 1e-3, zTol = 1e-6) {
    const reasons = [];
    const warnings = [];
    const railsList = layout.rails || [], partsList = layout.parts || [];
    const ids = [...railsList.map(r => r.id), ...partsList.map(p => p.id)];
    if (ids.length !== new Set(ids).size) reasons.push("duplicate_component_id");
    const rails = new Map(railsList.map(r => [r.id, r]));
    const parts = new Map(partsList.map(p => [p.id, p]));

    for (const rail of railsList) {
      const spec = railSpec(catalog, rail.rail_type);
      if (!spec) {
        reasons.push("unknown_rail_type:" + rail.id + ":" + rail.rail_type);
        continue;
      }
      const flow = rail.flow_direction ?? "a_to_b";
      if (!["a_to_b", "b_to_a", "to_hole", "from_hole"].includes(flow)) {
        reasons.push("invalid_flow_direction:" + rail.id + ":" + flow);
      } else if ((flow === "to_hole" || flow === "from_hole") &&
          !(rail.flow_hole != null && Number.isInteger(Number(rail.flow_hole)) &&
            Number(rail.flow_hole) >= 0 && Number(rail.flow_hole) < spec.holes_cm.length)) {
        reasons.push("invalid_flow_hole:" + rail.id + ":" + (rail.flow_hole == null ? "None" : rail.flow_hole));
      }
      for (const [idx, state] of holeEntries(rail)) {
        if (!(idx >= 0 && idx < spec.holes_cm.length)) reasons.push("invalid_hole_index:" + rail.id + ":" + idx);
        if (!HOLE_STATES.has(state)) reasons.push("invalid_hole_state:" + rail.id + ":" + idx + ":" + state);
      }
    }

    for (const part of partsList) {
      if (!hasPart(catalog, part.part_type)) {
        reasons.push("unknown_part_type:" + part.id + ":" + part.part_type);
        continue;
      }
      const rotations = allowedRotations(catalog, part.part_type);
      const rot = Math.trunc(Number(part.rotation_deg || 0));
      if (rotations && !rotations.includes(((rot % 360) + 360) % 360)) {
        reasons.push("invalid_rotation:" + part.id + ":" + rot);
      }
    }

    const used = new Map();
    const supportsByUpper = new Map(railsList.map(r => [r.id, []]));
    const foundationUsage = new Map();

    (layout.supports || []).forEach((support, i) => {
      const label = support.name || "support_" + i;
      if (support.upper_rail_id == null) {
        reasons.push(...freeStackReasons(support, label, layout, catalog, used, xyTol, zTol, rails, parts));
        return;
      }
      const upper = rails.get(support.upper_rail_id);
      if (!upper) {
        reasons.push("unknown_upper_rail:" + label + ":" + support.upper_rail_id);
        return;
      }
      const upperSpec = railSpec(catalog, upper.rail_type);
      if (!upperSpec) return;
      const uh = Number(support.upper_hole_index);
      if (!(uh >= 0 && uh < upperSpec.holes_cm.length)) {
        reasons.push("invalid_upper_hole:" + label + ":" + support.upper_hole_index);
        return;
      }
      supportsByUpper.get(upper.id).push(uh);
      const [ux, uy] = railHoleWorld(catalog, upper, uh);
      let baseZ, isGround;
      if (support.lower_rail_id == null) {
        if (support.lower_hole_index != null) reasons.push("ground_support_has_lower_hole:" + label);
        baseZ = 0;
        isGround = true;
      } else {
        const lower = rails.get(support.lower_rail_id);
        if (!lower) {
          reasons.push("unknown_lower_rail:" + label + ":" + support.lower_rail_id);
          return;
        }
        if (support.lower_hole_index == null) {
          reasons.push("missing_lower_hole:" + label);
          return;
        }
        const lowerSpec = railSpec(catalog, lower.rail_type);
        const lh = Number(support.lower_hole_index);
        if (!(lh >= 0 && lh < lowerSpec.holes_cm.length)) {
          reasons.push("invalid_lower_hole:" + label + ":" + support.lower_hole_index);
          return;
        }
        const [lx, ly] = railHoleWorld(catalog, lower, lh);
        if (Math.hypot(ux - lx, uy - ly) > xyTol) {
          reasons.push("support_xy_mismatch:" + label + ":upper=(" + g6(ux) + "," + g6(uy) + "):lower=(" +
            g6(lx) + "," + g6(ly) + ")");
        }
        baseZ = Number(lower.z_units) + holeLevel(lowerSpec, lh) + lowerSpec.height_units;
        isGround = false;
      }
      let expected = baseZ;
      (support.stack_part_ids || []).forEach((partId, stackIndex) => {
        const part = parts.get(partId);
        if (!part) {
          reasons.push("unknown_stack_part:" + label + ":" + partId);
          return;
        }
        if (used.has(partId)) reasons.push("stack_part_reused:" + partId + ":" + used.get(partId) + ":" + label);
        else used.set(partId, label);
        const h = heightUnits(catalog, part.part_type);
        if (h == null) {
          reasons.push("unknown_stack_height:" + label + ":" + partId + ":" + part.part_type);
          return;
        }
        if (Math.hypot(Number(part.x_cm) - ux, Number(part.y_cm) - uy) > xyTol) {
          reasons.push("stack_xy_mismatch:" + label + ":" + partId);
        }
        if (Math.abs(Number(part.z_units) - expected) > zTol) {
          reasons.push("stack_z_mismatch:" + label + ":" + partId + ":expected=" + g6(expected) +
            ":actual=" + g6(part.z_units));
        }
        if (part.part_type === "wooden_foundation") {
          foundationUsage.set(partId, [isGround, stackIndex]);
          if (!isGround || stackIndex !== 0) reasons.push("foundation_not_ground_base:" + label + ":" + partId);
        }
        expected += h;
      });
      const upperZ = Number(upper.z_units) + holeLevel(upperSpec, uh);
      if (Math.abs(upperZ - expected) > zTol) {
        reasons.push("upper_rail_z_mismatch:" + label + ":" + upper.id + ":expected=" + g6(expected) +
          ":actual=" + g6(upperZ));
      }
      if (isGround && !(support.stack_part_ids || []).length) {
        warnings.push("rail_directly_on_ground:" + label + ":" + upper.id);
      }
    });

    for (const [railId, holes] of supportsByUpper) {
      const uniq = [...new Set(holes)].sort((a, b) => a - b);
      if (uniq.length < 2) {
        reasons.push("insufficient_support_points:" + railId + ":" + uniq.length);
        continue;
      }
      const spec = railSpec(catalog, rails.get(railId).rail_type);
      const accepted = new Set(supportPairs(spec).map(p => p.join(",")));
      const local = uniq.map(i => spec.holes_cm[i]);
      let ok = false;
      for (let a = 0; a < local.length && !ok; a++) {
        for (let b = a + 1; b < local.length && !ok; b++) {
          ok = accepted.has([Math.min(local[a], local[b]), Math.max(local[a], local[b])].join(","));
        }
      }
      if (!ok) reasons.push("no_stable_support_pair:" + railId);
    }

    for (const rail of railsList) {
      const spec = railSpec(catalog, rail.rail_type);
      if (spec && spec.shape === "twist" && (holeState(rail, spec.holes_cm.length - 1) ?? "open") === "covered") {
        reasons.push("twist_center_hole_covered:" + rail.id);
      }
    }

    const loaded = new Set((layout.supports || [])
      .filter(s => s.lower_rail_id && (s.stack_part_ids || []).length).map(s => s.lower_rail_id));
    for (const rail of railsList) {
      const spec = railSpec(catalog, rail.rail_type);
      if (spec && spec.needs_load_above && !loaded.has(rail.id)) reasons.push("curve_needs_load_above:" + rail.id);
    }

    for (const part of partsList) {
      if (part.part_type === "wooden_foundation" && !foundationUsage.has(part.id)) {
        reasons.push("unused_or_elevated_foundation:" + part.id);
      }
    }

    reasons.push(...seesawReasons(layout, catalog));
    reasons.push(...solidCollisions(layout, catalog));
    return { valid: reasons.length === 0, reasons: unique(reasons), warnings: unique(warnings) };
  }

  // Mirror of assembly._seesaw_reasons.
  function seesawReasons(layout, catalog) {
    const reasons = [];
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const holder = new Map();
    for (const s of layout.supports || []) for (const pid of s.stack_part_ids || []) holder.set(pid, s);
    for (const part of layout.parts || []) {
      const spec = findPart(catalog, part.part_type)?.[1];
      if (!spec || spec.shape !== "seesaw") continue;
      const support = holder.get(part.id);
      if (!support || support.upper_rail_id != null || (support.stack_part_ids || []).length !== 1) {
        reasons.push("seesaw_must_stand_alone_on_a_rail:" + part.id);
        continue;
      }
      const host = support.lower_rail_id != null ? rails.get(support.lower_rail_id) : null;
      const mount = spec.mount || {};
      if (!host || !(mount.rails || []).includes(host.rail_type) || support.lower_hole_index !== mount.hole) {
        reasons.push("seesaw_needs_center_hole:" + part.id);
        continue;
      }
      const turn = (((Number(part.rotation_deg || 0) - Number(host.yaw_deg || 0)) % 180) + 180) % 180;
      if (Math.min(turn, 180 - turn) > 0.5) reasons.push("seesaw_not_along_rail:" + part.id + ":" + host.id);
      if (host.flow_direction !== "from_hole" || Number(host.flow_hole) !== Number(support.lower_hole_index) ||
          host.flow_hole == null) {
        reasons.push("seesaw_rail_must_flow_outward:" + part.id + ":" + host.id);
      }
    }
    return reasons;
  }

  function freeStackReasons(support, label, layout, catalog, used, xyTol, zTol, rails, parts) {
    const reasons = [];
    const lower = support.lower_rail_id != null ? rails.get(support.lower_rail_id) : null;
    if (!lower || !(support.stack_part_ids || []).length) return ["free_stack_needs_lower_rail:" + label];
    const spec = railSpec(catalog, lower.rail_type);
    const hole = support.lower_hole_index;
    if (!spec || hole == null || !(Number(hole) >= 0 && Number(hole) < spec.holes_cm.length)) {
      return ["invalid_lower_hole:" + label + ":" + (hole == null ? "None" : hole)];
    }
    const [x, y] = railHoleWorld(catalog, lower, Number(hole));
    let expected = Number(lower.z_units) + holeLevel(spec, Number(hole)) + spec.height_units;
    for (const partId of support.stack_part_ids) {
      const part = parts.get(partId);
      if (!part) {
        reasons.push("unknown_stack_part:" + label + ":" + partId);
        continue;
      }
      if (used.has(partId)) reasons.push("stack_part_reused:" + partId + ":" + used.get(partId) + ":" + label);
      else used.set(partId, label);
      const h = heightUnits(catalog, part.part_type);
      if (h == null) {
        reasons.push("unknown_stack_height:" + label + ":" + partId + ":" + part.part_type);
        continue;
      }
      if (Math.hypot(Number(part.x_cm) - x, Number(part.y_cm) - y) > xyTol) {
        reasons.push("stack_xy_mismatch:" + label + ":" + partId);
      }
      if (Math.abs(Number(part.z_units) - expected) > zTol) {
        reasons.push("stack_z_mismatch:" + label + ":" + partId + ":expected=" + g6(expected) +
          ":actual=" + g6(part.z_units));
      }
      if (part.part_type === "wooden_foundation") reasons.push("foundation_not_ground_base:" + label + ":" + partId);
      expected += h;
    }
    return reasons;
  }

  // ---- layout_stability.py ------------------------------------------------------

  function cross(o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }

  function convexHull(points) {
    const seen = new Map();
    for (const p of points) seen.set(p[0] + "," + p[1], p);
    const pts = [...seen.values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (pts.length <= 1) return pts;
    const lower = [];
    for (const p of pts) {
      while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
      lower.push(p);
    }
    const upper = [];
    for (const p of [...pts].reverse()) {
      while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
      upper.push(p);
    }
    return [...lower.slice(0, -1), ...upper.slice(0, -1)];
  }

  function distPointSegment(p, a, b) {
    const vx = b[0] - a[0], vy = b[1] - a[1];
    const wx = p[0] - a[0], wy = p[1] - a[1];
    const vv = vx * vx + vy * vy;
    if (vv <= 1e-18) return Math.hypot(p[0] - a[0], p[1] - a[1]);
    const t = Math.max(0, Math.min(1, (wx * vx + wy * vy) / vv));
    return Math.hypot(p[0] - (a[0] + t * vx), p[1] - (a[1] + t * vy));
  }

  function supportMargin(point, hull, tol) {
    if (!hull.length) return [false, -Infinity];
    if (hull.length === 1) {
      const d = Math.hypot(point[0] - hull[0][0], point[1] - hull[0][1]);
      return [d <= tol, d <= tol ? 0 : -d];
    }
    if (hull.length === 2) {
      const d = distPointSegment(point, hull[0], hull[1]);
      return [d <= tol, d <= tol ? 0 : -d];
    }
    const margins = [];
    hull.forEach((a, i) => {
      const b = hull[(i + 1) % hull.length];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len > 1e-18) margins.push(cross(a, b, point) / len);
    });
    const margin = margins.length ? Math.min(...margins) : -Infinity;
    return [margin >= -tol, margin];
  }

  function globalStability(layout, catalog, tol = 1e-6) {
    let wx = 0, wy = 0, wz = 0, total = 0;
    const reasons = [];
    for (const rail of layout.rails || []) {
      const spec = railSpec(catalog, rail.rail_type);
      if (!spec) { reasons.push("unknown_rail:" + rail.id + ":" + rail.rail_type); continue; }
      if (spec.mass_g == null) { reasons.push("unknown_mass:" + rail.id + ":" + rail.rail_type); continue; }
      const com = spec.com_cm != null ? spec.com_cm : spec.length_cm / 2;
      const [x, y] = pose(catalog, rail, com);
      const z = Number(rail.z_units) + spec.height_units / 2;
      total += spec.mass_g; wx += spec.mass_g * x; wy += spec.mass_g * y; wz += spec.mass_g * z;
    }
    for (const part of layout.parts || []) {
      const mass = massG(catalog, part.part_type);
      if (mass == null) { reasons.push("unknown_mass:" + part.id + ":" + part.part_type); continue; }
      const h = heightUnits(catalog, part.part_type) || 0;
      total += mass; wx += mass * Number(part.x_cm); wy += mass * Number(part.y_cm);
      wz += mass * (Number(part.z_units) + h / 2);
    }
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const ground = [];
    for (const s of layout.supports || []) {
      if (s.lower_rail_id != null) continue;
      const upper = rails.get(s.upper_rail_id);
      if (!upper || !railSpec(catalog, upper.rail_type)) continue;
      try {
        const [x, y] = railHoleWorld(catalog, upper, Number(s.upper_hole_index));
        ground.push([x, y]);
      } catch (e) { /* invalid hole: skipped as in Python */ }
    }
    const hull = convexHull(ground);
    if (total <= 0) {
      reasons.push("no_known_mass");
      return { evaluable: false, stable: false, total_mass_g: 0, com_xyz_cm: null, support_polygon_xy_cm: hull,
        margin_cm: null, reasons: unique(reasons) };
    }
    const com = [wx / total, wy / total, wz / total];
    if (!hull.length) reasons.push("no_ground_support_points");
    if (reasons.some(r => r.startsWith("unknown_mass:")) || !hull.length) {
      return { evaluable: false, stable: false, total_mass_g: total, com_xyz_cm: com, support_polygon_xy_cm: hull,
        margin_cm: null, reasons: unique(reasons) };
    }
    const [stable, margin] = supportMargin([com[0], com[1]], hull, tol);
    if (!stable) reasons.push("global_tipping:com=(" + g6(com[0]) + "," + g6(com[1]) + ")");
    return { evaluable: true, stable, total_mass_g: total, com_xyz_cm: com, support_polygon_xy_cm: hull,
      margin_cm: margin, reasons: unique(reasons) };
  }

  // ---- statics.py ---------------------------------------------------------------

  const weightN = mass => mass / 1000 * GRAVITY;

  function analyzeStructure(bodies) {
    const ids = Object.keys(bodies);
    if (!ids.length) return { valid: true, rails: {}, ground_reactions: [], total_ground_force_n: 0, reasons: [] };
    for (const id of ids) {
      const rail = bodies[id];
      const com = rail.com_cm == null ? rail.length_cm / 2 : rail.com_cm;
      if (!(com >= 0 && com <= rail.length_cm)) throw new Error(id + ": com_cm outside rail");
      const xs = rail.supports.map(s => s.x_cm);
      if (!xs.every(x => x >= 0 && x <= rail.length_cm)) throw new Error(id + ": support outside rail");
      if (Math.abs(xs[0] - xs[1]) <= 1e-12) throw new Error(id + ": supports must be at distinct positions");
      for (const p of rail.point_masses) {
        if (!(p.x_cm >= 0 && p.x_cm <= rail.length_cm)) throw new Error(id + ": point mass " + p.name + " outside rail");
      }
    }
    const parentsByChild = Object.fromEntries(ids.map(k => [k, new Set()]));
    const childrenByParent = Object.fromEntries(ids.map(k => [k, new Set()]));
    for (const rail of Object.values(bodies)) {
      for (const s of rail.supports) {
        if (s.target_id == null) continue;
        if (!(s.target_id in bodies)) throw new Error(rail.id + ": unknown support target " + s.target_id);
        if (!(s.target_x_cm >= 0 && s.target_x_cm <= bodies[s.target_id].length_cm)) {
          throw new Error(rail.id + ": target coordinate outside " + s.target_id);
        }
        parentsByChild[rail.id].add(s.target_id);
        childrenByParent[s.target_id].add(rail.id);
      }
    }
    const remaining = Object.fromEntries(ids.map(k => [k, childrenByParent[k].size]));
    const ready = ids.filter(k => remaining[k] === 0).sort();
    const incoming = Object.fromEntries(ids.map(k => [k, []]));
    const solved = {};
    const ground = [];
    const reasons = [];
    while (ready.length) {
      const id = ready.shift();
      const rail = bodies[id];
      const loads = [];
      const com = rail.com_cm == null ? rail.length_cm / 2 : rail.com_cm;
      const self = weightN(rail.mass_g);
      if (self > 0) loads.push({ source: id + ":self", x_cm: com, force_n: self });
      for (const p of rail.point_masses) {
        const f = weightN(p.mass_g);
        if (f > 0) loads.push({ source: id + ":point:" + p.name, x_cm: p.x_cm, force_n: f });
      }
      loads.push(...incoming[id]);
      const totalForce = loads.reduce((a, l) => a + l.force_n, 0);
      const effective = totalForce <= 0 ? com : loads.reduce((a, l) => a + l.force_n * l.x_cm, 0) / totalForce;
      const [s0, s1] = rail.supports;
      const [left, right] = s0.x_cm <= s1.x_cm ? [s0, s1] : [s1, s0];
      const span = right.x_cm - left.x_cm;
      let leftR = 0, rightR = 0;
      if (totalForce > 0) {
        rightR = loads.reduce((a, l) => a + l.force_n * (l.x_cm - left.x_cm), 0) / span;
        leftR = totalForce - rightR;
      }
      const margin = Math.min(effective - left.x_cm, right.x_cm - effective);
      const stable = leftR >= -1e-9 && rightR >= -1e-9;
      if (!stable) {
        reasons.push("tipping:" + id + ":com=" + g6(effective) + ":supports=" + g6(left.x_cm) + "," + g6(right.x_cm));
      }
      const reactions = [];
      for (const [support, reaction] of [[left, leftR], [right, rightR]]) {
        const transferred = Math.max(0, reaction) + weightN(support.transfer_mass_g);
        reactions.push({ support, force_n: reaction, transmitted_force_n: transferred });
        if (support.target_id == null) {
          ground.push({ source_rail_id: id, support_name: support.name, force_n: transferred });
        } else {
          incoming[support.target_id].push({ source: id + ":" + (support.name || "support"),
            x_cm: support.target_x_cm, force_n: transferred });
        }
      }
      solved[id] = {
        rail_id: id, total_force_n: totalForce, equivalent_mass_g: totalForce / GRAVITY * 1000,
        effective_com_cm: effective, support_span_cm: span, stability_margin_cm: margin,
        normalized_margin: margin / (span / 2), stable, reactions, applied_loads: loads,
      };
      for (const parent of parentsByChild[id]) {
        remaining[parent] -= 1;
        if (remaining[parent] === 0) { ready.push(parent); ready.sort(); }
      }
    }
    if (Object.keys(solved).length !== ids.length) {
      reasons.push("support_cycle:" + ids.filter(k => !(k in solved)).sort().join(","));
    }
    return {
      valid: Object.keys(solved).length === ids.length && Object.values(solved).every(x => x.stable),
      rails: solved, ground_reactions: ground,
      total_ground_force_n: ground.reduce((a, x) => a + x.force_n, 0), reasons,
    };
  }

  function layoutStatics(layout, catalog) {
    const rails = new Map((layout.rails || []).map(r => [r.id, r]));
    const parts = new Map((layout.parts || []).map(p => [p.id, p]));
    const byUpper = new Map((layout.rails || []).map(r => [r.id, []]));
    const reasons = [];
    for (const s of layout.supports || []) if (byUpper.has(s.upper_rail_id)) byUpper.get(s.upper_rail_id).push(s);
    const points = new Map((layout.rails || []).map(r => [r.id, []]));
    (layout.supports || []).forEach((s, i) => {
      if (s.upper_rail_id != null || !points.has(s.lower_rail_id)) return;
      const lower = rails.get(s.lower_rail_id);
      const spec = railSpec(catalog, lower.rail_type);
      const hole = s.lower_hole_index;
      if (!spec || hole == null || !(Number(hole) >= 0 && Number(hole) < spec.holes_cm.length)) return;
      const masses = (s.stack_part_ids || []).filter(id => parts.has(id)).map(id => massG(catalog, parts.get(id).part_type));
      if (masses.some(m => m == null)) {
        reasons.push("unknown_mass:" + (s.name || "support_" + i));
        return;
      }
      points.get(lower.id).push({ name: s.name || "free_stack_" + i, x_cm: spec.holes_cm[Number(hole)],
        mass_g: masses.reduce((a, b) => a + b, 0) });
    });
    const bodies = {};
    const extra = new Map();
    for (const rail of layout.rails || []) {
      const spec = railSpec(catalog, rail.rail_type);
      if (!spec) { reasons.push("unknown_rail:" + rail.id + ":" + rail.rail_type); continue; }
      if (spec.mass_g == null) { reasons.push("unknown_mass:" + rail.id + ":" + rail.rail_type); continue; }
      const supports = byUpper.get(rail.id) || [];
      if (supports.length < 2) {
        reasons.push("statics_needs_two_supports:" + rail.id + ":" + supports.length);
        continue;
      }
      const converted = [];
      supports.forEach((s, idx) => {
        const uh = Number(s.upper_hole_index);
        if (!(uh >= 0 && uh < spec.holes_cm.length)) {
          reasons.push("invalid_upper_hole:" + rail.id + ":" + s.upper_hole_index);
          return;
        }
        let transfer = 0, known = true;
        for (const pid of s.stack_part_ids || []) {
          const part = parts.get(pid);
          if (!part) { reasons.push("unknown_stack_part:" + rail.id + ":" + pid); known = false; continue; }
          const m = massG(catalog, part.part_type);
          if (m == null) { reasons.push("unknown_mass:" + part.id + ":" + part.part_type); known = false; continue; }
          transfer += m;
        }
        if (!known) return;
        let targetX = null;
        if (s.lower_rail_id != null) {
          const lower = rails.get(s.lower_rail_id);
          if (!lower) { reasons.push("unknown_lower_rail:" + rail.id + ":" + s.lower_rail_id); return; }
          const ls = railSpec(catalog, lower.rail_type);
          const lh = s.lower_hole_index;
          if (!ls || lh == null || !(Number(lh) >= 0 && Number(lh) < ls.holes_cm.length)) {
            reasons.push("invalid_lower_hole:" + rail.id + ":" + s.lower_rail_id);
            return;
          }
          targetX = ls.holes_cm[Number(lh)];
        }
        converted.push({ x_cm: spec.holes_cm[uh], target_id: s.lower_rail_id ?? null, target_x_cm: targetX,
          transfer_mass_g: transfer, name: s.name || rail.id + "_support_" + idx });
      });
      let used = converted;
      if (converted.length > 2 && converted.length === supports.length) {
        // Mirror of layout_stability: outermost two take the rail; a middle
        // column's weight goes down to the rail it stands on.
        const ordered = converted.slice().sort((a, b) => a.x_cm - b.x_cm);
        for (const middle of ordered.slice(1, -1)) {
          if (middle.target_id == null) continue;
          if (!extra.has(middle.target_id)) extra.set(middle.target_id, []);
          extra.get(middle.target_id).push({ name: middle.name, x_cm: middle.target_x_cm, mass_g: middle.transfer_mass_g });
        }
        used = [ordered[0], ordered[ordered.length - 1]];
      }
      if (used.length === 2) {
        bodies[rail.id] = { id: rail.id, length_cm: spec.length_cm, mass_g: spec.mass_g,
          supports: used, com_cm: spec.com_cm, point_masses: points.get(rail.id) || [] };
      }
    }
    for (const [target, masses] of extra) {
      if (bodies[target]) bodies[target] = { ...bodies[target], point_masses: [...bodies[target].point_masses, ...masses] };
    }
    if (reasons.length || Object.keys(bodies).length !== (layout.rails || []).length) {
      return { evaluable: false, statics: null, reasons: unique(reasons) };
    }
    return { evaluable: true, statics: analyzeStructure(bodies), reasons: [] };
  }

  // ---- connectivity.validate_connectivity ---------------------------------------

  function validateConnectivity(layout, catalog, source, sinks) {
    const graph = R.buildGraph(layout, catalog);
    const edges = graph.edges;
    const reasons = [...graph.reasons];
    if (!Object.prototype.hasOwnProperty.call(edges, source)) {
      reasons.push("unknown_source:" + source);
      return { valid: false, reachable: false, source, sinks, reached_sinks: [], reachable_nodes: [],
        dead_ends: [], reasons: unique(reasons), paths: {} };
    }
    for (const s of sinks) if (!Object.prototype.hasOwnProperty.call(edges, s)) reasons.push("unknown_sink:" + s);
    const visited = new Set([source]);
    const previous = new Map();
    const queue = [source];
    for (let i = 0; i < queue.length; i++) {
      for (const t of edges[queue[i]] || []) {
        if (visited.has(t)) continue;
        visited.add(t);
        previous.set(t, queue[i]);
        queue.push(t);
      }
    }
    const reached = [...new Set(sinks)].filter(s => visited.has(s)).sort();
    const paths = {};
    for (const sink of reached) {
      const nodes = [sink];
      while (nodes[nodes.length - 1] !== source) nodes.push(previous.get(nodes[nodes.length - 1]));
      paths[sink] = nodes.reverse();
    }
    const sinkSet = new Set(sinks);
    const deadEnds = [...visited].filter(n => !(edges[n] || []).length && !sinkSet.has(n)).sort();
    const reachable = reached.length > 0;
    if (!reachable) reasons.push("no_requested_sink_reachable");
    return { valid: reachable && reasons.length === 0, reachable, source, sinks, reached_sinks: reached,
      reachable_nodes: [...visited].sort(), dead_ends: deadEnds, reasons: unique(reasons), paths };
  }

  // ---- validation.validate_layout -----------------------------------------------

  function validateLayout(layout, catalog, { source = null, sinks = [] } = {}) {
    const assembly = validateAssembly(layout, catalog);
    const global = globalStability(layout, catalog);
    let statics;
    try {
      statics = layoutStatics(layout, catalog);
    } catch (error) {  // Python raises here; an editor needs a result instead
      statics = { evaluable: false, statics: null, reasons: ["statics_error:" + error.message] };
    }
    let connectivity = null;
    let clearance = [];
    if (source != null || sinks.length) {
      if (source == null || !sinks.length) throw new Error("connectivity validation requires both source and at least one sink");
      connectivity = validateConnectivity(layout, catalog, source, sinks);
      clearance = marbleClearanceConflicts(layout, catalog, connectivity.reachable_nodes);
    }
    const localValid = statics.evaluable && statics.statics != null && statics.statics.valid;
    return {
      valid: assembly.valid && global.evaluable && global.stable && localValid &&
        (connectivity ? connectivity.valid : true) && clearance.length === 0,
      assembly, global_stability: global, local_statics: statics, connectivity, marble_clearance: clearance,
    };
  }

  return {
    validateLayout, validateAssembly, globalStability, layoutStatics, analyzeStructure,
    validateConnectivity, solidCollisions, marbleClearanceConflicts, componentSolids, penetration,
    railSpec, massG, heightUnits, supportPairs, g6,
  };
});
