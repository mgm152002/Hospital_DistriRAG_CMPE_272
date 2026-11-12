import { expect, test, type Page } from "@playwright/test";
import { removeDocuments } from "./support";

const title = `Synthetic Ward Guide ${Date.now()}`;
test.afterAll(() => removeDocuments([title]));

async function demo(page: Page, name: string) {
  const logout = page.getByRole("button", { name: "Sign out", exact: true });
  if (await logout.isVisible()) await logout.click();
  await page.getByRole("button", { name: `Sign in as ${name}` }).click();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toBeVisible();
}

test("registration, persistent login and logout", async ({ page }) => {
  const email = `staff-${Date.now()}@example.test`;
  await page.goto("/register");
  await page.getByLabel("Full name", { exact: true }).fill("Demo New Staff");
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TestAccount!2026");
  await page.getByLabel("Confirm password", { exact: true }).fill("TestAccount!2026");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "Search approved documents" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Search approved documents" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TestAccount!2026");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("searchbox", { name: "Search approved documents" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin panel", exact: true })).toHaveCount(0);
});

test("admin upload, independent approval, new versions, comparison and rejection", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/10-login.png", fullPage: true });
  await demo(page, "Alex Morgan");
  await expect(page.getByRole("heading", { name: "Knowledge control center" })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/11-admin.png", fullPage: true });
  await page.getByRole("link", { name: "Upload document", exact: true }).click();
  await page.getByLabel("Choose a file").setInputFiles({ name: "guide-v1.md", mimeType: "text/markdown",
    buffer: Buffer.from(`# ${title}\n\nSYNTHETIC DEMONSTRATION ONLY.\nVisiting hours are 09:00 to 17:00.\n`) });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(title);
  await page.getByLabel("Category").selectOption("Operational Workflow");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("checkbox", { name: "all-staff", exact: true }).check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
  const firstVersion = page.url().split("/versions/")[1];
  const firstStatus = await (await page.request.get(`/api/versions/${firstVersion}/status`)).json();
  const documentId = firstStatus.document_id;
  await page.goto("/admin/approvals");
  const ownCard = page.getByRole("article", { name: `${title} version 1` });
  await expect(ownCard.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();

  await demo(page, "Taylor Brooks");
  await page.goto("/admin/approvals");
  await page.getByRole("article", { name: `${title} version 1` }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText(`Approved ${title}`)).toBeVisible();
  await expect.poll(async () => (await (await page.request.get(`/api/versions/${firstVersion}/status`)).json()).status).toBe("READY");

  await demo(page, "Alex Morgan");
  await page.goto(`/admin/documents/${documentId}`);
  await page.getByRole("link", { name: "Upload new version", exact: true }).click();
  await page.getByLabel("Choose a file").setInputFiles({ name: "guide-v2.md", mimeType: "text/markdown",
    buffer: Buffer.from(`# ${title}\n\nSYNTHETIC DEMONSTRATION ONLY.\nVisiting hours are 10:00 to 18:00.\n`) });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
  const secondVersion = page.url().split("/versions/")[1];
  await page.goto(`/admin/documents/${documentId}`);
  await expect(page.getByLabel("Version changes")).toContainText("Visiting hours are 10:00 to 18:00.");
  await page.screenshot({ path: "e2e/screenshots/12-version-diff.png", fullPage: true });

  await demo(page, "Taylor Brooks");
  await page.goto("/admin/approvals");
  await page.getByRole("article", { name: `${title} version 2` }).getByRole("button", { name: "Approve", exact: true }).click();
  await expect.poll(async () => (await (await page.request.get(`/api/versions/${secondVersion}/status`)).json()).status).toBe("READY");
  const history = await (await page.request.get(`/api/documents/${documentId}`)).json();
  expect(history.versions.find((version: any) => version.version_number === 1).status).toBe("SUPERSEDED");

  await demo(page, "Alex Morgan");
  await page.goto(`/library/${documentId}/new-version`);
  await page.getByLabel("Choose a file").setInputFiles({ name: "guide-v3.md", mimeType: "text/markdown", buffer: Buffer.from("Draft change requiring review.") });
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Waiting for approval").first()).toBeVisible();
  await demo(page, "Taylor Brooks");
  await page.goto("/admin/approvals");
  const rejected = page.getByRole("article", { name: `${title} version 3` });
  await rejected.getByRole("button", { name: "Reject", exact: true }).click();
  await rejected.getByRole("textbox", { name: "Reason for rejection" }).fill("Needs a clearer escalation procedure.");
  await rejected.getByRole("button", { name: "Confirm rejection" }).click();
  await expect(page.getByText(`Rejected ${title}`)).toBeVisible();
  const final = await (await page.request.get(`/api/documents/${documentId}`)).json();
  expect(final.active_version_id).toBe(secondVersion);
  expect(final.versions.find((version: any) => version.version_number === 3).status).toBe("REJECTED");
});
