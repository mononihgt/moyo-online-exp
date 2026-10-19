import { expect, test } from "@playwright/test";

import {
  adminLoginPage,
  createAdditionalRoom,
  prepareWorld,
} from "./support";

test.skip(process.env.RUN_ROOMS_PAGINATION_E2E !== "1", "单独运行");

test("房间列表分页", async ({ browser, request, baseURL }) => {
  test.setTimeout(300_000);
  if (!baseURL) throw new Error("baseURL missing");

  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "分页甲", phone: "13600001001" },
      { name: "分页乙", phone: "13600001002" },
    ],
    startsInSeconds: 3600,
    roomLabel: "分页基础房间",
  });
  for (let index = 0; index < 101; index += 1) {
    await createAdditionalRoom(request, baseURL, world, {
      label: `分页草稿 ${String(index + 1).padStart(3, "0")}`,
      startsInSeconds: 7200 + index,
      publish: false,
    });
  }

  const context = await browser.newContext();
  const page = await context.newPage();
  await adminLoginPage(page);
  await page.goto("/admin/rooms?section=draft");
  await expect(page.locator("h1.admin-page-title")).toHaveText("房间");

  const rows = page.locator("table.admin-table tbody tr");
  await expect(rows).toHaveCount(100);
  await expect(page.getByText("第 1 至 100 条，共 101 条")).toBeVisible();

  await page.getByRole("button", { name: "下一页" }).click();
  await expect(rows).toHaveCount(1);
  await expect(page.getByText("第 101 至 101 条，共 101 条")).toBeVisible();

  const sectionFilter = page.getByTestId("room-section-filter");
  await sectionFilter.selectOption("open");
  await expect(rows).toHaveCount(1);
  await sectionFilter.selectOption("draft");
  await expect(rows).toHaveCount(100);
  await expect(page.getByText("第 1 至 100 条，共 101 条")).toBeVisible();

  await context.close();
});
