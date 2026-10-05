// Puts MediaPipe's runtime and hand model under public/ so hand tracking runs fully offline.
// Runs before `npm run dev` and `npm run build`; both folders are gitignored.

import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const wasmFrom = join(root, "node_modules/@mediapipe/tasks-vision/wasm");
const wasmTo = join(root, "public/mediapipe/wasm");
mkdirSync(wasmTo, { recursive: true });
for (const file of readdirSync(wasmFrom)) {
  const src = join(wasmFrom, file);
  const dest = join(wasmTo, file);
  if (!existsSync(dest) || statSync(dest).size !== statSync(src).size) copyFileSync(src, dest);
}

const model = join(root, "public/models/hand_landmarker.task");
mkdirSync(dirname(model), { recursive: true });

// Documents may sync to iCloud; these are large generated files, so ask iCloud to skip them.
if (process.platform === "darwin") {
  for (const dir of [wasmTo, dirname(model)]) {
    try {
      execFileSync("xattr", ["-w", "com.apple.fileprovider.ignore#P", "1", dir]);
    } catch {
      // not on iCloud, or xattr unavailable: nothing to do
    }
  }
}
if (!existsSync(model)) {
  console.log("Downloading the MediaPipe hand model (~8 MB)...");
  const res = await fetch(MODEL_URL);
  if (!res.ok) throw new Error(`model download failed: HTTP ${res.status}`);
  writeFileSync(model, Buffer.from(await res.arrayBuffer()));
}
