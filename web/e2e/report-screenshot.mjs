// Capture the Playwright HTML report as a PNG, so the README can show the functional suite passing.
// Run after `playwright test --reporter=list,html`:  node e2e/report-screenshot.mjs <output.png>
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const out = process.argv[2] ?? "e2e/functional/screenshots/FT-00-report.png";
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(pathToFileURL(resolve("playwright-report/index.html")).href);
  await page.getByText(/FT-12/).first().waitFor(); // the report renders client-side
  await page.screenshot({ path: out, fullPage: true });
  console.log(`report screenshot: ${out}`);
} finally {
  await browser.close();
}
