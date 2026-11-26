// Functional test suite FT-01…FT-12: the end-to-end behaviours a hospital evaluator cares about, run in a real
// browser against a running, seeded deployment (BASE_URL), with a screenshot saved for every test.
//
//   BASE_URL=http://35.184.233.38 npx playwright test e2e/functional.spec.ts
//
// Preconditions: `make seed` (the 24 policies) and `make seed-chats` (the titled demo conversations).
// Everything the suite creates (one uploaded policy, the conversations it asks) is deleted again afterwards, so it
// is safe to run against the demo environment. Assertions avoid the language model's exact wording: they check
// sources, banners, refusals, access and state, which are deterministic.
import { expect, request as playwrightRequest, test, type Page } from "@playwright/test";
import { removeDocuments } from "./support";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8000";
const SHOTS = process.env.SHOTS ?? "e2e/functional/screenshots";
const stamp = Date.now().toString(36);
const policy = `Quiet Hours Policy ${stamp}`;
const created: { persona: string; id: string }[] = []; // conversations this suite starts, removed in afterAll

test.describe.configure({ mode: "serial" }); // later tests use the policy that FT-02 uploads

async function signInAs(page: Page, name: string) {
  await page.goto("/");
  const logout = page.getByRole("button", { name: "Sign out", exact: true });
  if (await logout.isVisible().catch(() => false)) await logout.click();
  await page.getByRole("button", { name: `Sign in as ${name}` }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
}

/** Ask the assistant one question and wait for the final answer. */
async function ask(page: Page, persona: string, question: string) {
  await page.goto("/assistant");
  await page.getByRole("textbox", { name: "Ask about a policy or procedure" }).fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const log = page.getByRole("log");
  try {
    await expect(log.getByText("Checking approved documents…")).toHaveCount(0, { timeout: 90_000 });
    // A finished reply ends with its footer, "<model> · <seconds>s"; previews and streaming text do not.
    await expect(log.getByText(/ · \d+(\.\d+)?s$/).last()).toBeVisible({ timeout: 90_000 });
  } finally {
    // Record the conversation even when an assertion fails, so afterAll still removes it.
    const id = new URL(page.url()).searchParams.get("c");
    if (id) created.push({ persona, id });
  }
  return log;
}

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true, animations: "disabled" }); // no half-faded text

test.afterAll(async () => {
  await removeDocuments([policy]);
  for (const { persona, id } of created) {
    const ctx = await playwrightRequest.newContext({ baseURL: BASE_URL, extraHTTPHeaders: { "X-User-Id": persona } });
    await ctx.post(`/api/auth/demo/${persona}`);
    await ctx.delete(`/api/conversations/${id}`);
    await ctx.dispose();
  }
});

test("FT-01 the sign-in page offers the fictional demo accounts", async ({ page }) => {
  await page.goto("/");
  for (const name of ["Alex Morgan", "Taylor Brooks", "Sam Lee", "Dr. Priya Rao", "Casey Diaz"]) {
    await expect(page.getByRole("button", { name: `Sign in as ${name}` })).toBeVisible();
  }
  await shot(page, "FT-01-sign-in");
});

test("FT-02 a document admin uploads a policy, which waits for approval", async ({ page }) => {
  await signInAs(page, "Alex Morgan");
  await page.goto("/library/new");
  await page.getByLabel("Choose a file").setInputFiles({
    name: "quiet-hours.md", mimeType: "text/markdown",
    buffer: Buffer.from(`# ${policy}\n\n## Quiet hours\nQuiet hours run from 22:00 to 06:00 on every ward ${stamp}.\n`),
  });
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Title").fill(policy);
  await page.getByLabel("Category").selectOption("Operational Workflow");
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByText("Everyone on staff", { exact: true }).click(); // the styled label; the input is visually hidden
  await expect(page.getByRole("checkbox", { name: "all-staff" })).toBeChecked();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
  await shot(page, "FT-02-upload-pending");
});

test("FT-03 a compliance officer (not the uploader) approves it", async ({ page }) => {
  await signInAs(page, "Taylor Brooks");
  await page.goto("/compliance");
  const card = page.getByRole("article", { name: `${policy} version 1` });
  await expect(card).toBeVisible();
  await shot(page, "FT-03-approval-queue");
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(`Approved ${policy}`)).toBeVisible();
});

