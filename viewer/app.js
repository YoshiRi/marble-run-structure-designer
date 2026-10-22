(() => {
  "use strict";

  const DATA_ROOT = window.location.pathname.includes("/viewer/") ? "../" : "./";
  // Defaults mirror catalog/parts.yaml; loaded catalog geometry is authoritative.
  let HEIGHT_SCALE_CM = 1.5;
  let RAIL_WIDTH_CM = 4.5;
  let RAIL_GROOVE_WIDTH_CM = 1.0;
  let RAIL_GROOVE_DEPTH_CM = 0.3; // Provisional until physically measured.
  let BLOCK_WIDTH_CM = 4.5;
  let BLOCK_DEPTH_CM = 4.5;
  let HOLE_DIAMETER_CM = 1.8;
  let BLOCK_PORT_DIAMETER_CM = 1.8; // Provisional until block ports are measured.
  let CONNECTOR_PROTRUSION_CM = 1.0;

  const canvas = document.getElementById("renderCanvas");
  const engine = new BABYLON.Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
  const scene = new BABYLON.Scene(engine);
  scene.clearColor = new BABYLON.Color4(0.055, 0.075, 0.11, 1);

  const camera = new BABYLON.ArcRotateCamera(
    "camera",
    -Math.PI / 3,
    Math.PI / 3.1,
    95,
    new BABYLON.Vector3(25, 10, 0),
    scene
  );
  camera.attachControl(canvas, true);
  camera.wheelDeltaPercentage = 0.02;
  camera.panningSensibility = 80;
  camera.lowerRadiusLimit = 8;
  camera.upperRadiusLimit = 400;

  const light1 = new BABYLON.HemisphericLight("hemi", new BABYLON.Vector3(0.2, 1, 0.1), scene);
  light1.intensity = 0.9;
  const light2 = new BABYLON.DirectionalLight("dir", new BABYLON.Vector3(-0.3, -1, -0.2), scene);
  light2.intensity = 0.55;

  const grid = BABYLON.MeshBuilder.CreateGround("ground", { width: 140, height: 100, subdivisions: 2 }, scene);
  const groundMat = new BABYLON.StandardMaterial("groundMat", scene);
  groundMat.diffuseColor = new BABYLON.Color3(0.12, 0.15, 0.20);
  groundMat.specularColor = BABYLON.Color3.Black();
  grid.material = groundMat;

  const groups = {
    holes: [],
    supports: [],
    route: [],
    com: [],
    polygon: [],
    structure: [],
  };

  // Show the z=0 datum explicitly instead of relying on a plain ground plane.
  // Babylon uses Y as vertical; the grid is slightly above the floor to avoid z-fighting.
  function createGroundLevelGrid() {
    const lines = [];
    for (let x = -70; x <= 70; x += 10) {
      lines.push([
        new BABYLON.Vector3(x, 0.025, -50),
        new BABYLON.Vector3(x, 0.025, 50),
      ]);
    }
    for (let z = -50; z <= 50; z += 10) {
      lines.push([
        new BABYLON.Vector3(-70, 0.025, z),
        new BABYLON.Vector3(70, 0.025, z),
      ]);
    }
    const mesh = BABYLON.MeshBuilder.CreateLineSystem("ground-level-grid", { lines }, scene);
    mesh.color = new BABYLON.Color3(0.25, 0.31, 0.40);
    mesh.alpha = 0.7;
    mesh.isPickable = false;
    return mesh;
  }
  const groundLevelGrid = createGroundLevelGrid();

  let catalog = null;
  let layout = null;
  let routingGraph = null;
  let lastOutcomes = null;
  // Sampled runs for the current input hole: exit node -> count.
  const rollTally = { source: "", counts: new Map(), total: 0 };
  // Animated marbles in flight; cancelled when the layout or input changes.
  const flyingMarbles = [];
  let MARBLE_DIAMETER_CM = 1.6; // Official 16 mm; catalog value is authoritative.
  const MARBLE_SPEED_CM_S = 30;

  const palette = {
    yellow: "#eab308",
    blue: "#2563eb",
    green: "#16a34a",
    cyan: "#06b6d4",
    natural_drop: "#d6b98c",
    red_random_split: "#dc2626",
    red_right_angle: "#b91c1c",
    orange_vertical: "#f97316",
    purple_drop: "#7c3aed",
    wooden_foundation: "#d8c39e",
    accelerator_plate: "#64748b",
    default: "#94a3b8",
    rail: "#c8a66a",
    twist: "#dcc497",
  };

  function clearRendered() {
    for (const list of Object.values(groups)) {
      for (const mesh of list) {
        if (mesh && !mesh.isDisposed()) mesh.dispose();
      }
      list.length = 0;
    }
  }

  function material(name, hex, alpha = 1) {
    const mat = new BABYLON.StandardMaterial(name + Math.random(), scene);
    const c = BABYLON.Color3.FromHexString(hex);
    mat.diffuseColor = c;
    mat.emissiveColor = c.scale(0.08);
    mat.specularColor = new BABYLON.Color3(0.08, 0.08, 0.08);
    mat.alpha = alpha;
    return mat;
  }

  function geometryValue(raw, fallback) {
    const value = Number(raw && typeof raw === "object" ? raw.value : raw);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  }

  function applyCatalogGeometry() {
    const geometry = catalog.geometry_cm || {};
    HEIGHT_SCALE_CM = geometryValue(geometry.height_unit, HEIGHT_SCALE_CM);
    RAIL_WIDTH_CM = geometryValue(geometry.rail_width_cm, RAIL_WIDTH_CM);
    RAIL_GROOVE_WIDTH_CM = geometryValue(geometry.rail_groove_width_cm, RAIL_GROOVE_WIDTH_CM);
    RAIL_GROOVE_DEPTH_CM = geometryValue(geometry.rail_groove_depth_cm, RAIL_GROOVE_DEPTH_CM);
    HOLE_DIAMETER_CM = geometryValue(geometry.rail_hole_diameter_cm, HOLE_DIAMETER_CM);
    BLOCK_PORT_DIAMETER_CM = geometryValue(geometry.block_port_diameter_cm, BLOCK_PORT_DIAMETER_CM);
    MARBLE_DIAMETER_CM = geometryValue(geometry.marble_diameter_cm, MARBLE_DIAMETER_CM);
    BLOCK_WIDTH_CM = geometryValue(geometry.standard_block_footprint?.width_cm, BLOCK_WIDTH_CM);
    BLOCK_DEPTH_CM = geometryValue(geometry.standard_block_footprint?.depth_cm, BLOCK_DEPTH_CM);
    CONNECTOR_PROTRUSION_CM = geometryValue(
      geometry.standard_block_connector_protrusion_cm, CONNECTOR_PROTRUSION_CM
    );
  }

  function massValue(spec) {
    if (!spec || spec.mass_g == null) return null;
    if (typeof spec.mass_g === "number") return spec.mass_g;
    if (typeof spec.mass_g === "object" && spec.mass_g.value != null) return Number(spec.mass_g.value);
    return null;
  }

  function blockMass(partType) {
    const groups = [catalog.routing_blocks, catalog.structural_parts];
    for (const group of groups) {
      const spec = group && group[partType];
      if (!spec) continue;
      const measured = massValue(spec);
      if (measured != null) return measured;
      if (group === catalog.routing_blocks && Number(spec.height || 0) === 4) {
        const fallback = catalog.mass_defaults?.standard_routing_block_g;
        if (typeof fallback === "number") return fallback;
        if (fallback && fallback.value != null) return Number(fallback.value);
      }
    }
    for (const sub of ["routing_affecting", "non_routing"]) {
      const spec = catalog.accessories?.[sub]?.[partType];
      if (spec) return massValue(spec);
    }
    return null;
  }

  // Straight rails come from catalog.rails. Curved rails (catalog.curved_rails)
  // are viewer-only for now: they are presented with the same fields, measured
  // along the centerline arc, plus shape/radius.
  function railSpec(type) {
    const spec = catalog.rails?.[type];
    if (spec) return spec;
    const curved = catalog.curved_rails?.[type];
    if (curved) {
      return {
        ...curved,
        shape: "arc",
        radius_cm: geometryValue(curved.hole_circle_radius_cm, 23),
        length_cm: Number(curved.centerline_length_cm),
        hole_positions_cm: curved.hole_arc_positions_cm || [],
      };
    }
    throw new Error("Unknown rail type: " + type);
  }

  // Point on the rail centerline at distance localX from end A. For a curved
  // rail, x_cm/y_cm is end A, yaw_deg the travel direction there, and
  // turn: left|right (default left) the side the arc bends toward.
  function railPoint(rail, localX) {
    const yaw = (Number(rail.yaw_deg || 0) * Math.PI) / 180;
    const spec = railSpec(rail.rail_type);
    if (spec.shape === "arc") {
      const r = spec.radius_cm;
      const sign = rail.turn === "right" ? -1 : 1;
      const cx = Number(rail.x_cm) - sign * r * Math.sin(yaw);
      const cy = Number(rail.y_cm) + sign * r * Math.cos(yaw);
      const start = Math.atan2(Number(rail.y_cm) - cy, Number(rail.x_cm) - cx);
      const angle = start + sign * Number(localX) / r;
      return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
    }
    return {
      x: Number(rail.x_cm) + Number(localX) * Math.cos(yaw),
      y: Number(rail.y_cm) + Number(localX) * Math.sin(yaw),
    };
  }

  function buildCurvedRailMesh(rail, spec) {
    const heightUnits = Number(spec.height || 1);
    const h = heightUnits * HEIGHT_SCALE_CM;
    const half = RAIL_WIDTH_CM / 2;
    const steps = Math.max(12, Math.ceil(Number(spec.length_cm) / 1.5));
    const path = [];
    for (let i = 0; i <= steps; i++) {
      const p = railPoint(rail, Number(spec.length_cm) * i / steps);
      path.push(world(p.x, p.y, Number(rail.z_units) + heightUnits / 2));
    }
    const shape = [
      new BABYLON.Vector3(-half, -h / 2, 0), new BABYLON.Vector3(half, -h / 2, 0),
      new BABYLON.Vector3(half, h / 2, 0), new BABYLON.Vector3(-half, h / 2, 0),
      new BABYLON.Vector3(-half, -h / 2, 0),
    ];
    const mesh = BABYLON.MeshBuilder.ExtrudeShape("rail-" + rail.id, {
      shape, path, cap: BABYLON.Mesh.CAP_ALL, sideOrientation: BABYLON.Mesh.DOUBLESIDE,
    }, scene);
    mesh.material = material("railMat", palette.rail);
    // Groove line along the top of the arc (schematic, no CSG on curves).
    const groovePath = path.map(v => v.add(new BABYLON.Vector3(0, h / 2 + 0.02, 0)));
    const groove = BABYLON.MeshBuilder.CreateTube("rail-groove-" + rail.id, {
      path: groovePath, radius: Math.min(RAIL_GROOVE_WIDTH_CM, RAIL_WIDTH_CM * 0.9) / 2,
      tessellation: 8,
    }, scene);
    groove.material = material("grooveFallbackMat", "#8b6c45");
    groove.isPickable = false;
    groove.parent = null;
    groups.structure.push(groove);
    return { mesh, cutouts: false, grooveCutout: true };
  }

  // Twist (catalog: special_parts.spiral). Placement: x_cm/y_cm = funnel
  // center (outlet hole), z_units = level the outlet rests on, rotation_deg =
  // direction from the funnel center toward the chute. Viewer-only, schematic.
  function renderTwist(part, spec) {
    const rimD = geometryValue(spec.funnel_rim_diameter_cm, 23);
    const spacing = geometryValue(spec.mount_hole_spacing_cm, 23);
    const overall = geometryValue(spec.overall_length_cm, 36);
    const rise = geometryValue(spec.level_difference_units, 3);
    const unit = HEIGHT_SCALE_CM;
    const z0 = Number(part.z_units);
    const yaw = (Number(part.rotation_deg || 0) * Math.PI) / 180;
    const dir = { x: Math.cos(yaw), y: Math.sin(yaw) };
    const at = (d, zUnits) => world(Number(part.x_cm) + d * dir.x, Number(part.y_cm) + d * dir.y, zUnits);
    const wood = material("twistWoodMat", palette.twist);
    const meshes = [];

    // Funnel: outlet floor 1 unit thick, cone rising to the rim.
    const base = BABYLON.MeshBuilder.CreateCylinder("twist-base-" + part.id, {
      diameter: 4.5, height: unit, tessellation: 32,
    }, scene);
    base.position = at(0, z0 + 0.5);
    const coneHeight = (rise - 1) * unit;
    const cone = BABYLON.MeshBuilder.CreateCylinder("twist-funnel-" + part.id, {
      diameterTop: rimD, diameterBottom: 3.2, height: coneHeight, tessellation: 64,
      cap: BABYLON.Mesh.NO_CAP, sideOrientation: BABYLON.Mesh.DOUBLESIDE,
    }, scene);
    cone.position = at(0, z0 + 1 + (rise - 1) / 2);
    const rim = BABYLON.MeshBuilder.CreateTorus("twist-rim-" + part.id, {
      diameter: rimD, thickness: 0.8, tessellation: 64,
    }, scene);
    rim.position = at(0, z0 + rise);

    // Chute: from the rim to the tip, sloping down toward the funnel.
    const chuteStart = rimD / 2 - 1.0;
    const tip = overall - rimD / 2;
    const chuteLength = tip - chuteStart;
    const chute = BABYLON.MeshBuilder.CreateBox("twist-chute-" + part.id, {
      width: chuteLength, height: unit, depth: 4.5,
    }, scene);
    // Tip rests on the inlet level (z + rise); the funnel end is one unit lower.
    chute.position = at(chuteStart + chuteLength / 2, z0 + rise);
    chute.rotation.y = -yaw;
    chute.rotation.z = Math.atan2(unit, chuteLength);
    for (const mesh of [base, cone, rim, chute]) { mesh.material = wood; meshes.push(mesh); }

    // Spiral groove on the funnel surface: from the chute side of the rim
    // inward to the outlet, so the twist reads as a twist.
    const turns = 2.25;
    const spiral = [];
    for (let i = 0; i <= 160; i++) {
      const t = i / 160;
      const radius = rimD / 2 - 0.9 - t * (rimD / 2 - 0.9 - 1.7);
      const theta = yaw + t * turns * 2 * Math.PI;
      const level = z0 + rise - t * (rise - 1) + 0.04;
      spiral.push(world(Number(part.x_cm) + radius * Math.cos(theta),
        Number(part.y_cm) + radius * Math.sin(theta), level));
    }
    const groove = BABYLON.MeshBuilder.CreateTube("twist-groove-" + part.id, {
      path: spiral, radius: 0.22, tessellation: 6,
    }, scene);
    groove.material = material("twistGrooveMat", "#a57f45");
    groove.isPickable = false;
    groups.structure.push(groove);

    // Mount holes: outlet at the center, inlet near the chute tip.
    const holes = [[0, z0 + 1], [spacing, z0 + rise + 1]];
    for (const [d, zLevel] of holes) {
      const ring = BABYLON.MeshBuilder.CreateTorus("twist-hole-" + part.id + "-" + d, {
        diameter: HOLE_DIAMETER_CM + 0.25, thickness: 0.15, tessellation: 32,
      }, scene);
      ring.position = at(d, zLevel);
      ring.position.y += 0.1;
      ring.material = material("holeRimMat", "#334155");
      groups.holes.push(ring);
    }
    const info = {
      id: part.id, kind: "twist", type: part.part_type, solver_support: "not_yet",
      outlet_level_units: z0, inlet_level_units: z0 + rise,
      funnel_rim_diameter_cm: rimD, mount_hole_spacing_cm: spacing, overall_length_cm: overall,
      geometry_status: "schematic, from user description",
    };
    for (const mesh of meshes) addSelectable(mesh, info);
  }

  function world(xCm, yCm, zUnits) {
    return new BABYLON.Vector3(Number(xCm), Number(zUnits) * HEIGHT_SCALE_CM, Number(yCm));
  }

  function railHoleWorld(rail, index) {
    const spec = railSpec(rail.rail_type);
    const localX = Number(spec.hole_positions_cm[index]);
    const p = railPoint(rail, localX);
    return { x: p.x, y: p.y, z: Number(rail.z_units) };
  }

  function railEndWorld(rail, end) {
    const spec = railSpec(rail.rail_type);
    const p = railPoint(rail, end === "end_b" ? Number(spec.length_cm) : 0);
    return { x: p.x, y: p.y, z: Number(rail.z_units) };
  }

  function addSelectable(mesh, info) {
    mesh.metadata = { selectable: true, info };
    groups.structure.push(mesh);
  }

  function buildRailMesh(rail, spec) {
    const length = Number(spec.length_cm);
    const heightUnits = Number(spec.height || 1);
    const railHeight = heightUnits * HEIGHT_SCALE_CM;
    const center = railPoint(rail, length / 2);
    const box = BABYLON.MeshBuilder.CreateBox("rail-solid-" + rail.id, {
      width: length,
      height: railHeight,
      depth: RAIL_WIDTH_CM,
    }, scene);
    box.material = material("railMat", palette.rail);
    box.rotation.y = -(Number(rail.yaw_deg || 0) * Math.PI) / 180;
    box.position = world(center.x, center.y, Number(rail.z_units) + heightUnits / 2);
    box.computeWorldMatrix(true);

    // Cut a centered longitudinal channel and vertical through-holes.
    // Channel width is measured; the rectangular 0.3 cm depth is provisional.
    // Without CSG, a visible top strip indicates the channel location.
    if (!BABYLON.CSG || typeof BABYLON.CSG.FromMesh !== "function") {
      return { mesh: box, cutouts: false, grooveCutout: false };
    }
    try {
      let solid = BABYLON.CSG.FromMesh(box);
      const grooveDepth = Math.min(RAIL_GROOVE_DEPTH_CM, railHeight * 0.8);
      const groove = BABYLON.MeshBuilder.CreateBox("rail-groove-cutter", {
        width: length + 0.25,
        height: grooveDepth + 0.12,
        depth: Math.min(RAIL_GROOVE_WIDTH_CM, RAIL_WIDTH_CM * 0.9),
      }, scene);
      try {
        groove.rotation.y = box.rotation.y;
        groove.position = world(center.x, center.y, Number(rail.z_units) + heightUnits);
        groove.position.y -= grooveDepth / 2 - 0.06;
        groove.computeWorldMatrix(true);
        solid = solid.subtract(BABYLON.CSG.FromMesh(groove));
      } finally {
        groove.dispose();
      }
      for (const localX of spec.hole_positions_cm || []) {
        const p = railPoint(rail, Number(localX));
        const cutter = BABYLON.MeshBuilder.CreateCylinder("hole-cutter", {
          diameter: HOLE_DIAMETER_CM,
          height: railHeight + 1.0,
          tessellation: 32,
        }, scene);
        try {
          cutter.position = world(p.x, p.y, Number(rail.z_units) + heightUnits / 2);
          cutter.computeWorldMatrix(true);
          solid = solid.subtract(BABYLON.CSG.FromMesh(cutter));
        } finally {
          cutter.dispose();
        }
      }
      const cutMesh = solid.toMesh("rail-" + rail.id, box.material, scene);
      box.dispose();
      return { mesh: cutMesh, cutouts: true, grooveCutout: true };
    } catch (error) {
      console.warn("CSG rail cutouts unavailable; using visible surface markers", error);
      return { mesh: box, cutouts: false, grooveCutout: false };
    }
  }

  function renderRail(rail) {
    const spec = railSpec(rail.rail_type);
    const length = Number(spec.length_cm);
    const heightUnits = Number(spec.height || 1);
    const railHeight = heightUnits * HEIGHT_SCALE_CM;
    const { mesh: railMesh, cutouts, grooveCutout } = spec.shape === "arc"
      ? buildCurvedRailMesh(rail, spec) : buildRailMesh(rail, spec);
    if (!grooveCutout) {
      const centerline = BABYLON.MeshBuilder.CreateBox("rail-groove-marker-" + rail.id, {
        width: length,
        height: 0.025,
        depth: Math.min(RAIL_GROOVE_WIDTH_CM, RAIL_WIDTH_CM * 0.9),
      }, scene);
      centerline.parent = railMesh;
      centerline.position.y = railHeight / 2 + 0.018;
      centerline.material = material("grooveFallbackMat", "#8b6c45");
      centerline.isPickable = false;
    }
    addSelectable(railMesh, {
      id: rail.id,
      kind: "rail",
      type: rail.rail_type,
      mass_g: massValue(spec),
      length_cm: length,
      z_units: rail.z_units,
      yaw_deg: rail.yaw_deg || 0,
      flow_direction: rail.flow_direction || "a_to_b",
      hole_states: rail.hole_states || {},
      hole_positions_cm: spec.hole_positions_cm || [],
      holes_are_cutouts: cutouts,
      center_groove_width_cm: RAIL_GROOVE_WIDTH_CM,
      center_groove_depth_cm: RAIL_GROOVE_DEPTH_CM,
      center_groove_depth_status: "provisional",
      center_groove_is_cutout: grooveCutout,
    });

    const holeColors = {
      open: "#334155",
      covered: "#f59e0b",
      block_connected: "#22d3ee",
      covered_slope: "#fb923c",
    };
    (spec.hole_positions_cm || []).forEach((localX, idx) => {
      const p = railPoint(rail, Number(localX));
      const state = (rail.hole_states || {})[idx] ?? "open";
      const topZ = Number(rail.z_units) + heightUnits;
      const markerInfo = {
        id: rail.id + ":hole:" + idx,
        kind: "rail_hole",
        rail_id: rail.id,
        hole_index: idx,
        local_x_cm: Number(localX),
        state,
        diameter_cm: HOLE_DIAMETER_CM,
        diameter_status: "approximate",
      };

      // A narrow ring remains visible even for genuinely open CSG holes.
      const rim = BABYLON.MeshBuilder.CreateTorus("hole-rim-" + rail.id + "-" + idx, {
        diameter: HOLE_DIAMETER_CM + 0.25,
        thickness: 0.15,
        tessellation: 32,
      }, scene);
      rim.position = world(p.x, p.y, topZ);
      rim.position.y += 0.10;
      rim.material = material("holeRimMat", holeColors[state] || holeColors.open);
      rim.metadata = { selectable: true, info: markerInfo };
      groups.holes.push(rim);

      // Covered holes get a visible cap; open holes remain transparent.
      if (state === "covered" || state === "covered_slope" || !cutouts) {
        const cap = BABYLON.MeshBuilder.CreateCylinder("hole-cap-" + rail.id + "-" + idx, {
          diameter: HOLE_DIAMETER_CM,
          height: 0.10,
          tessellation: 32,
        }, scene);
        cap.position = world(p.x, p.y, topZ);
        cap.position.y += 0.09;
        const capColor = !cutouts && state !== "covered" && state !== "covered_slope"
          ? "#111827"
          : holeColors[state] || holeColors.open;
        cap.material = material("holeCapMat", capColor);
        cap.metadata = { selectable: true, info: markerInfo };
        groups.holes.push(cap);
      }
    });

  }


  // Port directions are in the block's local coordinates. Exit holes are
  // centered; side inlets dropping downward use bottom-edge semicircular notches.
  // Hole diameters and actual internal channels remain provisional.
  function blockPortGeometry(port, heightCm) {
    const halfW = BLOCK_WIDTH_CM / 2;
    const halfD = BLOCK_DEPTH_CM / 2;
    const halfH = heightCm / 2;
    const faces = {
      top:    { normal: [0, 1, 0],  halfExtent: halfH },
      bottom: { normal: [0,-1, 0],  halfExtent: halfH },
      front:  { normal: [0, 0, 1],  halfExtent: halfD },
      rear:   { normal: [0, 0,-1],  halfExtent: halfD },
      right:  { normal: [1, 0, 0],  halfExtent: halfW },
      left:   { normal: [-1,0, 0],  halfExtent: halfW },
    };
    return faces[port] || null;
  }

  function orientPortCylinder(mesh, port) {
    // Babylon cylinders/toruses start with their axis aligned to local Y.
    if (port === "front" || port === "rear") mesh.rotation.x = Math.PI / 2;
    if (port === "left" || port === "right") mesh.rotation.z = Math.PI / 2;
  }

  function blockPortPosition(face, insetCm) {
    return new BABYLON.Vector3(
      face.normal[0] * (face.halfExtent - insetCm),
      face.normal[1] * (face.halfExtent - insetCm),
      face.normal[2] * (face.halfExtent - insetCm)
    );
  }

  function isSideEntryNotch(port, sideEntryNotches) {
    return ["front", "rear", "left", "right"].includes(port)
      && sideEntryNotches.has(port);
  }

  function blockPortCenter(face, port, heightCm, sideEntryNotches) {
    const p = blockPortPosition(face, 0);
    if (isSideEntryNotch(port, sideEntryNotches)) {
      // A full horizontal cylindrical cutter intersects the block only
      // above its bottom plane, producing a semicircular arch at the base.
      p.y = -heightCm / 2 + 0.005;
    } else if (["front", "rear", "left", "right"].includes(port)) {
      // Centered side holes open with their floor one height unit above the
      // installation level (the groove height of a rail at that level).
      p.y = -heightCm / 2 + Math.min(HEIGHT_SCALE_CM, heightCm) + BLOCK_PORT_DIAMETER_CM / 2;
    }
    return p;
  }

  function buildBlockMesh(part, heightCm, ports, sideEntryNotches) {
    // CSG subtracts short blind recesses. This does NOT model internal
    // marble channels or claim that a real block's openings are centered.
    const body = BABYLON.MeshBuilder.CreateBox("part-solid-" + part.id, {
      width: BLOCK_WIDTH_CM,
      height: heightCm,
      depth: BLOCK_DEPTH_CM,
    }, scene);
    body.material = material("partMat", palette[part.part_type] || palette.default);

    if (!ports.length || !BABYLON.CSG || typeof BABYLON.CSG.FromMesh !== "function") {
      return { mesh: body, cutouts: false };
    }
    const depth = Math.min(0.8, heightCm * 0.4);
    try {
      let solid = BABYLON.CSG.FromMesh(body);
      for (const port of ports) {
        const face = blockPortGeometry(port, heightCm);
        if (!face) continue;
        const cutter = BABYLON.MeshBuilder.CreateCylinder("block-port-cutter", {
          diameter: BLOCK_PORT_DIAMETER_CM,
          height: depth,
          tessellation: 32,
        }, scene);
        try {
          cutter.position = blockPortPosition(face, depth / 2 - 0.06);
          if (isSideEntryNotch(port, sideEntryNotches)) {
            cutter.position.y = -heightCm / 2 + 0.005;
          }
          orientPortCylinder(cutter, port);
          cutter.computeWorldMatrix(true);
          solid = solid.subtract(BABYLON.CSG.FromMesh(cutter));
        } finally {
          cutter.dispose();
        }
      }
      const mesh = solid.toMesh("part-" + part.id, body.material, scene);
      body.dispose();
      return { mesh, cutouts: true };
    } catch (error) {
      console.warn("Block port CSG unavailable; using face markers", error);
      return { mesh: body, cutouts: false };
    }
  }

  function renderSemicirclePortMarker(part, mesh, port, face, heightCm, depth, cutouts, info) {
    const radius = BLOCK_PORT_DIAMETER_CM / 2;
    const sideAxis = (port === "front" || port === "rear")
      ? new BABYLON.Vector3(1, 0, 0)
      : new BABYLON.Vector3(0, 0, 1);
    const outward = new BABYLON.Vector3(...face.normal);
    const bottomCenter = blockPortCenter(face, port, heightCm, new Set([port]));
    const pointAt = (angle, inset) => {
      const base = bottomCenter.subtract(outward.scale(inset));
      return base.add(sideAxis.scale(radius * Math.cos(angle)))
        .add(new BABYLON.Vector3(0, radius * Math.sin(angle), 0));
    };
    const count = 32;
    const center = bottomCenter.subtract(outward.scale(cutouts ? depth - 0.10 : -0.055));
    const positions = [center.x, center.y, center.z];
    for (let i = 0; i <= count; i++) {
      const p = pointAt(Math.PI * i / count, cutouts ? depth - 0.10 : -0.055);
      positions.push(p.x, p.y, p.z);
    }
    const indices = [];
    for (let i = 1; i <= count; i++) indices.push(0, i, i + 1);
    const normals = [];
    BABYLON.VertexData.ComputeNormals(positions, indices, normals);
    const disk = new BABYLON.Mesh("block-notch-inner-" + part.id + "-" + port, scene);
    const vertexData = new BABYLON.VertexData();
    vertexData.positions = positions;
    vertexData.indices = indices;
    vertexData.normals = normals;
    vertexData.applyToMesh(disk);
    disk.parent = mesh;
    disk.material = material("blockNotchInnerMat", "#111827");
    disk.material.backFaceCulling = false;
    disk.metadata = { selectable: true, info };
    groups.holes.push(disk);

    const arc = [];
    for (let i = 0; i <= count; i++) {
      arc.push(pointAt(Math.PI * i / count, -0.06));
    }
    const outline = BABYLON.MeshBuilder.CreateLines("block-notch-rim-" + part.id + "-" + port, {
      points: arc,
    }, scene);
    outline.parent = mesh;
    outline.color = BABYLON.Color3.FromHexString("#1e293b");
    outline.metadata = { selectable: true, info };
    groups.holes.push(outline);
  }

  function renderBlockPortMarkers(part, mesh, ports, heightCm, cutouts, sideEntryNotches) {
    const depth = Math.min(0.8, heightCm * 0.4);
    for (const port of ports) {
      const face = blockPortGeometry(port, heightCm);
      if (!face) continue;
      const notch = isSideEntryNotch(port, sideEntryNotches);
      const info = {
        id: part.id + ":port:" + port,
        kind: "block_port",
        part_id: part.id,
        part_type: part.part_type,
        port,
        opening_shape: notch ? "bottom_semicircle" : "centered_circle",
        diameter_cm: BLOCK_PORT_DIAMETER_CM,
        diameter_status: "provisional",
        position_status: notch ? "bottom_edge" : "face_center",
        internal_channel_geometry: "not_modeled",
      };

      if (notch) {
        renderSemicirclePortMarker(part, mesh, port, face, heightCm, depth, cutouts, info);
        continue;
      }

      const rim = BABYLON.MeshBuilder.CreateTorus("block-port-rim-" + part.id + "-" + port, {
        diameter: BLOCK_PORT_DIAMETER_CM + 0.20,
        thickness: 0.11,
        tessellation: 32,
      }, scene);
      rim.parent = mesh;
      rim.position = blockPortPosition(face, -0.035);
      orientPortCylinder(rim, port);
      rim.material = material("blockPortRimMat", "#1e293b");
      rim.metadata = { selectable: true, info };
      groups.holes.push(rim);

      const disk = BABYLON.MeshBuilder.CreateCylinder("block-port-inner-" + part.id + "-" + port, {
        diameter: BLOCK_PORT_DIAMETER_CM * 0.91,
        height: 0.035,
        tessellation: 32,
      }, scene);
      disk.parent = mesh;
      disk.position = blockPortPosition(face, cutouts ? depth - 0.10 : -0.055);
      orientPortCylinder(disk, port);
      disk.material = material("blockPortInnerMat", "#111827");
      disk.metadata = { selectable: true, info };
      groups.holes.push(disk);
    }
  }

  function partSpec(partType) {
    return catalog.routing_blocks?.[partType]
      || catalog.structural_parts?.[partType]
      || catalog.accessories?.routing_affecting?.[partType]
      || catalog.accessories?.non_routing?.[partType]
      || {};
  }

  function partBodyHeightCm(spec, fallbackUnits) {
    return Math.max(
      0.35,
      geometryValue(spec.body_height_cm, Number(fallbackUnits) * HEIGHT_SCALE_CM)
    );
  }

  function partBodyHeightUnits(part) {
    const spec = partSpec(part.part_type);
    const fallbackUnits = Number(spec.height || (part.part_type === "accelerator_plate" ? 0.15 : 1));
    return partBodyHeightCm(spec, fallbackUnits) / HEIGHT_SCALE_CM;
  }

  function renderPart(part) {
    const spec = partSpec(part.part_type);
    const catalogHeightUnits = Number(spec.height || (part.part_type === "accelerator_plate" ? 0.15 : 1));
    const heightCm = partBodyHeightCm(spec, catalogHeightUnits);
    const renderedHeightUnits = heightCm / HEIGHT_SCALE_CM;
    const bottomLevel = Number(part.z_units);
    const topLevel = bottomLevel + renderedHeightUnits;
    const ports = (spec.ports || []).filter(p => blockPortGeometry(p, heightCm));
    const sideEntryNotches = new Set(spec.port_visualization?.side_entry_notches || []);
    const { mesh, cutouts } = buildBlockMesh(part, heightCm, ports, sideEntryNotches);
    mesh.rotation.y = -(Number(part.rotation_deg || 0) * Math.PI) / 180;
    mesh.position = world(part.x_cm, part.y_cm, Number(part.z_units) + renderedHeightUnits / 2);
    addSelectable(mesh, {
      id: part.id,
      kind: "part",
      type: part.part_type,
      mass_g: blockMass(part.part_type),
      z_units: part.z_units,
      bottom_z_units: bottomLevel,
      top_z_units: topLevel,
      bottom_elevation_cm: bottomLevel * HEIGHT_SCALE_CM,
      top_elevation_cm: topLevel * HEIGHT_SCALE_CM,
      touches_ground: Math.abs(bottomLevel) < 0.01,
      rotation_deg: part.rotation_deg || 0,
      body_height_cm: heightCm,
      body_height_units: renderedHeightUnits,
      catalog_height_units: catalogHeightUnits,
      effective_stacking_height_cm: heightCm,
      connector_protrusion_cm: catalogHeightUnits === 4 ? CONNECTOR_PROTRUSION_CM : null,
      connector_protrusion_rendered: false,
      ports,
      port_hole_diameter_cm: BLOCK_PORT_DIAMETER_CM,
      port_geometry_status: "centered_side_exits_and_bottom_semicircle_side_inlets",
      side_entry_notches: [...sideEntryNotches],
      port_holes_are_cutouts: cutouts,
    });
    renderBlockPortMarkers(part, mesh, ports, heightCm, cutouts, sideEntryNotches);
  }

  // Same-type pieces that touch vertically otherwise look like one tall block.
  // Add a subtle joint at the boundary so two 1-unit purple drops read as two parts.
  function renderStackSeams() {
    const parts = layout.parts || [];
    for (const lower of parts) {
      const topUnits = Number(lower.z_units) + partBodyHeightUnits(lower);
      const upper = parts.find(candidate =>
        candidate.id !== lower.id &&
        candidate.part_type === lower.part_type &&
        Math.abs(Number(candidate.x_cm) - Number(lower.x_cm)) < 0.01 &&
        Math.abs(Number(candidate.y_cm) - Number(lower.y_cm)) < 0.01 &&
        Math.abs(Number(candidate.z_units) - topUnits) < 0.01
      );
      if (!upper) continue;
      const x = Number(lower.x_cm);
      const y = Number(lower.y_cm);
      const z = topUnits;
      const halfW = BLOCK_WIDTH_CM / 2;
      const halfD = BLOCK_DEPTH_CM / 2;
      const seamMat = material("partJointMat", "#111827");
      const strips = [
        { width: BLOCK_WIDTH_CM + 0.04, height: 0.035, depth: 0.035, x, y: y + halfD, z },
        { width: BLOCK_WIDTH_CM + 0.04, height: 0.035, depth: 0.035, x, y: y - halfD, z },
        { width: 0.035, height: 0.035, depth: BLOCK_DEPTH_CM + 0.04, x: x + halfW, y, z },
        { width: 0.035, height: 0.035, depth: BLOCK_DEPTH_CM + 0.04, x: x - halfW, y, z },
      ];
      for (const strip of strips) {
        const seam = BABYLON.MeshBuilder.CreateBox("part-joint-" + lower.id + "-" + upper.id, {
          width: strip.width, height: strip.height, depth: strip.depth,
        }, scene);
        seam.position = world(strip.x, strip.y, strip.z);
        seam.material = seamMat;
        seam.isPickable = false;
        groups.structure.push(seam);
      }
    }
  }

  function renderSupports() {
    const railMap = Object.fromEntries((layout.rails || []).map(r => [r.id, r]));
    for (const support of layout.supports || []) {
      const rail = railMap[support.upper_rail_id];
      if (!rail) continue;
      const p = railHoleWorld(rail, Number(support.upper_hole_index));
      let lowerZ = 0;
      if (support.lower_rail_id) {
        const lower = railMap[support.lower_rail_id];
        const lowerSpec = lower ? railSpec(lower.rail_type) : null;
        if (lower && lowerSpec) lowerZ = Number(lower.z_units) + Number(lowerSpec.height || 1);
      }
      const upperZ = Number(rail.z_units);
      const line = BABYLON.MeshBuilder.CreateLines("support-" + (support.name || support.upper_rail_id), {
        points: [world(p.x, p.y, lowerZ), world(p.x, p.y, upperZ)],
      }, scene);
      line.color = BABYLON.Color3.FromHexString("#60a5fa");
      groups.supports.push(line);
    }
  }

  function routingPortKey(ref) {
    if (!ref) return null;
    if (typeof ref === "string") return ref;
    return ref.component_id && ref.port ? ref.component_id + ":" + ref.port : null;
  }

  function routingNodePosition(key) {
    const colon = key.indexOf(":");
    if (colon < 0) return null;
    const componentId = key.slice(0, colon);
    const port = key.slice(colon + 1);
    const rail = (layout.rails || []).find(r => r.id === componentId);
    if (rail && port.startsWith("hole:")) {
      const index = Number(port.slice(5));
      const spec = railSpec(rail.rail_type);
      if (!Number.isInteger(index) || index < 0 ||
          index >= (spec.hole_positions_cm || []).length) return null;
      const p = railHoleWorld(rail, index);
      // The route follows the rail's real central groove, not a side overlay.
      return world(p.x, p.y, Number(rail.z_units) + Number(spec.height || 1) + 0.12 / HEIGHT_SCALE_CM);
    }

    // Use exactly the same port pose as the geometry validator. An unknown
    // catalog port cannot produce a visual marker or a phantom route.
    const pose = MarbleRouting.portPose(layout, catalog, {
      component_id: componentId, port,
    });
    if (!pose) return null;
    const [x, y, z] = pose.position;
    const [nx, ny, nz] = pose.normal;
    const clearance = 0.12;
    return new BABYLON.Vector3(
      x + nx * clearance,
      z + nz * clearance + (rail ? 0.12 : 0),
      y + ny * clearance
    );
  }

  function routingEdgePoints(from, to) {
    const a = routingNodePosition(from);
    const b = routingNodePosition(to);
    if (!a || !b) return null;
    const fromId = from.slice(0, from.indexOf(":"));
    const toId = to.slice(0, to.indexOf(":"));
    if (fromId === toId && (layout.parts || []).some(p => p.id === fromId)) {
      // Actual internal block channels are unknown. Never invent an arc that
      // leaves the block through solid material or cuts across a solid face.
      return null;
    }
    return [a, b];
  }

  function drawRoutingBlockHighlight(partId, color) {
    const part = (layout.parts || []).find(p => p.id === partId);
    if (!part) return;
    const spec = catalog.routing_blocks?.[part.part_type]
      || catalog.special_parts?.[part.part_type];
    if (!spec?.height) return;
    const outline = BABYLON.MeshBuilder.CreateBox("routing-block-outline-" + partId, {
      width: BLOCK_WIDTH_CM + 0.18,
      height: Number(spec.height) * HEIGHT_SCALE_CM + 0.18,
      depth: BLOCK_DEPTH_CM + 0.18,
    }, scene);
    outline.position = world(part.x_cm, part.y_cm,
      Number(part.z_units) + Number(spec.height) / 2);
    outline.rotation.y = -(Number(part.rotation_deg || 0) * Math.PI) / 180;
    outline.material = material("routingBlockOutlineMat", color, 0.9);
    outline.material.wireframe = true;
    outline.isPickable = false;
    groups.route.push(outline);
  }

  function drawRoutingEdge(from, to, color, radius, label) {
    const fromId = from.slice(0, from.indexOf(":"));
    const toId = to.slice(0, to.indexOf(":"));
    if (fromId === toId && (layout.parts || []).some(p => p.id === fromId)) {
      // Internal route = highlighted *existing* ports and a block outline.
      // We deliberately do not draw a physically unverified channel.
      drawRoutingMarker(from, color, radius * 4);
      drawRoutingMarker(to, color, radius * 4);
      if (label === "selected-route") drawRoutingBlockHighlight(fromId, color);
      return;
    }
    const points = routingEdgePoints(from, to);
    if (!points || points.every(p => BABYLON.Vector3.DistanceSquared(p, points[0]) < 0.0001)) return;
    const tube = BABYLON.MeshBuilder.CreateTube(label, {
      path: points, radius, tessellation: 8, cap: BABYLON.Mesh.CAP_ALL,
    }, scene);
    tube.material = material("routingMat", color);
    tube.material.emissiveColor = BABYLON.Color3.FromHexString(color).scale(0.65);
    tube.isPickable = false;
    groups.route.push(tube);
  }

  function drawRoutingMarker(key, color, diameter) {
    const pos = routingNodePosition(key);
    if (!pos) return;
    const marker = BABYLON.MeshBuilder.CreateSphere("routing-marker-" + key, {
      diameter, segments: 12,
    }, scene);
    marker.position = pos;
    marker.material = material("routingMarkerMat", color);
    marker.material.emissiveColor = BABYLON.Color3.FromHexString(color).scale(0.55);
    marker.isPickable = false;
    groups.route.push(marker);
  }

  function clearRoutingMeshes() {
    for (const mesh of groups.route) {
      if (mesh && !mesh.isDisposed()) mesh.dispose();
    }
    groups.route.length = 0;
  }

  function setSelectOptions(select, options, preferred, emptyLabel) {
    select.replaceChildren();
    if (!options.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = emptyLabel;
      select.appendChild(option);
      select.value = "";
      return;
    }
    for (const item of options) {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      select.appendChild(option);
    }
    select.value = options.some(item => item.value === preferred)
      ? preferred : options[0].value;
  }

  // Valid input holes for the current graph; drawn as clickable drop markers.
  let inputHoleCandidates = [];

  function drawInputHoleMarkers(selectedKey) {
    for (const hole of inputHoleCandidates) {
      const base = routingNodePosition(hole.key);
      if (!base) continue;
      const selected = hole.key === selectedKey;
      const color = selected ? "#22c55e" : "#2dd4bf";
      // Downward cone above the hole: "drop the marble here".
      const cone = BABYLON.MeshBuilder.CreateCylinder("input-hole-marker-" + hole.key, {
        diameterTop: selected ? 1.9 : 1.5,
        diameterBottom: 0,
        height: selected ? 2.4 : 1.9,
        tessellation: 20,
      }, scene);
      cone.position = base.add(new BABYLON.Vector3(0, selected ? 2.6 : 2.2, 0));
      cone.material = material(selected ? "inputMarkerSelectedMat" : "inputMarkerMat",
        color, selected ? 1 : 0.55);
      cone.material.emissiveColor = BABYLON.Color3.FromHexString(color).scale(selected ? 0.6 : 0.35);
      cone.metadata = { inputHoleKey: hole.key, info: { ...hole, kind: "input_hole_candidate" } };
      groups.route.push(cone);
    }
  }

  function selectInputHole(key) {
    if (!inputHoleCandidates.some(hole => hole.key === key)) return false;
    const sourceSelect = document.getElementById("routeSource");
    if (sourceSelect.value !== key) {
      sourceSelect.value = key;
      updateRouting();
    }
    return true;
  }

  function updateRollButtons(enabled) {
    for (const id of ["rollOne", "rollOneTop", "rollMany"]) {
      document.getElementById(id).disabled = !enabled;
    }
  }

  function populateRoutingControls() {
    const sourceSelect = document.getElementById("routeSource");
    const sinkSelect = document.getElementById("routeSink");
    const inputHoles = MarbleRouting.listInputHoles(layout, catalog, routingGraph);
    inputHoleCandidates = inputHoles;
    const querySource = routingPortKey(layout.routing_query?.source);
    const sourceOptions = inputHoles.map(hole => ({ value: hole.key, label: hole.label }));
    const preferredSource = sourceOptions.some(item => item.value === querySource)
      ? querySource : sourceOptions[0]?.value;
    setSelectOptions(sourceSelect, sourceOptions, preferredSource, "No valid input holes");
    updateRollButtons(sourceOptions.length > 0);
    setSelectOptions(sinkSelect, [], "", "Select an input hole first");
  }

  function formatPercent(fraction) {
    const percentage = fraction * 100;
    return Math.abs(percentage - Math.round(percentage)) < 0.05
      ? Math.round(percentage) + "%"
      : percentage.toFixed(1) + "%";
  }

  function renderExitProbabilities(outcomes, selectedExit) {
    const container = document.getElementById("exitProbabilities");
    container.replaceChildren();
    if (!outcomes || !outcomes.exits.length) {
      const message = document.createElement("p");
      message.className = "muted small-note";
      message.textContent = outcomes?.complete === false && outcomes.reasons?.some(
        reason => reason.startsWith("unknown_source:")
      ) ? "No valid input hole is selected." : "No external exits are reachable from this input hole.";
      container.appendChild(message);
      if (outcomes?.reasons?.length) {
        const details = document.createElement("p");
        details.className = "muted small-note";
        details.textContent = "Probability unavailable: " + outcomes.reasons.join(", ");
        container.appendChild(details);
      }
      return;
    }

    const note = document.createElement("p");
    note.className = "muted small-note";
    if (!outcomes.complete) {
      note.textContent = "Probability not calculated: the routing graph contains unresolved or unsupported behavior.";
    } else if (outcomes.estimated) {
      note.textContent = "Estimated only: each random branch is temporarily assumed equally likely. This is not a measured physical probability.";
    } else {
      note.textContent = "Deterministic result under the current routing model; this is not a physical-motion simulation.";
    }
    container.appendChild(note);

    const table = document.createElement("table");
    table.className = "exit-table";
    const head = document.createElement("thead");
    const tallyActive = rollTally.total > 0 && rollTally.source === outcomes.source;
    head.innerHTML = "<tr><th>Exit</th><th>Probability</th><th>" +
      (tallyActive ? "Rolled (" + rollTally.total + ")" : "Rolled") + "</th></tr>";
    table.appendChild(head);
    const body = document.createElement("tbody");
    for (const exit of outcomes.exits) {
      const row = document.createElement("tr");
      if (exit.node === selectedExit) row.className = "selected-exit";
      const nameCell = document.createElement("td");
      const selectButton = document.createElement("button");
      selectButton.type = "button";
      selectButton.className = "exit-select";
      selectButton.textContent = exit.label;
      selectButton.addEventListener("click", () => {
        document.getElementById("routeSink").value = exit.node;
        updateRouting();
      });
      nameCell.appendChild(selectButton);
      const probabilityCell = document.createElement("td");
      if (exit.probability == null) {
        probabilityCell.textContent = "Not calculated";
      } else {
        probabilityCell.textContent = (outcomes.estimated ? "≈ " : "") + formatPercent(exit.probability);
      }
      const rolledCell = document.createElement("td");
      rolledCell.className = "rolled";
      const count = tallyActive ? (rollTally.counts.get(exit.node) || 0) : 0;
      rolledCell.textContent = tallyActive
        ? formatPercent(count / rollTally.total) + " · " + count
        : "—";
      row.dataset.exit = exit.node;
      row.append(nameCell, probabilityCell, rolledCell);
      body.appendChild(row);
    }
    table.appendChild(body);
    container.appendChild(table);
    if (!outcomes.complete && outcomes.reasons?.length) {
      const details = document.createElement("p");
      details.className = "muted small-note";
      details.textContent = "Reasons: " + outcomes.reasons.join(", ");
      container.appendChild(details);
    }
  }

  function updateRouting() {
    clearRoutingMeshes();
    const source = document.getElementById("routeSource").value;
    const sinkSelect = document.getElementById("routeSink");
    const status = document.getElementById("routeStatus");
    drawInputHoleMarkers(source);
    if (!routingGraph || !source) {
      lastOutcomes = null;
      setSelectOptions(sinkSelect, [], "", "No reachable exits");
      renderExitProbabilities(null, "");
      status.textContent = "No valid block-connected input hole. Set an input rail hole to block_connected and verify its support.";
      return;
    }

    const outcomes = MarbleRouting.analyzeOutcomes(layout, catalog, routingGraph, source);
    lastOutcomes = outcomes;
    if (rollTally.source !== source) {
      cancelMarbles();
      resetTally(source);
    }
    const querySink = routingPortKey(layout.routing_query?.sinks?.[0]);
    const preferredSink = [sinkSelect.value, querySink].find(candidate =>
      candidate && outcomes.exits.some(exit => exit.node === candidate));
    setSelectOptions(
      sinkSelect,
      outcomes.exits.map(exit => ({ value: exit.node, label: exit.label })),
      preferredSink,
      "No reachable exits",
    );
    const sink = sinkSelect.value;
    renderExitProbabilities(outcomes, sink);
    if (!sink) {
      const lines = [
        "No external exit found from " + source,
        "Graph status: " + (routingGraph.reasons.length ? "invalid / incomplete" : "no reachable terminal output"),
      ];
      if (routingGraph.reasons.length) lines.push("Reasons: " + routingGraph.reasons.join(", "));
      status.textContent = lines.join("\n");
      applyVisibility();
      return;
    }

    const trace = MarbleRouting.trace(routingGraph, source, sink);
    const pathPairs = new Set();
    for (let i = 1; i < trace.path.length; i++) {
      pathPairs.add(JSON.stringify([trace.path[i - 1], trace.path[i]]));
    }
    for (const [from, to] of trace.reachableEdges) {
      if (pathPairs.has(JSON.stringify([from, to]))) continue;
      drawRoutingEdge(from, to, "#38bdf8", 0.07, "reachable-route");
    }
    for (let i = 1; i < trace.path.length; i++) {
      drawRoutingEdge(trace.path[i - 1], trace.path[i], "#4ade80", 0.13, "selected-route");
    }
    drawRoutingMarker(source, "#22c55e", 0.95);
    if (trace.reachable) drawRoutingMarker(sink, "#facc15", 1.0);
    for (const node of trace.deadEnds) drawRoutingMarker(node, "#f87171", 0.8);
    for (const exit of outcomes.exits) {
      if (exit.probability == null) continue;
      drawExitLabel(exit.node,
        (outcomes.estimated ? "≈" : "") + formatPercent(exit.probability),
        exit.node === sink);
    }
    const lines = [
      trace.reachable ? "REACHABLE" : "UNREACHABLE",
      "Graph status: " + (trace.valid ? "valid" : "invalid / incomplete"),
      "Input hole: " + source,
      "Reachable nodes: " + trace.reachableNodes.length,
      "External exits: " + outcomes.exits.length,
      outcomes.complete
        ? "Probability model: " + (outcomes.estimated ? "estimated (uniform random branches)" : "deterministic routing")
        : "Probability model: unavailable (unresolved graph behavior)",
      "Block internals: only actual entry/exit ports are highlighted (channels unknown).",
    ];
    if (layout.routing_options?.allow_side_entry_plus_one) {
      lines.push("Side-drop +1-level connection allowance: enabled.");
    }
    if (trace.path.length) lines.push("Path (" + (trace.path.length - 1) + " edges):\n" +
      trace.path.join(" → "));
    if (trace.deadEnds.length) lines.push("Dead ends: " + trace.deadEnds.join(", "));
    if (trace.reasons.length) lines.push("Reasons: " + trace.reasons.join(", "));
    status.textContent = lines.join("\n");
    applyVisibility();
  }

  // ---- Probability labels at exits -------------------------------------
  function drawExitLabel(nodeKey, text, emphasized) {
    const anchor = routingNodePosition(nodeKey);
    if (!anchor) return;
    const texture = new BABYLON.DynamicTexture("exit-label-tex-" + nodeKey,
      { width: 256, height: 112 }, scene, true);
    texture.hasAlpha = true;
    const ctx = texture.getContext();
    ctx.clearRect(0, 0, 256, 112);
    ctx.fillStyle = emphasized ? "rgba(250, 204, 21, 0.95)" : "rgba(15, 23, 42, 0.82)";
    const r = 22;
    ctx.beginPath();
    ctx.moveTo(r, 4); ctx.lineTo(252 - r, 4); ctx.quadraticCurveTo(252, 4, 252, 4 + r);
    ctx.lineTo(252, 108 - r); ctx.quadraticCurveTo(252, 108, 252 - r, 108);
    ctx.lineTo(r, 108); ctx.quadraticCurveTo(4, 108, 4, 108 - r);
    ctx.lineTo(4, 4 + r); ctx.quadraticCurveTo(4, 4, r, 4); ctx.fill();
    ctx.fillStyle = emphasized ? "#111827" : "#f8fafc";
    ctx.font = "bold 62px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 128, 58);
    texture.update();
    const plane = BABYLON.MeshBuilder.CreatePlane("exit-label-" + nodeKey,
      { width: 6.4, height: 2.8 }, scene);
    plane.position = anchor.add(new BABYLON.Vector3(0, 3.8, 0));
    plane.billboardMode = BABYLON.Mesh.BILLBOARDMODE_ALL;
    const mat = new BABYLON.StandardMaterial("exit-label-mat-" + nodeKey, scene);
    mat.diffuseTexture = texture;
    mat.emissiveColor = BABYLON.Color3.White();
    mat.disableLighting = true;
    mat.useAlphaFromDiffuseTexture = true;
    mat.backFaceCulling = false;
    plane.material = mat;
    plane.isPickable = false;
    plane.renderingGroupId = 1; // Keep labels readable in front of parts.
    groups.route.push(plane);
  }

  // ---- Sampled runs and marble animation --------------------------------
  function resetTally(source) {
    rollTally.source = source;
    rollTally.counts.clear();
    rollTally.total = 0;
  }

  function recordArrival(source, exitNode) {
    if (rollTally.source !== source) return; // Marble from a previous input.
    rollTally.counts.set(exitNode, (rollTally.counts.get(exitNode) || 0) + 1);
    rollTally.total += 1;
    if (lastOutcomes && lastOutcomes.source === source) {
      renderExitProbabilities(lastOutcomes, document.getElementById("routeSink").value);
    }
  }

  function flashExitRow(exitNode) {
    const row = [...document.querySelectorAll("#exitProbabilities tr[data-exit]")]
      .find(item => item.dataset.exit === exitNode);
    if (!row) return;
    row.classList.remove("just-arrived");
    void row.offsetWidth; // Restart the CSS animation.
    row.classList.add("just-arrived");
  }

  // Exit tail: leave the last opening and fall to the ground plane.
  function exitTailPoints(exitNode, last) {
    const radius = MARBLE_DIAMETER_CM / 2;
    const colon = exitNode.indexOf(":");
    const pose = MarbleRouting.portPose(layout, catalog, {
      component_id: exitNode.slice(0, colon), port: exitNode.slice(colon + 1),
    });
    const points = [];
    let p = last;
    if (pose) {
      const [nx, ny] = pose.normal;
      p = last.add(new BABYLON.Vector3(nx * 2.5, 0, ny * 2.5));
      points.push(p);
    }
    points.push(new BABYLON.Vector3(p.x, radius, p.z));
    return points;
  }

  function marblePathPoints(run) {
    const radius = MARBLE_DIAMETER_CM / 2;
    const points = [];
    for (const node of run.path) {
      const pos = routingNodePosition(node);
      if (!pos) continue;
      const lifted = pos.add(new BABYLON.Vector3(0, radius, 0));
      const prev = points[points.length - 1];
      if (!prev || BABYLON.Vector3.DistanceSquared(prev, lifted) > 1e-4) points.push(lifted);
    }
    if (!points.length) return points;
    // Start a little above the input hole so the drop-in is visible.
    points.unshift(points[0].add(new BABYLON.Vector3(0, 4, 0)));
    if (run.exit) points.push(...exitTailPoints(run.exit, points[points.length - 1]));
    return points;
  }

  function launchMarble(source, run) {
    const points = marblePathPoints(run);
    if (points.length < 2) return false;
    const lengths = [0];
    for (let i = 1; i < points.length; i++) {
      lengths.push(lengths[i - 1] + BABYLON.Vector3.Distance(points[i - 1], points[i]));
    }
    const mesh = BABYLON.MeshBuilder.CreateSphere("marble", {
      diameter: MARBLE_DIAMETER_CM, segments: 16,
    }, scene);
    const mat = new BABYLON.StandardMaterial("marbleMat", scene);
    mat.diffuseColor = BABYLON.Color3.FromHexString("#cbd5e1");
    mat.specularColor = new BABYLON.Color3(1, 1, 1);
    mat.specularPower = 64;
    mat.emissiveColor = BABYLON.Color3.FromHexString("#334155");
    mesh.material = mat;
    mesh.isPickable = false;
    mesh.position = points[0].clone();
    flyingMarbles.push({ mesh, points, lengths, travelled: 0, source, run, done: false });
    return true;
  }

  function stepMarbles() {
    if (!flyingMarbles.length) return;
    const dt = Math.min(engine.getDeltaTime() / 1000, 0.1);
    for (const marble of flyingMarbles) {
      marble.travelled += MARBLE_SPEED_CM_S * dt;
      const total = marble.lengths[marble.lengths.length - 1];
      if (marble.travelled >= total) {
        marble.mesh.position = marble.points[marble.points.length - 1].clone();
        marble.done = true;
        continue;
      }
      let i = 1;
      while (marble.lengths[i] < marble.travelled) i++;
      const span = marble.lengths[i] - marble.lengths[i - 1] || 1;
      const t = (marble.travelled - marble.lengths[i - 1]) / span;
      marble.mesh.position = BABYLON.Vector3.Lerp(marble.points[i - 1], marble.points[i], t);
    }
    for (let i = flyingMarbles.length - 1; i >= 0; i--) {
      const marble = flyingMarbles[i];
      if (!marble.done) continue;
      flyingMarbles.splice(i, 1);
      setTimeout(() => marble.mesh.dispose(), 400);
      if (marble.run.exit) {
        recordArrival(marble.source, marble.run.exit);
        flashExitRow(marble.run.exit);
      }
    }
  }

  function cancelMarbles() {
    for (const marble of flyingMarbles) marble.mesh.dispose();
    flyingMarbles.length = 0;
  }

  function rollStatus(text) {
    document.getElementById("routeStatus").textContent = text;
  }

  function rollOne() {
    const source = document.getElementById("routeSource").value;
    if (!routingGraph || !source) return;
    const run = MarbleRouting.sampleRun(layout, catalog, routingGraph, source);
    if (!run.complete) {
      rollStatus("The marble cannot finish from " + source + ": " + run.reason);
      return;
    }
    if (!launchMarble(source, run)) recordArrival(source, run.exit);
  }

  function rollMany(count) {
    const source = document.getElementById("routeSource").value;
    if (!routingGraph || !source) return;
    let failed = null;
    for (let i = 0; i < count; i++) {
      const run = MarbleRouting.sampleRun(layout, catalog, routingGraph, source);
      if (!run.complete) { failed = run.reason; break; }
      if (rollTally.source !== source) resetTally(source);
      rollTally.counts.set(run.exit, (rollTally.counts.get(run.exit) || 0) + 1);
      rollTally.total += 1;
    }
    if (failed) rollStatus("The marble cannot finish from " + source + ": " + failed);
    if (lastOutcomes) {
      renderExitProbabilities(lastOutcomes, document.getElementById("routeSink").value);
    }
  }

  function renderRouting() {
    cancelMarbles();
    resetTally("");
    routingGraph = MarbleRouting.buildGraph(layout, catalog);
    populateRoutingControls();
    updateRouting();
  }

  function globalCom() {
    let total = 0;
    let wx = 0, wy = 0, wz = 0;
    const unknown = [];

    for (const rail of layout.rails || []) {
      const spec = railSpec(rail.rail_type);
      const mass = massValue(spec);
      if (mass == null) { unknown.push(rail.id); continue; }
      const p = railPoint(rail, Number(spec.length_cm) / 2);
      const z = Number(rail.z_units) + Number(spec.height || 1) / 2;
      total += mass; wx += mass * p.x; wy += mass * p.y; wz += mass * z;
    }
    for (const part of layout.parts || []) {
      const spec = catalog.routing_blocks?.[part.part_type] || catalog.structural_parts?.[part.part_type] || {};
      const mass = blockMass(part.part_type);
      if (mass == null) { unknown.push(part.id); continue; }
      const hCm = partBodyHeightCm(spec, Number(spec.height || 1));
      const hUnits = hCm / HEIGHT_SCALE_CM;
      total += mass;
      wx += mass * Number(part.x_cm);
      wy += mass * Number(part.y_cm);
      wz += mass * (Number(part.z_units) + hUnits / 2);
    }
    if (!total || unknown.length) return { evaluable: false, unknown, total_mass_g: total };
    return {
      evaluable: true,
      total_mass_g: total,
      x: wx / total,
      y: wy / total,
      z_units: wz / total,
    };
  }

  function groundSupportPoints() {
    const railMap = Object.fromEntries((layout.rails || []).map(r => [r.id, r]));
    const points = [];
    for (const support of layout.supports || []) {
      if (support.lower_rail_id) continue;
      const rail = railMap[support.upper_rail_id];
      if (!rail) continue;
      const p = railHoleWorld(rail, Number(support.upper_hole_index));
      points.push({ x: p.x, y: p.y });
    }
    return points;
  }

  function hull(points) {
    const pts = [...new Map(points.map(p => [p.x + "," + p.y, p])).values()]
      .sort((a,b) => a.x - b.x || a.y - b.y);
    if (pts.length <= 1) return pts;
    const cross = (o,a,b) => (a.x-o.x)*(b.y-o.y) - (a.y-o.y)*(b.x-o.x);
    const lower = [];
    for (const p of pts) {
      while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), p) <= 0) lower.pop();
      lower.push(p);
    }
    const upper = [];
    for (const p of [...pts].reverse()) {
      while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), p) <= 0) upper.pop();
      upper.push(p);
    }
    return lower.slice(0,-1).concat(upper.slice(0,-1));
  }

  function renderComAndPolygon() {
    const com = globalCom();
    const comSummary = document.getElementById("comSummary");
    if (com.evaluable) {
      comSummary.textContent =
        "mass = " + com.total_mass_g.toFixed(1) + " g\n" +
        "COM = (" + com.x.toFixed(2) + ", " + com.y.toFixed(2) + ", " + com.z_units.toFixed(2) + "u)";
      const sphere = BABYLON.MeshBuilder.CreateSphere("global-com", { diameter: 2.5, segments: 18 }, scene);
      sphere.position = world(com.x, com.y, com.z_units);
      sphere.material = material("comMat", "#facc15");
      sphere.metadata = { selectable: true, info: { kind: "global_com", ...com } };
      groups.com.push(sphere);

      const down = BABYLON.MeshBuilder.CreateLines("com-down", {
        points: [world(com.x, com.y, com.z_units), world(com.x, com.y, 0)],
      }, scene);
      down.color = BABYLON.Color3.FromHexString("#facc15");
      groups.com.push(down);
    } else {
      comSummary.textContent = "COM unavailable; unknown mass: " + (com.unknown || []).join(", ");
    }

    const points = hull(groundSupportPoints());
    if (points.length >= 2) {
      const path = points.map(p => world(p.x, p.y, 0.05));
      if (points.length >= 3) path.push(path[0].clone());
      const polygon = BABYLON.MeshBuilder.CreateLines("support-polygon", { points: path }, scene);
      polygon.color = BABYLON.Color3.FromHexString("#f59e0b");
      groups.polygon.push(polygon);
    }
  }

  function updateSummary() {
    const summary = document.getElementById("summary");
    const rows = [
      ["Rails", (layout.rails || []).length],
      ["Parts", (layout.parts || []).length],
      ["Ground level", "z=0 (0 cm)"],
      ["Support links", (layout.supports || []).length],
      ["Route links", (layout.route_links || []).length],
      ["Height scale", HEIGHT_SCALE_CM + " cm/u (derived from 6 cm / 4u)"],
      ["Standard block", (4 * HEIGHT_SCALE_CM) + " cm stacked (measured)"],
      ["Connector peg", CONNECTOR_PROTRUSION_CM + " cm (inserted; not added)"],
      ["Rail width", RAIL_WIDTH_CM + " cm (measured)"],
      ["Block footprint", BLOCK_WIDTH_CM + " × " + BLOCK_DEPTH_CM + " cm (measured)"],
      ["Hole diameter", "≈" + HOLE_DIAMETER_CM + " cm (approx.)"],
      ["Rail thickness", HEIGHT_SCALE_CM + " cm (1u, user-confirmed)"],
      ["Rail groove width", RAIL_GROOVE_WIDTH_CM + " cm (measured)"],
      ["Rail groove depth", RAIL_GROOVE_DEPTH_CM + " cm (provisional)"],
      ["Block port holes", "Ø" + BLOCK_PORT_DIAMETER_CM + " cm (provisional)"],
    ];
    summary.innerHTML = rows.map(([k,v]) => "<dt>" + k + "</dt><dd>" + v + "</dd>").join("");
    document.getElementById("layoutMeta").textContent = layout.name || "unnamed layout";
    document.getElementById("groundLevelLabel").textContent =
      "Ground level: z=0 (0 cm) · 1u = " + HEIGHT_SCALE_CM + " cm";
  }

  function fitCamera() {
    const meshes = groups.structure.filter(m => m && !m.isDisposed());
    if (!meshes.length) return;
    const min = new BABYLON.Vector3(Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY);
    const max = new BABYLON.Vector3(Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NEGATIVE_INFINITY);
    for (const mesh of meshes) {
      mesh.computeWorldMatrix(true);
      const bb = mesh.getBoundingInfo().boundingBox;
      min.minimizeInPlace(bb.minimumWorld);
      max.maximizeInPlace(bb.maximumWorld);
    }
    const center = min.add(max).scale(0.5);
    const size = max.subtract(min).length();
    camera.setTarget(center);
    camera.radius = Math.max(25, size * 1.25);
  }

  function renderAll() {
    document.getElementById("allowSideEntryPlusOne").checked =
      Boolean(layout.routing_options?.allow_side_entry_plus_one);
    clearRendered();
    for (const rail of layout.rails || []) renderRail(rail);
    for (const part of layout.parts || []) {
      const special = catalog.special_parts?.[part.part_type];
      if (special?.shape === "twist_funnel") renderTwist(part, special);
      else renderPart(part);
    }
    renderStackSeams();
    renderSupports();
    renderRouting();
    renderComAndPolygon();
    updateSummary();
    applyVisibility();
    fitCamera();
  }

  function applyVisibility() {
    const settings = {
      holes: document.getElementById("toggleHoles").checked,
      supports: document.getElementById("toggleSupports").checked,
      route: document.getElementById("toggleRoute").checked,
      com: document.getElementById("toggleCom").checked,
      polygon: document.getElementById("togglePolygon").checked,
    };
    groundLevelGrid.setEnabled(document.getElementById("toggleGroundLevel").checked);
    for (const [key, visible] of Object.entries(settings)) {
      for (const mesh of groups[key]) mesh.setEnabled(visible);
    }
  }

  async function loadCatalog() {
    const response = await fetch(DATA_ROOT + "catalog/parts.yaml");
    if (!response.ok) throw new Error("Failed to load catalog/parts.yaml");
    return jsyaml.load(await response.text());
  }

  async function loadExample(path) {
    const response = await fetch(DATA_ROOT + path);
    if (!response.ok) throw new Error("Failed to load " + path);
    layout = jsyaml.load(await response.text());
    renderAll();
  }

  async function initialize() {
    try {
      catalog = await loadCatalog();
      applyCatalogGeometry();
      await loadExample(document.getElementById("exampleSelect").value);
    } catch (error) {
      document.getElementById("layoutMeta").textContent = String(error);
      console.error(error);
    }
  }

  document.getElementById("exampleSelect").addEventListener("change", event => {
    loadExample(event.target.value).catch(console.error);
  });

  document.getElementById("layoutFile").addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        layout = jsyaml.load(String(reader.result));
        renderAll();
      } catch (error) {
        alert("YAML parse error: " + error);
      }
    };
    reader.readAsText(file);
  });

  document.getElementById("resetCamera").addEventListener("click", fitCamera);
  document.getElementById("rollOne").addEventListener("click", rollOne);
  document.getElementById("rollOneTop").addEventListener("click", rollOne);
  document.getElementById("rollMany").addEventListener("click", () => rollMany(100));
  document.getElementById("rollReset").addEventListener("click", () => {
    resetTally(document.getElementById("routeSource").value);
    if (lastOutcomes) renderExitProbabilities(lastOutcomes, document.getElementById("routeSink").value);
  });
  scene.onBeforeRenderObservable.add(stepMarbles);
  for (const id of ["routeSource", "routeSink"]) {
    document.getElementById(id).addEventListener("change", updateRouting);
  }
  document.getElementById("allowSideEntryPlusOne").addEventListener("change", event => {
    layout.routing_options = {
      ...(layout.routing_options || {}),
      allow_side_entry_plus_one: event.target.checked,
    };
    renderRouting();
  });
  for (const id of ["toggleHoles","toggleSupports","toggleRoute","toggleCom","togglePolygon","toggleGroundLevel"]) {
    document.getElementById(id).addEventListener("change", applyVisibility);
  }

  scene.onPointerObservable.add(pointerInfo => {
    if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERPICK) return;
    const picked = pointerInfo.pickInfo?.pickedMesh;
    // Clicking a drop marker, or the rim/cap of a valid input hole, selects
    // that hole as the marble input.
    const inputKey = picked?.metadata?.inputHoleKey
      ?? (picked?.metadata?.info?.kind === "rail_hole" ? picked.metadata.info.id : null);
    // Copy the info first: selecting re-renders the route and disposes the marker.
    const pickedInfo = picked?.metadata?.info;
    if (inputKey && selectInputHole(inputKey)) {
      document.getElementById("selection").textContent =
        JSON.stringify({ selected_input_hole: inputKey, ...pickedInfo }, null, 2);
      return;
    }
    if (!picked?.metadata?.selectable) return;
    document.getElementById("selection").textContent =
      JSON.stringify(picked.metadata.info, null, 2);
  });

  // Pointer cursor over clickable input-hole markers.
  scene.onPointerObservable.add(pointerInfo => {
    if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERMOVE) return;
    const pick = scene.pick(scene.pointerX, scene.pointerY,
      mesh => Boolean(mesh.metadata?.inputHoleKey) && mesh.isEnabled());
    canvas.style.cursor = pick?.hit ? "pointer" : "";
  });

  window.addEventListener("resize", () => engine.resize());
  engine.runRenderLoop(() => scene.render());
  initialize();
})();
