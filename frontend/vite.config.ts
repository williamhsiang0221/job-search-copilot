import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // API_TARGET lets the demo (backend/demo/run_demo.sh) point a second
      // dev server at the demo backend without touching this one.
      "/api": { target: process.env.API_TARGET ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
