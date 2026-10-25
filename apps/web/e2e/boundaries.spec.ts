import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// Seeded by `make seed`: client@lodestar.example only belongs to the "Harbor Bakery" workspace.
test("agency client user only sees assigned workspace", async ({ page }) => {
  await signIn(page, "client@lodestar.example", "demo-password-123");
  await page.goto("/app/workspaces");
  await expect(page.getByRole("heading", { name: "Harbor Bakery" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Summit Outfitters" })).toHaveCount(0);
  const sites = await page.request.get("/api/v1/sites");
  const names = (await sites.json()).map((s: { name: string }) => s.name);
  expect(names).toEqual(["Harbor Bakery"]);
  // client role has no audit-log or billing access
  expect((await page.request.get("/api/v1/audit-events")).status()).toBe(403);
  expect((await page.request.get("/api/v1/usage")).status()).toBe(403);
});

test("agency owner sees every client workspace", async ({ page }) => {
  await signIn(page, "agency@lodestar.example", "demo-password-123");
  await page.goto("/app/workspaces");
  await expect(page.getByRole("heading", { name: "Harbor Bakery" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Summit Outfitters" })).toBeVisible();
});

test("unauthenticated users are redirected to sign-in", async ({ page }) => {
  await page.goto("/app/approvals");
  await expect(page).toHaveURL(/\/signin/);
});
