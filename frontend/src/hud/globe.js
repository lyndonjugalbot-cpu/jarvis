// The globe in the dashboard's top-right corner: land drawn as dots (Natural Earth 1:110m from
// world-atlas), a faint grid and atmosphere, and a marker on home (config.toml's home place,
// located by the core). It turns slowly and follows the globe slot element's box.

import { feature } from "topojson-client";
import * as THREE from "three";
import land from "world-atlas/land-110m.json";

const STEP_DEG = 1.5;
const TILT = 0.38; // radians; the north pole leans back a little
const SPIN = 0.05; // radians per second

// Land polygons as rings of [lon, lat] with bounding boxes, for point-in-polygon tests.
function landPolygons() {
  const geometry = feature(land, land.objects.land);
  const features = geometry.type === "FeatureCollection" ? geometry.features : [geometry];
  const polygons = [];
  for (const f of features) {
    const g = f.geometry;
    const list = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
    for (const rings of list) {
      let [minX, minY, maxX, maxY] = [180, 90, -180, -90];
      for (const [x, y] of rings[0]) {
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
      polygons.push({ rings, box: [minX, minY, maxX, maxY] });
    }
  }
  return polygons;
}

function inRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function onLand(lon, lat, polygons) {
  for (const { rings, box } of polygons) {
    if (lon < box[0] || lon > box[2] || lat < box[1] || lat > box[3]) continue;
    let inside = false;
    for (const ring of rings) if (inRing(lon, lat, ring)) inside = !inside;
    if (inside) return true;
  }
  return false;
}

// A point on the unit sphere; lon 0 faces the camera (+z) before the globe turns.
export function toSphere(lat, lon, r = 1) {
  const phi = THREE.MathUtils.degToRad(lat);
  const lambda = THREE.MathUtils.degToRad(lon);
  return new THREE.Vector3(r * Math.cos(phi) * Math.sin(lambda), r * Math.sin(phi), r * Math.cos(phi) * Math.cos(lambda));
}

function landDots() {
  const polygons = landPolygons();
  const points = [];
  for (let lat = -84; lat <= 84; lat += STEP_DEG) {
    const step = STEP_DEG / Math.max(Math.cos(THREE.MathUtils.degToRad(lat)), 0.2);
    for (let lon = -180; lon < 180; lon += step) {
      if (onLand(lon, lat, polygons)) points.push(toSphere(lat, lon, 1.004));
    }
  }
  return new THREE.BufferGeometry().setFromPoints(points);
}

function haloTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d");
  const g = ctx.createRadialGradient(128, 128, 70, 128, 128, 128);
  g.addColorStop(0, "rgba(34, 211, 238, 0.0)");
  g.addColorStop(0.42, "rgba(34, 211, 238, 0.35)");
  g.addColorStop(0.55, "rgba(34, 211, 238, 0.12)");
  g.addColorStop(1, "rgba(34, 211, 238, 0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(canvas);
}

export function createGlobe(view, layout, slotEl, labelEl) {
  const root = new THREE.Group();
  view.scene.add(root);
  const tilt = new THREE.Group();
  tilt.rotation.x = TILT;
  root.add(tilt);
  const globe = new THREE.Group();
  tilt.add(globe);

  // The body hides the dots on the far side.
  globe.add(
    new THREE.Mesh(
      new THREE.SphereGeometry(1, 48, 32),
      new THREE.MeshBasicMaterial({ color: 0x041a2e, transparent: true, opacity: 0.92 }),
    ),
  );
  const grid = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.SphereGeometry(1.002, 18, 12)),
    new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.08 }),
  );
  globe.add(grid);

  const dots = new THREE.Points(
    new THREE.BufferGeometry(),
    new THREE.PointsMaterial({
      color: 0x38bdf8,
      size: 1.6 * Math.min(window.devicePixelRatio, 2),
      sizeAttenuation: false,
    }),
  );
  globe.add(dots);
  // Finding the land dots takes a moment, so it waits until the page is idle.
  const idle = window.requestIdleCallback ?? ((fn) => setTimeout(fn, 200));
  idle(() => {
    dots.geometry.dispose();
    dots.geometry = landDots();
  });

  const halo = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: haloTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }),
  );
  halo.scale.setScalar(2.9);
  root.add(halo);

  // Home: a bright point with a pulsing ring.
  const marker = new THREE.Group();
  marker.visible = false;
  const pin = new THREE.Mesh(new THREE.CircleGeometry(0.035, 20), new THREE.MeshBasicMaterial({ color: 0xbaf8ff }));
  const pulse = new THREE.Mesh(
    new THREE.RingGeometry(0.06, 0.075, 32),
    new THREE.MeshBasicMaterial({ color: 0x67e8f9, transparent: true, side: THREE.DoubleSide, depthWrite: false }),
  );
  marker.add(pin, pulse);
  globe.add(marker);

  let homeLon = 0;
  let spin = 0;
  let t = 0;

  function place() {
    const r = layout.rectOf(slotEl);
    const radius = Math.min(r.w, r.h) * 0.36;
    root.visible = r.visible && radius > 0.05;
    root.position.set(r.x, r.y + r.h * 0.03, 0);
    root.scale.setScalar(radius);
  }

  return {
    setHome(home) {
      if (!home) return;
      const at = toSphere(home.lat, home.lon, 1.01);
      marker.position.copy(at);
      marker.lookAt(at.clone().multiplyScalar(2));
      marker.visible = true;
      homeLon = home.lon;
      spin = 0;
      const lat = `${Math.abs(home.lat).toFixed(1)}°${home.lat < 0 ? "S" : "N"}`;
      const lon = `${Math.abs(home.lon).toFixed(1)}°${home.lon < 0 ? "W" : "E"}`;
      labelEl.textContent = `${home.name}  ${lat} ${lon}`;
    },
    update(dt) {
      place();
      t += dt;
      // Turn slowly, starting with home facing the viewer and swinging back to it.
      spin = Math.sin(t * SPIN) * 0.9;
      globe.rotation.y = -THREE.MathUtils.degToRad(homeLon) + spin;
      const p = (t * 0.8) % 1;
      pulse.scale.setScalar(1 + p * 1.6);
      pulse.material.opacity = 0.9 * (1 - p);
    },
  };
}
