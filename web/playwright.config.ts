import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.BASE_URL ?? "http://localhost:8000", viewport: { width: 1280, height: 800 },
         screenshot: "only-on-failure", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } }],
});
