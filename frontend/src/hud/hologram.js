// The hologram in the middle of the dashboard (HUD.png): JARVIS's avatar on a glowing ring
// platform, with light beams, rising sparks and brackets either side. The avatar is the image at
// /api/avatar (~/.jarvis/avatar.png); without one an orb stands in. It follows the stage element's
// box and reacts to JARVIS's state: idle, listening, thinking, speaking.

import * as THREE from "three";

const CYAN = 0x22d3ee;
const BRIGHT = 0x7ff3ff;
const FLAT = 0.2; // how flat the platform rings look (seen from slightly above)
const FLOOR = -0.38; // platform height, in stage units (the stage is 1 unit tall)
const SPARKS = 160;

const SPEED = { idle: 1, listening: 1.6, thinking: 4, speaking: 2 };
const GLOW = { idle: 0.75, listening: 1, thinking: 0.9, speaking: 1 };

function glowTexture(stops) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d");
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [at, color] of stops) g.addColorStop(at, color);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function beamTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 8;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  const g = ctx.createLinearGradient(0, 128, 0, 0);
  g.addColorStop(0, "rgba(127, 243, 255, 0.9)");
  g.addColorStop(0.4, "rgba(34, 211, 238, 0.25)");
  g.addColorStop(1, "rgba(34, 211, 238, 0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 8, 128);
  return new THREE.CanvasTexture(canvas);
}

function additive(options) {
  return new THREE.MeshBasicMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    ...options,
  });
}

// A ring (or arc) lying on the platform.
function ring(inner, outer, { opacity = 0.8, color = CYAN, start = 0, length = Math.PI * 2 } = {}) {
  const mesh = new THREE.Mesh(
    new THREE.RingGeometry(inner, outer, 160, 1, start, length),
    additive({ color, opacity, side: THREE.DoubleSide }),
  );
  mesh.userData.opacity = opacity;
  return mesh;
}

