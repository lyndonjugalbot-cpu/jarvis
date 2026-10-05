// A holographic 3D model on the dashboard's stage, to break apart and explore: spread two
// pinched hands to pull it into its parts (squeeze to put it back), pinch-drag to turn it, pinch
// a part to select it. The model is drawn as glowing glass: a rim-lit see-through surface with
// scan lines, plus its edges.
//
// Models are the built-ins (holograms/builtins.js) or the user's .glb/.gltf files, served by the
// core from ~/.jarvis/holograms.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

import { BUILTINS, buildBuiltin } from "./holograms/builtins.js";
import { explodeVectors, fitScale, reach } from "./holograms/explode.js";

const CYAN = new THREE.Color(0x22d3ee);
const AMBER = new THREE.Color(0xfbbf24);
const EXPLODE_RATE = 6; // how quickly the parts follow the explode amount
const IDLE_SPIN = 0.18; // radians a second, after a few seconds without a touch
const IDLE_AFTER_S = 4;
const FADE_RATE = 5;
const MAX_FILE_PARTS = 160; // a model with more meshes than this is split by its top-level nodes

const VERTEX = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vView;
  varying float vHeight;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vec4 view = viewMatrix * world;
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-view.xyz);
    vHeight = world.y;
    gl_Position = projectionMatrix * view;
  }
`;

const FRAGMENT = /* glsl */ `
  uniform vec3 color;
  uniform float opacity;
  uniform float time;
  uniform float lines;
  varying vec3 vNormal;
  varying vec3 vView;
  varying float vHeight;
  void main() {
    float rim = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
    float scan = 0.72 + 0.28 * sin(vHeight * lines - time * 3.0);
    gl_FragColor = vec4(color, (0.012 + 0.16 * rim) * scan * opacity);
  }
