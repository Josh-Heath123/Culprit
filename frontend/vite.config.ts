import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Phase 38 part 1: dist/.vite/manifest.json names every entry and the
  // files its first load fetches. `culprit check` reads it, against the
  // bundle budget the root culprit.yaml declares for culprit-web.
  build: {
    manifest: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
});
