import { expect, test } from "@playwright/test";
import type { Browser, Locator } from "@playwright/test";

import {
  adminApi,
  adminLogin,
  adminLoginPage,
  bookRoom,
  completeInstructionsPair,
  enterRoom,
  expectBothBooked,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  uploadMedia,
  waitBothEntered,
} from "./support";

const BOARD_ROWS = 10;
const BOARD_COLS = 10;
const BOARD_SIZE = 600;
const PNG_CELL = 12;
const JPEG_CELL = 34;
const SPAWN_A = 0;
const SPAWN_B = 99;

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
