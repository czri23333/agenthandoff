import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxy: `npm run dev` pairs with `handoff ui --port 8620` for live reload.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8620" },
  },
  build: { outDir: "dist", sourcemap: false },
});
