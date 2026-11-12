// Covers: UX-1, UX-2, UX-3, UX-5, UX-6, UX-7, AT-01, AT-04, AT-07, AT-14, AT-18 (demo storyline, spec 9.2)
import { expect, test, type Page } from "@playwright/test";
import { removeDocuments } from "./support";

const stamp = Date.now().toString(36);
const title = `Quiet Hours Policy ${stamp}`;
const shots = "e2e/screenshots";

async function signInAs(page: Page, name: string) {
  await page.goto("/");
  const switcher = page.getByRole("button", { name: "Switch person" });
  if (await switcher.isVisible().catch(() => false)) await switcher.click();
  await page.getByRole("button", { name: `Sign in as ${name}` }).click();
}

test.describe.configure({ mode: "serial" });
test.afterAll(() => removeDocuments([title]));

test("persona picker", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Choose who you are for this demo" })).toBeVisible();
  await page.screenshot({ path: `${shots}/01-personas.png`, fullPage: true });
});

test("Alex uploads a policy through the wizard", async ({ page }) => {
  await signInAs(page, "Alex Morgan");
  await page.goto("/library/new");
  await page.getByLabel("Choose a file").setInputFiles({
    name: "quiet-hours.md", mimeType: "text/markdown",
    buffer: Buffer.from(`# ${title}\n\n## Quiet hours\nQuiet hours run from 22:00 to 06:00 on every ward ${stamp}.\n`),
  });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Category").selectOption("Operational Workflow");
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("checkbox", { name: "all-staff" }).check();
  await page.screenshot({ path: `${shots}/02-upload-access.png`, fullPage: true });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
});

test("Taylor approves it", async ({ page }) => {
  await signInAs(page, "Taylor Brooks");
  await page.goto("/compliance");
  const card = page.getByRole("article", { name: `${title} version 1` });
  await expect(card).toBeVisible();
  await page.screenshot({ path: `${shots}/03-approvals.png`, fullPage: true });
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(`Approved ${title}`)).toBeVisible();
});

test("Casey sees it reach Ready on the pipeline board", async ({ page }) => {
  await signInAs(page, "Casey Diaz");
  await page.goto("/ops");
  await expect(page.getByRole("region", { name: "Ready" }).getByText(`${title} v1`)).toBeVisible();
  await page.screenshot({ path: `${shots}/04-pipeline.png`, fullPage: true });
});

test("Sam finds it with its version", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await page.goto(`/search?q=${encodeURIComponent(`quiet hours ${stamp}`)}`);
  await expect(page.getByRole("link", { name: title })).toBeVisible();
  await page.goto(`/search?q=${encodeURIComponent("how long should I rub hands with alcohol")}`);
  await expect(page.getByRole("link", { name: "Hand Hygiene Policy" }).first()).toBeVisible();
  await page.screenshot({ path: `${shots}/05-search.png`, fullPage: true });
  await page.getByRole("link", { name: "Hand Hygiene Policy" }).first().click();
  await expect(page.getByRole("list", { name: "Version history" })).toBeVisible();
  await page.screenshot({ path: `${shots}/06-reader.png`, fullPage: true });
});

test("Priya gets a cited answer with a guardrail receipt", async ({ page }) => {
  await signInAs(page, "Dr. Priya Rao");
  await page.goto("/assistant");
  await page.getByRole("textbox", { name: "Ask about a policy or procedure" }).fill("What are our sepsis screening criteria?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText("Guardrail receipt")).toBeVisible();
  await expect(page.getByText(/Reference only/).first()).toBeVisible();
  await page.screenshot({ path: `${shots}/07-assistant.png`, fullPage: true });
});

test("an emergency shows the banner first", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await page.goto("/assistant");
  await page.getByRole("textbox", { name: "Ask about a policy or procedure" }).fill("My patient is unresponsive and not breathing");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("alert")).toContainText("Rapid Response");
  await page.screenshot({ path: `${shots}/08-emergency.png`, fullPage: true });
});