test("FT-04 the distributed pipeline indexes it to Ready", async ({ page }) => {
  await signInAs(page, "Casey Diaz");
  await page.goto("/ops");
  await expect(page.getByRole("region", { name: "Ready" }).getByText(`${policy} v1`)).toBeVisible();
  await shot(page, "FT-04-pipeline-ready");
});

test("FT-05 staff search finds the new policy and the current version of an existing one", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await page.goto(`/search?q=${encodeURIComponent(`quiet hours ${stamp}`)}`);
  await expect(page.getByRole("link", { name: policy })).toBeVisible();
  await page.goto(`/search?q=${encodeURIComponent("how long should I rub hands with alcohol")}`);
  await expect(page.getByRole("link", { name: "Hand Hygiene Policy" }).first()).toBeVisible();
  await shot(page, "FT-05-search");
  await page.getByRole("link", { name: "Hand Hygiene Policy" }).first().click();
  await expect(page.getByRole("list", { name: "Version history" })).toBeVisible();
  await shot(page, "FT-05-reader-version-history");
});

test("FT-06 a seeded clinical conversation shows cited sources", async ({ page }) => {
  await signInAs(page, "Dr. Priya Rao");
  await page.goto("/assistant");
  await page.getByRole("navigation", { name: "Recent conversations" })
    .getByRole("link", { name: "ED triage: possible sepsis escalation" }).click();
  await expect(page.getByRole("log").getByText(/Sepsis Screening and Escalation Protocol/).first()).toBeVisible();
  await shot(page, "FT-06-cited-conversation");
});

test("FT-07 a question with patient identifiers is refused before search (PHI guard)", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  const log = await ask(page, "sam", "Patient John Smith MRN 00482913 fell, what now?");
  await expect(log.getByText(/Not sent/).first()).toBeVisible();
  // The person's own bubble echoes what they typed; what is stored (and listed in the sidebar) is redacted.
  const recents = page.getByRole("navigation", { name: "Recent conversations" });
  await expect(recents.getByText(/\[REDACTED-NAME\]/).first()).toBeVisible();
  await expect(recents.getByText(/00482913/)).toHaveCount(0);
  await shot(page, "FT-07-phi-blocked");
});

test("FT-08 an emergency shows the rapid-response banner first", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await ask(page, "sam", "My patient is unresponsive and not breathing");
  await expect(page.getByRole("alert").first()).toContainText(/Rapid Response|Code Blue|5555/);
  await shot(page, "FT-08-emergency-banner");
});

test("FT-09 access control: front-desk staff cannot see clinical protocols", async ({ page }) => {
  await signInAs(page, "Riley Chen");
  await page.goto(`/search?q=${encodeURIComponent("sepsis screening criteria")}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sepsis Screening and Escalation Protocol" })).toHaveCount(0);
  await shot(page, "FT-09-access-control");
});

test("FT-10 a conversation can be renamed from the sidebar", async ({ page }) => {
  await signInAs(page, "Sam Lee");
  await page.goto("/assistant");
  const recents = page.getByRole("navigation", { name: "Recent conversations" });
  const original = "Hand hygiene: rub versus soap and water";
  const renamed = `Hand hygiene (renamed ${stamp})`;
  await recents.getByRole("link", { name: original }).hover();
  await recents.getByRole("button", { name: `Rename ${original}` }).click();
  await page.getByRole("textbox", { name: `New title for ${original}` }).fill(renamed);
  await page.keyboard.press("Enter");
  await expect(recents.getByRole("link", { name: renamed })).toBeVisible();
  await shot(page, "FT-10-rename-conversation");
  // Put the demo title back.
  await recents.getByRole("link", { name: renamed }).hover();
  await recents.getByRole("button", { name: `Rename ${renamed}` }).click();
  await page.getByRole("textbox", { name: `New title for ${renamed}` }).fill(original);
  await page.keyboard.press("Enter");
  await expect(recents.getByRole("link", { name: original })).toBeVisible();
});

test("FT-11 administrators see live usage and document analytics", async ({ page }) => {
  await signInAs(page, "Alex Morgan");
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Knowledge control center" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Usage over 14 days/ })).toBeVisible();
  await shot(page, "FT-11-admin-analytics");
});

test("FT-12 compliance can audit every action", async ({ page }) => {
  await signInAs(page, "Taylor Brooks");
  await page.goto("/compliance");
  await page.getByRole("navigation", { name: "Compliance" }).getByRole("link", { name: /Audit/ }).click();
  await expect(page.getByText(/version\.approved|search\.performed|conversation\./).first()).toBeVisible();
  await shot(page, "FT-12-audit-log");
});
