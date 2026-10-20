import { expect, test } from "@playwright/test";

import { adminApi, adminLoginPage, prepareWorld } from "./support";

interface SavedMapGroup {
  id: string;
  rows: number;
  cols: number;
  spawns: { A: number; B: number };
  maps: {
    slot: string;
    cells: (string | null)[];
    colors: (string | null)[];
  }[];
}

const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test("调整尺寸后出生格与选中格按行列重映射并持久化", async ({
  page,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "映射甲", phone: "13100000001" },
      { name: "映射乙", phone: "13100000002" },
    ],
    startsInSeconds: 3600,
    map: {
      rows: 10,
      cols: 10,
      description: "索引映射",
      factorLevel: "标准",
      spawns: { A: 0, B: 99 },
    },
  });

  await adminLoginPage(page);
  await page.goto("/admin/map-groups");
  await expect(
    page.getByRole("heading", { name: "地图组", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await page.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  await page.getByTestId("map-group-new-version").click();
  await expect(page.getByTestId("map-group-save")).toBeVisible();

  await page.getByTestId("map-group-cell-23").click();
  await page.getByTestId("map-group-spawn-a").click();
  await expect(page.getByText("出生格 A · 23", { exact: true })).toBeVisible();
  await page.getByTestId("map-group-cell-57").click();
  await page.getByTestId("map-group-spawn-b").click();
  await expect(page.getByText("出生格 B · 57", { exact: true })).toBeVisible();
  await page.getByTestId("map-group-cell-35").click();
  await expect(page.getByText("选中格 35", { exact: true })).toBeVisible();

  // 10×10 → 10×8：23 → 19，57 → 47，选中 35 → 29
  await page.getByTestId("map-group-cols").fill("8");
  await expect(page.getByTestId("map-group-cell-79")).toBeVisible();
  await expect(page.getByTestId("map-group-cell-80")).toHaveCount(0);
  await expect(page.getByText("出生格 A · 19", { exact: true })).toBeVisible();
  await expect(page.getByText("出生格 B · 47", { exact: true })).toBeVisible();
  await expect(page.getByText("选中格 29", { exact: true })).toBeVisible();
  await expect(page.getByTestId("map-group-cell-29")).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // 10×8 → 4×8：19 保持第 2 行，47 越界回退到 31，选中 29 保持
  await page.getByTestId("map-group-rows").fill("4");
  await expect(page.getByTestId("map-group-cell-31")).toBeVisible();
  await expect(page.getByTestId("map-group-cell-32")).toHaveCount(0);
  await expect(page.getByText("出生格 A · 19", { exact: true })).toBeVisible();
  await expect(page.getByText("出生格 B · 31", { exact: true })).toBeVisible();
  await expect(page.getByText("选中格 29", { exact: true })).toBeVisible();

  const createdResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/admin/api/map-groups") &&
      response.request().method() === "POST",
  );
  await page.getByTestId("map-group-save").click();
  const response = await createdResponse;
  expect(response.ok()).toBeTruthy();
  const created = (await response.json()) as { mapGroup: { id: string } };
  await expect(page.getByText(/地图组草稿已创建/)).toBeVisible();

  const saved = await adminApi<{ mapGroup: SavedMapGroup }>(
    request,
    baseURL,
    "GET",
    `/admin/api/map-groups/${created.mapGroup.id}`,
  );
  expect(saved.mapGroup.rows).toBe(4);
  expect(saved.mapGroup.cols).toBe(8);
  expect(saved.mapGroup.spawns).toEqual({ A: 19, B: 31 });
});

