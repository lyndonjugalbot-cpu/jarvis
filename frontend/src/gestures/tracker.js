// Webcam + MediaPipe HandLandmarker, entirely in the browser: video frames never leave the machine.
// Emits frames of mirrored, One-Euro-smoothed landmarks for the gesture engine.

import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

import { LandmarkSmoother } from "./filters.js";

async function createLandmarker(delegate) {
  const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
  return HandLandmarker.createFromOptions(fileset, {
    baseOptions: { modelAssetPath: "/models/hand_landmarker.task", delegate },
    runningMode: "VIDEO",
    numHands: 2,
    minHandDetectionConfidence: 0.5,
    minHandPresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });
}

export async function startTracker({ video, settings, onFrame }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
    audio: false,
  });
  video.srcObject = stream;
  await video.play();

  let landmarker;
  try {
    landmarker = await createLandmarker("GPU");
  } catch {
    landmarker = await createLandmarker("CPU");
  }

  const smoothers = new Map();
  let running = true;
  let lastVideoTime = -1;
  let fps = 0;
  let count = 0;
  let since = performance.now();

  function smootherFor(key) {
    const params = [settings.smoothMinCutoff, settings.smoothBeta];
    const existing = smoothers.get(key);
    if (existing && existing.params.join() === params.join()) return existing;
    const smoother = new LandmarkSmoother({ minCutoff: params[0], beta: params[1] });
    smoother.params = params;
    smoothers.set(key, smoother);
    return smoother;
  }

  function tick() {
    if (!running) return;
    if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      const t = performance.now();
      const result = landmarker.detectForVideo(video, t);
      const seen = new Set();
      const hands = result.landmarks.map((points, i) => {
        const category = result.handedness[i]?.[0];
        const label = category?.categoryName ?? "Right";
        const key = seen.has(label) ? `${label}#2` : label;
        seen.add(key);
        const mirrored = points.map((p) => ({ x: 1 - p.x, y: p.y, z: p.z }));
        return {
          handedness: label,
          score: category?.score ?? 1,
          landmarks: smootherFor(key).smooth(mirrored, t),
        };
      });
      for (const key of smoothers.keys()) if (!seen.has(key)) smoothers.delete(key);

      count += 1;
      if (t - since >= 1000) {
        fps = (count * 1000) / (t - since);
        count = 0;
        since = t;
      }
      onFrame({ t, aspect: video.videoWidth / video.videoHeight, hands }, fps);
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  return {
    stop() {
      running = false;
      for (const track of stream.getTracks()) track.stop();
      video.srcObject = null;
      landmarker.close();
    },
  };
}
