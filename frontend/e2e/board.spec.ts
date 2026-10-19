import { expect, test } from "@playwright/test";
import type {
  APIRequestContext,
  Browser,
  BrowserContextOptions,
  Locator,
  Page,
} from "@playwright/test";

import {
  adminApi,
  adminLogin,
  adminLoginPage,
  bookRoom,
  completeInstructionsPair,
  continueFromRestPair,
  enterRoom,
  expectBothBooked,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  uploadMedia,
  waitBothEntered,
} from "./support";
import type { RosterEntry, TroopRow } from "./support";

const BOARD_ROWS = 10;
const BOARD_COLS = 10;
const BOARD_SIZE = 600;
const PNG_CELL = 12;
const JPEG_CELL = 34;
const SPAWN_A = 0;
const SPAWN_B = 99;

const WAR_ROWS = 2;
const WAR_COLS = 2;
const PRACTICE_TURN_TWO = "练习 2/2";

const LEGACY_RESULT_TEXT = [
  "结算中",
  "回合结算中",
  "回合已结算，请等待下一回合。",
  "本回合交火",
  "即将进入下一回合",
  "系统已自动选择",
];

interface PointSample {
  label: string;
  x: number;
  y: number;
  rgba: number[];
}

interface BoardSnapshot {
  width: number;
  height: number;
  digest: string;
  white: number[];
  grid: PointSample[];
  coverPngLow: number[];
  coverPngHigh: number[];
  coverJpegLow: number[];
  coverJpegHigh: number[];
  gridPngEdge: number[];
  pngBeforeGrid: number[];
  pngAfterGrid: number[];
  gridJpegEdge: number[];
  jpegBeforeGrid: number[];
  jpegAfterGrid: number[];
  spawnInkA: number;
  spawnInkB: number;
}

interface WarConfig {
  formalTrials: number;
  practiceTurnCap: number;
  practiceTurnSeconds: number;
  formalTurnCap: number;
  formalTurnSeconds: number;
  restSeconds: number;
}

async function generateCoverImages(
  browser: Browser,
): Promise<{ png: Buffer; jpeg: Buffer }> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("about:blank");
  const urls = await page.evaluate(() => {
    const stripes = (
      width: number,
      height: number,
      colors: string[],
      vertical: boolean,
    ): HTMLCanvasElement => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (context === null) throw new Error("missing 2d context");
      colors.forEach((color, index) => {
        context.fillStyle = color;
        if (vertical) {
          context.fillRect((index * width) / colors.length, 0, width / colors.length, height);
        } else {
          context.fillRect(0, (index * height) / colors.length, width, height / colors.length);
        }
      });
      return canvas;
    };
    const png = stripes(
      40,
      10,
      ["#ff0000", "#00ff00", "#0000ff", "#ffffff"],
      true,
    );
    const jpeg = stripes(
      10,
      40,
      ["#ff0000", "#00c800", "#0000ff", "#ffffff"],
      false,
    );
    return {
      png: png.toDataURL("image/png"),
      jpeg: jpeg.toDataURL("image/jpeg", 0.95),
    };
  });
  await context.close();
  const decode = (url: string): Buffer => {
    const marker = "base64,";
    const index = url.indexOf(marker);
    if (index < 0) throw new Error("unexpected data URL");
    return Buffer.from(url.slice(index + marker.length), "base64");
  };
  return { png: decode(urls.png), jpeg: decode(urls.jpeg) };
}

function rgbaKey(values: number[]): string {
  return values.join(",");
}

async function waitForCanvas(canvas: Locator): Promise<void> {
  await expect(canvas).toBeVisible({ timeout: 30000 });
  await expect(canvas).toHaveAttribute("data-images-ready", "true", {
    timeout: 30000,
  });
  await canvas.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
  await canvas.evaluate(() => document.fonts.ready.then(() => undefined));
}

