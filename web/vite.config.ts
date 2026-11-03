import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" } },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false, globals: true, exclude: ["e2e/**", "node_modules/**"] },
});
