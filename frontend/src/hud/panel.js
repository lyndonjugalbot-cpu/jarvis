// A floating holographic panel. The frame (tint, border, corner brackets) is a WebGL plane so it
// glows with the bloom pass; the content is HTML in a CSS3DObject that follows the plane, so text
// stays sharp. Object model (spec 5.3): id, type, title, data, state, position, size, createdAt.

import * as THREE from "three";
import { CSS3DObject } from "three/addons/renderers/CSS3DRenderer.js";

const FRAME_PX_PER_UNIT = 150;
const CSS_PX_PER_UNIT = 110; // content size in CSS pixels; about 1:1 with the screen at rest
const OPEN_FLICKER_MS = 120;
const DIM_OPACITY = 0.12; // other panels while one is maximized
const REST_SCALE = 1.04; // a focused panel's scale
const SETTLE_RATE = 14; // ~250 ms to settle
const DRAG_RATE = 30;

export class Panel {
  constructor({ id, type = "text", title = "", data = "", position = {}, size = {} }) {
    this.id = id;
    this.type = type;
    this.size = { w: size.w ?? 3.4, h: size.h ?? 2.2 };
    this.createdAt = Date.now();
    this.state = "normal";
    this.hovered = false;
    this.grabbed = false;
    this.previewScale = 1;
    this.opacity = 0;
    this.closing = false;
    this.dimmed = false;
    this.expand = 1;
    this.openedAt = performance.now();

    this.canvas = document.createElement("canvas");
    this.canvas.width = Math.round(this.size.w * FRAME_PX_PER_UNIT);
    this.canvas.height = Math.round(this.size.h * FRAME_PX_PER_UNIT);
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.material = new THREE.MeshBasicMaterial({
      map: this.texture,
      transparent: true,
      depthWrite: false,
      opacity: 0,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(this.size.w, this.size.h), this.material);
    this.mesh.userData.panel = this;

    this.element = document.createElement("div");
    this.element.className = "panel-content";
    this.element.style.width = `${this.size.w * CSS_PX_PER_UNIT}px`;
    this.element.style.height = `${this.size.h * CSS_PX_PER_UNIT}px`;
    this.cssObject = new CSS3DObject(this.element);

    this.home = new THREE.Vector3(position.x ?? 0, position.y ?? 0, position.z ?? 0);
    this.mesh.position.copy(this.home);
    this.mesh.scale.setScalar(0.8); // opens from 0.8 to 1 with a fade
    this.target = { position: this.home.clone(), scale: 1, opacity: 1 };
    this.setContent(title, data);
    this.drawFrame();
  }

  setContent(title, data) {
    this.title = title;
    this.data = data;
    const heading = document.createElement("h3");
    heading.textContent = title;
    let body;
    if (this.type === "list") {
      body = document.createElement("ul");
      for (const item of Array.isArray(data) ? data : [data]) {
        const li = document.createElement("li");
        li.textContent = String(item);
        body.append(li);
      }
    } else {
      body = document.createElement("p");
      body.textContent = typeof data === "string" ? data : JSON.stringify(data);
    }
    this.element.replaceChildren(heading, body);
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

  setLook({ hovered = this.hovered, grabbed = this.grabbed } = {}) {
    if (hovered === this.hovered && grabbed === this.grabbed) return;
    this.hovered = hovered;
    this.grabbed = grabbed;
    this.drawFrame();
  }

  // layout: { dock: Vector3, maxScale: number }
  setState(state, layout) {
    this.state = state;
    if (state === "minimized") {
      this.target = { position: layout.dock.clone(), scale: 0.05, opacity: 0 };
    } else if (state === "maximized") {
      this.mesh.visible = true;
      this.target = { position: new THREE.Vector3(0, 0.15, 1.5), scale: layout.maxScale, opacity: 1 };
    } else {
      this.mesh.visible = true;
      const lift = state === "focused" ? 0.3 : 0;
      this.target = {
        position: this.home.clone().add(new THREE.Vector3(0, 0, lift)),
        scale: state === "focused" ? REST_SCALE : 1,
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
    if (this.state === "normal" || this.state === "focused") {
      const lift = this.state === "focused" ? 0.3 : 0;
      this.target.position.set(position.x, position.y, position.z + lift);
    }
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

    // Tilt slightly toward the edges, with parallax as the cursor moves.
    const cx = cursor ? cursor.x - 0.5 : 0;
    const cy = cursor ? cursor.y - 0.5 : 0;
    const tilt = this.state === "maximized" ? 0 : -this.home.x * 0.06;
    mesh.rotation.y += (tilt + cx * 0.12 - mesh.rotation.y) * k;
    mesh.rotation.x += (cy * 0.08 - mesh.rotation.x) * k;

    if (this.opacity < 0.02) {
      if (this.state === "minimized") mesh.visible = false;
      if (this.closing && this.onClosed) {
        this.onClosed();
        this.onClosed = null;
      }
    }

    // The HTML content follows the frame. When the panel grows past its resting size (maximize,
    // two-hand preview) the content area grows instead of the text, so more fits at the same size.
    const expand = Math.max(1, mesh.scale.x / REST_SCALE);
    if (Math.abs(expand - this.expand) > 0.001) {
      this.expand = expand;
      this.element.style.width = `${this.size.w * CSS_PX_PER_UNIT * expand}px`;
      this.element.style.height = `${this.size.h * CSS_PX_PER_UNIT * expand}px`;
    }
    const css = this.cssObject;
    css.position.copy(mesh.position);
    css.quaternion.copy(mesh.quaternion);
    css.scale.setScalar(mesh.scale.x / (CSS_PX_PER_UNIT * this.expand));
    css.visible = mesh.visible;
    this.element.style.opacity = this.material.opacity.toFixed(3);
  }

  drawFrame() {
    const ctx = this.canvas.getContext("2d");
    const W = this.canvas.width;
    const H = this.canvas.height;
    const lit = this.grabbed
      ? 1
      : this.state === "focused" || this.state === "maximized"
        ? 0.85
        : this.hovered
          ? 0.7
          : 0.45;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = `rgba(34, 211, 238, ${0.07 + lit * 0.05})`;
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = `rgba(34, 211, 238, ${lit})`;
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, W - 2, H - 2);

    ctx.strokeStyle = "#22d3ee";
    ctx.lineWidth = 5;
    const L = 26;
    for (const [x, y, dx, dy] of [[2.5, 2.5, 1, 1], [W - 2.5, 2.5, -1, 1], [2.5, H - 2.5, 1, -1], [W - 2.5, H - 2.5, -1, -1]]) {
      ctx.beginPath();
      ctx.moveTo(x + dx * L, y);
      ctx.lineTo(x, y);
      ctx.lineTo(x, y + dy * L);
      ctx.stroke();
    }
    this.texture.needsUpdate = true;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.material.dispose();
    this.texture.dispose();
  }
}
