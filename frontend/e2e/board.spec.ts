import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContextOptions,
  type Page,
} from "@playwright/test";

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
import type { ConditionConfig, RosterEntry } from "./support";

const LEGACY_RESULT_TEXT = [
  "结算中",
  "回合结算中",
  "回合已结算，请等待下一回合。",
  "本回合交火",
  "即将进入下一回合",
  "系统已自动选择",
];

function roster(names: string[], prefix: string): RosterEntry[] {
  return names.map((name, index) => ({
    name,
    phone: `${prefix}${String(index + 1).padStart(4, "0")}`,
  }));
}

async function canvasBox(page: Page) {
  const canvas = page.getByTestId("game-canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("game canvas has no bounding box");
  return box;
}

async function selectTopRight(page: Page): Promise<void> {
  const box = await canvasBox(page);
  await page.mouse.click(box.x + box.width * 0.75, box.y + box.height * 0.25);
}

async function selectOwnBase(page: Page): Promise<void> {
  const box = await canvasBox(page);
  const roleText = await page.locator(".exp-hud-role").innerText();
  const isCircle = roleText.includes("○");
  await page.mouse.click(
    box.x + box.width * (isCircle ? 0.25 : 0.75),
    box.y + box.height * (isCircle ? 0.25 : 0.75),
  );
}

function parseClock(text: string): number {
  const [minutes, seconds] = text.trim().split(":").map(Number);
  return minutes * 60 + seconds;
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
    const rightEdge = Array.from(
      context.getImageData(canvas.width - 1, Math.floor(canvas.height * 0.75), 1, 1).data,
    ).slice(0, 3);
    const bottomEdge = Array.from(
      context.getImageData(Math.floor(canvas.width * 0.25), canvas.height - 1, 1, 1).data,
    ).slice(0, 3);
    return {
      grid,
      selection,
      ink,
      background,
      legacyGreen,
      inkFraction: ink / total,
      total,
      rightEdge,
      bottomEdge,
    };
  });
}

interface WarTiming {
  warVisibleAt: number | null;
  nextRoundAt: number | null;
}

interface WarSample {
  frames: number;
  overlayFrames: number;
  selectionFrames: number;
  done: boolean;
}

async function startGamePair(
  browser: Browser,
  request: APIRequestContext,
  baseURL: string,
  entries: RosterEntry[],
  condition: ConditionConfig,
  contextOptions: BrowserContextOptions = {},
) {
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition,
  });

  const contextOne = await browser.newContext(contextOptions);
  const contextTwo = await browser.newContext(contextOptions);
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

  return { contextOne, contextTwo, pageOne, pageTwo };
}

async function installWarInstrumentation(page: Page): Promise<void> {
  await page.evaluate(() => {
    const timing: WarTiming = { warVisibleAt: null, nextRoundAt: null };
    const sample: WarSample = {
      frames: 0,
      overlayFrames: 0,
      selectionFrames: 0,
      done: false,
    };
    const scope = window as Window & {
      __warTiming?: WarTiming;
      __warSample?: WarSample;
    };
    scope.__warTiming = timing;
    scope.__warSample = sample;

    const hud = document.querySelector(".exp-hud-left");
    const canvas = document.querySelector('[data-testid="game-canvas"]');
    if (hud === null) throw new Error("hud left missing");
    if (!(canvas instanceof HTMLCanvasElement)) throw new Error("game canvas missing");

    const checkTiming = () => {
      if (
        timing.warVisibleAt === null &&
        document.querySelector(".exp-war-cell") !== null
      ) {
        timing.warVisibleAt = performance.now();
      }
      if (
        timing.warVisibleAt !== null &&
        timing.nextRoundAt === null &&
        (hud.textContent ?? "").includes("回合 2/2")
      ) {
        timing.nextRoundAt = performance.now();
      }
    };
    new MutationObserver(checkTiming).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    checkTiming();

    const sampleFrame = () => {
      sample.frames += 1;
      const warVisible = document.querySelector(".exp-war-cell") !== null;
      if (warVisible) {
        sample.overlayFrames += 1;
        const context = canvas.getContext("2d");
        if (context === null) throw new Error("canvas context missing");
        const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const pixels = new Uint32Array(
          data.buffer,
          data.byteOffset,
          data.byteLength / 4,
        );
        for (let index = 0; index < pixels.length; index += 1) {
          // 小端序下不透明 #505050 为 0xFF505050。
          if (pixels[index] === 0xff505050) {
            sample.selectionFrames += 1;
            break;
          }
        }
      }
      if (sample.overlayFrames > 0 && !warVisible) {
        sample.done = true;
        return;
      }
      if (sample.frames >= 240) {
        sample.done = true;
        return;
      }
      requestAnimationFrame(sampleFrame);
    };
    requestAnimationFrame(sampleFrame);
  });
}

async function readWarTiming(page: Page): Promise<WarTiming> {
  const timing = await page.evaluate(() => {
    const scope = window as Window & { __warTiming?: WarTiming };
    return scope.__warTiming ?? null;
  });
  if (timing === null) throw new Error("war timing was not captured");
  return timing;
}