async function snapshotBoard(
  canvas: Locator,
  spawns: number[],
): Promise<BoardSnapshot> {
  return canvas.evaluate(
    async (element, options) => {
      const board = element as HTMLCanvasElement;
      const context = board.getContext("2d", { willReadFrequently: true });
      if (context === null) throw new Error("missing canvas context");
      const { width, height } = board;
      const image = context.getImageData(0, 0, width, height);
      const masked = new Uint8ClampedArray(image.data);
      const rows = options.rows;
      const cols = options.cols;
      for (const index of options.spawns) {
        const row = Math.floor(index / cols);
        const col = index % cols;
        const x0 = Math.floor((width * col) / cols);
        const x1 = Math.ceil((width * (col + 1)) / cols);
        const y0 = Math.floor((height * row) / rows);
        const y1 = Math.ceil((height * (row + 1)) / rows);
        for (let y = y0; y < y1; y += 1) {
          for (let x = x0; x < x1; x += 1) {
            const offset = (y * width + x) * 4;
            masked[offset] = 0;
            masked[offset + 1] = 0;
            masked[offset + 2] = 0;
            masked[offset + 3] = 0;
          }
        }
      }
      const hashed = await crypto.subtle.digest("SHA-256", masked);
      const digest = Array.from(new Uint8Array(hashed))
        .map((value) => value.toString(16).padStart(2, "0"))
        .join("");
      const pixel = (x: number, y: number): number[] => {
        const data = context.getImageData(
          Math.min(width - 1, Math.max(0, x)),
          Math.min(height - 1, Math.max(0, y)),
          1,
          1,
        ).data;
        return [data[0], data[1], data[2], data[3]];
      };
      const cellPoint = (index: number, fx: number, fy: number): [number, number] => {
        const row = Math.floor(index / cols);
        const col = index % cols;
        return [
          Math.floor((width * (col + fx)) / cols),
          Math.floor((height * (row + fy)) / rows),
        ];
      };
      const samples: { x: number; y: number; rgba: number[] }[] = [];
      for (let col = 1; col < cols; col += 1) {
        const x = Math.round((width * col) / cols);
        samples.push({ x, y: Math.round(height * 0.35), rgba: pixel(x, Math.round(height * 0.35)) });
      }
      for (let row = 1; row < rows; row += 1) {
        const y = Math.round((height * row) / rows);
        samples.push({ x: Math.round(width * 0.35), y, rgba: pixel(Math.round(width * 0.35), y) });
      }
      samples.push({ x: 0, y: Math.round(height * 0.35), rgba: pixel(0, Math.round(height * 0.35)) });
      samples.push({
        x: width - 1,
        y: Math.round(height * 0.35),
        rgba: pixel(width - 1, Math.round(height * 0.35)),
      });
      samples.push({ x: Math.round(width * 0.35), y: 0, rgba: pixel(Math.round(width * 0.35), 0) });
      samples.push({
        x: Math.round(width * 0.35),
        y: height - 1,
        rgba: pixel(Math.round(width * 0.35), height - 1),
      });
      const [pngLowX, pngLowY] = cellPoint(options.pngCell, 0.25, 0.5);
      const [pngHighX, pngHighY] = cellPoint(options.pngCell, 0.75, 0.5);
      const [jpegLowX, jpegLowY] = cellPoint(options.jpegCell, 0.5, 0.25);
      const [jpegHighX, jpegHighY] = cellPoint(options.jpegCell, 0.5, 0.75);
      const [pngEdgeX, pngEdgeY] = cellPoint(options.pngCell, 1, 0.5);
      const [jpegEdgeX, jpegEdgeY] = cellPoint(options.jpegCell, 0, 0.4);
      const darkPixels = (index: number): number => {
        const row = Math.floor(index / cols);
        const col = index % cols;
        const x0 = Math.floor((width * col) / cols) + 2;
        const x1 = Math.ceil((width * (col + 1)) / cols) - 2;
        const y0 = Math.floor((height * row) / rows) + 2;
        const y1 = Math.ceil((height * (row + 1)) / rows) - 2;
        const data = context.getImageData(x0, y0, x1 - x0, y1 - y0).data;
        let count = 0;
        for (let offset = 0; offset < data.length; offset += 4) {
          if (data[offset] < 128 || data[offset + 1] < 128 || data[offset + 2] < 128) {
            count += 1;
          }
        }
        return count;
      };
      return {
        width,
        height,
        digest,
        white: pixel(...cellPoint(2, 0.5, 0.5)),
        grid: samples.map((sample, index) => ({
          label: `grid-${index}`,
          x: sample.x,
          y: sample.y,
          rgba: sample.rgba,
        })),
        coverPngLow: pixel(pngLowX, pngLowY),
        coverPngHigh: pixel(pngHighX, pngHighY),
        coverJpegLow: pixel(jpegLowX, jpegLowY),
        coverJpegHigh: pixel(jpegHighX, jpegHighY),
        gridPngEdge: pixel(pngEdgeX, pngEdgeY),
        pngBeforeGrid: pixel(pngEdgeX - 1, pngEdgeY),
        pngAfterGrid: pixel(pngEdgeX + 1, pngEdgeY),
        gridJpegEdge: pixel(jpegEdgeX, jpegEdgeY),
        jpegBeforeGrid: pixel(jpegEdgeX - 1, jpegEdgeY),
        jpegAfterGrid: pixel(jpegEdgeX + 1, jpegEdgeY),
        spawnInkA: darkPixels(options.spawns[0]),
        spawnInkB: darkPixels(options.spawns[1]),
      };
    },
    {
      rows: BOARD_ROWS,
      cols: BOARD_COLS,
      spawns,
      pngCell: PNG_CELL,
      jpegCell: JPEG_CELL,
    },
  );
}

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
      else if (red === 255 && green === 255 && blue === 255) background += 1;
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
  config: WarConfig,
  contextOptions: BrowserContextOptions = {},
) {
  const troopRows: TroopRow[] = [
    { soldiersA: 7, soldiersB: 7 },
    ...Array.from({ length: config.formalTrials }, () => ({
      soldiersA: 8,
      soldiersB: 9,
    })),
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 35,
    troopRows,
    map: {
      rows: WAR_ROWS,
      cols: WAR_COLS,
      formalTrials: config.formalTrials,
      practiceTurnCap: config.practiceTurnCap,
      practiceTurnSeconds: config.practiceTurnSeconds,
      formalTurnCap: config.formalTurnCap,
      formalTurnSeconds: config.formalTurnSeconds,
      restSeconds: config.restSeconds,
      randomizeFormal: false,
    },
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
        (hud.textContent ?? "").includes("练习 2/2")
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

test("地图编辑预览与参与者画布的地图背景逐像素一致", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(240_000);
  if (!baseURL) throw new Error("baseURL missing");
  const images = await generateCoverImages(browser);
  await adminLogin(request, baseURL);
  const pngAssetId = await uploadMedia(request, baseURL, {
    data: images.png,
    filename: "cover-wide.png",
    mimeType: "image/png",
  });
  const jpegAssetId = await uploadMedia(request, baseURL, {
    data: images.jpeg,
    filename: "cover-tall.jpg",
    mimeType: "image/jpeg",
  });
  const cells: (string | null)[] = Array.from(
    { length: BOARD_ROWS * BOARD_COLS },
    () => null,
  );
  cells[PNG_CELL] = pngAssetId;
  cells[JPEG_CELL] = jpegAssetId;

  const entries = [
    { name: "像素甲", phone: "13600000001" },
    { name: "像素乙", phone: "13600000002" },
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 25,
    troopRows: [
      { soldiersA: 7, soldiersB: 7 },
      { soldiersA: 8, soldiersB: 9 },
    ],
    map: {
      rows: BOARD_ROWS,
      cols: BOARD_COLS,
      images: cells,
      spawns: { A: SPAWN_A, B: SPAWN_B },
      practiceTurnCap: 1,
      practiceTurnSeconds: 60,
      formalTurnCap: 1,
      formalTurnSeconds: 60,
    },
  });
  expect(world.rows).toBe(BOARD_ROWS);
  expect(world.cols).toBe(BOARD_COLS);

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminLoginPage(adminPage);
  await adminPage.goto("/admin/map-groups");
  await expect(
    adminPage.getByRole("heading", { name: "地图组", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await adminPage.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  const previewRow = adminPage.getByTestId("map-group-preview-row");
  await expect(previewRow).toHaveValue("1");
  await expect(previewRow.locator("option")).toHaveText(["练习", "正式 1"]);
  const adminCanvas = adminPage.getByTestId("map-group-board");
  await waitForCanvas(adminCanvas);
  const adminSnapshot = await snapshotBoard(adminCanvas, [SPAWN_A, SPAWN_B]);
  expect(adminSnapshot.width).toBe(BOARD_SIZE);
  expect(adminSnapshot.height).toBe(BOARD_SIZE);

  const viewport = { width: 616, height: 900 };
  const contextOne = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
  });
  const contextTwo = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
  });
  const pageOne = await contextOne.newPage();
  const pageTwo = await contextTwo.newPage();
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

  const playerCanvas = pageOne.getByTestId("game-canvas");
  await waitForCanvas(playerCanvas);
  const playerSnapshot = await snapshotBoard(playerCanvas, [SPAWN_A, SPAWN_B]);
  expect(playerSnapshot.width).toBe(BOARD_SIZE);
  expect(playerSnapshot.height).toBe(BOARD_SIZE);
  await expect(pageOne.locator(".exp-war-overlay")).toHaveCount(0);

  expect(playerSnapshot.digest).toBe(adminSnapshot.digest);
  expect(rgbaKey(playerSnapshot.white)).toBe(rgbaKey(adminSnapshot.white));
  expect(rgbaKey(playerSnapshot.white)).toBe("255,255,255,255");

  expect(playerSnapshot.grid).toHaveLength(BOARD_COLS - 1 + BOARD_ROWS - 1 + 4);
  for (const [index, sample] of playerSnapshot.grid.entries()) {
    const adminSample = adminSnapshot.grid[index];
    expect(sample.rgba).toEqual(adminSample.rgba);
    expect(sample.rgba).toEqual([184, 184, 184, 255]);
  }

  expect(rgbaKey(playerSnapshot.coverPngLow)).toBe(
    rgbaKey(adminSnapshot.coverPngLow),
  );
  expect(rgbaKey(playerSnapshot.coverPngHigh)).toBe(
    rgbaKey(adminSnapshot.coverPngHigh),
  );
  expect(playerSnapshot.coverPngLow[1]).toBeGreaterThan(200);
  expect(playerSnapshot.coverPngLow[0]).toBeLessThan(30);
  expect(playerSnapshot.coverPngLow[2]).toBeLessThan(30);
  expect(playerSnapshot.coverPngHigh[2]).toBeGreaterThan(200);
  expect(playerSnapshot.coverPngHigh[0]).toBeLessThan(30);
  expect(playerSnapshot.coverPngHigh[1]).toBeLessThan(30);

  expect(rgbaKey(playerSnapshot.coverJpegLow)).toBe(
    rgbaKey(adminSnapshot.coverJpegLow),
  );
  expect(rgbaKey(playerSnapshot.coverJpegHigh)).toBe(
    rgbaKey(adminSnapshot.coverJpegHigh),
  );
  for (const field of [
    "gridPngEdge",
    "pngBeforeGrid",
    "pngAfterGrid",
    "gridJpegEdge",
    "jpegBeforeGrid",
    "jpegAfterGrid",
  ] as const) {
    expect(rgbaKey(playerSnapshot[field])).toBe(
      rgbaKey(adminSnapshot[field]),
    );
  }
  expect(playerSnapshot.gridPngEdge).toEqual([184, 184, 184, 255]);
  expect(playerSnapshot.pngBeforeGrid[2]).toBeGreaterThan(200);
  expect(playerSnapshot.pngBeforeGrid[0]).toBeLessThan(30);
  expect(playerSnapshot.pngBeforeGrid[1]).toBeLessThan(30);
  expect(playerSnapshot.pngAfterGrid).toEqual([255, 255, 255, 255]);
  expect(playerSnapshot.gridJpegEdge).toEqual([184, 184, 184, 255]);
  expect(playerSnapshot.jpegBeforeGrid).toEqual([255, 255, 255, 255]);
  expect(playerSnapshot.jpegAfterGrid[1]).toBeGreaterThan(150);
  expect(playerSnapshot.jpegAfterGrid[2]).toBeLessThan(120);
  expect(playerSnapshot.coverJpegLow[1]).toBeGreaterThan(
    playerSnapshot.coverJpegLow[2],
  );
  expect(playerSnapshot.coverJpegLow[1]).toBeGreaterThan(
    playerSnapshot.coverJpegLow[0],
  );
  expect(playerSnapshot.coverJpegHigh[2]).toBeGreaterThan(
    playerSnapshot.coverJpegHigh[1],
  );
  expect(playerSnapshot.coverJpegHigh[2]).toBeGreaterThan(
    playerSnapshot.coverJpegHigh[0],
  );

  expect(adminSnapshot.spawnInkA).toBe(0);
  expect(adminSnapshot.spawnInkB).toBe(0);
  expect(playerSnapshot.spawnInkA).toBeGreaterThan(0);
  expect(playerSnapshot.spawnInkB).toBeGreaterThan(0);

  await contextOne.close();
  await contextTwo.close();
  await adminContext.close();
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/rooms/${world.roomId}/archive`,
    { reason: "admin_aborted" },
  );
});

test("练习回合棋盘使用灰色网格、描边棋子与红色交火边框", async ({
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
      formalTrials: 1,
      practiceTurnCap: 2,
      practiceTurnSeconds: 60,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
      restSeconds: 30,
    },
  );

  await expect(pageOne.locator(".exp-hud-role")).toHaveText(/^你是玩家 [○◇]$/);
  await expect(pageTwo.locator(".exp-hud-role")).toHaveText(/^你是玩家 [○◇]$/);
  await expect(pageOne.getByTestId("hud-partner")).toContainText("另一名玩家在线");
  await expect(pageOne.locator(".exp-hud-left")).toContainText("练习 1/2");

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

  await expect(pageOne.locator(".exp-hud-left")).toContainText(PRACTICE_TURN_TWO, {
    timeout: 3000,
  });
  await expectFullTurnCountdown(pageOne, 60);
  await expect(pageTwo.locator(".exp-hud-left")).toContainText(PRACTICE_TURN_TWO, {
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
      formalTrials: 1,
      practiceTurnCap: 2,
      practiceTurnSeconds: 60,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
      restSeconds: 30,
    },
  );

  await Promise.all([selectOwnBase(pageOne), selectOwnBase(pageTwo)]);
  await pageOne.getByTestId("confirm-selection").click();
  await pageTwo.getByTestId("confirm-selection").click();
  await expect(pageOne.locator(".exp-hud-left")).toContainText(PRACTICE_TURN_TWO, {
    timeout: 900,
  });
  await expectFullTurnCountdown(pageOne, 60);
  await expect(pageTwo.locator(".exp-hud-left")).toContainText(PRACTICE_TURN_TWO, {
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
      formalTrials: 2,
      practiceTurnCap: 1,
      practiceTurnSeconds: 60,
      formalTurnCap: 1,
      formalTurnSeconds: 60,
      restSeconds: 30,
    },
  );

  await expect(pageOne.locator(".exp-hud-left")).toContainText("练习 1/1");
  await Promise.all([selectTopRight(pageOne), selectTopRight(pageTwo)]);
  await pageOne.getByTestId("confirm-selection").click();
  await pageTwo.getByTestId("confirm-selection").click();
  await expect(pageOne.getByTestId("rest-view")).toBeVisible({ timeout: 5000 });
  await expect(pageTwo.getByTestId("rest-view")).toBeVisible({ timeout: 5000 });
  await expect(pageOne.getByTestId("rest-trial-chip")).toHaveText("练习局");
  await continueFromRestPair(pageOne, pageTwo);

  await expect(pageOne.locator(".exp-hud-left")).toContainText(
    "正式 1/2 · 回合 1/1",
  );

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
      formalTrials: 1,
      practiceTurnCap: 2,
      practiceTurnSeconds: 60,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
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
