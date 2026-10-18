import { expect, test, type Page } from "@playwright/test";

import {
  bookRoom,
  completeInstructionsPair,
  enterRoom,
  expectBothBooked,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  waitBothEntered,
} from "./support";
import type { RosterEntry } from "./support";

function roster(names: string[], prefix: string): RosterEntry[] {
  return names.map((name, index) => ({
    name,
    phone: `${prefix}${String(index + 1).padStart(4, "0")}`,
  }));
}

async function selectTopRight(page: Page): Promise<void> {
  const canvas = page.getByTestId("game-canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("game canvas has no bounding box");
  await page.mouse.click(box.x + box.width * 0.75, box.y + box.height * 0.25);
}

async function canvasColors(page: Page) {
  return page.getByTestId("game-canvas").evaluate((element) => {
    const canvas = element as HTMLCanvasElement;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("canvas context missing");
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let grid = 0;
    let selection = 0;
    let ink = 0;
    let background = 0;
    let legacyGreen = 0;
    for (let index = 0; index < data.length; index += 4) {
      const red = data[index];
      const green = data[index + 1];
      const blue = data[index + 2];
      if (red === 184 && green === 184 && blue === 184) grid += 1;
      else if (red === 80 && green === 80 && blue === 80) selection += 1;
      else if (red === 28 && green === 28 && blue === 30) ink += 1;
      else if (red === 52 && green === 199 && blue === 89) legacyGreen += 1;
      else if (red === 232 && green === 240 && blue === 255) background += 1;
    }
    const total = canvas.width * canvas.height;
    return {
      grid,
      selection,
      ink,
      background,
      legacyGreen,
      inkFraction: ink / total,
      total,
    };
  });
}

test("正式回合棋盘使用灰色网格、描边棋子与红色交火边框", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["棋盘甲", "棋盘乙"], "1346000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition: {
      practiceTrials: 0,
      formalTrials: 1,
      turnCount: 2,
      turnSeconds: 60,
      restSeconds: 30,
    },
  });

  const contextOne = await browser.newContext();
  const contextTwo = await browser.newContext();
  const pageOne = await contextOne.newPage();
  const pageTwo = await contextTwo.newPage();

  await Promise.all([
    loginParticipant(pageOne, entries[0].name, entries[0].phone),
    loginParticipant(pageTwo, entries[1].name, entries[1].phone),
  ]);
  await Promise.all([bookRoom(pageOne, world.roomId), bookRoom(pageTwo, world.roomId)]);
  await expectBothBooked(pageOne, pageTwo);
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);
  await completeInstructionsPair(pageOne, pageTwo);

  await expect(pageOne.getByTestId("game-canvas")).toBeVisible({ timeout: 30000 });
  await expect(pageTwo.getByTestId("game-canvas")).toBeVisible({ timeout: 30000 });
  await expect(pageOne.locator(".exp-hud-role")).toHaveText(/^你是玩家 [○◇]$/);
  await expect(pageTwo.locator(".exp-hud-role")).toHaveText(/^你是玩家 [○◇]$/);
  await expect(pageOne.getByTestId("hud-partner")).toContainText("另一名玩家在线");

  await Promise.all([selectTopRight(pageOne), selectTopRight(pageTwo)]);
  await expect(pageOne.getByTestId("confirm-selection")).toBeEnabled();
  await expect(pageTwo.getByTestId("confirm-selection")).toBeEnabled();

  const colors = await canvasColors(pageOne);
  expect(colors.grid).toBeGreaterThan(0);
  expect(colors.selection).toBeGreaterThan(0);
  expect(colors.ink).toBeGreaterThan(0);
  expect(colors.background).toBeGreaterThan(0);
  expect(colors.legacyGreen).toBe(0);
  expect(colors.inkFraction).toBeLessThan(0.05);

  const beforeBox = await pageOne.getByTestId("game-canvas").boundingBox();
  if (beforeBox === null) throw new Error("game canvas has no bounding box");

  await pageOne.getByTestId("confirm-selection").click();
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("已提交");
  const waitingColors = await canvasColors(pageOne);
  expect(waitingColors.selection).toBeGreaterThan(0);
  await expect(pageOne.getByTestId("hud-partner")).toContainText("另一名玩家在线");
  await expect(pageTwo.getByTestId("hud-partner")).toContainText("另一名玩家在线");
  await expect(pageTwo.getByTestId("hud-partner")).not.toContainText("已提交");

  await pageTwo.getByTestId("confirm-selection").click();
  const warCell = pageOne.locator(".exp-war-cell").first();
  await expect(warCell).toBeVisible({ timeout: 1500 });
  await expect(pageOne.locator(".exp-result-line")).toHaveCount(0);
  await expect
    .poll(async () => (await canvasColors(pageOne)).selection, { timeout: 2000 })
    .toBe(0);
  const duringBox = await pageOne.getByTestId("game-canvas").boundingBox();
  if (duringBox === null) throw new Error("game canvas has no bounding box");
  expect(Math.abs(duringBox.width - beforeBox.width)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(duringBox.height - beforeBox.height)).toBeLessThanOrEqual(0.5);
  const warStyle = await warCell.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      borderColor: style.borderTopColor,
      borderWidth: style.borderTopWidth,
      animationDuration: style.animationDuration,
    };
  });
  expect(warStyle.borderColor).toBe("rgb(255, 59, 48)");
  expect(warStyle.borderWidth).toBe("2px");
  expect(warStyle.animationDuration).toBe("1s");

  await expect(pageOne.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 3000,
  });
  await expect(pageTwo.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 3000,
  });
  await expect(pageOne.locator(".exp-war-cell")).toHaveCount(0);

  await contextOne.close();
  await contextTwo.close();
});