export function createHologram(view, layout, stageEl) {
  const root = new THREE.Group();
  root.renderOrder = -1;
  view.scene.add(root);

  // ---- platform: concentric rings seen at an angle, a bright pool of light and dashed arcs
  const platform = new THREE.Group();
  platform.position.y = FLOOR;
  platform.scale.y = FLAT;
  root.add(platform);
  const rings = [
    ring(0.7, 0.708, { opacity: 0.55 }),
    ring(0.58, 0.6, { opacity: 0.9, color: BRIGHT }),
    ring(0.44, 0.452, { opacity: 0.6 }),
    ring(0.3, 0.33, { opacity: 1, color: BRIGHT }),
    ring(0.16, 0.17, { opacity: 0.7 }),
  ];
  platform.add(...rings);
  const spinners = [];
  for (const [radius, count, dir] of [[0.65, 3, 1], [0.38, 4, -1], [0.82, 2, 1]]) {
    const group = new THREE.Group();
    for (let i = 0; i < count; i += 1) {
      group.add(ring(radius, radius + 0.014, { opacity: 0.9, color: BRIGHT, start: (i / count) * Math.PI * 2, length: 0.55 }));
    }
    group.userData.dir = dir;
    platform.add(group);
    spinners.push(group);
  }
  const pool = new THREE.Mesh(
    new THREE.CircleGeometry(0.62, 64),
    additive({
      map: glowTexture([[0, "rgba(160,250,255,1)"], [0.35, "rgba(34,211,238,0.55)"], [1, "rgba(34,211,238,0)"]]),
      opacity: 0.8,
    }),
  );
  platform.add(pool);

  // ---- light beams rising from the platform
  const beams = new THREE.Group();
  const beamMap = beamTexture();
  for (let i = 0; i < 14; i += 1) {
    const x = (Math.random() - 0.5) * 0.9;
    const height = 0.25 + Math.random() * 0.55;
    const beam = new THREE.Mesh(
      new THREE.PlaneGeometry(0.008 + Math.random() * 0.01, height),
      additive({ map: beamMap, opacity: 0.25 + Math.random() * 0.35 }),
    );
    beam.position.set(x, FLOOR + height / 2, -0.05 + Math.random() * 0.1);
    beam.userData = { phase: Math.random() * 6, base: beam.material.opacity };
    beams.add(beam);
  }
  root.add(beams);

  // ---- sparks drifting up
  const sparkPositions = new Float32Array(SPARKS * 3);
  const sparkSpeed = new Float32Array(SPARKS);
  const resetSpark = (i, y = FLOOR + Math.random() * 0.9) => {
    const angle = Math.random() * Math.PI * 2;
    const r = 0.1 + Math.random() * 0.5;
    sparkPositions[i * 3] = Math.cos(angle) * r;
    sparkPositions[i * 3 + 1] = y;
    sparkPositions[i * 3 + 2] = Math.sin(angle) * r * 0.3;
    sparkSpeed[i] = 0.03 + Math.random() * 0.08;
  };
  for (let i = 0; i < SPARKS; i += 1) resetSpark(i);
  const sparkGeometry = new THREE.BufferGeometry();
  sparkGeometry.setAttribute("position", new THREE.BufferAttribute(sparkPositions, 3));
  const sparks = new THREE.Points(
    sparkGeometry,
    new THREE.PointsMaterial({
      color: BRIGHT,
      size: 2 * Math.min(window.devicePixelRatio, 2),
      sizeAttenuation: false,
      transparent: true,
      opacity: 0.7,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  root.add(sparks);

  // ---- brackets either side: tall arcs with a bright tab at the middle
  const brackets = new THREE.Group();
  for (const side of [-1, 1]) {
    const arc = new THREE.Group();
    arc.scale.set(0.62, 0.48, 1);
    const start = side < 0 ? Math.PI * 0.72 : -Math.PI * 0.28;
    arc.add(ring(0.98, 1, { opacity: 0.55, start, length: Math.PI * 0.56 }));
    arc.add(ring(1.04, 1.046, { opacity: 0.3, start: start + 0.12, length: Math.PI * 0.4 }));
    brackets.add(arc);
    const tab = new THREE.Mesh(new THREE.PlaneGeometry(0.018, 0.08), additive({ color: BRIGHT, opacity: 0.95 }));
    tab.position.set(side * 0.6, 0.02, 0);
    brackets.add(tab);
  }
  brackets.position.y = 0.04;
  root.add(brackets);

  // ---- the avatar, or an orb until (or unless) it loads
  const figure = new THREE.Group();
  root.add(figure);
  const orb = new THREE.Group();
  orb.add(
    new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(0.24, 1)),
      new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.55 }),
    ),
    new THREE.Mesh(
      new THREE.CircleGeometry(0.2, 48),
      additive({ map: glowTexture([[0, "rgba(200,255,255,1)"], [0.4, "rgba(34,211,238,0.6)"], [1, "rgba(34,211,238,0)"]]) }),
    ),
  );
  orb.position.y = 0.02;
  figure.add(orb);

  let avatar = null;
  new THREE.TextureLoader().load(
    "/api/avatar",
    (texture) => {
      texture.colorSpace = THREE.SRGBColorSpace;
      const { width, height } = texture.image;
      const h = 0.84;
      avatar = new THREE.Mesh(
        new THREE.PlaneGeometry((h * width) / height, h),
        // Dimmed a little so the bloom pass keeps the fur's detail.
        new THREE.MeshBasicMaterial({ map: texture, color: 0xc4d8e8, transparent: true, depthWrite: false }),
      );
      avatar.position.y = FLOOR + h / 2 - 0.02;
      figure.remove(orb);
      figure.add(avatar);
      scan.visible = true;
    },
    undefined,
    () => {}, // no avatar: keep the orb
  );

  // A thin scan line sweeping up through the figure.
  const scan = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.004), additive({ color: BRIGHT, opacity: 0.5 }));
  scan.visible = false;
  root.add(scan);

  let state = "idle";
  let level = 0; // microphone level, 0..1
  let glow = GLOW.idle;
  let t = 0;

  function place() {
    const r = layout.rectOf(stageEl);
    const unit = Math.min(r.h * 0.96, r.w / 2.35);
    root.visible = r.visible && unit > 0.5;
    root.position.set(r.x, r.y, 0);
    root.scale.setScalar(unit);
  }

  return {
    setState(next) {
      state = SPEED[next] ? next : "idle";
    },
    setLevel(value) {
      level = Math.max(level, value);
    },
    // hidden: a maximized panel is in front
    update(dt, { hidden = false } = {}) {
      place();
      if (hidden) root.visible = false;
      const speed = SPEED[state];
      t += dt * speed;
      glow += (GLOW[state] + level * 0.4 - glow) * Math.min(1, dt * 6);
      level *= Math.exp(-dt * 4);

      for (const group of spinners) group.rotation.z += dt * 0.35 * speed * group.userData.dir;
      const pulse = state === "speaking" ? 0.5 + 0.5 * Math.sin(t * 5) : 0.5 + 0.5 * Math.sin(t * 1.3);
      rings.forEach((mesh, i) => {
        mesh.material.opacity = mesh.userData.opacity * glow * (0.75 + 0.25 * Math.sin(t * 1.7 + i));
      });
      pool.material.opacity = 0.55 * glow + 0.25 * pulse;
      const s = 1 + 0.04 * pulse * (state === "speaking" ? 2 : 1);
      pool.scale.setScalar(s);

      for (const beam of beams.children) {
        const { phase, base } = beam.userData;
        beam.material.opacity = base * glow * (0.6 + 0.4 * Math.sin(t * 2 + phase));
      }

      for (let i = 0; i < SPARKS; i += 1) {
        sparkPositions[i * 3 + 1] += sparkSpeed[i] * dt * speed;
        if (sparkPositions[i * 3 + 1] > 0.5) resetSpark(i, FLOOR);
      }
      sparkGeometry.attributes.position.needsUpdate = true;

      figure.position.y = Math.sin(t * 1.1) * 0.008;
      orb.rotation.y += dt * 0.6 * speed;
      orb.rotation.x += dt * 0.2 * speed;
      if (avatar) avatar.material.opacity = 0.88 + 0.12 * glow * (0.8 + 0.2 * Math.sin(t * 9));
      const sweep = (t * 0.25) % 1;
      scan.position.y = FLOOR + sweep * 0.86;
      scan.material.opacity = 0.45 * Math.sin(sweep * Math.PI);
    },
  };
}
