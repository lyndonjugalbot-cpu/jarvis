// Built-in holographic models, made from simple shapes so they need no files: a turbofan jet
// engine, a quadcopter drone and an arc reactor. The ids match BUILTIN_MODELS in
// backend/tools/hud.py, so JARVIS can show them by name.
//
// A model is { id, title, view: { yaw, pitch }, parts }. Each part is { name, info, geometry,
// explode }: the geometry is already in place (model units), and `explode` is how far the part
// moves when the model is fully broken apart.

import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const TAU = Math.PI * 2;

// A geometry moved, turned and scaled into place.
function put(geometry, { x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0, sx = 1, sy = 1, sz = 1 } = {}) {
  const matrix = new THREE.Matrix4().compose(
    new THREE.Vector3(x, y, z),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz)),
    new THREE.Vector3(sx, sy, sz),
  );
  return geometry.applyMatrix4(matrix);
}

function part(name, info, geometries, explode) {
  const list = (Array.isArray(geometries) ? geometries : [geometries]).map((g) => (g.index ? g.toNonIndexed() : g));
  for (const g of list) {
    for (const key of Object.keys(g.attributes)) if (key !== "position" && key !== "normal") g.deleteAttribute(key);
  }
  return { name, info, geometry: mergeGeometries(list), explode };
}

// ---------------------------------------------------------------- jet engine (axis along x)

// One ring of blades around the engine's axis at `x`, with its disc.
function bladeStage(x, outer, hub, count, { chord = 0.045, thick = 0.008, twist = 0.6 } = {}) {
  const shapes = [put(new THREE.CylinderGeometry(hub, hub, chord * 1.3, 32), { x, rz: Math.PI / 2 })];
  const length = outer - hub;
  for (let i = 0; i < count; i += 1) {
    const blade = new THREE.BoxGeometry(chord, length, thick);
    blade.translate(0, hub + length / 2, 0);
    blade.rotateY(twist);
    blade.rotateX((i / count) * TAU);
    blade.translate(x, 0, 0);
    shapes.push(blade);
  }
  return shapes;
}

function stages(xs, outer, hub, count, options) {
  return xs.flatMap((x, i) => bladeStage(x, typeof outer === "function" ? outer(i) : outer, hub, count, options));
}

function shell(radius, from, to, segments = 48) {
  return put(new THREE.CylinderGeometry(radius, radius, to - from, segments, 1, true), { x: (from + to) / 2, rz: Math.PI / 2 });
}

function jetEngine() {
  const nozzle = new THREE.LatheGeometry([new THREE.Vector2(0.33, 0), new THREE.Vector2(0.3, 0.16), new THREE.Vector2(0.24, 0.34)], 48);
  return {
    id: "jet-engine",
    title: "Jet engine",
    view: { yaw: -0.6, pitch: 0.28 },
    parts: [
      part(
        "Spinner",
        "The nose cone. It smooths air into the fan and sheds ice before it can build up.",
        put(new THREE.ConeGeometry(0.12, 0.2, 32), { x: -0.93, rz: Math.PI / 2 }),
        [-0.85, 0, 0],
      ),
      part(
        "Fan",
        "Twenty-two wide blades. In a turbofan most of the thrust comes from the air the fan pushes around the core, not through it.",
        bladeStage(-0.78, 0.47, 0.12, 22, { chord: 0.09, thick: 0.01, twist: 0.7 }),
        [-0.62, 0, 0],
      ),
      part(
        "Fan case",
        "The front of the nacelle. It guides air into the fan and is built to contain a blade if one ever breaks off.",
        [shell(0.5, -0.93, -0.3), put(new THREE.TorusGeometry(0.5, 0.025, 12, 64), { x: -0.93, ry: Math.PI / 2 })],
        [0, 0.78, 0],
      ),
      part(
        "Low-pressure compressor",
        "Three stages that start squeezing the air entering the core. The low-pressure shaft turns them, together with the fan.",
        stages([-0.63, -0.57, -0.51], 0.3, 0.13, 16),
        [-0.4, 0, 0],
      ),
      part(
        "High-pressure compressor",
        "Six tighter stages that raise the pressure about forty times before the air is burned. The high-pressure shaft turns them.",
        stages([-0.42, -0.36, -0.3, -0.24, -0.18, -0.12], (i) => 0.25 - i * 0.012, 0.11, 20, { chord: 0.035 }),
        [-0.17, 0, 0],
      ),
      part(
        "Combustion chamber",
        "Fuel is sprayed into the squeezed air and burned at around 2,000 °C, hotter than the metal around it could stand without cooling air.",
        [
          put(new THREE.TorusGeometry(0.17, 0.055, 16, 48), { x: 0, ry: Math.PI / 2 }),
          ...Array.from({ length: 10 }, (_, i) => {
            const a = (i / 10) * TAU;
            return put(new THREE.CylinderGeometry(0.012, 0.012, 0.08, 8), { x: -0.07, y: Math.cos(a) * 0.17, z: Math.sin(a) * 0.17, rz: Math.PI / 2 });
          }),
        ],
        [0, 0, 0.5],
      ),
      part(
        "High-pressure turbine",
        "Two stages spun by the hot gas; they drive the high-pressure compressor. Air flows through tiny holes in the blades to keep them from melting.",
        stages([0.1, 0.15], 0.22, 0.13, 24),
        [0.24, 0, 0],
      ),
      part(
        "Low-pressure turbine",
        "Four stages that take more energy from the gas to turn the fan and the low-pressure compressor.",
        stages([0.22, 0.27, 0.32, 0.37], (i) => 0.26 + i * 0.016, 0.14, 26),
        [0.48, 0, 0],
      ),
      part(
        "Core casing",
        "The core's outer shell. It holds the compressor, combustor and turbine stages in line.",
        shell(0.33, -0.46, 0.42),
        [0, -0.7, 0],
      ),
      part(
        "Exhaust nozzle",
        "Shapes the hot gas leaving the core into a fast jet. The cone in the middle is the tail plug.",
        [put(nozzle, { x: 0.44, rz: -Math.PI / 2 }), put(new THREE.ConeGeometry(0.15, 0.3, 32), { x: 0.6, rz: -Math.PI / 2 })],
        [0.85, 0, 0],
      ),
      part(
        "Shafts",
        "Two shafts, one inside the other: the low-pressure shaft links the fan to the rear turbine; the high-pressure shaft links the compressor to the front turbine.",
        [shell(0.03, -0.82, 0.45, 16), shell(0.05, -0.44, 0.18, 16)],
        [0, -0.4, 0],
      ),
    ],
  };
}