`;

function glassMaterial() {
  return new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    uniforms: {
      color: { value: CYAN.clone() },
      opacity: { value: 1 },
      time: { value: 0 },
      lines: { value: 40 },
    },
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
}

function edgeMaterial() {
  return new THREE.LineBasicMaterial({
    color: CYAN.clone(),
    transparent: true,
    opacity: 0.55,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

// Only position and normal are kept, so geometries from any file can be merged.
function plain(geometry) {
  const g = geometry.index ? geometry.toNonIndexed() : geometry.clone();
  for (const key of Object.keys(g.attributes)) if (key !== "position" && key !== "normal") g.deleteAttribute(key);
  if (!g.attributes.normal) g.computeVertexNormals();
  return g;
}

const tidy = (name) => String(name || "").replace(/[_.]+/g, " ").replace(/\s+/g, " ").trim();

// A .glb/.gltf as a model: each mesh becomes a part (or each top-level node, for files with very
// many meshes), baked into model space, moving straight out from the center when broken apart.
async function loadFile(spec) {
  const gltf = await new GLTFLoader().loadAsync(`/api/holograms/${encodeURIComponent(spec.file)}`);
  const scene = gltf.scene;
  scene.updateMatrixWorld(true);
  const meshes = [];
  scene.traverse((o) => {
    if (o.isMesh && o.geometry?.attributes?.position) meshes.push(o);
  });
  if (!meshes.length) throw new Error("the file has no meshes");

  const groups = new Map();
  const topOf = (o) => {
    while (o.parent && o.parent !== scene) o = o.parent;
    return o;
  };
  for (const mesh of meshes) {
    const key = meshes.length > MAX_FILE_PARTS ? topOf(mesh) : mesh;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(plain(mesh.geometry).applyMatrix4(mesh.matrixWorld));
  }
  const parts = [...groups.entries()].map(([node, geometries], i) => ({
    name: tidy(node.name) || tidy(node.parent?.name) || `Part ${i + 1}`,
    info: `Part of ${spec.title}.`,
    geometry: geometries.length > 1 ? mergeGeometries(geometries) : geometries[0],
  }));

  // Where each part goes when broken apart.
  const box = new THREE.Box3();
  for (const p of parts) {
    p.geometry.computeBoundingBox();
    box.union(p.geometry.boundingBox);
  }
  const center = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() / 2;
  const centers = parts.map((p) => p.geometry.boundingBox.getCenter(new THREE.Vector3()).toArray());
  explodeVectors(centers, center.toArray(), radius).forEach((v, i) => (parts[i].explode = v));
  return { id: spec.id, title: spec.title, view: { yaw: 0.6, pitch: 0.3 }, parts };
}

export function createModelView(view, layout, stageEl, { onChange = () => {} } = {}) {
  const root = new THREE.Group(); // on the stage
  const pivot = new THREE.Group(); // turns
  const body = new THREE.Group(); // the parts, centered on the pivot
  root.add(pivot);
  pivot.add(body);
  root.visible = false;
  view.scene.add(root);

  let model = null; // { spec, title, parts: [{ name, info, mesh, edges, explode, rest }], ... }
  let catalog = BUILTINS.map(({ id, title }) => ({ id, title }));
  let loading = 0;
  let target = 0; // explode amount asked for
  let shown = 0; // explode amount drawn
  let fade = 0;
  let closing = false;
  let hovered = null;
  let selected = null;
  let yaw = 0;
  let pitch = 0;
  let spin = 0; // turning speed left over from a flick
  let idleFor = 0;
  let turning = null;
  let time = 0;
  let home = { yaw: 0.5, pitch: 0.3 }; // the model's best viewing angle
  let aiming = false; // swinging back to it, so a breakdown is seen side-on

  function report() {
    onChange({
      model: model && !closing ? model.title : null,
      part: selected?.name ?? null,
      explode: target,
      selected,
    });
  }

  function clear() {
    for (const p of model?.parts ?? []) {
      p.mesh.geometry.dispose();
      p.mesh.material.dispose();
      p.edges.geometry.dispose();
      p.edges.material.dispose();
    }
    body.clear();
    model = null;
    hovered = null;
    selected = null;
  }

  function build(data) {
    clear();
    const parts = data.parts.map((p) => {
      const mesh = new THREE.Mesh(p.geometry, glassMaterial());
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(p.geometry, 28), edgeMaterial());
      mesh.add(edges);
      p.geometry.computeBoundingBox();
      const part = { name: p.name, info: p.info, mesh, edges, explode: new THREE.Vector3(...p.explode), box: p.geometry.boundingBox.clone() };
      mesh.userData.part = part;
      body.add(mesh);
      return part;
    });
    const all = new THREE.Box3();
    for (const p of parts) all.union(p.box);
    const center = all.getCenter(new THREE.Vector3());
    body.position.copy(center).negate();
    const boxes = parts.map((p) => ({ min: p.box.min.toArray(), max: p.box.max.toArray() }));
    const offsets = parts.map((p) => p.explode.toArray());
    model = {
      id: data.id,
      title: data.title,
      parts,
      assembled: reach(boxes, offsets, 0, center.toArray()),
      exploded: reach(boxes, offsets, 1, center.toArray()),
    };
    home = { yaw: data.view?.yaw ?? 0.5, pitch: data.view?.pitch ?? 0.3 };
    yaw = home.yaw;
    pitch = home.pitch;
    aiming = false;
    spin = 0;
    idleFor = 0;
    closing = false;
    root.visible = true;
  }

  // Each part's glow: amber when selected, brighter under the cursor, dimmer when another part is
  // selected. update() applies it, times the fade.
  function look() {
    for (const p of model?.parts ?? []) {
      const isSelected = p === selected;
      const dim = selected && !isSelected ? 0.35 : 1;
      const lift = p === hovered && !isSelected ? 1.7 : 1;
      p.mesh.material.uniforms.color.value.copy(isSelected ? AMBER : CYAN);
      p.edges.material.color.copy(isSelected ? AMBER : CYAN);
      p.glow = dim * lift;
      p.edgeGlow = Math.min(1, (isSelected ? 0.9 : 0.32) * dim * lift);
    }
  }

  function screenRect() {
    const r = stageEl.getBoundingClientRect();
    return { left: r.left / window.innerWidth, right: r.right / window.innerWidth, top: r.top / window.innerHeight, bottom: r.bottom / window.innerHeight };
  }

  async function refreshCatalog() {
    try {
      const response = await fetch("/api/holograms");
      if (response.ok) catalog = (await response.json()).models;
    } catch {
      // the core is offline: the built-ins still work
    }
    return catalog;
  }

  const api = {
    get active() {
      return Boolean(model) && !closing;
    },
    get title() {
      return model?.title ?? "";
    },
    get partCount() {
      return model?.parts.length ?? 0;
    },
    get explode() {
      return target;
    },
    get catalog() {
      return catalog;
    },
    refreshCatalog,

    // spec: { id, title, file? } as the core's show_model sends it, or just an id.
    async show(spec, { explode = 0 } = {}) {
      const want = typeof spec === "string" ? (catalog.find((m) => m.id === spec) ?? { id: spec }) : spec;
      const ticket = ++loading;
      const data = want.file ? await loadFile({ ...want, title: want.title || want.file }) : buildBuiltin(want.id);
      if (ticket !== loading) return null; // another model was asked for meanwhile
      if (!data) throw new Error(`there's no model called ${want.id}`);
      build(data);
      target = Math.max(0, Math.min(1, explode));
      shown = 0;
      fade = 0;
      look();
      report();
      return model.title;
    },
    // Next or previous in the catalog (built-ins, then the user's files).
    async cycle(step) {
      const list = await refreshCatalog();
      const i = list.findIndex((m) => m.id === model?.id);
      const next = list[(i + step + list.length) % list.length];
      return api.show(next);
    },
    close() {
      if (!model) return;
      closing = true;
      selected = null;
      hovered = null;
      report();
    },

    setExplode(t) {
      const next = Math.max(0, Math.min(1, t));
      if (target < 0.05 && next >= 0.05 && !turning) aiming = true; // starting to break apart
      target = next;
      idleFor = 0;
      report();
    },
    toggleExplode() {
      api.setExplode(target > 0.5 ? 0 : 1);
    },

    // Is the screen point (0..1) on the stage while a model shows?
    contains(sx, sy) {
      if (!api.active) return false;
      const r = screenRect();
      return sx >= r.left && sx <= r.right && sy >= r.top && sy <= r.bottom;
    },
    hit(sx, sy) {
      if (!api.active) return null;
      const meshes = model.parts.map((p) => p.mesh);
      const [first] = view.ray(sx, sy).intersectObjects(meshes, false);
      return first?.object.userData.part ?? null;
    },
    hover(part) {
      if (part === hovered) return;
      hovered = part;
      look();
    },
    select(part) {
      selected = part && part !== selected ? part : null;
      idleFor = 0;
      look();
      report();
      return selected;
    },

    beginTurn(sx, sy) {
      turning = { x: sx, y: sy, yaw, pitch, lastX: sx, at: performance.now() };
      spin = 0;
      aiming = false;
      idleFor = 0;
    },
    turnTo(sx, sy) {
      if (!turning) return;
      const now = performance.now();
      const dt = Math.max((now - turning.at) / 1000, 1 / 120);
      spin = ((sx - turning.lastX) * 5) / dt;
      turning.lastX = sx;
      turning.at = now;
      yaw = turning.yaw + (sx - turning.x) * 5;
      pitch = Math.max(-1.2, Math.min(1.2, turning.pitch + (sy - turning.y) * 3.5));
      idleFor = 0;
    },
    endTurn() {
      turning = null;
      spin = Math.max(-4, Math.min(4, spin));
    },
    get turning() {
      return Boolean(turning);
    },

    update(dt, { hidden = false } = {}) {
      if (!model) return;
      time += dt;
      fade += ((closing || hidden ? 0 : 1) - fade) * Math.min(1, dt * FADE_RATE);
      if (closing && fade < 0.02) {
        clear();
        closing = false;
        root.visible = false;
        return;
      }
      root.visible = fade > 0.01;

      // Follow the stage element; the model fits a sphere that grows as it breaks apart.
      const r = layout.rectOf(stageEl);
      const room = Math.min(r.h * 0.42, r.w * 0.21);
      shown += (target - shown) * Math.min(1, dt * EXPLODE_RATE);
      const scale = fitScale(room, model.assembled, model.exploded, shown) * (0.85 + 0.15 * fade);
      root.position.set(r.x, r.y + r.h * 0.05, 0.2);
      root.scale.setScalar(scale);

      idleFor += dt;
      if (aiming) {
        // The shortest way round to the best angle.
        const dy = Math.atan2(Math.sin(home.yaw - yaw), Math.cos(home.yaw - yaw));
        const k = Math.min(1, dt * 3);
        yaw += dy * k;
        pitch += (home.pitch - pitch) * k;
        if (Math.abs(dy) < 0.01 && Math.abs(home.pitch - pitch) < 0.01) aiming = false;
      } else if (!turning) {
        yaw += spin * dt;
        spin *= Math.exp(-dt * 2.5);
        // Turn slowly on its own while assembled; held still while broken apart.
        if (idleFor > IDLE_AFTER_S && shown < 0.15) yaw += IDLE_SPIN * dt;
      }
      pivot.rotation.set(pitch, yaw, 0, "XYZ");

      const lines = (2 * Math.PI * layout.pxPerUnit(0)) / 6; // a scan line every 6 pixels
      for (const p of model.parts) {
        p.mesh.position.copy(p.explode).multiplyScalar(shown);
        const u = p.mesh.material.uniforms;
        u.time.value = time;
        u.lines.value = lines;
        u.opacity.value = p.glow * fade;
        p.edges.material.opacity = p.edgeGlow * fade;
      }
    },
  };
  return api;
}
