import { expect, test } from "@playwright/test";

import {
  bookRoom,
  completeInstructionsPair,
  enterRoom,
  expectBothBooked,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  submitQuestionnaire,
  waitBothEntered,
} from "./support";

test("技术中止到场费待问卷，提交后生成到场费且不能重新预约", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(240_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = [
    { name: "中止甲", phone: "13700000041" },
    { name: "中止乙", phone: "13700000042" },
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 8,
    waitWindowSeconds: 120,
    reconnectWindowSeconds: 2,
    troopRows: [
      { soldiersA: 7, soldiersB: 7 },
      { soldiersA: 8, soldiersB: 9 },
    ],
    map: {
      rows: 2,
      cols: 2,
      formalTrials: 1,
      practiceTurnCap: 2,
      practiceTurnSeconds: 45,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
      restSeconds: 2,
      randomizeFormal: false,
      basePayCents: 4500,
      performanceRateCents: 1,
      performanceCapCents: 2000,
      showupPayCents: 1000,
    },
    roomLabel: "技术中止问卷房间",
  });

  const contextOne = await browser.newContext();
  const contextTwo = await browser.newContext();
  const pageOne = await contextOne.newPage();
  const pageTwo = await contextTwo.newPage();
  try {
    await Promise.all([
      loginParticipant(pageOne, entries[0].name, entries[0].phone),
      loginParticipant(pageTwo, entries[1].name, entries[1].phone),
    ]);
    await Promise.all([
      bookRoom(pageOne, world.roomId),
      bookRoom(pageTwo, world.roomId),
    ]);
    await expectBothBooked(pageOne, pageTwo);
    await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
    await waitBothEntered(pageOne, pageTwo);
    await startMatchingPair(pageOne, pageTwo);
    await completeInstructionsPair(pageOne, pageTwo);

    await pageTwo.close();
    await expect(
      pageOne.getByRole("heading", { name: "实验提前结束", exact: true }),
    ).toBeVisible({ timeout: 30000 });
    await expect(
      pageOne.getByText("本次实验结束后，你不能再预约新的实验", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(pageOne.getByTestId("continue-questionnaire")).toBeVisible();
    await expect(pageOne.getByTestId("rebook")).toHaveCount(0);

    const abortedHome = await contextTwo.newPage();
    await abortedHome.goto("/");
    const pendingCard = abortedHome.getByTestId("pending-questionnaire-card");
    await expect(pendingCard).toBeVisible({ timeout: 20000 });
    await expect(pendingCard).toContainText("实验提前结束：待填写问卷");
    await expect(
      pendingCard.getByTestId("continue-questionnaire"),
    ).toBeVisible();
    await expect(abortedHome.getByTestId("bookable-hidden")).toBeVisible();
    await expect(pendingCard).toContainText(
      "本次实验结束后，你不能再预约新的实验",
    );

    await submitQuestionnaire(pageOne, baseURL, world.roomId, "tech-abort-a");
    await pageOne.goto(`/complete?room=${world.roomId}`);
    await expect(pageOne.getByTestId("reward-info")).toBeVisible({
      timeout: 20000,
    });
    const archiveRow = pageOne.locator(".p-detail-row", {
      hasText: "实验结束原因",
    });
    await expect(archiveRow).toContainText("网络或系统故障");
    const formalRow = pageOne.locator(".p-detail-row", {
      hasText: "正式实验",
    });
    await expect(formalRow).toContainText("未完成");
    await expect(pageOne.getByTestId("complete-total")).toHaveText("¥10.00");
    await expect(pageOne.getByText("基础费", { exact: true })).toHaveCount(0);
    await expect(pageOne.getByText("绩效费", { exact: true })).toHaveCount(0);
    await expect(
      pageOne.getByText("本次实验未完成，不产生基础费与绩效费", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(pageOne.getByTestId("rebook")).toHaveCount(0);

    await pageOne.goto("/history");
    const historyItem = pageOne.locator(".history-item", {
      hasText: "提前结束",
    });
    await expect(historyItem).toContainText("未完成");
    await expect(historyItem).toContainText("到场费：¥10.00");
    await expect(historyItem.getByTestId("rebook")).toHaveCount(0);

    await abortedHome.reload();
    await expect(pendingCard).toBeVisible({ timeout: 20000 });
    await expect(abortedHome.locator(".p-account-status")).toContainText(
      "请先填写并提交后测问卷",
    );
  } finally {
    await contextOne.close();
    await contextTwo.close();
  }
});