// ---------------------------------------------------------------- quadcopter (y up, front is +z)

const CORNERS = [
  ["front right", Math.PI / 4],
  ["front left", (3 * Math.PI) / 4],
  ["back left", (5 * Math.PI) / 4],
  ["back right", (7 * Math.PI) / 4],
];

function drone() {
  const out = (a, d, up = 0) => [Math.cos(a) * d, up, Math.sin(a) * d];
  const at = (a, d, y = 0) => ({ x: Math.cos(a) * d, y, z: Math.sin(a) * d });
  const parts = [
    part(
      "Body",
      "The frame's center plate. Everything else bolts to it.",
      [put(new THREE.BoxGeometry(0.36, 0.08, 0.26)), put(new THREE.CylinderGeometry(0.15, 0.15, 0.09, 32))],
      [0, 0, 0],
    ),
    part(
      "Top shell",
      "A light cover that keeps rain and knocks off the electronics and the GPS.",
      put(new THREE.SphereGeometry(0.2, 32, 12, 0, TAU, 0, Math.PI / 2), { y: 0.04, sy: 0.45 }),
      [0, 0.45, 0],
    ),
    part(
      "Flight controller",
      "The drone's brain: gyroscopes, accelerometers and a processor that adjust each motor hundreds of times a second to keep it level. The puck on top is the GPS.",
      [put(new THREE.BoxGeometry(0.12, 0.015, 0.12), { y: 0.06 }), put(new THREE.CylinderGeometry(0.035, 0.035, 0.02, 24), { y: 0.085 })],
      [0, 0.26, 0],
    ),
    part(
      "Battery",
      "A lithium-polymer pack, usually four cells (about 15 V). It's the heaviest part, so it sits in the middle for balance.",
      put(new THREE.BoxGeometry(0.22, 0.06, 0.12), { y: -0.08 }),
      [0, -0.36, 0],
    ),
    part(
      "Camera gimbal",
      "A camera on a three-axis gimbal that keeps the picture steady while the drone tilts to fly.",
      [put(new THREE.BoxGeometry(0.08, 0.04, 0.06), { y: -0.08, z: 0.16 }), put(new THREE.SphereGeometry(0.045, 24, 16), { y: -0.13, z: 0.19 })],
      [0, -0.24, 0.42],
    ),
    part(
      "Landing gear",
      "Legs and skids to land on, keeping the camera off the ground.",
      [
        put(new THREE.CylinderGeometry(0.012, 0.012, 0.42, 12), { x: 0.13, y: -0.22, rx: Math.PI / 2 }),
        put(new THREE.CylinderGeometry(0.012, 0.012, 0.42, 12), { x: -0.13, y: -0.22, rx: Math.PI / 2 }),
        ...[
          [0.13, 0.1],
          [0.13, -0.1],
          [-0.13, 0.1],
          [-0.13, -0.1],
        ].map(([x, z]) => put(new THREE.CylinderGeometry(0.01, 0.01, 0.18, 8), { x, y: -0.13, z })),
      ],
      [0, -0.62, 0],
    ),
  ];
  CORNERS.forEach(([where, a], i) => {
    parts.push(
      part(
        `Arm (${where})`,
        "A carbon-fibre arm holding a motor out from the body.",
        put(new THREE.BoxGeometry(0.42, 0.035, 0.045), { ...at(a, 0.34), ry: -a }),
        out(a, 0.22),
      ),
      part(
        `Motor (${where})`,
        "A brushless motor. Changing how fast each one spins is the only way the drone steers.",
        [put(new THREE.CylinderGeometry(0.055, 0.055, 0.06, 24), at(a, 0.56, 0.02)), put(new THREE.CylinderGeometry(0.045, 0.05, 0.02, 24), at(a, 0.56, 0.06))],
        out(a, 0.4, 0.12),
      ),
      part(
        `Propeller (${where})`,
        "Opposite corners spin the same way and neighbours the other way, so the drone doesn't turn on its own.",
        put(new THREE.BoxGeometry(0.5, 0.006, 0.05), { ...at(a, 0.56, 0.085), ry: a + (i % 2 ? 0.3 : -0.3), rx: i % 2 ? 0.12 : -0.12 }),
        out(a, 0.52, 0.34),
      ),
    );
  });
  return { id: "drone", title: "Quadcopter drone", view: { yaw: 0.5, pitch: 0.45 }, parts };
}

