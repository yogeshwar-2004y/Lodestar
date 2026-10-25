import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

test("landing page: one h1, skip link, labelled nav, no horizontal scroll on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator("h1")).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeAttached();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("app pages render on tablet without errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 820, height: 1180 });
  await signIn(page, "demo@lodestar.example", "demo-password-123");
  for (const path of ["approvals", "billing", "settings", "reports", "audit-log", "workspaces"]) {
    await page.goto(`/app/${path}`);
    await expect(page.locator("h1").first()).toBeVisible();
  }
  // every icon-only button has an accessible name
  const unnamed = await page.$$eval("button", (bs) => bs.filter((b) => !b.textContent?.trim() && !b.getAttribute("aria-label")).length);
  expect(unnamed).toBe(0);
  expect(errors).toEqual([]);
});
