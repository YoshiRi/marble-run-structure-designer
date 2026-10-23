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
    build: [],
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
  // The loaded layout. In Build mode `layout` is the part placed so far.
  let fullLayout = null;
  const build = { on: false, step: 0, plan: [], graph: null, ghost: false, onRoute: new Set(), reframe: false };
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

  // Rail geometry is shared with the routing engine (routing.js), so the 3D
  // view and the routing graph agree on curved rails too.
  function railSpec(type) {
    const spec = MarbleRouting.railGeometry(catalog, type);
    if (!spec) throw new Error("Unknown rail type: " + type);
    return spec;
  }

  function railPoint(rail, localX) {
    const [x, y] = MarbleRouting.railPose(catalog, rail, Number(localX));
    return { x, y };
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

  // Twist mesh (catalog: special_rails.spiral, a two-level rail). Placement here: x_cm/y_cm = funnel
  // center (outlet hole), z_units = level the outlet rests on, rotation_deg =
  // direction from the funnel center toward the chute. Viewer-only, schematic.
  function renderTwist(part, spec, rail = null) {
    const rimD = geometryValue(spec.funnel_rim_diameter_cm, 23);
    const holePositions = spec.hole_positions_cm || [];
    const spacing = holePositions.length >= 2
      ? Number(holePositions[holePositions.length - 1]) - Number(holePositions[0])
      : geometryValue(spec.mount_hole_spacing_cm, 23);
    const overall = geometryValue(spec.overall_length_cm, 36);
    const rise = Number(spec.hole_mount_levels_units?.[0] ?? geometryValue(spec.level_difference_units, 3));
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
      id: part.id, kind: "twist", type: part.part_type,
      solver_support: rail ? "rail_model" : "viewer_only",
      hole_states: rail?.hole_states || {},
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
    if (spec.shape === "twist") {
      // Twist rail: end A at the chute tip, heading to the funnel center.
      const center = railPoint(rail, Number(spec.length_cm));
      renderTwist({
        id: rail.id, part_type: rail.rail_type, x_cm: center.x, y_cm: center.y,
        z_units: rail.z_units, rotation_deg: Number(rail.yaw_deg || 0) + 180,
      }, spec, rail);
      return;
    }
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
      const topZ = Number(rail.z_units) + MarbleRouting.holeLevel(spec, idx) + heightUnits;
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
        if (lower && lowerSpec) {
          lowerZ = Number(lower.z_units) + MarbleRouting.holeLevel(lowerSpec, Number(support.lower_hole_index))
            + Number(lowerSpec.height || 1);
        }
      }
      const upperZ = Number(rail.z_units) + MarbleRouting.holeLevel(railSpec(rail.rail_type), Number(support.upper_hole_index));
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
      return world(p.x, p.y, Number(rail.z_units) + MarbleRouting.holeLevel(spec, index) + Number(spec.height || 1) + 0.12 / HEIGHT_SCALE_CM);
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

  // Position along a rail (cm from end A) for a rail node key, or null.
  function railNodeStation(key) {
    const colon = key.indexOf(":");
    const rail = (layout.rails || []).find(r => r.id === key.slice(0, colon));
    if (!rail) return null;
    const spec = railSpec(rail.rail_type);
    const port = key.slice(colon + 1);
    if (port === "end_a") return { rail, spec, s: 0 };
    if (port === "end_b") return { rail, spec, s: Number(spec.length_cm) };
    if (port.startsWith("hole:")) {
      const x = spec.hole_positions_cm?.[Number(port.slice(5))];
      return x == null ? null : { rail, spec, s: Number(x) };
    }
    return null;
  }

  // Hook-shaped path through a twist (user-described): the marble drops into
  // the chute at the chute hole, rolls down the chute to the rim, veers right
  // and circles the funnel counter-clockwise (seen from above) into the
  // center hole. Empty unless `to` is a twist's center hole.
  function twistPointsInto(from, to, lift) {
    const b = railNodeStation(to);
    if (!b || b.spec.shape !== "twist") return [];
    const holes = (b.spec.hole_positions_cm || []).map(Number);
    if (b.s !== holes[holes.length - 1]) return [];
    const z0 = Number(b.rail.z_units);
    const rise = MarbleRouting.holeLevel(b.spec, 0);
    const rimR = geometryValue(b.spec.funnel_rim_diameter_cm, 23) / 2 - 1.0;
    const [cx, cy, heading] = MarbleRouting.railPose(catalog, b.rail, b.s);
    const up = new BABYLON.Vector3(0, lift, 0);
    const out = [];
    // Chute: from the chute hole down to the rim, one unit lower.
    const s0 = holes[0], s1 = b.s - rimR;
    for (let i = 0; i <= 6; i++) {
      const s = s0 + (s1 - s0) * i / 6;
      const p = railPoint(b.rail, s);
      out.push(world(p.x, p.y, z0 + rise + 1 - i / 6).add(up));
    }
    // Funnel: spiral from the rim (chute side) to the center, descending.
    const start = heading + Math.PI, turns = 1.75, steps = 72;
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      const r = rimR * (1 - t) + 0.6 * t;
      const theta = start + t * turns * 2 * Math.PI;
      out.push(world(cx + r * Math.cos(theta), cy + r * Math.sin(theta), z0 + rise - t * (rise - 1)).add(up));
    }
    return out;
  }

  // Intermediate points that keep a path on a curved rail's arc between two
  // nodes of the same rail (empty for straight rails).
  function arcPointsBetween(from, to, lift) {
    const twist = twistPointsInto(from, to, lift);
    if (twist.length) return twist;
    const a = railNodeStation(from), b = railNodeStation(to);
    if (!a || !b || a.rail !== b.rail || a.spec.shape !== "arc") return [];
    const steps = Math.max(2, Math.ceil(Math.abs(b.s - a.s) / 1.5));
    const top = Number(a.rail.z_units) + Number(a.spec.height || 1);
    const out = [];
    for (let i = 1; i < steps; i++) {
      const p = railPoint(a.rail, a.s + (b.s - a.s) * i / steps);
      out.push(world(p.x, p.y, top).add(new BABYLON.Vector3(0, lift, 0)));
    }
    return out;
  }

  function routingEdgePoints(from, to) {
    const a = routingNodePosition(from);
    const b = routingNodePosition(to);
    if (!a || !b) return null;
    const between = arcPointsBetween(from, to, 0.12);  // same groove offset as hole markers
    if (between.length) return [a, ...between, b];
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
    let previousNode = null;
    for (const node of run.path) {
      const pos = routingNodePosition(node);
      if (!pos) continue;
      if (previousNode) {
        // Follow the arc between two holes of the same curved rail.
        const lift = radius + 0.12;
        for (const q of arcPointsBetween(previousNode, node, lift)) points.push(q);
      }
      const lifted = pos.add(new BABYLON.Vector3(0, radius, 0));
      const prev = points[points.length - 1];
      if (!prev || BABYLON.Vector3.DistanceSquared(prev, lifted) > 1e-4) points.push(lifted);
      previousNode = node;
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
    const name = layout.name || "unnamed layout";
    document.getElementById("layoutMeta").textContent =
      layout.layout_id && layout.layout_id !== name ? layout.layout_id + " · " + name : name;
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

  // ---- Build mode (docs/assembly-assist.md) --------------------------------
  const BUILD_STORE = "marble-run-build-v1:";
  const PART_NAMES = {
    wooden_foundation: "foundation", natural_drop: "natural", purple_drop: "purple 1u",
    orange_vertical: "orange", red_random_split: "red splitter", red_right_angle: "red right-angle",
    blue: "blue", green: "green", cyan: "cyan", yellow: "yellow",
    straight_short: "short straight", straight_long: "long straight",
    straight_long_center: "long straight (center hole)", curved_short: "short curve",
    curved_long: "long curve", s_curve: "S-curve", spiral: "twist", cover: "cover",
  };
  const partName = type => PART_NAMES[type] || type;

  function stepIds(step) { return new Set(build.plan[step]?.components || []); }

  // Components placed up to the current step (all of them on the first and
  // last steps, so the parts list and the final check show the whole build).
  function placedIds() {
    const last = build.plan.length - 1;
    if (build.step === 0 || build.step === last) {
      return new Set(build.plan.flatMap(s => s.components));
    }
    const ids = new Set();
    for (let i = 1; i <= build.step; i++) for (const id of build.plan[i].components) ids.add(id);
    return ids;
  }

  function buildView() {
    const ids = placedIds();
    if (build.ghost) for (const s of build.plan) for (const id of s.components) ids.add(id);
    const view = { ...fullLayout };
    view.rails = (fullLayout.rails || []).filter(r => ids.has(r.id));
    view.parts = (fullLayout.parts || []).filter(p => ids.has(p.id));
    view.supports = (fullLayout.supports || []).filter(s =>
      (s.stack_part_ids || []).every(id => ids.has(id)) &&
      (s.upper_rail_id == null || ids.has(s.upper_rail_id)) &&
      (s.lower_rail_id == null || ids.has(s.lower_rail_id)));
    view.route_links = (fullLayout.route_links || []).filter(l =>
      ids.has(l.source.component_id) && ids.has(l.target.component_id));
    return view;
  }

  function stepMeshes(ids) {
    return groups.structure.filter(m => m && !m.isDisposed() && ids.has(m.metadata?.info?.id));
  }

  function frameMeshes(meshes) {
    if (!meshes.length) return fitCamera();
    const min = new BABYLON.Vector3(Infinity, Infinity, Infinity);
    const max = new BABYLON.Vector3(-Infinity, -Infinity, -Infinity);
    for (const mesh of meshes) {
      mesh.computeWorldMatrix(true);
      const bb = mesh.getBoundingInfo().boundingBox;
      min.minimizeInPlace(bb.minimumWorld);
      max.maximizeInPlace(bb.maximumWorld);
    }
    camera.setTarget(min.add(max).scale(0.5));
    camera.radius = Math.max(35, max.subtract(min).length() * 1.6);
  }

  // Outline the current step, ghost later steps, and draw facing arrows.
  // Current step in color (outlined), parts placed in earlier steps dark gray,
  // later steps ghosted. The camera stays where the user put it; it is
  // framed only when Build mode opens (user request).
  function decorateBuildStep() {
    const step = build.plan[build.step];
    const current = stepIds(build.step);
    const placed = placedIds();
    const earlier = material("buildEarlierMat", "#555c66");
    earlier.emissiveColor = BABYLON.Color3.FromHexString("#555c66").scale(0.35);
    earlier.specularColor = BABYLON.Color3.Black();
    const earlierEdges = new BABYLON.Color4(0.42, 0.45, 0.5, 1);
    for (const mesh of scene.meshes) {
      const owner = mesh.metadata?.owner;
      if (owner === undefined || mesh.isDisposed()) continue;
      if (!placed.has(owner)) {
        mesh.visibility = 0.15;
      } else if (step.kind === "rail" && !current.has(owner)) {
        if (mesh instanceof BABYLON.LinesMesh) mesh.color = new BABYLON.Color3(0.42, 0.45, 0.5);
        else mesh.material = earlier;
        if (mesh.edgesRenderer) mesh.edgesColor = earlierEdges;
      } else if (step.kind === "rail" && mesh.metadata?.info?.id === owner) {
        mesh.renderOutline = true;
        mesh.outlineColor = BABYLON.Color3.FromHexString("#f8fafc");
        mesh.outlineWidth = 0.12;
      }
    }
    if (step.kind === "rail") for (const id of current) drawFacingArrows(id);
    if (build.reframe) {
      build.reframe = false;
      if (step.kind === "rail") frameMeshes(stepMeshes(current)); else fitCamera();
    }
  }

  // Blocks the marble passes through from the layout's input (BFS over the
  // routing graph). Only these need a particular facing; the rest are
  // structure, any way round.
  function routeParts() {
    const query = fullLayout.routing_query?.source;
    const start = query ? query.component_id + ":" + query.port : null;
    const seen = new Set(start ? [start] : []);
    const queue = start ? [start] : [];
    while (queue.length) {
      for (const next of build.graph.edges[queue.shift()] || []) {
        if (!seen.has(next)) { seen.add(next); queue.push(next); }
      }
    }
    return new Set([...seen].map(node => node.slice(0, node.indexOf(":"))));
  }

  function routeTargets(partId, port) {
    return (build.graph?.edges[partId + ":" + port] || [])
      .map(node => node.slice(0, node.indexOf(":")))
      .filter(id => id !== partId);
  }

  function blockPorts(part) {
    const spec = partSpec(part.part_type);
    const outlets = new Set(), inlets = new Set();
    for (const route of spec?.routes || []) {
      for (const to of [route.to, ...(route.to_any_of || [])]) if (to) outlets.add(to);
      if (route.from) inlets.add(route.from);
    }
    const sides = ["front", "rear", "left", "right"];
    const notches = spec?.port_visualization?.side_entry_notches || [];
    return {
      outlets: sides.filter(p => outlets.has(p)),
      // Only notches something actually feeds (a rail end, another block).
      inlets: sides.filter(p => inlets.has(p) && notches.includes(p) && build.fed?.has(part.id + ":" + p)),
    };
  }

  function drawArrow(pose, inward, color) {
    const [x, y, z] = pose.position;
    const [nx, ny] = pose.normal;
    const lift = 0.9;
    const tail = new BABYLON.Vector3(x + nx * (inward ? 3.2 : 0.2), z + lift, y + ny * (inward ? 3.2 : 0.2));
    const head = new BABYLON.Vector3(x + nx * (inward ? 0.4 : 3.0), z + lift, y + ny * (inward ? 0.4 : 3.0));
    const shaft = BABYLON.MeshBuilder.CreateTube("build-arrow", { path: [tail, head], radius: 0.18 }, scene);
    const dir = head.subtract(tail).normalize();
    const cone = BABYLON.MeshBuilder.CreateCylinder("build-arrow-head",
      { diameterTop: 0, diameterBottom: 0.9, height: 1.0, tessellation: 12 }, scene);
    cone.position = head;
    const axis = BABYLON.Vector3.Cross(BABYLON.Axis.Y, dir);
    const angle = Math.acos(Math.max(-1, Math.min(1, BABYLON.Vector3.Dot(BABYLON.Axis.Y, dir))));
    if (axis.length() > 1e-6) cone.rotationQuaternion = BABYLON.Quaternion.RotationAxis(axis.normalize(), angle);
    for (const mesh of [shaft, cone]) {
      mesh.material = material("buildArrowMat", color);
      mesh.material.emissiveColor = BABYLON.Color3.FromHexString(color).scale(0.5);
      mesh.isPickable = false;
      groups.build.push(mesh);
    }
  }

  function drawFacingArrows(partId) {
    const part = (layout.parts || []).find(p => p.id === partId);
    if (!part || !partSpec(part.part_type)?.routes || !build.onRoute.has(partId)) return;
    const { outlets, inlets } = blockPorts(part);
    for (const port of outlets) {
      const pose = MarbleRouting.portPose(layout, catalog, { component_id: partId, port });
      if (pose) drawArrow(pose, false, "#22c55e");
    }
    for (const port of inlets) {
      const pose = MarbleRouting.portPose(layout, catalog, { component_id: partId, port });
      if (pose) drawArrow(pose, true, "#38bdf8");
    }
  }

  // "front: along rail2 → rail4" style facing text, relative to the step's rail.
  function facingText(part, rail) {
    const { outlets, inlets } = blockPorts(part);
    const sided = outlets.length || (partSpec(part.part_type)?.routes || []).some(r =>
      ["front", "rear", "left", "right"].includes(r.from));
    if (!sided) return "";  // vertical-only parts look the same any way round
    if (!build.onRoute.has(part.id)) return "structure, any way round";
    if (!outlets.length && !inlets.length) return "";
    const spec = railSpec(rail.rail_type);
    const ref = MarbleRouting.railPose(catalog, rail, Number(spec.length_cm) / 2)[2];
    const words = [];
    const relative = port => {
      const pose = MarbleRouting.portPose(fullLayout, catalog, { component_id: part.id, port });
      if (!pose) return "";
      const a = Math.atan2(pose.normal[1], pose.normal[0]) - ref;
      const c = Math.cos(a), s = Math.sin(a);
      return Math.abs(c) >= Math.abs(s) ? (c > 0 ? "along " : "back along ") + rail.id
        : (s > 0 ? "left of " : "right of ") + rail.id;
    };
    for (const port of outlets) {
      const to = routeTargets(part.id, port);
      words.push("out " + port + ": " + relative(port) + (to.length ? " → " + to.join(", ") : ""));
    }
    for (const port of inlets) {
      const key = part.id + ":" + port;
      const from = Object.entries(build.graph.edges)
        .filter(([src, targets]) => targets.includes(key) && !src.startsWith(part.id + ":"))
        .map(([src]) => src.slice(0, src.indexOf(":")));
      words.push("in " + port + " notch: " + relative(port) + (from.length ? " ← " + from.join(", ") : ""));
    }
    return words.join("; ");
  }

  function groupParts(ids) {
    const parts = new Map((fullLayout.parts || []).map(p => [p.id, p]));
    const runs = [];
    for (const id of ids) {
      const type = parts.get(id)?.part_type;
      if (runs.length && runs[runs.length - 1].type === type && !build.onRoute.has(id)
          && !build.onRoute.has(runs[runs.length - 1].ids[0])) {
        runs[runs.length - 1].ids.push(id);
      } else runs.push({ type, ids: [id] });
    }
    return runs;
  }

  function swatch(type) {
    const color = palette[type] || (String(type).includes("straight") || String(type).includes("curve")
      ? palette.rail : type === "spiral" ? palette.twist : palette.default);
    return '<i class="swatch" style="background:' + color + '"></i>';
  }

  const esc = text => String(text).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function doneKey() { return BUILD_STORE + (fullLayout?.layout_id || fullLayout?.name || "layout"); }
  function loadDone() {
    try { return new Set(JSON.parse(localStorage.getItem(doneKey()) || "[]")); } catch (e) { return new Set(); }
  }
  function saveDone(done) {
    try { localStorage.setItem(doneKey(), JSON.stringify([...done])); } catch (e) { /* unavailable */ }
  }

  function stepTitle(step, i) {
    if (step.kind === "parts") return "Parts";
    if (step.kind === "check") return "Roll the marble";
    return partName(step.rail_type) + " " + step.rail + " · level " + step.z_units +
      (step.brace ? " · brace (no marble)" : "");
  }

  function bomHtml() {
    const info = fullLayout.bill_of_materials;
    const used = info?.used || MarbleAssembly.billOfMaterials(fullLayout);
    const check = info?.check ? new Map(info.check.map(r => [r.part, r])) : null;
    const pooled = { straight_long_center: "straight_long", spiral_large: "spiral", spiral_small: "spiral" };
    const rows = Object.entries(used).map(([type, n]) => {
      const row = check?.get(pooled[type] || type);
      let status = "";
      if (row) {
        status = row.short ? '<span class="short">short ' + row.short + "</span>"
          : '<span class="ok">ok</span>' + (row.wildcard ? " (" + row.wildcard + " any straight)" : "");
      }
      return "<tr><td>" + swatch(type) + esc(partName(type)) + "</td><td>" + n + "</td><td>" +
        (row ? row.available + (pooled[type] ? " (shared)" : "") : "—") + "</td><td>" + status + "</td></tr>";
    }).join("");
    const sets = fullLayout.generator?.sets;
    return '<p class="muted small-note">' + (sets
      ? "Checked against sets " + esc(sets.join(", ")) +
        (fullLayout.generator.exclude?.length ? " without " + esc(fullLayout.generator.exclude.map(partName).join(", ")) : "")
      : "No set list in this layout: counts only.") + "</p>" +
      '<table class="bom"><thead><tr><th>Part</th><th>Need</th><th>Have</th><th></th></tr></thead><tbody>' +
      rows + "</tbody></table>";
  }

  function railStepHtml(step) {
    const rail = (fullLayout.rails || []).find(r => r.id === step.rail);
    const parts = new Map((fullLayout.parts || []).map(p => [p.id, p]));
    const items = [];
    for (const column of step.columns) {
      const base = column.base === "ground" ? "on the ground" : "on " + column.base.rail + " hole " + column.base.hole;
      const runs = groupParts(column.parts).map(run => {
        const part = parts.get(run.ids[0]);
        const facing = facingText(part, rail);
        return swatch(run.type) + esc(partName(run.type)) + (run.ids.length > 1 ? " ×" + run.ids.length : "") +
          (facing ? ' <span class="facing">(' + esc(facing) + ")</span>" : "");
      });
      items.push({ ids: column.parts, html: "<b>Column under hole " + column.hole + "</b>, " + esc(base) +
        ", bottom to top: " + runs.join(" · ") });
    }
    const fit = [];
    fit.push("rests on " + step.rests.map(([h, c]) => "hole " + h).join(" and "));
    if (step.covers.length) fit.push("covers on holes " + step.covers.join(", "));
    if (step.open.length) fit.push("hole " + step.open.join(", ") + " stays open: the marble dives through; keep below clear");
    if (step.drops.length) fit.push("hole " + step.drops.join(", ") + " drops into the block below");
    items.push({ ids: [step.rail], html: "<b>Lay " + swatch(rail.rail_type) + esc(partName(rail.rail_type)) + " " +
      esc(rail.id) + "</b>" + (railSpec(rail.rail_type)?.shape === "arc" && rail.turn
        ? " (turns " + esc(rail.turn) + ")" : "") + ": " + esc(fit.join("; ")) });
    for (const free of step.free) {
      const part = parts.get(free.parts[0]);
      const facing = facingText(part, rail);
      const what = free.support.startsWith("cw") ? "Counterweight" : "Stand";
      items.push({ ids: free.parts, html: "<b>" + what + " on hole " + free.hole + "</b>: " +
        groupParts(free.parts).map(run => swatch(run.type) + esc(partName(run.type)) +
          (run.ids.length > 1 ? " ×" + run.ids.length : "")).join(" · ") +
        (facing ? ' <span class="facing">(' + esc(facing) + ")</span>" : "") });
    }
    return '<ol class="build-items">' + items.map(item =>
      '<li data-ids="' + esc(item.ids.join(" ")) + '">' + item.html + "</li>").join("") + "</ol>" +
      '<p class="muted small-note">Green arrows: where the marble leaves a block. Blue arrows: side notches it enters.</p>';
  }

  function renderBuildPanel() {
    const panel = document.getElementById("buildPanel");
    document.getElementById("buildToggle").textContent = build.on ? "Exit build" : "Build";
    document.getElementById("buildToggle").setAttribute("aria-pressed", String(build.on));
    panel.hidden = !build.on;
    if (!build.on || !fullLayout) return;
    const step = build.plan[build.step];
    const done = loadDone();
    const last = build.plan.length - 1;
    document.getElementById("buildStepTitle").textContent =
      "Step " + build.step + " / " + last + " · " + stepTitle(step, build.step);
    document.getElementById("buildPrev").disabled = build.step === 0;
    document.getElementById("buildNext").disabled = build.step === last;
    const doneBox = document.getElementById("buildDone");
    doneBox.checked = done.has(build.step);
    document.getElementById("buildProgress").textContent = done.size + " of " + (last + 1) + " steps done";
    const body = document.getElementById("buildBody");
    if (step.kind === "parts") body.innerHTML = bomHtml();
    else if (step.kind === "check") {
      body.innerHTML = '<p>Everything is placed. Roll a marble from the input (toolbar <b>Roll a marble</b> or the buttons below) and compare the exits.</p>';
    } else body.innerHTML = railStepHtml(step);
    for (const li of body.querySelectorAll("li[data-ids]")) {
      const ids = new Set(li.dataset.ids.split(" "));
      li.addEventListener("mouseenter", () => {
        for (const m of stepMeshes(ids)) m.outlineColor = BABYLON.Color3.FromHexString("#facc15");
      });
      li.addEventListener("mouseleave", () => {
        for (const m of stepMeshes(ids)) m.outlineColor = BABYLON.Color3.FromHexString("#f8fafc");
      });
    }
    const url = new URL(window.location.href);
    url.searchParams.set("mode", "build");
    url.searchParams.set("step", String(build.step));
    window.history.replaceState(null, "", url);
  }

  function goToStep(step) {
    build.step = Math.max(0, Math.min(build.plan.length - 1, step));
    renderAll();
  }

  function setBuildMode(on) {
    build.on = on;
    build.reframe = on;
    if (on) {
      for (const id of ["toggleCom", "togglePolygon"]) document.getElementById(id).checked = false;
    }
    if (!on) {
      const url = new URL(window.location.href);
      url.searchParams.delete("mode");
      url.searchParams.delete("step");
      window.history.replaceState(null, "", url);
    }
    renderAll();
  }

  function setLayout(data) {
    fullLayout = data;
    layout = data;
    build.plan = MarbleAssembly.buildPlan(fullLayout);
    build.graph = MarbleRouting.buildGraph(fullLayout, catalog);
    build.onRoute = routeParts();
    build.fed = new Set(Object.values(build.graph.edges).flat());
    build.step = Math.min(build.step, build.plan.length - 1);
    build.reframe = true;  // a new layout: frame it once, then keep the view
    renderAll();
  }

  function renderAll() {
    layout = build.on ? buildView() : fullLayout;
    document.getElementById("allowSideEntryPlusOne").checked =
      Boolean(layout.routing_options?.allow_side_entry_plus_one);
    clearRendered();
    // Tag every mesh with the component that made it (Build mode colors by it).
    const owned = (owner, draw) => {
      const before = scene.meshes.length;
      draw();
      for (const mesh of scene.meshes.slice(before)) mesh.metadata = { ...(mesh.metadata || {}), owner };
    };
    for (const rail of layout.rails || []) owned(rail.id, () => renderRail(rail));
    for (const part of layout.parts || []) {
      const special = catalog.special_parts?.[part.part_type];
      owned(part.id, () => (special?.shape === "twist_funnel" ? renderTwist(part, special) : renderPart(part)));
    }
    renderStackSeams();
    renderSupports();
    renderRouting();
    renderComAndPolygon();
    updateSummary();
    applyVisibility();
    if (build.on) decorateBuildStep();
    else if (build.reframe) { build.reframe = false; fitCamera(); }
    renderBuildPanel();
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
    setLayout(jsyaml.load(await response.text()));
  }

  async function initialize() {
    try {
      catalog = await loadCatalog();
      applyCatalogGeometry();
      // ?layout=examples/... opens a specific layout (e.g. from the gallery).
      const requested = new URLSearchParams(window.location.search).get("layout");
      const select = document.getElementById("exampleSelect");
      if (requested && /^examples\/[\w\-./]+\.ya?ml$/.test(requested) && !requested.includes("..")) {
        if (![...select.options].some(o => o.value === requested)) {
          const option = document.createElement("option");
          option.value = requested;
          option.textContent = requested.split("/").pop().replace(/\.ya?ml$/, "");
          select.appendChild(option);
        }
        select.value = requested;
      }
      const params = new URLSearchParams(window.location.search);
      if (params.get("mode") === "build") {
        build.on = true;
        build.reframe = true;
        for (const id of ["toggleCom", "togglePolygon"]) document.getElementById(id).checked = false;
        build.step = Math.max(0, Number(params.get("step")) || 0);
      }
      await loadExample(select.value);
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
        build.step = 0;
        setLayout(jsyaml.load(String(reader.result)));
      } catch (error) {
        alert("YAML parse error: " + error);
      }
    };
    reader.readAsText(file);
  });

  document.getElementById("resetCamera").addEventListener("click", fitCamera);
  document.getElementById("buildToggle").addEventListener("click", () => setBuildMode(!build.on));
  document.getElementById("buildPrev").addEventListener("click", () => goToStep(build.step - 1));
  document.getElementById("buildNext").addEventListener("click", () => goToStep(build.step + 1));
  document.getElementById("buildGhost").addEventListener("change", event => {
    build.ghost = event.target.checked;
    renderAll();
  });
  document.getElementById("buildDone").addEventListener("change", event => {
    const done = loadDone();
    if (event.target.checked) done.add(build.step); else done.delete(build.step);
    saveDone(done);
    if (event.target.checked && build.step < build.plan.length - 1) goToStep(build.step + 1);
    else renderBuildPanel();
  });
  window.addEventListener("keydown", event => {
    if (!build.on || event.target.closest?.("input, select, textarea")) return;
    if (event.key === "ArrowRight") goToStep(build.step + 1);
    if (event.key === "ArrowLeft") goToStep(build.step - 1);
  });
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
