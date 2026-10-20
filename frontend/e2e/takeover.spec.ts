import { expect, test } from "@playwright/test";

import {
  bookRoom,
  enterRoom,
  loginParticipant,
  prepareWorld,
} from "./support";

test("同一参与者打开第二个页面后旧页面停止重连", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const world = await prepareWorld(request, baseURL, {
    entries: [{ name: "接管测试", phone: "13700000031" }],
    startsInSeconds: 8,
    waitWindowSeconds: 120,
    roomLabel: "接管测试房间",
  });

  const context = await browser.newContext();
  try {
    const pageOne = await context.newPage();
    await loginParticipant(pageOne, "接管测试", "13700000031");
    await bookRoom(pageOne, world.roomId);
    await pageOne.reload();
    await enterRoom(pageOne);

    const pageTwo = await context.newPage();
    await pageTwo.goto(`/room/${world.roomId}`, {
      waitUntil: "domcontentloaded",
    });

    await expect(pageOne.getByTestId("takeover-refresh")).toBeVisible({
      timeout: 15000,
    });
    await expect(pageTwo.getByTestId("start-matching")).toBeVisible({
      timeout: 30000,
    });

    await pageOne.waitForTimeout(3000);
    await expect(pageOne.getByTestId("takeover-refresh")).toBeVisible();
  } finally {
    await context.close();
  }
});
