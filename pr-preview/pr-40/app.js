(() => {
  "use strict";

  const DATA_ROOT = window.location.pathname.includes("/viewer/") ? "../" : "./";
  // Defaults mirror catalog/parts.yaml; loaded catalog geometry is authoritative.
  let HEIGHT_SCALE_CM = 1.2;  // replaced by the catalog value on load
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
    review: [],
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
  let layoutOrigin = "";  // where the open layout came from (review notes cite it)
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
  const sound = window.MarbleSound || { land() {}, seesaw() {}, exit() {}, rolling() {}, unlock() {}, setEnabled() {}, enabled: false };

  const palette = {
    yellow: "#eab308",
    blue: "#2563eb",
    green: "#16a34a",
    cyan: "#06b6d4",
    natural_drop: "#d6b98c",
    red_random_split: "#dc2626",
    red_right_angle: "#b91c1c",
    seesaw: "#dc2626",
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

  // Materials are shared by (name, color, alpha): creating one per mesh on
  // every redraw leaked hundreds of materials and made each redraw slower.
  // Callers that tweak a material do so the same way for the same key.
  const materialCache = new Map();
  function material(name, hex, alpha = 1) {
    const key = name + "|" + hex + "|" + alpha;
    const hit = materialCache.get(key);
    if (hit) return hit;
    const mat = new BABYLON.StandardMaterial(name + Math.random(), scene);
    materialCache.set(key, mat);
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

  function standardBlockUnits() {
    const v = catalog?.height_units?.standard_block ?? 5;
    return Math.trunc(Number(typeof v === "object" ? v.value : v));
  }

  function blockMass(partType) {
    const groups = [catalog.routing_blocks, catalog.structural_parts, catalog.special_parts];
    for (const group of groups) {
      const spec = group && group[partType];
      if (!spec) continue;
      const measured = massValue(spec);
      if (measured != null) return measured;
      if (group === catalog.routing_blocks && Number(spec.height || 0) === standardBlockUnits()) {
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
    // Outlet at the center; chute holes (two, user-confirmed) toward the tip.
    const center = Number(holePositions[holePositions.length - 1] ?? spacing);
    const holes = [[0, z0 + 1], ...holePositions.slice(0, -1).map(x => [center - Number(x), z0 + rise + 1])];
    const stateColor = { covered: "#f59e0b", block_connected: "#22d3ee", covered_slope: "#fb923c" };
    holes.forEach(([d, zLevel], i) => {
      const index = i === 0 ? holePositions.length - 1 : i - 1;
      const state = rail?.hole_states?.[index];
      const ring = BABYLON.MeshBuilder.CreateTorus("twist-hole-" + part.id + "-" + d, {
        diameter: HOLE_DIAMETER_CM + 0.25, thickness: state === "covered" ? 0.5 : 0.15, tessellation: 32,
      }, scene);
      ring.position = at(d, zLevel);
      ring.position.y += 0.1;
      ring.material = material("holeRimMat", stateColor[state] || "#334155");
      groups.holes.push(ring);
    });
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

  // The straight rail shape (groove and holes cut by CSG) is built once per
  // rail type at the origin, then copied and placed: CSG per rail per redraw
  // made every edit slow.
  const railShapeCache = new Map();
  function railShape(type, spec) {
    if (railShapeCache.has(type)) return railShapeCache.get(type);
    const length = Number(spec.length_cm);
    const railHeight = Number(spec.height || 1) * HEIGHT_SCALE_CM;
    const box = BABYLON.MeshBuilder.CreateBox("rail-shape", { width: length, height: railHeight, depth: RAIL_WIDTH_CM }, scene);
    let shape = { data: BABYLON.VertexData.ExtractFromMesh(box, true, true), cutouts: false };
    // Cut a centered longitudinal channel and vertical through-holes.
    // Channel width is measured; the rectangular 0.3 cm depth is provisional.
    // Without CSG, a visible top strip indicates the channel location.
    if (BABYLON.CSG && typeof BABYLON.CSG.FromMesh === "function") {
      const cutters = [];
      try {
        let solid = BABYLON.CSG.FromMesh(box);
        if (spec.shape !== "plate") {   // hole plates have no groove
          const grooveDepth = Math.min(RAIL_GROOVE_DEPTH_CM, railHeight * 0.8);
          const groove = BABYLON.MeshBuilder.CreateBox("rail-groove-cutter", {
            width: length + 0.25, height: grooveDepth + 0.12, depth: Math.min(RAIL_GROOVE_WIDTH_CM, RAIL_WIDTH_CM * 0.9),
          }, scene);
          cutters.push(groove);
          groove.position.y = railHeight / 2 - (grooveDepth / 2 - 0.06);
          groove.computeWorldMatrix(true);
          solid = solid.subtract(BABYLON.CSG.FromMesh(groove));
        }
        for (const localX of spec.hole_positions_cm || []) {
          const cutter = BABYLON.MeshBuilder.CreateCylinder("hole-cutter", {
            diameter: HOLE_DIAMETER_CM, height: railHeight + 1.0, tessellation: 32,
          }, scene);
          cutters.push(cutter);
          cutter.position.x = Number(localX) - length / 2;
          cutter.computeWorldMatrix(true);
          solid = solid.subtract(BABYLON.CSG.FromMesh(cutter));
        }
        const cut = solid.toMesh("rail-shape-cut", null, scene);
        shape = { data: BABYLON.VertexData.ExtractFromMesh(cut, true, true), cutouts: true };
        cut.dispose();
      } catch (error) {
        console.warn("CSG rail cutouts unavailable; using visible surface markers", error);
      } finally {
        for (const c of cutters) c.dispose();
      }
    }
    box.dispose();
    railShapeCache.set(type, shape);
    return shape;
  }

  function buildRailMesh(rail, spec) {
    const length = Number(spec.length_cm);
    const heightUnits = Number(spec.height || 1);
    const center = railPoint(rail, length / 2);
    const shape = railShape(rail.rail_type, spec);
    const mesh = new BABYLON.Mesh("rail-" + rail.id, scene);
    shape.data.applyToMesh(mesh);
    mesh.material = material("railMat", palette.rail);
    mesh.rotation.y = -(Number(rail.yaw_deg || 0) * Math.PI) / 180;
    mesh.position = world(center.x, center.y, Number(rail.z_units) + heightUnits / 2);
    mesh.computeWorldMatrix(true);
    return { mesh, cutouts: shape.cutouts, grooveCutout: shape.cutouts };
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
    if (!grooveCutout && spec.shape !== "plate") {
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

  // CSG is slow (tens of ms per block): build each block shape once and copy
  // its vertices for every other block of the same type.
  const blockShapeCache = new Map();
  function buildBlockMesh(part, heightCm, ports, sideEntryNotches) {
    const key = [part.part_type, heightCm, ports.join(","), [...sideEntryNotches].join(",")].join("|");
    const cached = blockShapeCache.get(key);
    if (cached) {
      const mesh = new BABYLON.Mesh("part-" + part.id, scene);
      cached.data.applyToMesh(mesh);
      mesh.material = material("partMat", palette[part.part_type] || palette.default);
      return { mesh, cutouts: cached.cutouts };
    }
    const built = buildBlockMeshUncached(part, heightCm, ports, sideEntryNotches);
    blockShapeCache.set(key, { data: BABYLON.VertexData.ExtractFromMesh(built.mesh, true, true), cutouts: built.cutouts });
    return built;
  }

  function buildBlockMeshUncached(part, heightCm, ports, sideEntryNotches) {
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
      connector_protrusion_cm: catalogHeightUnits === standardBlockUnits() ? CONNECTOR_PROTRUSION_CM : null,
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

  // Path through a twist: the marble rolls down the chute from where it got
  // on (a chute hole or the tip) to the rim, veers right and circles the
  // funnel counter-clockwise (seen from above) into the center hole. Empty
  // unless `to` is a twist's center hole.
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
    // Chute: from where the marble enters (a chute hole, or the tip) down to
    // the rim, one unit lower.
    const a = railNodeStation(from);
    let s0 = a && a.rail === b.rail ? a.s : holes[0];
    const fromPart = (layout.parts || []).find(p => p.id === from.slice(0, from.indexOf(":")));
    if (fromPart) {
      let best = Infinity;
      for (const x of holes.slice(0, -1)) {
        const p = railPoint(b.rail, x);
        const dist = Math.hypot(p.x - Number(fromPart.x_cm), p.y - Number(fromPart.y_cm));
        if (dist < best) { best = dist; s0 = x; }
      }
    }
    const s1 = b.s - rimR;
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
    // Seesaws on the way flip when the marble reaches their top.
    const events = [];
    run.path.forEach(node => {
      const [id, port] = [node.slice(0, node.indexOf(":")), node.slice(node.indexOf(":") + 1)];
      if (!seesaws.has(id) || (port !== "a_side" && port !== "b_side")) return;
      const top = routingNodePosition(id + ":top");
      if (!top) return;
      let best = 0;
      points.forEach((p, i) => { if (BABYLON.Vector3.DistanceSquared(p, top) < BABYLON.Vector3.DistanceSquared(points[best], top)) best = i; });
      events.push({ at: lengths[best], id, port });
    });
    flyingMarbles.push({ mesh, points, lengths, travelled: 0, source, run, done: false, events });
    return true;
  }

  function stepMarbles() {
    if (!flyingMarbles.length) return;
    const dt = Math.min(engine.getDeltaTime() / 1000, 0.1);
    for (const marble of flyingMarbles) {
      marble.travelled += MARBLE_SPEED_CM_S * dt;
      for (const event of marble.events || []) {
        if (!event.done && marble.travelled >= event.at) { event.done = true; tipSeesaw(event.id, event.port); }
      }
      const total = marble.lengths[marble.lengths.length - 1];
      if (marble.travelled >= total) {
        marble.mesh.position = marble.points[marble.points.length - 1].clone();
        marble.done = true;
        let fall = marble.fall || 0;   // the last fall ends on the ground
        for (let k = (marble.segment || 1); k < marble.points.length; k++) {
          if (isFalling(marble, k)) fall += marble.points[k - 1].y - marble.points[k].y;
        }
        if (fall > 1.5) sound.land(fall);
        continue;
      }
      let i = 1;
      while (marble.lengths[i] < marble.travelled) i++;
      if (marble.segment !== i) {   // sound: a fall ending is a landing
        const falling = isFalling(marble, i);
        for (let k = (marble.segment || 1); k < i; k++) {
          if (isFalling(marble, k)) marble.fall = (marble.fall || 0) + marble.points[k - 1].y - marble.points[k].y;
        }
        if (!falling && (marble.fall || 0) > 1.5) { sound.land(marble.fall); marble.fall = 0; }
        if (!falling && (marble.fall || 0) <= 1.5) marble.fall = 0;
        marble.segment = i;
      }
      const span = marble.lengths[i] - marble.lengths[i - 1] || 1;
      const t = (marble.travelled - marble.lengths[i - 1]) / span;
      marble.mesh.position = BABYLON.Vector3.Lerp(marble.points[i - 1], marble.points[i], t);
    }
    sound.rolling(flyingMarbles.filter(m => !m.done && !isFalling(m, m.segment || 1)).length);
    for (let i = flyingMarbles.length - 1; i >= 0; i--) {
      const marble = flyingMarbles[i];
      if (!marble.done) continue;
      flyingMarbles.splice(i, 1);
      setTimeout(() => marble.mesh.dispose(), 400);
      if (marble.run.exit) {
        if (flyingMarbles.length < 3) sound.exit();
        recordArrival(marble.source, marble.run.exit);
        flashExitRow(marble.run.exit);
      }
    }
  }

  // A path segment that drops more than it runs (a free fall or a block drop).
  function isFalling(marble, i) {
    const a = marble.points[i - 1], b = marble.points[i];
    if (!a || !b) return false;
    const dy = a.y - b.y;
    return dy > 0.6 && dy > Math.hypot(b.x - a.x, b.z - a.z);
  }

  function cancelMarbles() {
    for (const marble of flyingMarbles) marble.mesh.dispose();
    flyingMarbles.length = 0;
    sound.rolling(0);
  }

  function rollStatus(text) {
    document.getElementById("routeStatus").textContent = text;
  }

  function rollOne() {
    sound.unlock();
    const source = document.getElementById("routeSource").value;
    if (!routingGraph || !source || flyingMarbles.length >= 40) return;
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

  // Full layout validation (viewer/validation.js mirrors the Python validators).
  let lastValidation = null;
  function updateValidation() {
    const box = document.getElementById("validationStatus");
    if (!box || !window.MarbleValidation) return;
    const query = layout.routing_query || {};
    const key = ref => (ref ? ref.component_id + ":" + ref.port : null);
    const sinks = (query.sinks || []).map(key);
    let result;
    try {
      // In Build mode only part is placed: check what stands, not the route.
      result = MarbleValidation.validateLayout(layout, catalog,
        !build.on && query.source && sinks.length ? { source: key(query.source), sinks } : {});
    } catch (error) {
      box.textContent = "Validation error: " + error.message;
      lastValidation = { valid: false, reasons: ["validation error: " + error.message] };
      return;
    }
    const reasons = [
      ...result.assembly.reasons,
      ...(result.global_stability.stable ? [] : result.global_stability.reasons.length
        ? result.global_stability.reasons : ["global stability not evaluable"]),
      ...result.local_statics.reasons,
      ...(result.local_statics.statics?.reasons || []),
      ...(result.connectivity?.reasons || []),
      ...result.marble_clearance,
    ];
    lastValidation = { valid: result.valid, reasons: [...new Set(reasons)] };
    box.className = "validation-status " + (result.valid ? "ok" : "bad");
    box.textContent = result.valid
      ? "Valid: assembly, stability, statics" + (result.connectivity ? ", routing" : "") + " and clearance pass."
      : "Not valid:\n" + [...new Set(reasons)].slice(0, 12).join("\n");
  }

  function updateSummary() {
    const summary = document.getElementById("summary");
    const rows = [
      ["Rails", (layout.rails || []).length],
      ["Parts", (layout.parts || []).length],
      ["Ground level", "z=0 (0 cm)"],
      ["Support links", (layout.supports || []).length],
      ["Route links", (layout.route_links || []).length],
      ["Height scale", HEIGHT_SCALE_CM + " cm per level (measured; 5 levels = one 6 cm block)"],
      ["Standard block", standardBlockUnits() + " levels = " + +(standardBlockUnits() * HEIGHT_SCALE_CM).toFixed(2) + " cm stacked"],
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
      "Ground level: z=0 (0 cm) · 1 level = " + HEIGHT_SCALE_CM + " cm";
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
    curved_long: "long curve", s_curve: "S-curve", spiral: "twist", cover: "cover", seesaw: "seesaw",
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

  // Simple top-view-ish icons for the parts board (step 0).
  function partIcon(type) {
    const rail = palette.rail, edge = "rgba(0,0,0,.35)";
    const color = palette[type] || palette.default;
    const holes = (w, xs) => xs.map(x => '<circle cx="' + x + '" cy="20" r="3.2" fill="#3b2f1f" opacity=".55"/>').join("");
    const bar = (w, xs) => '<svg viewBox="0 0 ' + (w + 4) + ' 40" width="' + (w + 4) + '" height="40"><rect x="2" y="13" width="' + w +
      '" height="14" rx="2" fill="' + rail + '" stroke="' + edge + '"/>' + holes(w, xs) + "</svg>";
    switch (type) {
      case "straight_short": return bar(56, [6, 17, 46, 56]);
      case "straight_long": return bar(100, [6, 16, 92, 102]);
      case "straight_long_center": return bar(100, [6, 16, 54, 92, 102]);
      case "curved_short": return '<svg viewBox="0 0 60 40" width="60" height="40"><path d="M6 34 A 40 40 0 0 1 54 34" fill="none" stroke="' + rail + '" stroke-width="12"/></svg>';
      case "curved_long": return '<svg viewBox="0 0 84 44" width="84" height="44"><path d="M6 38 A 38 34 0 0 1 78 38" fill="none" stroke="' + rail + '" stroke-width="12"/></svg>';
      case "s_curve": return '<svg viewBox="0 0 96 40" width="96" height="40"><path d="M6 30 C 30 2, 42 2, 48 20 S 66 38, 90 10" fill="none" stroke="' + rail + '" stroke-width="11"/></svg>';
      case "spiral": return '<svg viewBox="0 0 76 44" width="76" height="44"><circle cx="54" cy="22" r="19" fill="' + palette.twist + '" stroke="' + edge + '"/><circle cx="54" cy="22" r="11" fill="none" stroke="#a57f45" stroke-width="2"/><circle cx="54" cy="22" r="3" fill="#3b2f1f"/><rect x="2" y="15" width="34" height="14" rx="2" fill="' + palette.twist + '" stroke="' + edge + '"/></svg>';
      case "cover": return '<svg viewBox="0 0 24 40" width="24" height="40"><circle cx="12" cy="20" r="8" fill="#f59e0b" stroke="' + edge + '"/></svg>';
      case "purple_drop": return '<svg viewBox="0 0 40 40" width="40" height="40"><rect x="2" y="14" width="36" height="12" rx="2" fill="' + color + '" stroke="' + edge + '"/></svg>';
      case "wooden_foundation": return '<svg viewBox="0 0 40 40" width="40" height="40"><rect x="2" y="16" width="36" height="9" rx="2" fill="' + color + '" stroke="' + edge + '"/></svg>';
      default: return '<svg viewBox="0 0 40 40" width="40" height="40"><rect x="2" y="2" width="36" height="36" rx="4" fill="' + color + '" stroke="' + edge + '"/><circle cx="20" cy="20" r="6" fill="rgba(0,0,0,.35)"/></svg>';
    }
  }

  function renderPartsBoard() {
    const info = fullLayout.bill_of_materials;
    const used = info?.used || MarbleAssembly.billOfMaterials(fullLayout);
    const pooled = { straight_long_center: "straight_long", spiral_large: "spiral", spiral_small: "spiral" };
    const check = info?.check ? new Map(info.check.map(r => [r.part, r])) : null;
    const order = t => (/straight|curve|s_curve/.test(t) ? 0 : t === "spiral" ? 1 : t === "cover" ? 3 :
      t === "wooden_foundation" || t === "purple_drop" ? 4 : 2);
    const tiles = Object.entries(used).sort(([a], [b]) => order(a) - order(b) || (a < b ? -1 : 1)).map(([type, n]) => {
      const short = check?.get(pooled[type] || type)?.short;
      const wide = order(type) <= 1 ? " is-wide" : "";
      return '<div class="part-tile' + wide + (short ? " is-short" : "") + '"><div class="part-icon">' + partIcon(type) +
        '</div><div class="part-count">×' + n + '</div><div class="part-name">' + esc(partName(type)) +
        (short ? ' <b class="short">short ' + short + "</b>" : "") + "</div></div>";
    }).join("");
    const total = Object.values(used).reduce((a, b) => a + b, 0);
    document.getElementById("partsBoard").innerHTML = '<div class="parts-board-head"><h2>Parts for this build</h2>' +
      '<span class="muted">' + total + " pieces · press → to start</span></div>" +
      '<div class="parts-grid">' + tiles + "</div>";
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
    document.getElementById("buildBar").hidden = !build.on;
    document.getElementById("partsBoard").hidden = !build.on || build.step !== 0;
    if (!build.on || !fullLayout) return;
    const step = build.plan[build.step];
    const done = loadDone();
    const last = build.plan.length - 1;
    document.getElementById("buildStepTitle").textContent =
      "Step " + build.step + " / " + last + " · " + stepTitle(step, build.step);
    document.getElementById("buildBarStep").textContent = "Step " + build.step + " / " + last;
    if (build.step === 0) renderPartsBoard();
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
    if (on && edit.on) edit.on = false;
    if (on && review.on) review.on = false;
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

  function setLayout(data, opts = {}) {
    if (!opts.edit) resetEdit(data);
    fullLayout = data;
    if (!opts.edit) { review.draft = null; review.open = null; loadReview(); }
    layout = data;
    build.plan = MarbleAssembly.buildPlan(fullLayout);
    build.graph = MarbleRouting.buildGraph(fullLayout, catalog);
    build.onRoute = routeParts();
    build.fed = new Set(Object.values(build.graph.edges).flat());
    build.step = Math.min(build.step, build.plan.length - 1);
    if (!opts.edit) build.reframe = true;  // a new layout: frame it once, then keep the view
    renderAll(opts.changed || null);
  }

  // Tag every mesh with the component that made it (Build and Edit modes use it).
  function owned(owner, draw) {
    const before = scene.meshes.length;
    draw();
    for (const mesh of scene.meshes.slice(before)) mesh.metadata = { ...(mesh.metadata || {}), owner };
  }

  function renderComponent(id) {
    const rail = (layout.rails || []).find(r => r.id === id);
    if (rail) return owned(rail.id, () => renderRail(rail));
    const part = (layout.parts || []).find(p => p.id === id);
    if (!part) return;
    const special = catalog.special_parts?.[part.part_type];
    owned(part.id, () => (special?.shape === "twist_funnel" ? renderTwist(part, special)
      : special?.shape === "seesaw" ? renderSeesaw(part, special) : renderPart(part)));
  }

  // Seesaw: a red rhombus plate (user) on a pivot over the rail's center
  // hole, lying along the rail and tipped toward one arm, which rests near
  // the rail. Marbles roll down the low arm; the plate flips to the side each
  // rolled marble takes (the real one switches every ~5 marbles).
  const SEESAW_TILT = 0.21;  // rad, about 12 degrees
  const seesaws = new Map();  // part id -> { pivot, target }
  function renderSeesaw(part, spec) {
    const length = Number(spec.footprint_cm?.length ?? 19);
    const width = Number(spec.footprint_cm?.width ?? 3);
    const height = geometryValue(spec.body_height_cm, 8);
    const L = length / 2;
    // Short diagonal chosen so the tipped plate is `height` tall with its low
    // corner on the rail: pivot = L sin t + h cos t, top = 2 x pivot.
    const pivotY = height / 2;
    const h = Math.max(1.2, (pivotY - L * Math.sin(SEESAW_TILT)) / Math.cos(SEESAW_TILT));
    const root = new BABYLON.TransformNode("seesaw-" + part.id, scene);
    root.position = world(part.x_cm, part.y_cm, Number(part.z_units));
    root.rotation.y = -(Number(part.rotation_deg || 0) * Math.PI) / 180;
    const red = material("seesawMat", palette.seesaw);
    const wood = material("seesawPivotMat", "#e7c9a0");
    const stand = BABYLON.MeshBuilder.CreateBox("seesaw-stand-" + part.id,
      { width: 2.4, height: pivotY, depth: width * 0.7 }, scene);
    stand.parent = root;
    stand.position.y = pivotY / 2;
    stand.material = red;
    const pivot = new BABYLON.TransformNode("seesaw-pivot-" + part.id, scene);
    pivot.parent = root;
    pivot.position.y = pivotY;
    const shape = [new BABYLON.Vector3(-L, 0, 0), new BABYLON.Vector3(0, h, 0),
      new BABYLON.Vector3(L, 0, 0), new BABYLON.Vector3(0, -h, 0), new BABYLON.Vector3(-L, 0, 0)];
    const plate = BABYLON.MeshBuilder.ExtrudeShape("seesaw-plate-" + part.id, {
      shape, path: [new BABYLON.Vector3(0, 0, -width / 2), new BABYLON.Vector3(0, 0, width / 2)],
      cap: BABYLON.Mesh.CAP_ALL, sideOrientation: BABYLON.Mesh.DOUBLESIDE,
    }, scene);
    plate.parent = pivot;
    plate.material = red;
    plate.enableEdgesRendering();
    plate.edgesWidth = 2;
    plate.edgesColor = new BABYLON.Color4(0.45, 0.05, 0.05, 1);
    for (const side of [-1, 1]) {
      const disc = BABYLON.MeshBuilder.CreateCylinder("seesaw-disc-" + part.id + side,
        { diameter: 2.6, height: 0.12, tessellation: 32 }, scene);
      disc.parent = pivot;
      disc.rotation.x = Math.PI / 2;
      disc.position.z = side * (width / 2 + 0.06);
      disc.material = wood;
    }
    const state = seesaws.get(part.id);
    const tilt = state ? state.target : -SEESAW_TILT;  // starts low toward end B
    pivot.rotation.z = tilt;
    seesaws.set(part.id, { pivot, target: tilt });
    const info = {
      id: part.id, kind: "part", type: part.part_type, mass_g: blockMass(part.part_type),
      z_units: part.z_units, rotation_deg: part.rotation_deg || 0,
      footprint_cm: { length, width }, body_height_cm: height, shape: "rhombus plate on a pivot",
      routing: "random distributor (real seesaw switches every ~5 marbles)",
    };
    addSelectable(plate, info);
    addSelectable(stand, info);
  }

  // Low arm toward the side the marble takes ("a_side" = toward end A).
  function tipSeesaw(id, port) {
    const state = seesaws.get(id);
    if (!state) return;
    const target = port === "a_side" ? SEESAW_TILT : -SEESAW_TILT;
    if (state.target !== target) sound.seesaw();
    state.target = target;
  }
  scene.onBeforeRenderObservable.add(() => {
    const dt = Math.min(engine.getDeltaTime() / 1000, 0.1);
    for (const state of seesaws.values()) {
      if (state.pivot.isDisposed()) continue;
      const delta = state.target - state.pivot.rotation.z;
      if (Math.abs(delta) > 1e-4) state.pivot.rotation.z += Math.sign(delta) * Math.min(Math.abs(delta), 2.5 * dt);
    }
  });

  // Dispose the meshes of some owners only (edit mode redraws what changed).
  function disposeOwned(owners) {
    for (const mesh of scene.meshes.slice()) {
      if (owners.has(mesh.metadata?.owner) && !mesh.isDisposed()) mesh.dispose();
    }
    for (const list of Object.values(groups)) {
      const keep = list.filter(m => m && !m.isDisposed());
      list.length = 0;
      list.push(...keep);
    }
  }

  // changed: ids whose meshes are stale (edit mode); otherwise redraw all.
  function renderAll(changed = null) {
    layout = build.on ? buildView() : fullLayout;
    document.getElementById("allowSideEntryPlusOne").checked =
      Boolean(layout.routing_options?.allow_side_entry_plus_one);
    if (changed && !build.on) {
      disposeOwned(new Set([...changed, "__seams", "__supports"]));
      for (const list of [groups.com, groups.polygon]) {
        for (const mesh of list) if (!mesh.isDisposed()) mesh.dispose();
        list.length = 0;
      }
      for (const id of changed) renderComponent(id);
    } else {
      clearRendered();
      for (const rail of layout.rails || []) renderComponent(rail.id);
      for (const part of layout.parts || []) renderComponent(part.id);
    }
    owned("__seams", renderStackSeams);
    owned("__supports", renderSupports);
    renderRouting();
    renderComAndPolygon();
    updateSummary();
    updateValidation();
    applyVisibility();
    if (build.on) decorateBuildStep();
    else if (build.reframe) { build.reframe = false; fitCamera(); }
    if (edit.on) decorateEdit();
    else if (changed) for (const mesh of scene.meshes) if (mesh.metadata?.owner !== undefined) mesh.visibility = 1;
    renderBuildPanel();
    renderEditPanel();
    renderReview();
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
    layoutOrigin = path;
    setLayout(jsyaml.load(await response.text()));
  }

  async function initialize() {
    try {
      catalog = await loadCatalog();
      applyCatalogGeometry();
      // The example list is the current review gallery (its index), so it
      // never points at a layout a gallery rebuild removed.
      const select = document.getElementById("exampleSelect");
      try {
        const index = await (await fetch(DATA_ROOT + "examples/gallery/index.json")).json();
        const options = (index.layouts || []).map(entry => {
          const option = document.createElement("option");
          option.value = entry.file;
          const tags = (entry.tags || []).filter(t => t !== "braced").slice(0, 2).join(", ");
          option.textContent = (tags ? tags + " · " : "") + entry.id;
          return option;
        });
        select.prepend(...options);
        if (options.length) select.value = options[0].value;
      } catch (error) {
        console.warn("Gallery index unavailable; examples limited", error);
      }
      // ?layout=examples/... opens a specific layout (e.g. from the gallery).
      const requested = new URLSearchParams(window.location.search).get("layout");
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
      // ?play=1 opens in play mode (the home-screen app starts this way).
      if (params.get("play") === "1") setTimeout(() => setPlayMode(true), 0);
    } catch (error) {
      document.getElementById("layoutMeta").textContent = String(error);
      console.error(error);
    }
  }

  document.getElementById("exampleSelect").addEventListener("change", event => {
    const generated = generatedLayouts.get(event.target.value);
    if (generated) { build.step = 0; layoutOrigin = "generated in the browser"; setLayout(structuredClone(generated)); return; }
    loadExample(event.target.value).catch(console.error);
  });

  // ---- Edit mode -------------------------------------------------------
  // Block edits (type, rotation, covers, free-standing stacks) are field
  // changes made here. Rail rewrites (curve, shorten) are the generator's own
  // Python passes, run in the worker (web.edit_json), so their geometry has
  // one implementation. Every change is validated by viewer/validation.js;
  // invalid results are kept (and shown) so the user can see why, then undo.
  const edit = { on: false, selected: null, undo: [], redo: [], available: null, origin: null,
                 pyReady: false, busy: false, note: "", pending: new Map() };
  let editRequestId = 0;
  const POOLED = { straight_long_center: "straight_long", spiral_large: "spiral", spiral_small: "spiral" };

  function resetEdit(data) {
    Object.assign(edit, { selected: null, undo: [], redo: [], note: "", busy: false });
    edit.origin = data?.layout_id || data?.name || null;
    const check = data?.bill_of_materials?.check;
    edit.available = check ? Object.fromEntries(check.map(r => [r.part, r.available])) : null;
  }

  function componentOf(id) {
    const rail = (fullLayout?.rails || []).find(r => r.id === id);
    if (rail) return { kind: "rail", item: rail };
    const part = (fullLayout?.parts || []).find(p => p.id === id);
    return part ? { kind: "part", item: part } : null;
  }

  function editedClone() {
    const data = structuredClone(fullLayout);
    if (data.layout_id) {
      data.name = data.layout_id + " (edited)";
      delete data.layout_id;
    }
    delete data.metrics;
    delete data.inventory_used;
    return data;
  }

  const splitNode = node => {
    const i = node.indexOf(":");
    return { component_id: node.slice(0, i), port: node.slice(i + 1) };
  };

  // The exits follow the build: after a change the routing query lists
  // whatever the marble now reaches from the same input.
  function exitsFrom(data) {
    const source = data.routing_query?.source;
    if (!source) return null;
    try {
      const graph = MarbleRouting.buildGraph(data, catalog);
      return MarbleRouting.analyzeOutcomes(data, catalog, graph, source.component_id + ":" + source.port).exits;
    } catch (error) {
      return null;
    }
  }

  function withCurrentExits(data) {
    const exits = exitsFrom(data);
    if (exits) data.routing_query = { ...data.routing_query, sinks: exits.map(e => splitNode(e.node)) };
    return data;
  }

  function validateData(data) {
    const q = data.routing_query || {};
    const key = ref => ref.component_id + ":" + ref.port;
    try {
      return MarbleValidation.validateLayout(data, catalog,
        q.source && q.sinks?.length ? { source: key(q.source), sinks: q.sinks.map(key) } : {}).valid;
    } catch (error) {
      return false;
    }
  }

  // Components whose data differ between two layouts (added, removed or changed).
  function changedIds(a, b) {
    const index = data => new Map([...(data.rails || []), ...(data.parts || [])].map(c => [c.id, JSON.stringify(c)]));
    const x = index(a), y = index(b);
    const out = new Set();
    for (const [id, v] of x) if (y.get(id) !== v) out.add(id);
    for (const id of y.keys()) if (!x.has(id)) out.add(id);
    return out;
  }

  function showEdited(next) {
    const changed = changedIds(fullLayout, next);
    setLayout(next, { edit: true, changed });
  }

  function commitEdit(next, note) {
    const before = fullLayout;
    edit.undo.push(before);
    edit.redo = [];
    edit.note = note || "";
    showEdited(withCurrentExits(next));
  }

  function undoEdit() {
    if (!edit.undo.length || edit.busy) return;
    edit.redo.push(fullLayout);
    edit.note = "Undone.";
    showEdited(edit.undo.pop());
  }

  function redoEdit() {
    if (!edit.redo.length || edit.busy) return;
    edit.undo.push(fullLayout);
    edit.note = "Redone.";
    showEdited(edit.redo.pop());
  }

  // Selecting only moves the outline and redraws the panel: no scene rebuild.
  function selectEdit(id) {
    edit.selected = id;
    decorateEdit();
    renderEditPanel();
  }

  // ---- block edits
  function blockHeight(type) {
    const spec = catalog.routing_blocks?.[type] || catalog.structural_parts?.[type];
    return spec?.height != null ? Number(spec.height) : null;
  }

  function swapChoices(type) {
    const height = blockHeight(type);
    if (height == null) return [];
    return [...Object.keys(catalog.routing_blocks || {}), ...Object.keys(catalog.structural_parts || {})]
      .filter(t => t !== type && blockHeight(t) === height);
  }

  function rotatePart(id, delta) {
    const data = editedClone();
    const part = data.parts.find(p => p.id === id);
    if (!part) return;
    part.rotation_deg = (((Number(part.rotation_deg) || 0) + delta) % 360 + 360) % 360;
    if (!part.rotation_deg) delete part.rotation_deg;
    commitEdit(data, "Rotated " + id + " by " + delta + "°.");
  }

  function retypePart(id, type) {
    const data = editedClone();
    const part = data.parts.find(p => p.id === id);
    if (!part) return;
    const was = part.part_type;
    part.part_type = type;
    commitEdit(data, id + ": " + partName(was) + " → " + partName(type) + ".");
  }

  // A free-standing stack (counterweight) that does not hold the input.
  function freeStackOf(id) {
    const source = fullLayout.routing_query?.source?.component_id;
    const support = (fullLayout.supports || []).find(s =>
      s.upper_rail_id == null && (s.stack_part_ids || []).includes(id));
    if (!support || (support.stack_part_ids || []).includes(source)) return null;
    return support;
  }

  function removeFreeStack(id) {
    const support = freeStackOf(id);
    if (!support) return;
    const data = editedClone();
    const gone = new Set(support.stack_part_ids);
    data.parts = data.parts.filter(p => !gone.has(p.id));
    data.supports = data.supports.filter(s => !(s.upper_rail_id == null && (s.stack_part_ids || []).includes(id)));
    edit.selected = null;
    commitEdit(data, "Removed the free-standing stack " + [...gone].join(", ") + ".");
  }

  function toggleCover(railId, index) {
    const data = editedClone();
    const rail = data.rails.find(r => r.id === railId);
    const states = { ...(rail.hole_states || {}) };
    const state = states[index] ?? "open";
    if (state === "open") states[index] = "covered";
    else if (state === "covered") delete states[index];
    else return;
    rail.hole_states = states;
    commitEdit(data, railId + " hole " + index + ": " + (state === "open" ? "cover added" : "cover removed") + ".");
  }

  // ---- rail rewrites (Python, in the worker)
  function pyEdit(op) {
    const id = "edit-" + (++editRequestId);
    return new Promise((resolve, reject) => {
      edit.pending.set(id, { resolve, reject });
      pyWorker(editListener).postMessage({
        type: "edit", id, base: new URL(DATA_ROOT, window.location.href).href,
        request: { layout: fullLayout, op },
      });
    });
  }

  function editListener(message) {
    if (message.type === "status" && edit.on && edit.busy) {
      edit.note = message.text;
      renderEditPanel();
    }
    const pending = edit.pending.get(message.id);
    if (!pending) return;
    edit.pending.delete(message.id);
    if (message.type === "edited") pending.resolve(message.response);
    else if (message.type === "error") pending.reject(new Error(message.message));
  }

  async function railEdit(op, railId, turn) {
    if (edit.busy) return;
    edit.busy = true;
    edit.note = "Working…";
    renderEditPanel();
    try {
      if (!edit.pyReady) edit.note = "Loading Python for rail rewrites (first time only, ~10 s)…";
      renderEditPanel();
      const response = await pyEdit({ op, rail: railId, turn });
      edit.pyReady = true;
      if (response.error) throw new Error(response.error);
      const base = editedClone();
      const trials = response.candidates.map(c => withCurrentExits({ ...structuredClone(base), ...c }));
      const chosen = trials.find(validateData) || trials[0];
      edit.busy = false;
      commitEdit(chosen, railId + ": " + (op === "curve" ? "curve to the " + turn : "shortened") +
        (trials.length > 1 ? " (" + trials.length + " placements tried)" : "") + ".");
    } catch (error) {
      edit.busy = false;
      edit.note = error.message;
      renderEditPanel();
    }
  }

  // ---- panel and highlight
  // Selected component in color with an outline; the rest fades back.
  function decorateEdit() {
    for (const mesh of scene.meshes) {
      const owner = mesh.metadata?.owner;
      if (owner === undefined || mesh.isDisposed()) continue;
      const mine = edit.selected && owner === edit.selected;
      mesh.visibility = !edit.selected || mine ? 1 : 0.28;
      mesh.renderOutline = Boolean(mine && mesh.metadata?.info?.id === owner);
      if (mesh.renderOutline) {
        mesh.outlineColor = BABYLON.Color3.FromHexString("#facc15");
        mesh.outlineWidth = 0.18;
      }
    }
  }

  function shortages() {
    if (!edit.available) return [];
    const need = {};
    for (const [type, n] of Object.entries(MarbleAssembly.billOfMaterials(fullLayout))) {
      const key = POOLED[type] || type;
      need[key] = (need[key] || 0) + n;
    }
    return Object.entries(need)
      .filter(([key, n]) => n > (edit.available[key] ?? 0))
      .map(([key, n]) => ({ part: key, needed: n, available: edit.available[key] ?? 0 }));
  }

  function editChecksHtml() {
    const lines = [];
    const valid = lastValidation?.valid;
    lines.push(valid ? "<b>Valid</b>: stands, routes and clears."
      : "<b>Not valid</b>:<br>" + (lastValidation?.reasons || []).slice(0, 6).map(esc).join("<br>"));
    const exits = exitsFrom(fullLayout) || [];
    const open = exits.filter(e => e.kind === "rail_end");
    lines.push("Exits: " + exits.length + (exits.length > 2 ? ' <span class="edit-warn">(more than 2)</span>' : "") +
      (open.length ? ' <span class="edit-warn">· ' + open.length + " roll off a rail end</span>" : ""));
    const short = shortages();
    if (edit.available) {
      lines.push(short.length
        ? '<span class="edit-short">Short: ' + short.map(r => esc(partName(r.part)) + " " + r.needed + "/" + r.available).join(", ") + "</span>"
        : "Parts: within the sets.");
    }
    return { html: lines.join("<br>"), ok: valid && exits.length <= 2 && !open.length && !short.length };
  }

  function button(label, attrs, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = label;
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "disabled") b.disabled = Boolean(v); else b.setAttribute(k, v);
    }
    b.addEventListener("click", onClick);
    return b;
  }

  function row(label, ...children) {
    const div = document.createElement("div");
    div.className = "edit-row";
    const span = document.createElement("span");
    span.className = "label";
    span.textContent = label;
    div.append(span, ...children);
    return div;
  }

  function renderEditPanel() {
    const toggle = document.getElementById("editToggle");
    toggle.textContent = edit.on ? "Exit edit" : "Edit";
    toggle.setAttribute("aria-pressed", String(edit.on));
    document.getElementById("editPanel").hidden = !edit.on;
    document.getElementById("editBar").hidden = !edit.on;
    if (!edit.on || !fullLayout) { renderEditPopup(); return; }
    document.getElementById("editUndo").disabled = !edit.undo.length || edit.busy;
    document.getElementById("editRedo").disabled = !edit.redo.length || edit.busy;
    const checks = editChecksHtml();
    const box = document.getElementById("editCheck");
    box.className = "validation-status " + (checks.ok ? "ok" : lastValidation?.valid ? "warn" : "bad");
    box.innerHTML = (edit.undo.length ? edit.undo.length + " change" + (edit.undo.length > 1 ? "s" : "") + " · " : "") + checks.html;
    document.getElementById("editNote").textContent = edit.note;
    const body = document.getElementById("editBody");
    body.replaceChildren();
    const pick = document.createElement("select");
    pick.setAttribute("aria-label", "Select a rail or block");
    pick.innerHTML = '<option value="">Select a rail or block…</option>' +
      '<optgroup label="Rails">' + (fullLayout.rails || []).map(r =>
        '<option value="' + esc(r.id) + '">' + esc(r.id + " · " + partName(r.rail_type) + " · z" + r.z_units) + "</option>").join("") + "</optgroup>" +
      '<optgroup label="Blocks">' + (fullLayout.parts || []).map(p =>
        '<option value="' + esc(p.id) + '">' + esc(p.id + " · " + partName(p.part_type) + " · z" + p.z_units) + "</option>").join("") + "</optgroup>";
    pick.value = edit.selected || "";
    pick.addEventListener("change", () => { edit.popupAt = null; selectEdit(pick.value || null); });
    body.append(pick);
    const found = edit.selected && componentOf(edit.selected);
    if (!found) {
      body.append(Object.assign(document.createElement("p"), { className: "muted",
        textContent: "Click a rail or block in the 3D view, or pick one above." }));
      renderEditPopup();
      return;
    }
    body.append(...editActions(found));
    renderEditPopup();
  }

  // Title and action buttons for the selected component (panel and popup).
  function editActions(found) {
    const out = [];
    const title = document.createElement("h3");
    const item = found.item;
    const type = found.kind === "rail" ? item.rail_type : item.part_type;
    title.innerHTML = swatch(type) + esc(partName(type)) + ' <span class="muted">' + esc(item.id) + "</span>";
    out.push(title);
    if (found.kind === "part") {
      const special = catalog.special_parts?.[type] || catalog.special_rails?.[type];
      if (special) {
        out.push(row("", Object.assign(document.createElement("span"), {
          className: "muted", textContent: "Special part: no edits yet." })));
      } else {
        out.push(row("Rotate",
          button("↺ 90°", { title: "Rotate counter-clockwise (Shift+R)" }, () => rotatePart(item.id, -90)),
          button("↻ 90°", { title: "Rotate clockwise (R)" }, () => rotatePart(item.id, 90)),
          Object.assign(document.createElement("span"), { className: "muted", textContent: (item.rotation_deg || 0) + "°" })));
        const choices = swapChoices(type);
        if (choices.length) {
          out.push(row("Swap to", ...choices.map(t =>
            button(swatch(t) + esc(partName(t)), { title: "Same height: the stack stays closed" }, () => retypePart(item.id, t)))));
        }
        if (freeStackOf(item.id)) {
          out.push(row("Stack", button("Remove free-standing stack", {}, () => removeFreeStack(item.id))));
        }
      }
    } else {
      const straight = /^straight_/.test(item.rail_type);
      const can = op => !edit.busy && straight && (op === "curve" || item.rail_type !== "straight_short");
      out.push(row("Rewrite",
        button("Curve left", { disabled: !can("curve") }, () => railEdit("curve", item.id, "left")),
        button("Curve right", { disabled: !can("curve") }, () => railEdit("curve", item.id, "right")),
        button("Shorten", { disabled: !can("shorten") }, () => railEdit("shorten", item.id))));
      out.push(Object.assign(document.createElement("p"), {
        className: "muted small-note",
        textContent: straight ? "Rewrites keep every hole in use; if one cannot, the note below says why. The first rewrite loads Python (~10 s)."
          : "Only straight rails can be rewritten." }));
      const spec = railSpec(item.rail_type);
      const chips = (spec?.hole_positions_cm || []).map((_, i) => {
        const state = (item.hole_states || {})[i] ?? "open";
        const editable = state === "open" || state === "covered";
        return button(String(i), {
          class: "hole-chip", "data-state": state, disabled: !editable || edit.busy,
          title: "hole " + i + ": " + state + (editable ? " (click to " + (state === "open" ? "cover" : "uncover") + ")" : ""),
        }, () => toggleCover(item.id, i));
      });
      if (chips.length) out.push(row("Covers", ...chips));
    }
    return out;
  }

  // Popup next to the tapped part: the same actions, close at hand.
  function renderEditPopup() {
    const popup = document.getElementById("editPopup");
    const found = edit.on && edit.popupAt && edit.selected && componentOf(edit.selected);
    popup.hidden = !found;
    if (!found) return;
    const close = button("✕", { class: "popup-close", "aria-label": "Close" }, () => { edit.popupAt = null; renderEditPopup(); });
    const status = document.createElement("div");
    status.className = "popup-status " + (lastValidation?.valid ? "ok" : "bad");
    status.textContent = (lastValidation?.valid ? "✓ valid" : "✗ " + (lastValidation?.reasons?.[0] || "not valid")) +
      (edit.note ? " · " + edit.note : "");
    popup.replaceChildren(close, ...editActions(found), status);
    placeEditPopup();
  }

  // Screen rectangle (in the viewport panel) covered by an owner's meshes.
  function ownerScreenBox(owner) {
    const rect = canvas.getBoundingClientRect();
    const host = canvas.parentElement.getBoundingClientRect();
    const k = rect.width / engine.getRenderWidth();
    const viewport = camera.viewport.toGlobal(engine.getRenderWidth(), engine.getRenderHeight());
    const transform = scene.getTransformMatrix();
    let box = null;
    for (const mesh of scene.meshes) {
      if (mesh.isDisposed() || owner == null || mesh.metadata?.owner !== owner) continue;
      mesh.computeWorldMatrix(true);
      for (const v of mesh.getBoundingInfo().boundingBox.vectorsWorld) {
        const p = BABYLON.Vector3.Project(v, BABYLON.Matrix.Identity(), transform, viewport);
        const x = rect.left - host.left + p.x * k, y = rect.top - host.top + p.y * k;
        box = box ? { l: Math.min(box.l, x), r: Math.max(box.r, x), t: Math.min(box.t, y), b: Math.max(box.b, y) }
          : { l: x, r: x, t: y, b: y };
      }
    }
    return box;
  }

  // Put the popup beside the selected part, never on it: right, left,
  // below or above, whichever fits; tap point as a fallback.
  function placeEditPopup() {
    placePopup(document.getElementById("editPopup"), edit.selected, edit.popupAt);
  }

  // Screen point (in the viewport panel) of a world position.
  function screenPoint(v) {
    const rect = canvas.getBoundingClientRect();
    const host = canvas.parentElement.getBoundingClientRect();
    const k = rect.width / engine.getRenderWidth();
    const p = BABYLON.Vector3.Project(v, BABYLON.Matrix.Identity(), scene.getTransformMatrix(),
      camera.viewport.toGlobal(engine.getRenderWidth(), engine.getRenderHeight()));
    return { x: rect.left - host.left + p.x * k, y: rect.top - host.top + p.y * k };
  }

  // anchor: {x, y} in the panel, used when the owner has no meshes.
  function placePopup(popup, owner, anchor) {
    if (popup.hidden) return;
    const host = popup.parentElement.getBoundingClientRect();
    const w = popup.offsetWidth, h = popup.offsetHeight, gap = 16, pad = 8;
    const box = ownerScreenBox(owner) || (anchor
      ? { l: anchor.x - 6, r: anchor.x + 6, t: anchor.y - 6, b: anchor.y + 6 } : { l: pad, r: pad, t: pad, b: pad });
    const clampY = y => Math.max(pad, Math.min(host.height - h - pad, y));
    const clampX = x => Math.max(pad, Math.min(host.width - w - pad, x));
    const midY = (box.t + box.b) / 2 - h / 2, midX = (box.l + box.r) / 2 - w / 2;
    const options = [
      { ok: box.r + gap + w <= host.width - pad, x: box.r + gap, y: clampY(midY) },
      { ok: box.l - gap - w >= pad, x: box.l - gap - w, y: clampY(midY) },
      { ok: box.b + gap + h <= host.height - pad, x: clampX(midX), y: box.b + gap },
      { ok: box.t - gap - h >= pad, x: clampX(midX), y: box.t - gap - h },
    ];
    const pick = options.find(o => o.ok) || { x: clampX(box.r + gap), y: clampY(box.b + gap) };
    popup.style.left = pick.x + "px";
    popup.style.top = pick.y + "px";
  }

  function setEditMode(on) {
    if (on && build.on) {
      build.on = false;
      const url = new URL(window.location.href);
      url.searchParams.delete("mode");
      url.searchParams.delete("step");
      window.history.replaceState(null, "", url);
    }
    if (on && review.on) review.on = false;
    edit.on = on;
    if (!on) { edit.selected = null; edit.popupAt = null; }
    renderAll();
  }

  function exportEdited() {
    const data = structuredClone(fullLayout);
    if (edit.undo.length) {
      data.edited_from = edit.origin;
      delete data.metrics;
      delete data.inventory_used;
      const used = MarbleAssembly.billOfMaterials(data);
      data.bill_of_materials = { used };
      if (edit.available) {
        const need = {};
        for (const [type, n] of Object.entries(used)) need[POOLED[type] || type] = (need[POOLED[type] || type] || 0) + n;
        data.bill_of_materials.check = Object.entries(need).map(([part, needed]) => ({
          part, needed, available: edit.available[part] ?? 0, short: Math.max(0, needed - (edit.available[part] ?? 0)) }));
      }
    }
    const stem = (edit.origin || "layout") + (edit.undo.length ? "-edited" : "");
    downloadYaml(data, stem + ".yaml");
  }

  document.getElementById("editToggle").addEventListener("click", () => setEditMode(!edit.on));
  document.getElementById("editUndo").addEventListener("click", undoEdit);
  document.getElementById("editRedo").addEventListener("click", redoEdit);
  document.getElementById("editSave").addEventListener("click", exportEdited);
  window.addEventListener("keydown", event => {
    if (!edit.on || event.target.closest?.("input, select, textarea, dialog")) return;
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === "z") { event.preventDefault(); (event.shiftKey ? redoEdit : undoEdit)(); }
    else if (mod && event.key.toLowerCase() === "y") { event.preventDefault(); redoEdit(); }
    else if (event.key === "Escape") { edit.popupAt = null; selectEdit(null); }
    else if (!mod && event.key.toLowerCase() === "r" && edit.selected && componentOf(edit.selected)?.kind === "part") {
      const type = componentOf(edit.selected).item.part_type;
      if (!catalog.special_parts?.[type] && !catalog.special_rails?.[type]) rotatePart(edit.selected, event.shiftKey ? -90 : 90);
    }
  });

  // ---- Review mode -----------------------------------------------------
  // Notes pinned to a part, rail, rail hole, block port or a point in space,
  // with a kind that maps onto the generator design's layers (a physics
  // fact, a taste/style judgment, something good, an idea). Kept per layout
  // in this browser; "Copy for Claude" turns them into text for the chat.
  const REVIEW_STORE = "marble-run-review-v1:";
  const REVIEW_KINDS = {
    physics: { label: "Physics", hint: "wrong: would not stand or roll like this", color: "#ef4444" },
    taste: { label: "Taste", hint: "works, but I would not want it", color: "#f59e0b" },
    good: { label: "Good", hint: "keep doing this", color: "#22c55e" },
    idea: { label: "Idea", hint: "try something here", color: "#3b82f6" },
  };
  const VERDICTS = ["", "good", "doubtful", "bad"];
  const review = { on: false, notes: [], verdict: "", comment: "", open: null, draft: null };

  function reviewKey() {
    return REVIEW_STORE + (fullLayout?.layout_id || fullLayout?.name || "layout");
  }

  function loadReview() {
    try {
      const saved = JSON.parse(localStorage.getItem(reviewKey()) || "null");
      Object.assign(review, { notes: saved?.notes || [], verdict: saved?.verdict || "", comment: saved?.comment || "" });
    } catch (error) {
      Object.assign(review, { notes: [], verdict: "", comment: "" });
    }
  }

  function saveReview() {
    try {
      localStorage.setItem(reviewKey(), JSON.stringify({ notes: review.notes, verdict: review.verdict, comment: review.comment }));
    } catch (error) { /* storage blocked: notes live for this page only */ }
  }

  const round2 = v => Math.round(v * 100) / 100;

  // What was clicked, as a target a person and the solver can both read.
  function reviewTarget(mesh, point) {
    const info = mesh.metadata?.info;
    const at = { x_cm: round2(point.x), y_cm: round2(point.z), z_units: round2(point.y / HEIGHT_SCALE_CM) };
    if (info?.kind === "rail_hole") return { kind: "rail_hole", id: info.rail_id, hole: info.hole_index, at };
    if (info?.kind === "block_port") return { kind: "block_port", id: info.part_id, port: info.port, at };
    const owner = mesh.metadata?.owner;
    const found = owner !== undefined && componentOf(owner);
    if (found) return { kind: found.kind, id: owner, at };
    return { kind: "point", at };
  }

  function describeTarget(t) {
    const found = t.id && componentOf(t.id);
    const item = found?.item;
    if (t.kind === "rail_hole") {
      const state = item?.hole_states?.[t.hole] ?? "open";
      return t.id + " hole " + t.hole + " (" + state + ")";
    }
    if (t.kind === "block_port") return t.id + " port " + t.port + (item ? " (" + partName(item.part_type) + ")" : "");
    if (t.kind === "rail" && item) return t.id + " (" + partName(item.rail_type) + ", z" + item.z_units + ")";
    if (t.kind === "part" && item) {
      return t.id + " (" + partName(item.part_type) + ", z" + item.z_units + (item.rotation_deg ? ", " + item.rotation_deg + "°" : "") + ")";
    }
    if (t.id) return t.id + " (no longer in this layout)";
    return "point (" + t.at.x_cm + ", " + t.at.y_cm + ") cm at z" + t.at.z_units;
  }

  function noteAnchor(note) {
    return new BABYLON.Vector3(note.target.at.x_cm, note.target.at.z_units * HEIGHT_SCALE_CM, note.target.at.y_cm);
  }

  function startReviewNote(mesh, point) {
    review.draft = { target: reviewTarget(mesh, point), kind: "taste", text: "" };
    review.open = null;
    renderReview();
    document.querySelector("#reviewPopup textarea")?.focus();
  }

  function openReviewNote(n) {
    const note = review.notes.find(x => x.n === n);
    if (!note) return;
    review.draft = { ...note, target: { ...note.target } };
    review.open = n;
    renderReview();
  }

  function closeReviewNote() {
    review.draft = null;
    review.open = null;
    renderReview();
  }

  function commitReviewNote() {
    const d = review.draft;
    if (!d || !d.text.trim()) return closeReviewNote();
    if (review.open) {
      const note = review.notes.find(x => x.n === review.open);
      Object.assign(note, { kind: d.kind, text: d.text.trim() });
    } else {
      const n = review.notes.reduce((m, x) => Math.max(m, x.n), 0) + 1;
      review.notes.push({ n, kind: d.kind, text: d.text.trim(), target: d.target, label: describeTarget(d.target) });
    }
    saveReview();
    closeReviewNote();
  }

  function deleteReviewNote(n) {
    review.notes = review.notes.filter(x => x.n !== n);
    saveReview();
    closeReviewNote();
  }

  // Numbered pins at each note's point, colored by kind.
  function drawReviewPins() {
    for (const mesh of groups.review) if (!mesh.isDisposed()) mesh.dispose();
    groups.review.length = 0;
    if (!review.on) return;
    const pins = [...review.notes];
    if (review.draft && !review.open) pins.push({ n: "+", kind: review.draft.kind, target: review.draft.target });
    for (const note of pins) {
      const color = REVIEW_KINDS[note.kind]?.color || "#94a3b8";
      const tex = new BABYLON.DynamicTexture("review-pin-tex-" + note.n, { width: 128, height: 128 }, scene, true);
      tex.hasAlpha = true;
      const ctx = tex.getContext();
      ctx.clearRect(0, 0, 128, 128);
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(64, 64, 58, 0, Math.PI * 2); ctx.fill();
      ctx.lineWidth = 8; ctx.strokeStyle = "#ffffff"; ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 64px system-ui, sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(note.n), 64, 68);
      tex.update();
      const plane = BABYLON.MeshBuilder.CreatePlane("review-pin-" + note.n, { size: 3.4 }, scene);
      plane.position = noteAnchor(note).add(new BABYLON.Vector3(0, 2.2, 0));
      plane.billboardMode = BABYLON.Mesh.BILLBOARDMODE_ALL;
      const mat = new BABYLON.StandardMaterial("review-pin-mat-" + note.n, scene);
      mat.diffuseTexture = tex;
      mat.emissiveColor = BABYLON.Color3.White();
      mat.disableLighting = true;
      mat.useAlphaFromDiffuseTexture = true;
      mat.backFaceCulling = false;
      plane.material = mat;
      plane.renderingGroupId = 1;
      plane.metadata = { reviewNote: note.n === "+" ? null : note.n };
      plane.isPickable = note.n !== "+";
      const stem = BABYLON.MeshBuilder.CreateLines("review-stem-" + note.n,
        { points: [noteAnchor(note), plane.position] }, scene);
      stem.color = BABYLON.Color3.FromHexString(color);
      stem.isPickable = false;
      groups.review.push(plane, stem);
    }
  }

  function highlightOwner(id, on) {
    for (const mesh of scene.meshes) {
      if (mesh.isDisposed() || mesh.metadata?.owner !== id || mesh.metadata?.info?.id !== id) continue;
      mesh.renderOutline = on;
      mesh.outlineColor = BABYLON.Color3.FromHexString("#facc15");
      mesh.outlineWidth = 0.16;
    }
  }

  function renderReviewPopup() {
    const popup = document.getElementById("reviewPopup");
    const d = review.on && review.draft;
    popup.hidden = !d;
    for (const mesh of scene.meshes) if (mesh.metadata?.reviewOutline) { mesh.renderOutline = false; mesh.metadata.reviewOutline = false; }
    if (!d) return;
    if (d.target.id) {
      highlightOwner(d.target.id, true);
      for (const mesh of scene.meshes) if (mesh.renderOutline && mesh.metadata?.owner === d.target.id) mesh.metadata.reviewOutline = true;
    }
    const title = document.createElement("h3");
    title.textContent = (review.open ? "#" + review.open + " · " : "New note · ") + describeTarget(d.target);
    const close = button("✕", { class: "popup-close", "aria-label": "Close" }, closeReviewNote);
    const kinds = row("Kind", ...Object.entries(REVIEW_KINDS).map(([k, v]) => {
      const b = button('<i class="swatch" style="background:' + v.color + '"></i>' + v.label,
        { "aria-pressed": String(d.kind === k), title: v.hint }, () => { d.kind = k; renderReview(); });
      return b;
    }));
    const text = document.createElement("textarea");
    text.rows = 3;
    text.placeholder = "What is wrong or right here? (Ctrl+Enter to save)";
    text.value = d.text;
    text.addEventListener("input", () => { d.text = text.value; });
    text.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); commitReviewNote(); }
      if (e.key === "Escape") { e.preventDefault(); closeReviewNote(); }
    });
    const actions = row("",
      button("Save", { class: "primary" }, commitReviewNote),
      ...(review.open ? [button("Delete", {}, () => deleteReviewNote(review.open))] : []),
      button("Cancel", {}, closeReviewNote));
    popup.replaceChildren(close, title, kinds, text, actions);
    placeReviewPopup();
  }

  function placeReviewPopup() {
    const d = review.draft;
    if (!d) return;
    const t = d.target;
    const owner = t.id && componentOf(t.id) ? t.id : null;
    placePopup(document.getElementById("reviewPopup"), owner, screenPoint(noteAnchor({ target: t })));
  }

  function reviewDocument() {
    const doc = {
      review: {
        layout: fullLayout.layout_id || fullLayout.name || "unnamed",
        source: layoutOrigin || "unknown",
        ...(fullLayout.edited_from || edit.undo.length ? { edited_from: fullLayout.edited_from || edit.origin } : {}),
        ...(review.verdict ? { verdict: review.verdict } : {}),
        ...(review.comment.trim() ? { comment: review.comment.trim() } : {}),
        notes: review.notes.map(x => ({
          pin: x.n, kind: x.kind, target: describeTarget(x.target),
          ...(x.target.id ? { component: x.target.id } : {}),
          ...(x.target.hole != null ? { hole: x.target.hole } : {}),
          ...(x.target.port ? { port: x.target.port } : {}),
          at_cm: "(" + [x.target.at.x_cm, x.target.at.y_cm, round2(x.target.at.z_units * HEIGHT_SCALE_CM)].join(", ") + ")",
          text: x.text,
        })),
      },
    };
    // Layouts that exist only in this browser travel with the review.
    if (!/^(examples|tests)\//.test(layoutOrigin) || edit.undo.length) {
      const data = structuredClone(fullLayout);
      delete data.metrics;
      doc.layout_data = data;
    }
    return doc;
  }

  function reviewText() {
    return "Review of " + (fullLayout.layout_id || fullLayout.name) + " (viewer Review mode)\n\n```yaml\n" +
      jsyaml.dump(reviewDocument(), { lineWidth: 120, noRefs: true }) + "```\n";
  }

  async function copyReview() {
    const status = document.getElementById("reviewStatus");
    const text = reviewText();
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Copied. Paste it into the chat with Claude.";
    } catch (error) {
      const area = document.getElementById("reviewExport");
      area.hidden = false;
      area.value = text;
      area.select();
      status.textContent = "Clipboard blocked: select the text below and copy it.";
    }
  }

  function renderReview() {
    const toggle = document.getElementById("reviewToggle");
    toggle.textContent = review.on ? "Exit review" : "Review";
    toggle.setAttribute("aria-pressed", String(review.on));
    document.getElementById("reviewPanel").hidden = !review.on;
    drawReviewPins();
    renderReviewPopup();
    if (!review.on || !fullLayout) return;
    document.getElementById("reviewTitle").textContent = "Review · " + (fullLayout.layout_id || fullLayout.name || "layout");
    const verdict = document.getElementById("reviewVerdict");
    if (verdict.value !== review.verdict) verdict.value = review.verdict;
    const comment = document.getElementById("reviewComment");
    if (document.activeElement !== comment) comment.value = review.comment;
    const list = document.getElementById("reviewList");
    list.replaceChildren(...review.notes.map(note => {
      const li = document.createElement("li");
      const kind = REVIEW_KINDS[note.kind] || {};
      li.innerHTML = '<span class="review-pin" style="background:' + kind.color + '">' + note.n + "</span>" +
        '<div><div class="review-target">' + esc(kind.label || note.kind) + " · " + esc(describeTarget(note.target)) + "</div>" +
        '<div class="review-text">' + esc(note.text) + "</div></div>";
      li.tabIndex = 0;
      li.addEventListener("click", () => openReviewNote(note.n));
      li.addEventListener("keydown", e => { if (e.key === "Enter") openReviewNote(note.n); });
      li.addEventListener("mouseenter", () => note.target.id && highlightOwner(note.target.id, true));
      li.addEventListener("mouseleave", () => note.target.id && highlightOwner(note.target.id, false));
      return li;
    }));
    document.getElementById("reviewEmpty").hidden = review.notes.length > 0;
    document.getElementById("reviewCopy").disabled = !review.notes.length && !review.verdict && !review.comment.trim();
  }

  function setReviewMode(on) {
    if (on) {
      if (build.on) setBuildMode(false);
      if (edit.on) setEditMode(false);
      loadReview();
    }
    review.on = on;
    review.draft = null;
    review.open = null;
    document.getElementById("reviewExport").hidden = true;
    document.getElementById("reviewStatus").textContent = "";
    renderReview();
  }

  document.getElementById("reviewToggle").addEventListener("click", () => setReviewMode(!review.on));
  document.getElementById("reviewVerdict").addEventListener("change", e => { review.verdict = e.target.value; saveReview(); renderReview(); });
  document.getElementById("reviewComment").addEventListener("input", e => { review.comment = e.target.value; saveReview(); renderReview(); });
  document.getElementById("reviewCopy").addEventListener("click", copyReview);
  document.getElementById("reviewDownload").addEventListener("click", () => {
    const blob = new Blob([jsyaml.dump(reviewDocument(), { lineWidth: 120, noRefs: true })], { type: "text/yaml" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = (fullLayout.layout_id || "layout") + ".review.yaml";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  document.getElementById("reviewClear").addEventListener("click", () => {
    if (!review.notes.length && !review.comment && !review.verdict) return;
    review.cleared = { notes: review.notes, verdict: review.verdict, comment: review.comment };
    Object.assign(review, { notes: [], verdict: "", comment: "", draft: null, open: null });
    saveReview();
    renderReview();
    const status = document.getElementById("reviewStatus");
    status.replaceChildren("Cleared. ", button("Undo", {}, () => {
      Object.assign(review, review.cleared);
      saveReview();
      status.textContent = "";
      renderReview();
    }));
  });
  window.addEventListener("keydown", event => {
    if (review.on && event.key === "Escape" && review.draft && !event.target.closest?.("textarea")) closeReviewNote();
  });

  // ---- Generate in the browser (viewer/generator-worker.js runs the Python
  // generator under Pyodide) ------------------------------------------------
  const generatedLayouts = new Map();  // "generated:<id>" -> layout data
  let generatorWorker = null;
  let generatorListening = false;
  let generationId = 0;
  const workerListeners = new Set();

  // One Python worker for generation and edit-mode rail rewrites; messages
  // go to every listener, each picks its own.
  function pyWorker(listener) {
    if (listener) workerListeners.add(listener);
    if (!generatorWorker) {
      generatorWorker = new Worker("./generator-worker.js");
      generatorWorker.onmessage = event => { for (const l of workerListeners) l(event.data); };
    }
    return generatorWorker;
  }

  async function populateGenerateSets() {
    const box = document.getElementById("genSets");
    if (box.childElementCount) return;
    let index;
    try {
      index = jsyaml.load(await (await fetch(DATA_ROOT + "catalog/sets/index.yaml")).text());
    } catch (error) {
      box.textContent = "Could not load the set list.";
      return;
    }
    const preset = new Set(["OWNED"]);  // the user's counted collection
    for (const group of Object.values(index.presets || {})) {
      for (const entry of group) {
        const label = document.createElement("label");
        label.className = "gen-check";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = entry.id;
        input.checked = preset.has(entry.id);
        label.append(input, " " + entry.id + (entry.name_ja ? " " + entry.name_ja : ""));
        box.appendChild(label);
      }
    }
  }

  // ---- Generator profile: score weights and rules (from Python via
  // generator-tunables.json) plus the dialog's settings; saved per browser.
  const PROFILE_STORE = "marble-run-profiles-v1";
  const GEN_FIELDS = ["genHeight", "genArea", "genExits", "genTwists", "genCurves", "genAttempts"];
  let tunables = null;

  async function loadTunables() {
    if (tunables) return tunables;
    try {
      tunables = await (await fetch("generator-tunables.json")).json();
    } catch (error) {
      tunables = { weights: [], style: [] };
    }
    const weights = document.getElementById("genWeights");
    weights.replaceChildren(...tunables.weights.map(t => {
      const label = document.createElement("label");
      label.title = t.help + " (" + t.source + ")";
      const name = document.createElement("span");
      name.innerHTML = '<b class="' + (t.sign > 0 ? "plus" : "minus") + '">' + (t.sign > 0 ? "+" : "−") + "</b> " + t.label;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = String(t.weight >= 1 ? 1 : t.weight >= 0.1 ? 0.05 : t.weight >= 0.01 ? 0.005 : 0.001);
      input.value = String(t.weight);
      input.dataset.key = t.key;
      input.dataset.default = String(t.weight);
      const help = document.createElement("small");
      help.textContent = t.help;
      label.append(name, input, help);
      return label;
    }));
    const style = document.getElementById("genStyle");
    style.replaceChildren(...tunables.style.map(t => {
      const label = document.createElement("label");
      label.title = t.help + " (" + t.source + ")";
      const name = document.createElement("span");
      name.textContent = t.label;
      let input;
      if (t.type === "bool") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(t.default);
      } else if (t.type === "choice") {
        input = document.createElement("select");
        for (const c of t.choices) input.append(new Option(c, c));
        input.value = t.default;
      } else {
        input = document.createElement("input");
        input.type = "number";
        input.min = String(t.min);
        input.max = String(t.max);
        input.step = String(t.step);
        input.value = String(t.default);
      }
      input.dataset.key = t.key;
      input.dataset.type = t.type;
      input.dataset.default = String(t.default);
      const help = document.createElement("small");
      help.textContent = t.help;
      label.append(name, input, help);
      return label;
    }));
    refreshProfiles();
    return tunables;
  }

  function readTunables() {
    const weights = {}, style = {};
    for (const input of document.querySelectorAll("#genWeights input")) {
      const v = Number(input.value);
      if (Number.isFinite(v) && v >= 0 && v !== Number(input.dataset.default)) weights[input.dataset.key] = v;
    }
    for (const input of document.querySelectorAll("#genStyle [data-key]")) {
      const v = input.dataset.type === "bool" ? input.checked
        : input.dataset.type === "choice" ? input.value : Number(input.value);
      if (String(v) !== input.dataset.default) style[input.dataset.key] = v;
    }
    return { weights, style };
  }

  function currentProfile(name) {
    return {
      name, ...readTunables(),
      settings: Object.fromEntries(GEN_FIELDS.map(id => [id, document.getElementById(id).value])),
      sets: [...document.querySelectorAll("#genSets input:checked")].map(i => i.value),
      noRightAngle: document.getElementById("genNoRightAngle").checked,
    };
  }

  function applyProfile(profile) {
    for (const input of document.querySelectorAll("#genWeights input")) {
      input.value = String(profile?.weights?.[input.dataset.key] ?? input.dataset.default);
    }
    for (const input of document.querySelectorAll("#genStyle [data-key]")) {
      const v = profile?.style?.[input.dataset.key];
      const value = v === undefined ? input.dataset.default : String(v);
      if (input.dataset.type === "bool") input.checked = value === "true";
      else input.value = value;
    }
    if (profile?.settings) {
      for (const id of GEN_FIELDS) if (profile.settings[id] != null) document.getElementById(id).value = profile.settings[id];
    }
    if (profile?.sets) {
      for (const input of document.querySelectorAll("#genSets input")) input.checked = profile.sets.includes(input.value);
    }
    if (profile && "noRightAngle" in profile) document.getElementById("genNoRightAngle").checked = Boolean(profile.noRightAngle);
  }

  function savedProfiles() {
    try { return JSON.parse(localStorage.getItem(PROFILE_STORE) || "{}") || {}; } catch (e) { return {}; }
  }
  function storeProfiles(all) {
    try { localStorage.setItem(PROFILE_STORE, JSON.stringify(all)); } catch (e) { /* unavailable */ }
  }
  function refreshProfiles(selected) {
    const select = document.getElementById("genProfile");
    const keep = selected ?? select.value;
    select.replaceChildren(new Option("Default", ""), ...Object.keys(savedProfiles()).sort().map(n => new Option(n, n)));
    select.value = savedProfiles()[keep] ? keep : "";
  }

  document.getElementById("genProfile").addEventListener("change", event => {
    applyProfile(event.target.value ? savedProfiles()[event.target.value] : null);
  });
  document.getElementById("genProfileSave").addEventListener("click", () => {
    const name = (window.prompt("Profile name", document.getElementById("genProfile").value || "my profile") || "").trim();
    if (!name) return;
    const all = savedProfiles();
    all[name] = currentProfile(name);
    storeProfiles(all);
    refreshProfiles(name);
  });
  document.getElementById("genProfileDelete").addEventListener("click", () => {
    const name = document.getElementById("genProfile").value;
    if (!name) return;
    const all = savedProfiles();
    delete all[name];
    storeProfiles(all);
    refreshProfiles("");
    applyProfile(null);
  });
  document.getElementById("genProfileReset").addEventListener("click", () => {
    document.getElementById("genProfile").value = "";
    applyProfile(null);
  });
  document.getElementById("genProfileExport").addEventListener("click", () => {
    const profile = currentProfile(document.getElementById("genProfile").value || "profile");
    const blob = new Blob([JSON.stringify(profile, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = (profile.name || "profile").replace(/[^\w-]+/g, "_") + ".json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  document.getElementById("genProfileImport").addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (!file) return;
    file.text().then(text => {
      const profile = JSON.parse(text);
      const name = String(profile.name || file.name.replace(/\.json$/, ""));
      const all = savedProfiles();
      all[name] = { ...profile, name };
      storeProfiles(all);
      refreshProfiles(name);
      applyProfile(all[name]);
    }).catch(error => { document.getElementById("genStatus").textContent = "Import failed: " + error.message; });
    event.target.value = "";
  });

  function generateOptions() {
    const value = id => document.getElementById(id).value;
    const area = Number(value("genArea"));
    return {
      sets: [...document.querySelectorAll("#genSets input:checked")].map(input => input.value),
      exclude: document.getElementById("genNoRightAngle").checked ? ["red_right_angle"] : [],
      max_height: Number(value("genHeight")),
      footprint: [area, area],
      max_exits: Number(value("genExits")),
      twist_probability: Number(value("genTwists")),
      curve_bias: Number(value("genCurves")),
      attempts: Number(value("genAttempts")),
      seed: Math.max(1, Math.trunc(Number(value("genSeed")) || 1)),
      keep: 6,
      ...readTunables(),
    };
  }

  function downloadYaml(data, filename) {
    const blob = new Blob([jsyaml.dump(data, { lineWidth: 120 })], { type: "text/yaml" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename || (data.layout_id || "layout") + ".yaml";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function openGenerated(data) {
    const key = "generated:" + data.layout_id;
    generatedLayouts.set(key, data);
    const select = document.getElementById("exampleSelect");
    if (![...select.options].some(o => o.value === key)) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = "browser · " + data.layout_id;
      select.appendChild(option);
    }
    select.value = key;
    build.step = 0;
    layoutOrigin = "generated in the browser";
    setLayout(structuredClone(data));
  }

  function showGenerated(layouts) {
    const list = document.getElementById("genResults");
    list.replaceChildren(...layouts.map(data => {
      const m = data.metrics || {};
      const li = document.createElement("li");
      const text = document.createElement("span");
      text.innerHTML = "<b>" + data.layout_id + "</b> · score " + data.generator.score +
        ' <span class="muted">· ' + m.levels + " levels, " + m.rails + " rails, " + m.exits + (m.exits === 1 ? " exit" : " exits") +
        (m.twists ? ", " + m.twists + " twist" + (m.twists > 1 ? "s" : "") : "") +
        (m.curved_rails ? ", " + m.curved_rails + " curve" + (m.curved_rails > 1 ? "s" : "") : "") + "</span>";
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "Open";
      open.addEventListener("click", () => {
        openGenerated(data);
        document.getElementById("generateDialog").close();
      });
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "YAML";
      save.title = "Download this layout as YAML";
      save.addEventListener("click", () => downloadYaml(data));
      li.append(text, open, save);
      return li;
    }));
  }

  function runGenerator() {
    const options = generateOptions();
    const status = document.getElementById("genStatus");
    const progress = document.getElementById("genProgress");
    const run = document.getElementById("genRun");
    if (!options.sets.length) { status.textContent = "Pick at least one set."; return; }
    if (!generatorListening) {
      generatorListening = true;
      pyWorker(message => {
        if (message.type === "edited" || (message.id !== undefined && message.id !== generationId)) return;
        if (message.type === "status") status.textContent = message.text;
        else if (message.type === "progress") {
          progress.max = message.total;
          progress.value = message.done;
          status.textContent = "Generating… " + message.done + " / " + message.total + " tries";
        } else if (message.type === "result") {
          run.disabled = false;
          status.textContent = message.layouts.length
            ? message.layouts.length + " layouts. Open one to view, build or roll it."
            : "No valid layout found: try more effort, a larger area or more sets.";
          showGenerated(message.layouts);
        } else if (message.type === "error") {
          run.disabled = false;
          status.textContent = "Error: " + message.message;
        }
      });
    }
    generationId += 1;
    run.disabled = true;
    progress.value = 0;
    document.getElementById("genResults").replaceChildren();
    const base = new URL(DATA_ROOT, window.location.href).href;
    pyWorker().postMessage({ type: "generate", id: generationId, base, options });
  }

  document.getElementById("generateOpen").addEventListener("click", async () => {
    await populateGenerateSets();
    await loadTunables();
    document.getElementById("generateDialog").showModal();
  });
  document.getElementById("genClose").addEventListener("click", () => document.getElementById("generateDialog").close());
  document.getElementById("genRun").addEventListener("click", runGenerator);
  document.getElementById("genReseed").addEventListener("click", () => {
    document.getElementById("genSeed").value = String(1 + Math.floor(Math.random() * 99999));
  });

  document.getElementById("layoutFile").addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        build.step = 0;
        layoutOrigin = "file " + file.name;
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

  // ---- Play mode: full screen, only "Roll" and a hold-to-exit button (for
  // children: nothing else to press). The camera still moves as usual.
  const play = { on: false, saved: null, holdTimer: null };
  const PLAY_HIDDEN = ["toggleRoute", "toggleCom", "togglePolygon"];

  function fullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }

  function setPlayMode(on) {
    if (on === play.on) return;
    play.on = on;
    if (on) {
      if (edit.on) setEditMode(false);
      if (review.on) setReviewMode(false);
      if (build.on) setBuildMode(false);
      play.saved = PLAY_HIDDEN.map(id => document.getElementById(id).checked);
      for (const id of PLAY_HIDDEN) document.getElementById(id).checked = false;
      applyVisibility();
      sound.unlock();
      const root = document.documentElement;
      const request = root.requestFullscreen || root.webkitRequestFullscreen;
      const gesture = !navigator.userActivation || navigator.userActivation.isActive;
      const standalone = window.matchMedia?.("(display-mode: fullscreen), (display-mode: standalone)").matches;
      if (request && gesture && !standalone && !fullscreenElement()) {
        try { Promise.resolve(request.call(root)).catch(() => {}); } catch (error) { /* not allowed */ }
      }
    } else {
      PLAY_HIDDEN.forEach((id, i) => { document.getElementById(id).checked = play.saved ? play.saved[i] : true; });
      applyVisibility();
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit && fullscreenElement()) {
        try { Promise.resolve(exit.call(document)).catch(() => {}); } catch (error) { /* ignore */ }
      }
    }
    document.body.classList.toggle("play", on);
    document.getElementById("playBar").hidden = !on;
    setTimeout(() => engine.resize(), 50);
  }

  document.getElementById("playToggle").addEventListener("click", () => setPlayMode(true));
  for (const name of ["fullscreenchange", "webkitfullscreenchange"]) {
    document.addEventListener(name, () => {
      if (!fullscreenElement() && play.on) setPlayMode(false);
      setTimeout(() => engine.resize(), 50);
    });
  }
  document.getElementById("playRoll").addEventListener("click", rollOne);
  // Exit needs a one-second hold, so a child tapping around does not leave.
  const playExit = document.getElementById("playExit");
  const stopHold = () => {
    clearTimeout(play.holdTimer);
    play.holdTimer = null;
    playExit.classList.remove("holding");
  };
  playExit.addEventListener("pointerdown", event => {
    event.preventDefault();
    playExit.classList.add("holding");
    play.holdTimer = setTimeout(() => { stopHold(); setPlayMode(false); }, 1000);
  });
  for (const name of ["pointerup", "pointerleave", "pointercancel"]) playExit.addEventListener(name, stopHold);
  playExit.addEventListener("contextmenu", event => event.preventDefault());

  const soundToggle = document.getElementById("soundToggle");
  const showSound = () => {
    soundToggle.textContent = sound.enabled ? "🔊" : "🔇";
    soundToggle.setAttribute("aria-pressed", String(sound.enabled));
    soundToggle.title = sound.enabled ? "Sound on (click to mute)" : "Sound off (click to turn on)";
  };
  soundToggle.addEventListener("click", () => { sound.setEnabled(!sound.enabled); showSound(); });
  showSound();
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
    if (play.on) return;   // play mode: taps only move the camera
    const picked = pointerInfo.pickInfo?.pickedMesh;
    // Clicking a drop marker, or the rim/cap of a valid input hole, selects
    // that hole as the marble input.
    const inputKey = edit.on ? null : picked?.metadata?.inputHoleKey
      ?? (picked?.metadata?.info?.kind === "rail_hole" ? picked.metadata.info.id : null);
    // Copy the info first: selecting re-renders the route and disposes the marker.
    const pickedInfo = picked?.metadata?.info;
    if (review.on) {
      if (picked?.metadata?.reviewNote) openReviewNote(picked.metadata.reviewNote);
      else if (picked && pointerInfo.pickInfo.pickedPoint) startReviewNote(picked, pointerInfo.pickInfo.pickedPoint);
      return;
    }
    if (edit.on) {
      const id = pickedInfo?.kind === "rail_hole" ? pickedInfo.rail_id : picked?.metadata?.owner;
      const rect = canvas.getBoundingClientRect();
      const host = canvas.parentElement.getBoundingClientRect();
      const k = rect.width / engine.getRenderWidth();
      edit.popupAt = id && componentOf(id)
        ? { x: rect.left - host.left + scene.pointerX * k, y: rect.top - host.top + scene.pointerY * k } : null;
      selectEdit(id && componentOf(id) ? id : null);
      if (pickedInfo) document.getElementById("selection").textContent = JSON.stringify(pickedInfo, null, 2);
      return;
    }
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

  window.addEventListener("resize", () => { engine.resize(); if (edit.on) placeEditPopup(); if (review.on) placeReviewPopup(); });
  camera.onViewMatrixChangedObservable.add(() => {
    if (edit.on && edit.popupAt) placeEditPopup();
    if (review.on) placeReviewPopup();
  });
  engine.runRenderLoop(() => scene.render());
  initialize();
})();
