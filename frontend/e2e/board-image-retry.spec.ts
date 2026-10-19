import { expect, test } from "@playwright/test";
import type { Browser, Locator } from "@playwright/test";

import {
  adminLogin,
  adminLoginPage,
  prepareWorld,
  uploadMedia,
} from "./support";

const ROWS = 3;
const COLS = 3;
const IMAGE_CELL = 4;

async function generateSolidPng(browser: Browser): Promise<Buffer> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("about:blank");
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    const canvasContext = canvas.getContext("2d");
    if (canvasContext === null) throw new Error("missing 2d context");
    canvasContext.fillStyle = "#ff0000";
    canvasContext.fillRect(0, 0, 16, 16);
    return canvas.toDataURL("image/png");
  });
  await context.close();
  const marker = "base64,";
  const index = dataUrl.indexOf(marker);
  if (index < 0) throw new Error("unexpected data URL");
  return Buffer.from(dataUrl.slice(index + marker.length), "base64");
}

async function cellCenterPixel(
  canvas: Locator,
  index: number,
): Promise<number[]> {
  return canvas.evaluate((element, options) => {
    const board = element as HTMLCanvasElement;
    const context = board.getContext("2d", { willReadFrequently: true });
    if (context === null) throw new Error("missing canvas context");
    const row = Math.floor(options.index / options.cols);
    const col = options.index % options.cols;
    const x = Math.floor((board.width * (col + 0.5)) / options.cols);
    const y = Math.floor((board.height * (row + 0.5)) / options.rows);
    const data = context.getImageData(x, y, 1, 1).data;
    return [data[0], data[1], data[2], data[3]];
  }, { rows: ROWS, cols: COLS, index });
}

test("棋盘图片首次加载失败后网络恢复时重试", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");

  await adminLogin(request, baseURL);
  const assetId = await uploadMedia(request, baseURL, {
    data: await generateSolidPng(browser),
    filename: "retry-red.png",
    mimeType: "image/png",
  });
  const cells: (string | null)[] = Array.from(
    { length: ROWS * COLS },
    () => null,
  );
  cells[IMAGE_CELL] = assetId;
  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "重试甲", phone: "13600000021" },
      { name: "重试乙", phone: "13600000022" },
    ],
    startsInSeconds: 3600,
    map: { rows: ROWS, cols: COLS, images: cells },
  });
  expect(world.rows).toBe(ROWS);
  expect(world.cols).toBe(COLS);

  const context = await browser.newContext();
  const page = await context.newPage();
  await adminLoginPage(page);

  let mediaRequests = 0;
  await page.route(`**/media/${assetId}`, async (route) => {
    mediaRequests += 1;
    if (mediaRequests === 1) {
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  await page.goto(`/admin/rooms/${world.roomId}`);
  const canvas = page.getByTestId("room-map-preview-canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  await expect(canvas).toHaveAttribute("data-images-ready", "true", {
    timeout: 30000,
  });
  expect(mediaRequests).toBe(1);
  expect(await cellCenterPixel(canvas, IMAGE_CELL)).toEqual([
    255, 255, 255, 255,
  ]);

  await page.evaluate(() => {
    window.dispatchEvent(new Event("online"));
  });
  await expect
    .poll(() => cellCenterPixel(canvas, IMAGE_CELL), { timeout: 15000 })
    .toEqual([255, 0, 0, 255]);
  expect(mediaRequests).toBeGreaterThanOrEqual(2);

  await context.close();
});
