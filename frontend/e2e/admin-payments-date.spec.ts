import { expect, test } from "@playwright/test";

import { adminLoginPage } from "./support";

test.use({ timezoneId: "America/Los_Angeles" });

test("付款页默认日期按上海时区计算并导出带区间文件名", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-19T00:30:00Z"));
  await adminLoginPage(page);

  await page.goto("/admin/payments");
  await expect(page.getByTestId("payment-range-from")).toHaveValue("2026-10-13");
  await expect(page.getByTestId("payment-range-to")).toHaveValue("2026-10-19");

  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId("payment-export-list").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    "payment-list-2026-10-13-2026-10-19.csv",
  );

  await page.goto("/admin/payments/bulk");
  await expect(
    page.getByRole("heading", { name: "批量付款", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("bulk-range-from")).toHaveValue("2026-10-13");
  await expect(page.getByTestId("bulk-range-to")).toHaveValue("2026-10-19");
});
