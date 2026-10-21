(() => {
  "use strict";

  const HEIGHT_SCALE_CM = 3.0;
  const RAIL_WIDTH_CM = 3.0;
  const BLOCK_WIDTH_CM = 5.0;
  const BLOCK_DEPTH_CM = 5.0;

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

  let catalog = null;
  let layout = null;

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

  function railSpec(type) {
    const spec = catalog.rails?.[type];
    if (!spec) throw new Error("Unknown rail type: " + type);
    return spec;
  }

  function railPoint(rail, localX) {
    const yaw = (Number(rail.yaw_deg || 0) * Math.PI) / 180;
    return {
      x: Number(rail.x_cm) + Number(localX) * Math.cos(yaw),
      y: Number(rail.y_cm) + Number(localX) * Math.sin(yaw),
    };
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

  function renderRail(rail) {
    const spec = railSpec(rail.rail_type);
    const length = Number(spec.length_cm);
    const railHeight = Number(spec.height || 1) * HEIGHT_SCALE_CM;
    const box = BABYLON.MeshBuilder.CreateBox("rail-" + rail.id, {
      width: length,
      height: railHeight,
      depth: RAIL_WIDTH_CM,
    }, scene);
    box.material = material("railMat", palette.rail);
    box.rotation.y = -(Number(rail.yaw_deg || 0) * Math.PI) / 180;
    const center = railPoint(rail, length / 2);
    box.position = world(center.x, center.y, Number(rail.z_units) + Number(spec.height || 1) / 2);
    addSelectable(box, {
      id: rail.id,
      kind: "rail",
      type: rail.rail_type,
      mass_g: massValue(spec),
      length_cm: length,
      z_units: rail.z_units,
      yaw_deg: rail.yaw_deg || 0,
      flow_direction: rail.flow_direction || "a_to_b",
      hole_states: rail.hole_states || {},
    });

    (spec.hole_positions_cm || []).forEach((localX, idx) => {
      const p = railPoint(rail, Number(localX));
      const marker = BABYLON.MeshBuilder.CreateCylinder("hole-" + rail.id + "-" + idx, {
        diameter: 1.5,
        height: railHeight + 0.35,
        tessellation: 20,
      }, scene);
      marker.position = world(p.x, p.y, Number(rail.z_units) + Number(spec.height || 1) / 2);
      marker.material = material("holeMat", "#111827");
      marker.metadata = { selectable: true, info: {
        id: rail.id + ":hole:" + idx,
        kind: "rail_hole",
        rail_id: rail.id,
        hole_index: idx,
        local_x_cm: Number(localX),
        state: (rail.hole_states || {})[idx] ?? "open",
      }};
      groups.holes.push(marker);
    });

    const start = railEndWorld(rail, (rail.flow_direction || "a_to_b") === "b_to_a" ? "end_b" : "end_a");
    const end = railEndWorld(rail, (rail.flow_direction || "a_to_b") === "b_to_a" ? "end_a" : "end_b");
    const routeLine = BABYLON.MeshBuilder.CreateLines("route-" + rail.id, {
      points: [
        world(start.x, start.y, Number(rail.z_units) + 1.0),
        world(end.x, end.y, Number(rail.z_units) + 1.0),
      ],
    }, scene);
    routeLine.color = BABYLON.Color3.FromHexString("#22c55e");
    groups.route.push(routeLine);
  }

  function renderPart(part) {
    const spec = catalog.routing_blocks?.[part.part_type]
      || catalog.structural_parts?.[part.part_type]
      || catalog.accessories?.routing_affecting?.[part.part_type]
      || catalog.accessories?.non_routing?.[part.part_type]
      || {};
    const heightUnits = Number(spec.height || (part.part_type === "accelerator_plate" ? 0.15 : 1));
    const heightCm = Math.max(0.35, heightUnits * HEIGHT_SCALE_CM);
    const mesh = BABYLON.MeshBuilder.CreateBox("part-" + part.id, {
      width: BLOCK_WIDTH_CM,
      height: heightCm,
      depth: BLOCK_DEPTH_CM,
    }, scene);
    mesh.material = material("partMat", palette[part.part_type] || palette.default);
    mesh.rotation.y = -(Number(part.rotation_deg || 0) * Math.PI) / 180;
    mesh.position = world(part.x_cm, part.y_cm, Number(part.z_units) + heightUnits / 2);
    addSelectable(mesh, {
      id: part.id,
      kind: "part",
      type: part.part_type,
      mass_g: blockMass(part.part_type),
      z_units: part.z_units,
      rotation_deg: part.rotation_deg || 0,
    });
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

  function renderRouteLinks() {
    const railMap = Object.fromEntries((layout.rails || []).map(r => [r.id, r]));
    const partMap = Object.fromEntries((layout.parts || []).map(p => [p.id, p]));

    function portPosition(ref) {
      if (railMap[ref.component_id]) {
        const rail = railMap[ref.component_id];
        if (ref.port === "end_a" || ref.port === "end_b") return railEndWorld(rail, ref.port);
        if (ref.port.startsWith("hole:")) return railHoleWorld(rail, Number(ref.port.split(":")[1]));
      }
      const part = partMap[ref.component_id];
      if (part) {
        const spec = catalog.routing_blocks?.[part.part_type] || {};
        const h = Number(spec.height || 1);
        return { x: Number(part.x_cm), y: Number(part.y_cm), z: Number(part.z_units) + h / 2 };
      }
      return null;
    }

    for (const link of layout.route_links || []) {
      const a = portPosition(link.source);
      const b = portPosition(link.target);
      if (!a || !b) continue;
      const line = BABYLON.MeshBuilder.CreateLines("route-link", {
        points: [world(a.x, a.y, a.z + 0.7), world(b.x, b.y, b.z + 0.7)],
      }, scene);
      line.color = BABYLON.Color3.FromHexString("#34d399");
      groups.route.push(line);
    }
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
      const h = Number(spec.height || 1);
      total += mass;
      wx += mass * Number(part.x_cm);
      wy += mass * Number(part.y_cm);
      wz += mass * (Number(part.z_units) + h / 2);
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
      ["Support links", (layout.supports || []).length],
      ["Route links", (layout.route_links || []).length],
      ["Height scale", HEIGHT_SCALE_CM + " cm/u"],
    ];
    summary.innerHTML = rows.map(([k,v]) => "<dt>" + k + "</dt><dd>" + v + "</dd>").join("");
    document.getElementById("layoutMeta").textContent = layout.name || "unnamed layout";
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
    clearRendered();
    for (const rail of layout.rails || []) renderRail(rail);
    for (const part of layout.parts || []) renderPart(part);
    renderSupports();
    renderRouteLinks();
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
    for (const [key, visible] of Object.entries(settings)) {
      for (const mesh of groups[key]) mesh.setEnabled(visible);
    }
  }

  async function loadCatalog() {
    const response = await fetch("./catalog/parts.yaml");
    if (!response.ok) throw new Error("Failed to load catalog/parts.yaml");
    return jsyaml.load(await response.text());
  }

  async function loadExample(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error("Failed to load " + path);
    layout = jsyaml.load(await response.text());
    renderAll();
  }

  async function initialize() {
    try {
      catalog = await loadCatalog();
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
  for (const id of ["toggleHoles","toggleSupports","toggleRoute","toggleCom","togglePolygon"]) {
    document.getElementById(id).addEventListener("change", applyVisibility);
  }

  scene.onPointerObservable.add(pointerInfo => {
    if (pointerInfo.type !== BABYLON.PointerEventTypes.POINTERPICK) return;
    const picked = pointerInfo.pickInfo?.pickedMesh;
    if (!picked?.metadata?.selectable) return;
    document.getElementById("selection").textContent =
      JSON.stringify(picked.metadata.info, null, 2);
  });

  window.addEventListener("resize", () => engine.resize());
  engine.runRenderLoop(() => scene.render());
  initialize();
})();
