import { expect, test } from "@playwright/test";

import { adminLoginPage } from "./support";

test.use({ timezoneId: "America/Los_Angeles" });

test("付款页默认日期按上海时区计算并导出带区间文件名", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-10-19T00:30:00Z"));
  const listRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/admin/api/payments") listRequests.push(request.url());
  });
  await adminLoginPage(page);

  await page.goto("/admin/payments");
  await expect(page.getByTestId("payment-range-from")).toHaveValue("2026-10-13");
  await expect(page.getByTestId("payment-range-to")).toHaveValue("2026-10-19");
  await expect(
    page.getByText("选择状态后显示日期区间内的付款记录。", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("搜索", { exact: true })).toHaveCount(0);
  await expect(page.locator(".admin-table-wrap, .admin-empty")).toHaveCount(0);
  expect(listRequests).toHaveLength(0);

  const listRequest = page.waitForRequest(
    (request) => new URL(request.url()).pathname === "/admin/api/payments",
  );
  await page.getByTestId("payment-status-filter").selectOption("pending");
  const requested = new URL((await listRequest).url());
  expect(requested.searchParams.get("status")).toBe("pending");
  expect(requested.searchParams.get("from")).toBe("2026-10-13");
  expect(requested.searchParams.get("to")).toBe("2026-10-19");
  await expect(page.getByTestId("payment-search")).toBeEnabled();
  await expect(page.locator(".admin-table-wrap, .admin-empty").first()).toBeVisible();

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