async function readWarSample(page: Page): Promise<WarSample> {
  const sample = await page.evaluate(() => {
    const scope = window as Window & { __warSample?: WarSample };
    return scope.__warSample ?? null;
  });
  if (sample === null) throw new Error("war sample was not captured");
  return sample;
}

async function expectFullTurnCountdown(page: Page, seconds: number): Promise<void> {
  // HUD 按整秒向下取整；等待一次 250ms 刷新后，完整回合应显示 seconds-1。
  // 如果交火结果没有从下一回合扣除，时间会继续减少到 seconds-2。
  await page.waitForTimeout(300);
  expect(parseClock(await page.getByTestId("game-countdown").innerText())).toBeGreaterThanOrEqual(
    seconds - 1,
  );
}

test("正式回合棋盘使用灰色网格、描边棋子与红色交火边框", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["棋盘甲", "棋盘乙"], "1348000");
  const { contextOne, contextTwo, pageOne, pageTwo } = await startGamePair(
    browser,
    request,
    baseURL,
    entries,
    {
      practiceTrials: 0,
      formalTrials: 1,
      turnCount: 2,
      turnSeconds: 60,
      restSeconds: 30,
    },
  );

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
  expect(colors.rightEdge).toEqual([184, 184, 184]);
  expect(colors.bottomEdge).toEqual([184, 184, 184]);

  const beforeBox = await pageOne.getByTestId("game-canvas").boundingBox();
  if (beforeBox === null) throw new Error("game canvas has no bounding box");

  await pageOne.getByTestId("confirm-selection").click();
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("已提交");
  const waitingColors = await canvasColors(pageOne);
  expect(waitingColors.selection).toBeGreaterThan(0);
  await expect(pageOne.getByTestId("hud-partner")).toContainText("另一名玩家在线");
  await expect(pageTwo.getByTestId("hud-partner")).toContainText("另一名玩家在线");
  await expect(pageTwo.getByTestId("hud-partner")).not.toContainText("已提交");

  await installWarInstrumentation(pageOne);
  await pageTwo.getByTestId("confirm-selection").click();
  const warCell = pageOne.locator(".exp-war-cell");
  await expect(warCell).toHaveCount(1, { timeout: 1500 });
  await expect(warCell.first()).toBeVisible({ timeout: 1500 });
  const resultStageText = await pageOne.locator(".exp-root").innerText();
  for (const text of LEGACY_RESULT_TEXT) {
    expect(resultStageText).not.toContain(text);
  }
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("已提交");
  const placement = await warCell.first().evaluate((element) => ({
    column: (element as HTMLElement).style.gridColumn,
    row: (element as HTMLElement).style.gridRow,
  }));
  expect(placement).toEqual({ column: "2", row: "1" });
  await expect
    .poll(async () => (await canvasColors(pageOne)).selection, { timeout: 2000 })
    .toBe(0);
  const duringBox = await pageOne.getByTestId("game-canvas").boundingBox();
  if (duringBox === null) throw new Error("game canvas has no bounding box");
  expect(Math.abs(duringBox.width - beforeBox.width)).toBeLessThanOrEqual(0.5);
  expect(Math.abs(duringBox.height - beforeBox.height)).toBeLessThanOrEqual(0.5);
  const warStyle = await warCell.first().evaluate((element) => {
    const style = getComputedStyle(element);
    const animation = element.getAnimations()[0];
    return {
      borderColor: style.borderTopColor,
      borderWidth: style.borderTopWidth,
      animationDuration: style.animationDuration,
      keyframes:
        animation?.effect
          ?.getKeyframes()
          .map((frame) => ({ offset: frame.offset, opacity: frame.opacity })) ?? [],
    };
  });
  expect(warStyle.borderColor).toBe("rgb(255, 59, 48)");
  expect(warStyle.borderWidth).toBe("2px");
  expect(warStyle.animationDuration).toBe("1s");
  expect(warStyle.keyframes).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ offset: 0, opacity: "1" }),
      expect.objectContaining({ offset: 0.6, opacity: "1" }),
      expect.objectContaining({ offset: 1, opacity: "0" }),
    ]),
  );

  const frozenClock = await pageOne.getByTestId("game-countdown").innerText();
  expect(parseClock(frozenClock)).toBe(60);
  await pageOne.waitForTimeout(400);
  expect(await pageOne.getByTestId("game-countdown").innerText()).toBe(frozenClock);

  await expect(pageOne.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 3000,
  });
  await expectFullTurnCountdown(pageOne, 60);
  await expect(pageTwo.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 3000,
  });
  await expectFullTurnCountdown(pageTwo, 60);
  await expect(pageOne.locator(".exp-war-cell")).toHaveCount(0);

  const timing = await readWarTiming(pageOne);
  if (timing.warVisibleAt === null || timing.nextRoundAt === null) {
    throw new Error(`war result timing incomplete: ${JSON.stringify(timing)}`);
  }
  const resultWindowMs = timing.nextRoundAt - timing.warVisibleAt;
  expect(resultWindowMs).toBeGreaterThanOrEqual(500);
  expect(resultWindowMs).toBeLessThan(1800);

  await expect
    .poll(async () => (await readWarSample(pageOne)).done, { timeout: 5000 })
    .toBe(true);
  const sample = await readWarSample(pageOne);
  expect(sample.overlayFrames).toBeGreaterThan(0);
  expect(sample.selectionFrames).toBe(0);

  await contextOne.close();
  await contextTwo.close();
});