test("批量选择格子设置颜色、上传图片并恢复白色", async ({
  page,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "批量甲", phone: "13100000005" },
      { name: "批量乙", phone: "13100000006" },
    ],
    startsInSeconds: 3600,
    map: {
      rows: 3,
      cols: 3,
      description: "批量编辑",
      factorLevel: "标准",
    },
  });

  await adminLoginPage(page);
  await page.goto("/admin/map-groups");
  await expect(
    page.getByRole("heading", { name: "地图组", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await page.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  await page.getByTestId("map-group-new-version").click();
  await expect(page.getByTestId("map-group-save")).toBeVisible();

  await page.getByTestId("map-group-cell-0").click();
  await page.getByTestId("map-group-cell-2").click({ modifiers: ["Shift"] });
  await expect(page.getByText("已选 3 格", { exact: true })).toBeVisible();

  await page.getByTestId("map-group-color-input").evaluate((element) => {
    const input = element as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(input, "#123456");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.getByTestId("map-group-apply-color").click();
  await expect(
    page.getByText("已设置 3 个格子的背景颜色", { exact: true }),
  ).toBeVisible();

  let mediaUploads = 0;
  page.on("request", (requestEvent) => {
    if (
      requestEvent.method() === "POST" &&
      requestEvent.url().endsWith("/admin/api/media")
    ) {
      mediaUploads += 1;
    }
  });
  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByTestId("map-group-upload-cell").click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "batch-cell.png",
    mimeType: "image/png",
    buffer: PNG_1X1,
  });
  await expect(
    page.getByText("已上传图片到 3 个格子", { exact: true }),
  ).toBeVisible({ timeout: 20000 });
  expect(mediaUploads).toBe(1);

  const createdResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/admin/api/map-groups") &&
      response.request().method() === "POST",
  );
  await page.getByTestId("map-group-save").click();
  const created = (await (await createdResponse).json()) as {
    mapGroup: { id: string };
  };
  await expect(page.getByText(/地图组草稿已创建/)).toBeVisible();

  const first = await adminApi<{ mapGroup: SavedMapGroup }>(
    request,
    baseURL,
    "GET",
    `/admin/api/map-groups/${created.mapGroup.id}`,
  );
  const firstMap = first.mapGroup.maps.find((map) => map.slot === "Both");
  expect(firstMap?.colors?.slice(0, 3)).toEqual([
    "#123456",
    "#123456",
    "#123456",
  ]);
  expect(firstMap?.cells?.[0]).toBeTruthy();
  expect(firstMap?.cells?.[1]).toBe(firstMap?.cells?.[0]);
  expect(firstMap?.cells?.[2]).toBe(firstMap?.cells?.[0]);

  await page.getByTestId("map-group-cell-0").click();
  await page.getByTestId("map-group-cell-2").click({ modifiers: ["Shift"] });
  await page.getByTestId("map-group-clear-cell").click();
  const clearedResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/admin/api/map-groups/${created.mapGroup.id}`) &&
      response.request().method() === "PATCH",
  );
  await page.getByTestId("map-group-save").click();
  await clearedResponse;
  await expect(page.getByText("地图组草稿已保存", { exact: true })).toBeVisible();

  const cleared = await adminApi<{ mapGroup: SavedMapGroup }>(
    request,
    baseURL,
    "GET",
    `/admin/api/map-groups/${created.mapGroup.id}`,
  );
  const clearedMap = cleared.mapGroup.maps.find((map) => map.slot === "Both");
  expect(clearedMap?.cells?.slice(0, 3)).toEqual([null, null, null]);
  expect(clearedMap?.colors?.slice(0, 3)).toEqual([
    "#123456",
    "#123456",
    "#123456",
  ]);

  await page.getByTestId("map-group-cell-0").click();
  await page.getByTestId("map-group-cell-2").click({ modifiers: ["Shift"] });
  await page.getByTestId("map-group-restore-white").click();
  const restoredResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/admin/api/map-groups/${created.mapGroup.id}`) &&
      response.request().method() === "PATCH",
  );
  await page.getByTestId("map-group-save").click();
  await restoredResponse;
  await expect(page.getByText("地图组草稿已保存", { exact: true })).toBeVisible();

  const restored = await adminApi<{ mapGroup: SavedMapGroup }>(
    request,
    baseURL,
    "GET",
    `/admin/api/map-groups/${created.mapGroup.id}`,
  );
  const restoredMap = restored.mapGroup.maps.find((map) => map.slot === "Both");
  expect(restoredMap?.colors?.slice(0, 3)).toEqual([null, null, null]);
  expect(restoredMap?.cells?.slice(0, 3)).toEqual([null, null, null]);
});

test("上传进行中切换版本会丢弃过期上传结果", async ({
  page,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "上传甲", phone: "13100000003" },
      { name: "上传乙", phone: "13100000004" },
    ],
    startsInSeconds: 3600,
    map: {
      rows: 3,
      cols: 3,
      description: "上传竞态",
      factorLevel: "标准",
    },
  });

  await adminLoginPage(page);
  await page.goto("/admin/map-groups");
  await expect(
    page.getByRole("heading", { name: "地图组", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await page.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  await page.getByTestId("map-group-new-version").click();
  await expect(page.getByTestId("map-group-save")).toBeVisible();

  const uploadControl = {
    release: () => {},
    started: () => {},
  };
  const uploadGate = new Promise<void>((resolve) => {
    uploadControl.release = () => resolve();
  });
  const uploadStarted = new Promise<void>((resolve) => {
    uploadControl.started = () => resolve();
  });
  await page.route("**/admin/api/media", async (route) => {
    if (route.request().method() === "POST") {
      uploadControl.started();
      await uploadGate;
    }
    await route.continue();
  });

  await page.getByTestId("map-group-cell-4").click();
  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByTestId("map-group-upload-cell").click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "cell.png",
    mimeType: "image/png",
    buffer: PNG_1X1,
  });
  await uploadStarted;

  // 上传未完成时切回已发布版本并重新创建草稿，使旧编辑会话失效
  await page.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  await page.getByTestId("map-group-new-version").click();

  uploadControl.release();
  await expect(
    page.getByText("已切换版本，过期上传已丢弃", { exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("格子图片已上传", { exact: true })).toHaveCount(0);

  await page.getByTestId("map-group-cell-4").click();
  await expect(
    page.getByText("未上传图片（白色）", { exact: true }),
  ).toBeVisible();

  const createdResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/admin/api/map-groups") &&
      response.request().method() === "POST",
  );
  await page.getByTestId("map-group-save").click();
  const response = await createdResponse;
  expect(response.ok()).toBeTruthy();
  const created = (await response.json()) as { mapGroup: { id: string } };

  const saved = await adminApi<{ mapGroup: SavedMapGroup }>(
    request,
    baseURL,
    "GET",
    `/admin/api/map-groups/${created.mapGroup.id}`,
  );
  const both = saved.mapGroup.maps.find((map) => map.slot === "Both");
  expect(both?.cells).toEqual(Array.from({ length: 9 }, () => null));
});
