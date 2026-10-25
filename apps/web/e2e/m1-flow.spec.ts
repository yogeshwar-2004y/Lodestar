import { expect, test } from "@playwright/test";

import { FIXTURE, signUp } from "./helpers";

test("onboarding → audit → draft → approve → execute → verify → rollback (WordPress fixture)", async ({ page }) => {
  await signUp(page);

  // organization onboarding
  await page.getByLabel("Organization name").fill("E2E Coffee");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/app\/sites\/new/);

  // add-website wizard
  await page.getByLabel("Name", { exact: true }).fill("E2E fixture site");
  await page.getByLabel("Domain or URL").fill(FIXTURE);
  await page.getByText("WordPress", { exact: true }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Via the WordPress plugin/ }).click();
  await page.getByRole("switch", { name: "Use WordPress test fixture" }).click();
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(page.getByText("Permissions & capabilities").first()).toBeVisible();
  await expect(page.getByText("meta_description").first()).toBeVisible();
  await page.getByRole("button", { name: "Check verification" }).click();
  await expect(page.getByText("Ownership verified").first()).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Start first audit" }).click();

  // overview updates when the crawl completes
  await expect(page.getByText("Top priorities")).toBeVisible();
  await expect(page.getByText(/Pages crawled/)).toBeVisible();
  await expect(page.getByText("Missing meta description").first()).toBeVisible({ timeout: 60_000 });

  // audit center shows evidence and remediation
  await page.getByRole("link", { name: "Audit center" }).first().click();
  await page.getByRole("button", { name: /Missing meta description/ }).first().click();
  await expect(page.getByText("Remediation").first()).toBeVisible();
  await expect(page.getByText(/Affected pages/)).toBeVisible();

  // draft a fix from the Auto-Fix center
  await page.getByRole("link", { name: "Auto-Fix center" }).click();
  await page.getByRole("button", { name: "Draft fix" }).first().click();
  await expect(page).toHaveURL(/\/app\/fixes\//);
  await expect(page.getByText("Approval pending").first()).toBeVisible();
  await expect(page.getByText("Fixture connector").first()).toBeVisible();

  // approve the exact hash, then execute
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByLabel("Note (optional)").fill("E2E approval");
  await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Execute" }).click();
  await expect(page.getByText("Verified live").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Verified in live HTML")).toBeVisible();
  await expect(page.getByText("execution · verified")).toBeVisible();

  // rollback restores the previous value and re-checks the page
  await page.getByRole("button", { name: "Roll back" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Roll back" }).click();
  await expect(page.getByText("Rolled back").first()).toBeVisible({ timeout: 60_000 });
});
