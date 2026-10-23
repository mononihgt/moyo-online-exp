import { expect, test } from "@playwright/test";

import {
  adminLogin,
  bookRoom,
  enterRoom,
  loginParticipant,
  prepareWorld,
  startMatchingPair,
  uploadMedia,
  waitBothEntered,
} from "./support";

const ANIMATED_GIF = Buffer.from(
  "R0lGODlhEAAQAIEAANweHgAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwAAAAAEAAQAAAIHQABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFgQEBACH5BAEKAAEALAAAAAAQABAAgR6gPAAAAAAAAAAAAAgdAAEIHEiwoMGDCBMqXMiwocOHECNKnEixosWBAQEAIfkEAQoAAQAsAAAAABAAEACBHjzcAAAAAAAAAAAACB0AAQgcSLCgwYMIEypcyLChw4cQI0qcSLGixYEBAQA7",
  "base64",
);

test("参与者在指导语中看到 GIF 动图", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  await adminLogin(request, baseURL);
  const assetId = await uploadMedia(
    request,
    baseURL,
    {
      data: ANIMATED_GIF,
      filename: "instruction.gif",
      mimeType: "image/gif",
    },
    "instruction-image",
  );
  const entries = [
    { name: "动图甲", phone: "13700000101" },
    { name: "动图乙", phone: "13700000102" },
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    roomLabel: "指导语 GIF 房间",
    instructionMarkdownP1: `# 玩家 A 指导语\n\n这是玩家 A 的指导语。\n\n![演示动图](asset://${assetId})`,
    instructionMarkdownP2: "# 玩家 B 指导语\n\n这是玩家 B 的指导语。",
  });

  const contextOne = await browser.newContext();
  const contextTwo = await browser.newContext();
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
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);

  const pagesWithGif = [];
  for (const page of [pageOne, pageTwo]) {
    const content = page.getByTestId("instruction-content");
    await expect(content).toBeVisible({ timeout: 30000 });
    const image = content.locator("img");
    if ((await image.count()) > 0) {
      pagesWithGif.push({ page, image });
    }
  }
  expect(pagesWithGif).toHaveLength(1);
  const { page, image } = pagesWithGif[0];
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute(
    "src",
    new RegExp(`/media/${assetId}$`),
  );
  const dimensions = await image.evaluate((element: HTMLImageElement) => ({
    complete: element.complete,
    width: element.naturalWidth,
    height: element.naturalHeight,
  }));
  expect(dimensions).toEqual({ complete: true, width: 16, height: 16 });

  const renderedFrames = new Set<string>();
  for (let index = 0; index < 6; index += 1) {
    renderedFrames.add((await image.screenshot()).toString("base64"));
    await page.waitForTimeout(50);
  }
  expect(renderedFrames.size).toBeGreaterThan(1);

  const download = await page.request.get(`${baseURL}/media/${assetId}`);
  expect(download.status()).toBe(200);
  expect(download.headers()["content-type"]).toContain("image/gif");
  expect(Buffer.from(await download.body())).toEqual(ANIMATED_GIF);

  await contextOne.close();
  await contextTwo.close();
});
