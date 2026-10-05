// A holographic panel. The frame (dark glass, angled corners, glowing outline) is a WebGL plane so
// it blooms; the content is HTML in a CSS3DObject that follows the plane, so text stays sharp.
// Object model (spec 5.3): id, type, title, data, state, position, size, createdAt.
// Types: text, list, calendar, chart, image, files (see content.js).
// Panels normally sit in the dashboard's panel slot (`docked`); one dragged elsewhere floats there.

import * as THREE from "three";
import { CSS3DObject } from "three/addons/renderers/CSS3DRenderer.js";

import { renderBody } from "./content.js";

const FRAME_PX_PER_UNIT = 150;
const OPEN_FLICKER_MS = 120;
const DIM_OPACITY = 0.12; // other panels while one is maximized
const SETTLE_RATE = 14; // ~250 ms to settle
const DRAG_RATE = 30;
const CUT = 0.16; // corner cut, in world units

export class Panel {
  constructor({ id, type = "text", title = "", data = "", position = {}, size = {} }) {
    this.id = id;
    this.type = type;
    this.createdAt = Date.now();
    this.state = "normal";
    this.docked = true;
    this.hovered = false;
    this.grabbed = false;
    this.previewScale = 1;
    this.opacity = 0;
    this.closing = false;
    this.dimmed = false;
    this.expand = 1;
    this.pxPerUnit = 110;
    this.openedAt = performance.now();
    this.touchedAt = this.openedAt;

    this.material = new THREE.MeshBasicMaterial({
      transparent: true,
      depthWrite: false,
      opacity: 0,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.material);
    this.mesh.userData.panel = this;

    this.element = document.createElement("div");
    this.element.className = "panel-content";
    this.cssObject = new CSS3DObject(this.element);

    this.home = new THREE.Vector3(position.x ?? 0, position.y ?? 0, position.z ?? 0);
    this.mesh.position.copy(this.home);
    this.mesh.scale.setScalar(0.8); // opens from 0.8 to 1 with a fade
    this.target = { position: this.home.clone(), scale: 1, opacity: 1 };
    this.size = { w: 0, h: 0 };
    this.resize(size.w ?? 3.4, size.h ?? 2.2);
    this.setContent(title, data);
  }

  setContent(title, data, type = this.type) {
    this.title = title;
    this.data = data;
    this.type = type;
    const heading = document.createElement("h3");
    heading.textContent = title;
    this.element.replaceChildren(heading, renderBody(this.type, data));
  }

  spec() {
    const { x, y, z } = this.home;
    return {
      id: this.id,
      type: this.type,
      title: this.title,
      data: this.data,
      state: this.state,
      position: { x, y, z },
      size: { ...this.size },
      createdAt: this.createdAt,
    };
  }

  // New world size: the plane, the frame texture and the HTML box all follow.
  resize(w, h) {
    if (Math.abs(w - this.size.w) < 0.01 && Math.abs(h - this.size.h) < 0.01) return;
    this.size = { w, h };
    this.mesh.geometry.dispose();
    this.mesh.geometry = new THREE.PlaneGeometry(w, h);
    // A texture keeps the size it was first uploaded with, so a new size needs a new one.
    this.canvas = document.createElement("canvas");
    this.canvas.width = Math.max(2, Math.round(w * FRAME_PX_PER_UNIT));
    this.canvas.height = Math.max(2, Math.round(h * FRAME_PX_PER_UNIT));
    this.texture?.dispose();
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.material.map = this.texture;
    this.material.needsUpdate = true;
    this.expand = 0; // forces the HTML box to be resized on the next update
    this.drawFrame();
  }

  setLook({ hovered = this.hovered, grabbed = this.grabbed } = {}) {
    if (hovered === this.hovered && grabbed === this.grabbed) return;
    this.hovered = hovered;
    this.grabbed = grabbed;
    this.drawFrame();
  }

  // layout: { dock: Vector3, center: Vector3, maxScale: number }
  setState(state, layout) {
    this.state = state;
    if (state === "minimized") {
      this.target = { position: layout.dock.clone(), scale: 0.05, opacity: 0 };
    } else if (state === "maximized") {
      this.mesh.visible = true;
      this.target = { position: layout.center.clone(), scale: layout.maxScale, opacity: 1 };
    } else {
      this.mesh.visible = true;
      this.target = {
        position: this.home.clone(),
        scale: 1,
        opacity: this.dimmed ? DIM_OPACITY : 1,
      };
    }
    this.drawFrame();
  }

  // Fade back while another panel is maximized.
  setDimmed(dimmed) {
    this.dimmed = dimmed;
    if (this.state !== "minimized" && !this.closing) this.target.opacity = dimmed ? DIM_OPACITY : 1;
  }

  moveHome(position) {
    this.home.copy(position);
    if (this.state === "normal" || this.state === "focused") this.target.position.copy(position);
  }

  close(onClosed) {
    this.closing = true;
    this.onClosed = onClosed;
    this.target = { position: this.mesh.position.clone(), scale: 0.6, opacity: 0 };
  }

  update(dt, cursor) {
    const mesh = this.mesh;
    const k = 1 - Math.exp(-dt * (this.grabbed ? DRAG_RATE : SETTLE_RATE));
    mesh.position.lerp(this.target.position, k);
    const scale = this.target.scale * this.previewScale;
    mesh.scale.setScalar(mesh.scale.x + (scale - mesh.scale.x) * k);
    this.opacity += (this.target.opacity - this.opacity) * k;
    const flicker = performance.now() - this.openedAt < OPEN_FLICKER_MS && Math.random() < 0.5;
    this.material.opacity = flicker ? this.opacity * 0.35 : this.opacity;

    // A slight parallax as the cursor moves; flat while maximized.
    const flat = this.state === "maximized";
    const cx = cursor && !flat ? cursor.x - 0.5 : 0;
    const cy = cursor && !flat ? cursor.y - 0.5 : 0;
    mesh.rotation.y += (cx * 0.05 - mesh.rotation.y) * k;
    mesh.rotation.x += (cy * 0.03 - mesh.rotation.x) * k;

    if (this.opacity < 0.02) {
      if (this.state === "minimized") mesh.visible = false;
      if (this.closing && this.onClosed) {
        this.onClosed();
        this.onClosed = null;
      }
    }

    // The HTML content follows the frame. When the panel grows past its resting size (maximize,
    // two-hand preview) the content area grows instead of the text, so more fits at the same size.
    const expand = Math.max(1, mesh.scale.x);
    if (Math.abs(expand - this.expand) > 0.001) {
      this.expand = expand;
      this.element.style.width = `${this.size.w * this.pxPerUnit * expand}px`;
      this.element.style.height = `${this.size.h * this.pxPerUnit * expand}px`;
    }
    const css = this.cssObject;
    css.position.copy(mesh.position);
    css.quaternion.copy(mesh.quaternion);
    css.scale.setScalar(mesh.scale.x / (this.pxPerUnit * this.expand));
    css.visible = mesh.visible;
    this.element.style.opacity = this.material.opacity.toFixed(3);
  }

  drawFrame() {
    const ctx = this.canvas.getContext("2d");
    const W = this.canvas.width;
    const H = this.canvas.height;
    const c = CUT * FRAME_PX_PER_UNIT;
    const lit = this.grabbed
      ? 1
      : this.state === "focused" || this.state === "maximized"
        ? 0.8
        : this.hovered
          ? 0.7
          : 0.5;
    const outline = () => {
      ctx.beginPath();
      ctx.moveTo(c, 1.5);
      ctx.lineTo(W - 1.5, 1.5);
      ctx.lineTo(W - 1.5, H - c);
      ctx.lineTo(W - c, H - 1.5);
      ctx.lineTo(1.5, H - 1.5);
      ctx.lineTo(1.5, c);
      ctx.closePath();
    };
    ctx.clearRect(0, 0, W, H);
    outline();
    const glass = ctx.createLinearGradient(0, 0, 0, H);
    glass.addColorStop(0, "rgba(8, 26, 44, 0.9)");
    glass.addColorStop(1, "rgba(4, 14, 26, 0.86)");
    ctx.fillStyle = glass;
    ctx.fill();
    ctx.strokeStyle = `rgba(34, 211, 238, ${lit})`;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Bright accents on the cut corners, and a short tab on the top edge.
    const A = 60;
    ctx.strokeStyle = "#67e8f9";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(2.5, c + A);
    ctx.lineTo(2.5, c);
    ctx.lineTo(c, 2.5);
    ctx.lineTo(c + A, 2.5);
    ctx.moveTo(W - 2.5, H - c - A);
    ctx.lineTo(W - 2.5, H - c);
    ctx.lineTo(W - c, H - 2.5);
    ctx.lineTo(W - c - A, H - 2.5);
    ctx.stroke();
    ctx.fillStyle = `rgba(103, 232, 249, ${0.4 + lit * 0.5})`;
    ctx.fillRect(W - 120, 0, 80, 5);
    this.texture.needsUpdate = true;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.material.dispose();
    this.texture.dispose();
  }
}
