import { defineConfig } from "vite";

// The core only listens on this machine; the HUD reaches it through the dev server's proxy.
const core = process.env.JARVIS_CORE_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true, // the core's Origin check (Phase 3) expects this exact port
    proxy: { "/api": core },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  // Served locally, so one ~750 kB bundle (Three.js + MediaPipe) is fine.
  build: { chunkSizeWarningLimit: 1000 },
});