// ---------------------------------------------------------------- arc reactor (axis along z)

function arcReactor() {
  const flat = (geometry, z = 0) => put(geometry, { z });
  const disc = (r, depth, z) => put(new THREE.CylinderGeometry(r, r, depth, 48), { z, rx: Math.PI / 2 });
  const parts = [
    part(
      "Back housing",
      "The metal casing the reactor sits in, set into the chest.",
      [disc(0.46, 0.06, -0.06), flat(new THREE.TorusGeometry(0.46, 0.02, 12, 64), -0.03)],
      [0, 0, -0.55],
    ),
    part("Outer ring", "Holds the coil array in place.", flat(new THREE.TorusGeometry(0.4, 0.045, 16, 64)), [0, 0, -0.25]),
    part("Inner ring", "Holds the core and links it to the coils.", flat(new THREE.TorusGeometry(0.2, 0.028, 12, 48), 0.01), [0, 0, 0.26]),
    part(
      "Core",
      "The glowing palladium core from the films. A real fusion reactor this small isn't possible; this is the fictional design.",
      [disc(0.12, 0.07, 0.02), put(new THREE.SphereGeometry(0.1, 24, 12, 0, TAU, 0, Math.PI / 2), { z: 0.05, rx: Math.PI / 2, sy: 0.5 })],
      [0, 0, 0.52],
    ),
    part(
      "Front ring",
      "The faceplate ring and its three supports: the part you see on the chest.",
      [
        flat(new THREE.TorusGeometry(0.43, 0.015, 8, 64), 0.07),
        ...[Math.PI / 2, Math.PI / 2 + TAU / 3, Math.PI / 2 + (2 * TAU) / 3].map((a) =>
          put(new THREE.BoxGeometry(0.24, 0.025, 0.02), { x: Math.cos(a) * 0.31, y: Math.sin(a) * 0.31, z: 0.07, rz: a }),
        ),
      ],
      [0, 0, 0.82],
    ),
  ];
  for (let i = 0; i < 10; i += 1) {
    const a = (i / 10) * TAU;
    const coil = [put(new THREE.BoxGeometry(0.12, 0.07, 0.06), { x: Math.cos(a) * 0.3, y: Math.sin(a) * 0.3, rz: a })];
    for (const k of [-0.035, 0, 0.035]) {
      const r = 0.3 + k;
      // A winding around the bar: turn the ring to face along x first, then out along the bar.
      coil.push(put(new THREE.TorusGeometry(0.045, 0.006, 6, 16).rotateY(Math.PI / 2), { x: Math.cos(a) * r, y: Math.sin(a) * r, rz: a }));
    }
    parts.push(
      part(`Coil ${i + 1}`, "One of ten copper coils around the core; together they shape its energy field.", coil, [Math.cos(a) * 0.3, Math.sin(a) * 0.3, 0.14]),
    );
  }
  return { id: "arc-reactor", title: "Arc reactor", view: { yaw: 0.75, pitch: 0.3 }, parts };
}

export const BUILTINS = [
  { id: "jet-engine", title: "Jet engine", build: jetEngine },
  { id: "drone", title: "Quadcopter drone", build: drone },
  { id: "arc-reactor", title: "Arc reactor", build: arcReactor },
];

export function buildBuiltin(id) {
  return BUILTINS.find((m) => m.id === id)?.build() ?? null;
}
