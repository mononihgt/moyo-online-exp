import { expect, test } from "@playwright/test";

import {
  adminApi,
  adminLoginPage,
  prepareWorld,
} from "./support";

function shanghaiInput(date: Date): string {
  return date
    .toLocaleString("sv-SE", { timeZone: "Asia/Shanghai" })
    .slice(0, 16)
    .replace(" ", "T");
}

test("过期草稿可以在管理端改期并保存", async ({ browser, request, baseURL }) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const world = await prepareWorld(request, baseURL, {
    entries: [{ name: "改期测试", phone: "13700000032" }],
    roomLabel: "改期材料房间",
  });
  const created = await adminApi<{ room: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/rooms",
    {
      internalLabel: "过期草稿界面测试",
      startsAt: new Date(Date.now() - 60_000).toISOString(),
      mapGroupVersionId: world.mapGroupVersionId,
      instructionVersionP1Id: world.instructionP1Id,
      instructionVersionP2Id: world.instructionP2Id,
      questionnaireVersionId: world.questionnaireVersionId,
      waitWindowSeconds: 300,
      reconnectWindowSeconds: 30,
    },
  );

  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await adminLoginPage(page);
    await page.goto(`/admin/rooms/${created.room.id}`);
    await expect(page.getByTestId("room-edit")).toBeVisible({
      timeout: 15000,
    });
    await page.getByTestId("room-edit").click();
    const future = new Date(Date.now() + 2 * 3600_000);
    await page.getByTestId("room-form-starts-at").fill(shanghaiInput(future));
    await page.getByTestId("room-edit-save").click();
    await expect(page.getByText("房间配置已保存")).toBeVisible({
      timeout: 15000,
    });

    const detail = await adminApi<{ room: { startsAt: string; status: string } }>(
      request,
      baseURL,
      "GET",
      `/admin/api/rooms/${created.room.id}`,
    );
    expect(detail.room.status).toBe("draft");
    expect(new Date(detail.room.startsAt).getTime()).toBeGreaterThan(
      Date.now() + 60 * 60 * 1000,
    );
  } finally {
    await context.close();
  }
});
