import { expect, test } from "@playwright/test";

test("administrator can switch external network access off and back on", async ({ page }) => {
  const headers = { "X-User-Id": "alex" };
  const originalResponse = await page.request.get("/api/chat/settings", { headers });
  expect(originalResponse.ok()).toBeTruthy();
  const original = await originalResponse.json();
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "Sign in as Alex Morgan" }).click();
    await page.getByRole("link", { name: "Settings", exact: true }).click();
    const network = page.getByRole("switch", { name: "Allow external AI network access" });
    await expect(network).toBeVisible();
    await expect(page.getByLabel("Replace API key")).toHaveValue("");
    await expect(page.getByText("API key is configured on the server.")).toBeVisible();
    await network.uncheck();
    await page.getByRole("button", { name: "Save chatbot settings" }).click();
    await expect(page.getByText("Chatbot settings saved. External AI requests are blocked; local search remains available.")).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Free model" })).toBeDisabled();
    const offline = await (await page.request.get("/api/chat/settings", { headers })).json();
    expect(offline.network_access).toBe(false);
    expect(offline.key_configured).toBe(true);

    await network.check();
    await page.getByRole("button", { name: "Save chatbot settings" }).click();
    await expect(page.getByText("Chatbot settings saved. New questions will use this model.")).toBeVisible();
    await expect(network).toBeChecked();
    await expect(page.getByRole("combobox", { name: "Free model" })).toHaveValue("openrouter/free");
    await page.screenshot({ path: "e2e/screenshots/09-settings.png", fullPage: true });
  } finally {
    const restored = await page.request.put("/api/chat/settings", {
      headers, data: { model: original.model, network_access: original.network_access },
    });
    expect(restored.ok()).toBeTruthy();
  }
});

test("operator can inspect settings but cannot edit network access or API keys", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in as Casey Diaz" }).click();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("switch", { name: "Allow external AI network access" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save chatbot settings" })).toBeDisabled();
  await expect(page.getByLabel("Replace API key")).toHaveCount(0);
});