test("没有交火格时直接进入下一回合并开始完整倒计时", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["静默甲", "静默乙"], "1348001");
  const { contextOne, contextTwo, pageOne, pageTwo } = await startGamePair(
    browser,
    request,
    baseURL,
    entries,
    {
      practiceTrials: 0,
      formalTrials: 1,
      turnCount: 2,
      turnSeconds: 60,
      restSeconds: 30,
    },
  );

  await Promise.all([selectOwnBase(pageOne), selectOwnBase(pageTwo)]);
  await pageOne.getByTestId("confirm-selection").click();
  await pageTwo.getByTestId("confirm-selection").click();
  await expect(pageOne.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 900,
  });
  await expectFullTurnCountdown(pageOne, 60);
  await expect(pageTwo.locator(".exp-hud-left")).toContainText("回合 2/2", {
    timeout: 900,
  });
  await expectFullTurnCountdown(pageTwo, 60);
  await expect(pageOne.locator(".exp-war-cell")).toHaveCount(0);

  await contextOne.close();
  await contextTwo.close();
});

test("试次结束的交火回合后进入休息并显示完整休息倒计时", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["终局甲", "终局乙"], "1349000");
  const { contextOne, contextTwo, pageOne, pageTwo } = await startGamePair(
    browser,
    request,
    baseURL,
    entries,
    {
      practiceTrials: 0,
      formalTrials: 2,
      turnCount: 1,
      turnSeconds: 60,
      restSeconds: 30,
    },
  );

  await expect(pageOne.locator(".exp-hud-left")).toContainText("回合 1/1");

  await Promise.all([selectTopRight(pageOne), selectTopRight(pageTwo)]);
  await pageOne.getByTestId("confirm-selection").click();
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("已提交");
  await pageTwo.getByTestId("confirm-selection").click();

  const warOne = pageOne.locator(".exp-war-cell");
  const warTwo = pageTwo.locator(".exp-war-cell");
  await expect(warOne).toHaveCount(1, { timeout: 1500 });
  await expect(warTwo).toHaveCount(1, { timeout: 1500 });
  await expect(warOne.first()).toHaveCSS("border-top-color", "rgb(255, 59, 48)");
  await expect(warOne.first()).toHaveCSS("border-top-width", "2px");
  await expect(pageOne.getByTestId("rest-view")).toHaveCount(0);

  await expect(pageOne.getByTestId("rest-view")).toBeVisible({ timeout: 5000 });
  const restClock = parseClock(
    await pageOne.getByTestId("rest-countdown").innerText(),
  );
  expect(restClock).toBeGreaterThanOrEqual(29);
  expect(restClock).toBeLessThanOrEqual(31);

  await expect(pageTwo.getByTestId("rest-view")).toBeVisible({ timeout: 5000 });
  await expect(pageOne.locator(".exp-war-cell")).toHaveCount(0);
  await expect(pageOne.getByTestId("rest-trial-chip")).toContainText("1/2");

  await contextOne.close();
  await contextTwo.close();
});

test("减少动态效果时交火边框保持静态红色", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["静态甲", "静态乙"], "1349100");
  const { contextOne, contextTwo, pageOne, pageTwo } = await startGamePair(
    browser,
    request,
    baseURL,
    entries,
    {
      practiceTrials: 0,
      formalTrials: 1,
      turnCount: 2,
      turnSeconds: 60,
      restSeconds: 30,
    },
    { reducedMotion: "reduce" },
  );

  await Promise.all([selectTopRight(pageOne), selectTopRight(pageTwo)]);
  await pageOne.getByTestId("confirm-selection").click();
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("已提交");
  await pageTwo.getByTestId("confirm-selection").click();

  const warCell = pageOne.locator(".exp-war-cell");
  await expect(warCell).toHaveCount(1, { timeout: 1500 });
  await expect(warCell.first()).toBeVisible({ timeout: 1500 });
  const style = await warCell.first().evaluate((element) => {
    const computed = getComputedStyle(element);
    return {
      borderColor: computed.borderTopColor,
      borderWidth: computed.borderTopWidth,
      animationName: computed.animationName,
      animations: element.getAnimations().length,
    };
  });
  expect(style).toEqual({
    borderColor: "rgb(255, 59, 48)",
    borderWidth: "2px",
    animationName: "none",
    animations: 0,
  });

  await contextOne.close();
  await contextTwo.close();
});
