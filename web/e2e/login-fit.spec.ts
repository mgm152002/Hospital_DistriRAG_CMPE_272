// The sign-in page must fit the window on desktop: no page scroll, nothing clipped at the top, every demo account
// reachable. Short windows scroll inside the form column only. Phones keep normal page scrolling.
import { expect, test, type Page } from "@playwright/test";

// The demo cards render after the sign-in config loads; measure only once they are there.
const ready = async (page: Page) => {
  await expect(page.getByRole("button", { name: "Sign in as Casey Diaz" })).toBeVisible();
};

const noPageScroll = (page: Page) =>
  page.evaluate(() => document.scrollingElement!.scrollHeight <= window.innerHeight + 1);

for (const [width, height] of [[1920, 1008], [1440, 900], [1366, 768], [1280, 800]] as const) {
  test(`sign-in fits a ${width}x${height} window without scrolling the page`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    await ready(page);
    expect(await noPageScroll(page)).toBe(true);
    await page.screenshot({ path: `e2e/screenshots/login-${width}x${height}.png` });
    const brand = await page.getByText(/^DistriRAG\.?$/).first().boundingBox();
    expect(brand!.y).toBeGreaterThanOrEqual(0); // not clipped off the top
    const secure = await page.getByText("Secure staff access").boundingBox();
    expect(secure!.y).toBeGreaterThanOrEqual(0);
  });
}

test("every demo account is visible without scrolling at a common laptop size", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  await ready(page);
  const buttons = page.getByRole("button", { name: /^Sign in as / });
  expect(await buttons.count()).toBeGreaterThanOrEqual(7);
  for (let i = 0; i < (await buttons.count()); i++) {
    const box = await buttons.nth(i).boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(900);
  }
});

test("a short window scrolls inside the form column, never the page", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 560 });
  await page.goto("/login");
  await ready(page);
  expect(await noPageScroll(page)).toBe(true);
  await page.getByRole("button", { name: "Sign in as Casey Diaz" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: "Sign in as Casey Diaz" })).toBeInViewport();
  expect(await noPageScroll(page)).toBe(true);
});

test("registration, the tallest form, also keeps the page still", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.waitForTimeout(300);
  expect(await noPageScroll(page)).toBe(true);
});

test("on a phone the page scrolls normally and the form comes first in reading order", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign in as Casey Diaz" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: "Sign in as Casey Diaz" })).toBeInViewport();
});
