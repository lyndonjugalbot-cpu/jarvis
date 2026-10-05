// Three.js scene, camera, renderer and the bloom post-processing pipeline. Panel frames glow in
// WebGL; panel content is real HTML placed in 3D by a CSS3DRenderer sharing the same camera, so
// text stays sharp and doesn't bloom. Screen points are normalized: x and y from 0 to 1, y down.

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { CSS3DRenderer } from "three/addons/renderers/CSS3DRenderer.js";

const BACKGROUND = 0x05080f;

export function createScene(canvas, cssHost) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BACKGROUND); // colour-managed, unlike setClearColor here
  const cssScene = new THREE.Scene();
  const css = new CSS3DRenderer({ element: cssHost });
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 10);

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 1.2, 0.4, 0.55);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  function resize() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    renderer.setSize(width, height, false);
    css.setSize(width, height);
    composer.setSize(width, height);
    bloom.resolution.set(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  window.addEventListener("resize", resize);
  resize();

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();

  function ray(sx, sy) {
    ndc.set(sx * 2 - 1, -(sy * 2 - 1));
    raycaster.setFromCamera(ndc, camera);
    return raycaster;
  }

  // The world point under a screen point, on the plane z = `z`.
  function pointAt(sx, sy, z = 0) {
    const target = new THREE.Vector3();
    ray(sx, sy).ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -z), target);
    return target;
  }

  // Where a world point lands on screen.
  function screenOf(position) {
    const p = position.clone().project(camera);
    return { x: (p.x + 1) / 2, y: (1 - p.y) / 2 };
  }

  // Width and height of the visible area at depth z.
  function viewSize(z = 0) {
    const height = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * (camera.position.z - z);
    return { width: height * camera.aspect, height };
  }

  function render() {
    composer.render();
    css.render(cssScene, camera);
  }

  return { scene, cssScene, camera, renderer, bloom, ray, pointAt, screenOf, viewSize, render };
}
