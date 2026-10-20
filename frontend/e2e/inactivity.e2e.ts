import { expect, test } from "@playwright/test";

import {
  bookRoom,
  enterRoom,
  expectBothBooked,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  waitBothEntered,
} from "./support";

test("指导语阶段无操作先警告再归档，双方可以重新预约", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = [
    { name: "无操作甲", phone: "13700000051" },
    { name: "无操作乙", phone: "13700000052" },
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 8,
    waitWindowSeconds: 120,
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
    },
    roomLabel: "无操作归档房间",
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

    const ackOne = pageOne.getByTestId("inactivity-ack");
    const ackTwo = pageTwo.getByTestId("inactivity-ack");
    await expect(ackOne).toBeVisible({ timeout: 30000 });
    await expect(ackTwo).toBeVisible({ timeout: 30000 });
    await expect(
      pageOne.getByText("若继续无操作，实验将在", { exact: false }),
    ).toBeVisible();
    await ackOne.click();
    await expect(ackOne).toHaveCount(0);
    await expect(pageOne.getByTestId("instruction-content")).toBeVisible();

    const archiveHeading = /实验已中止|你已退出实验/;
    for (const page of [pageOne, pageTwo]) {
      await expect(
        page
          .getByRole("heading", { name: archiveHeading })
          .or(page.getByText("你已主动退出本次实验", { exact: false })),
      ).toBeVisible({ timeout: 40000 });
      await expect(
        page
          .getByTestId("rebook")
          .or(page.getByRole("heading", { name: "可预约场次" })),
      ).toBeVisible({ timeout: 20000 });
    }
  } finally {
    await contextOne.close();
    await contextTwo.close();
  }
});
