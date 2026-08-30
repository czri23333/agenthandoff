import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxy: `npm run dev` pairs with `handoff ui --port 8620` for live reload.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8620" },
  },
  build: {
    // Emit straight into the package so the wheel/serve path reads the
    // same tree that is committed (see CONTRIBUTING "Cockpit frontend").
    outDir: "../src/agent_handoff/server/static",
    emptyOutDir: true,
    sourcemap: false,
  },
});
