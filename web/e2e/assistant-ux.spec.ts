// Covers: persona UX decisions. Asserts what does not depend on the language model's wording: retrieval, banners,
// redaction notices, refusals, next steps and access. Run against a seeded stack (BASE_URL).
import { expect, test, type Page } from "@playwright/test";

async function signInAs(page: Page, name: string) {
  await page.goto("/");
  const switcher = page.getByRole("button", { name: "Switch person" });
  if (await switcher.isVisible().catch(() => false)) await switcher.click();
  const logout = page.getByRole("button", { name: "Sign out", exact: true });
  if (await logout.isVisible().catch(() => false)) await logout.click();
  await page.getByRole("button", { name: `Sign in as ${name}` }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
}

async function ask(page: Page, question: string) {
  // A second question continues the conversation (its URL is /assistant?c=<id>); only open the page if elsewhere.
  if (new URL(page.url()).pathname !== "/assistant") await page.goto("/assistant");
  await page.getByRole("textbox", { name: "Ask about a policy or procedure" }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const log = page.getByRole("log");
  // Every reply ends with the reference-only line: assert only once the final answer, not a preview, is on screen.
  await expect(log.getByText("Checking approved documents…")).toHaveCount(0, { timeout: 90_000 });
  await expect(log.getByText(/Reference only\./).last()).toBeVisible({ timeout: 90_000 });
  return log;
}

const sources = (page: Page) => page.getByRole("region", { name: "Sources" });

test("a nurse who says she was stuck with a needle reaches the sharps policy", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  const log = await ask(page, "I just got stuck with a used needle");
  await expect(sources(page).getByRole("link", { name: "Sharps Injury and Bloodborne Exposure" }).first()).toBeVisible();
  await expect(log.getByText("I couldn't find this")).toHaveCount(0);
});

test("clinical shorthand reaches the policy", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await ask(page, "HH duration with ABHR?");
  await expect(sources(page).getByRole("link", { name: "Hand Hygiene Policy" }).first()).toBeVisible();
});

test("an emergency phrasing shows the banner and leads with the number to dial", async ({ page }) => {
  await signInAs(page, "Riley Chen");
  const log = await ask(page, "A visitor collapsed in the lobby and isn't breathing");
  await expect(log.getByRole("alert")).toContainText("Rapid Response");
  await expect(log.getByText(/Dial extension 5555/).first()).toBeVisible();
});

test("patient identifiers are removed, named in plain words, and the question is still answered", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  const log = await ask(page, "John Smith MRN 4471203 in room 12 fell, what now?");
  await expect(log.getByRole("note").filter({ hasText: "Removed a name" })).toContainText("before searching");
  await expect(sources(page).getByRole("link", { name: "Fall Risk Assessment and Prevention" }).first()).toBeVisible();
  await expect(log.getByText("John Smith")).toHaveCount(1); // only in the user's own bubble, never in an answer
});

test("a dose question is declined and points to the pharmacy", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  const log = await ask(page, "Heparin drip rate for a 90 kg pt?");
  await expect(log.getByText(/can't give or calculate doses/)).toBeVisible();
  await expect(log.getByText(/pharmacy/i).first()).toBeVisible();
});

test("a question the library cannot answer says so and offers next steps", async ({ page }) => {
  await signInAs(page, "Riley Chen");
  const log = await ask(page, "What is our DVT prophylaxis protocol for surgical patients?");
  await expect(log.getByText(/I couldn't find this in approved documents you can access/)).toBeVisible();
  await expect(log.getByText(/Patient services \/ front desk/)).toBeVisible();
  await expect(log.getByText(/Try different words/)).toBeVisible();
  await expect(log.getByText(/ask the knowledge administrator/)).toBeVisible();
});

test("an operator does not see the assistant, and the API refuses the request too", async ({ page }) => {
  await signInAs(page, "Casey Diaz");
  await expect(page.getByRole("link", { name: "Assistant", exact: true })).toHaveCount(0);
  const response = await page.request.post("/api/chat", { data: { message: "How do I call a code blue?" } });
  expect(response.status()).toBe(403);
});

test("the corpus questions are one click away and ask themselves", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await page.goto("/assistant");
  const panel = page.getByRole("region", { name: "Test questions" });
  await expect(panel).toBeVisible();
  await panel.getByText("Situational", { exact: false }).first().click();
  await panel.getByRole("button", { name: /I just got stuck with a used needle/ }).click();
  await expect(page.getByRole("region", { name: "Question 1" })).toContainText("I just got stuck with a used needle");
  await expect(sources(page).getByRole("link", { name: "Sharps Injury and Bloodborne Exposure" }).first()).toBeVisible();
});

test("a multi-step test conversation plays all of its steps", async ({ page }) => {
  await signInAs(page, "Riley Chen");
  await page.goto("/assistant");
  const panel = page.getByRole("region", { name: "Test questions" });
  await panel.getByText("Multi turn", { exact: false }).first().click();
  await panel.getByRole("button", { name: /How many visitors can be at the bedside\?.*2 steps/ }).click();
  await expect(page.getByRole("region", { name: "Question 2" })).toContainText("can one of them stay the night?", {
    timeout: 120_000 });
  await expect(page.getByText(/Reference only\./).last()).toBeVisible({ timeout: 120_000 });
});

test("the page itself never scrolls and the composer stays on screen as the conversation grows", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await signInAs(page, "Sam Lee");
  const log = await ask(page, "HH duration with ABHR?");
  await ask(page, "and with soap?");
  await expect(log.getByRole("region", { name: "Question 2" })).toBeVisible();
  const fits = await page.evaluate(() => document.scrollingElement!.scrollHeight <= window.innerHeight + 1);
  expect(fits).toBe(true);
  const box = await page.getByRole("textbox", { name: "Ask about a policy or procedure" }).boundingBox();
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);
});
