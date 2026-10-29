import { expect, test } from "@playwright/test";

import {
  adminApi,
  adminLoginPage,
  createAdditionalRoom,
  prepareWorld,
} from "./support";

const TROOP_ROWS = [
  { soldiersA: 7, soldiersB: 7 },
  { soldiersA: 8, soldiersB: 9 },
  { soldiersA: 6, soldiersB: 5 },
];

const ROOM_SECTIONS = [
  "未开放预约",
  "开放预约",
  "进行中",
  "未完全支付",
  "已归档",
];

const DETAIL_TABS = ["概览", "预约", "监控", "数据", "付款"];

test("管理端页面、房间分区、地图组预览与问卷受保护字段", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(240_000);
  if (!baseURL) throw new Error("baseURL missing");

  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "烟测甲", phone: "13500000001" },
      { name: "烟测乙", phone: "13500000002" },
    ],
    startsInSeconds: 3600,
    troopRows: TROOP_ROWS,
    map: {
      rows: 3,
      cols: 3,
      formalTrials: 2,
      practiceTurnCap: 2,
      practiceTurnSeconds: 45,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
      restSeconds: 2,
      randomizeFormal: false,
    },
    roomLabel: "烟测开放房间",
    instructionMarkdownP1: "# 烟测玩家 A\n\n这是烟测玩家 A 的指导语。",
    instructionMarkdownP2: "# 烟测玩家 B\n\n这是烟测玩家 B 的指导语。",
  });
  const draft = await createAdditionalRoom(request, baseURL, world, {
    label: "烟测草稿房间",
    startsInSeconds: 7200,
    publish: false,
  });
  const closing = await createAdditionalRoom(request, baseURL, world, {
    label: "烟测关闭房间",
    startsInSeconds: 7200,
  });
  const late = await createAdditionalRoom(request, baseURL, world, {
    label: "烟测开始锁定房间",
    startsInSeconds: 3,
    waitWindowSeconds: 300,
  });

  const context = await browser.newContext();
  const page = await context.newPage();
  await adminLoginPage(page);
  await expect(page.locator("h1.admin-page-title")).toHaveText("仪表盘");

  await page.getByTestId("nav-troop-profiles").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("兵力方案");
  await expect(page.getByTestId("troop-profile-create")).toBeVisible();

  await page.getByTestId("nav-map-groups").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("地图组");
  await page.getByTestId(`map-group-version-${world.mapGroupVersionId}`).click();
  const previewRow = page.getByTestId("map-group-preview-row");
  await expect(previewRow).toHaveValue("1");
  await expect(previewRow.locator("option")).toHaveText([
    "练习",
    "正式 1",
    "正式 2",
  ]);
  const previewBadge = page.getByTestId("trial-info-badge");
  await expect(previewBadge).toBeVisible();
  await expect(previewBadge).toHaveAttribute(
    "aria-label",
    "本局初始兵力与每格收益：玩家 A +8，玩家 B +9",
  );
  await expect(page.locator(".admin-map-badge-caption")).toHaveText(
    "A +8 · B +9",
  );
  await previewRow.selectOption("0");
  await expect(previewBadge).toHaveAttribute(
    "aria-label",
    "本局初始兵力与每格收益：玩家 A +7，玩家 B +7",
  );
  await previewRow.selectOption("2");
  await expect(previewBadge).toHaveAttribute(
    "aria-label",
    "本局初始兵力与每格收益：玩家 A +6，玩家 B +5",
  );
  await expect(previewBadge.locator("circle")).toHaveAttribute("cx", "40");
  await expect(previewBadge.locator("polygon")).toHaveAttribute(
    "points",
    "40,55 61,76 40,97 19,76",
  );

  await page.getByTestId("nav-instructions").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("指导语");
  await expect(page.getByTestId("instruction-create")).toBeVisible();
  await expect(
    page.getByTestId(`instruction-version-${world.instructionP1Id}`),
  ).toBeVisible();
  await page.getByTestId(`instruction-version-${world.instructionP1Id}`).click();
  await expect(page.getByText("已发布版本只读").first()).toBeVisible();

  await page.getByTestId("nav-questionnaires").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("问卷");
  await page.getByTestId("questionnaire-create").click();
  const protectedStatus = page.getByTestId("questionnaire-protected-status");
  await expect(protectedStatus).toBeVisible();
  for (const label of ["真实姓名", "支付宝手机号", "身份证明"]) {
    await expect(protectedStatus).toContainText(`缺少受保护字段：${label}`);
  }
  const publish = page.getByTestId("questionnaire-publish");
  await expect(publish).toBeDisabled();
  await expect(publish).toHaveAttribute("title", /缺少受保护字段/);

  const firstType = page.getByTestId("questionnaire-question-type-0-0");
  await firstType.selectOption("real_name");
  const firstRequired = page.getByTestId("questionnaire-required-0-0");
  await expect(firstRequired).toBeChecked();
  await expect(firstRequired).toBeDisabled();
  for (const [indexText, type] of [
    ["1", "alipay_phone"],
    ["2", "identity_document"],
  ] as const) {
    await page.getByTestId("questionnaire-add-question-0").click();
    const typeSelect = page.getByTestId(
      `questionnaire-question-type-0-${indexText}`,
    );
    await expect(typeSelect).toBeVisible();
    await typeSelect.selectOption(type);
    const required = page.getByTestId(
      `questionnaire-required-0-${indexText}`,
    );
    await expect(required).toBeChecked();
    await expect(required).toBeDisabled();
  }
  await expect(page.getByText("受保护字段 3/3")).toBeVisible();
  await expect(protectedStatus).toHaveCount(0);
  await expect(publish).toBeEnabled();
  const duplicatePhone = firstType.locator('option[value="alipay_phone"]');
  await expect(duplicatePhone).toBeDisabled();
  await expect(duplicatePhone).toContainText("已使用");
  const duplicateDocument = firstType.locator(
    'option[value="identity_document"]',
  );
  await expect(duplicateDocument).toBeDisabled();
  await expect(duplicateDocument).toContainText("已使用");
  await expect(firstType.locator('option[value="real_name"]')).toBeEnabled();

  await page.getByTestId("nav-rooms").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("房间");
  const sectionFilter = page.getByTestId("room-section-filter");
  await expect(sectionFilter).toHaveValue("draft");
  const sectionTexts = (await sectionFilter.locator("option").allTextContents()).map(
    (text) => text.trim(),
  );
  expect(sectionTexts.map((text) => text.split("（")[0])).toEqual(ROOM_SECTIONS);
  for (const text of sectionTexts) {
    expect(text).toMatch(/（\d+）$/);
  }
  await expect(page.getByTestId("room-create")).toBeVisible();
  await expect(page.getByTestId("room-batch-create")).toBeVisible();
  const table = page.locator("table.admin-table");
  await expect(
    table.getByRole("link", { name: "烟测草稿房间", exact: true }),
  ).toBeVisible();
  await expect(
    table.getByRole("link", { name: "烟测开放房间", exact: true }),
  ).toHaveCount(0);

  await sectionFilter.selectOption("open");
  await expect(
    table.getByRole("link", { name: "烟测开放房间", exact: true }),
  ).toBeVisible();
  await expect(
    table.getByRole("link", { name: "烟测关闭房间", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("room-create")).toHaveCount(0);
  await expect(page.getByTestId("room-batch-create")).toHaveCount(0);
  const closingRow = page.locator("table.admin-table tr").filter({
    hasText: "烟测关闭房间",
  });
  const closeBooking = closingRow.getByTestId("room-close-booking");
  await expect(closeBooking).toBeEnabled();
  await closeBooking.click();
  const closeDialog = page.getByRole("dialog", { name: "关闭预约" });
  await expect(closeDialog).toBeVisible();
  await closeDialog
    .getByRole("button", { name: "关闭预约", exact: true })
    .click();
  await expect(
    page.getByText("Room 已关闭预约并回到草稿状态"),
  ).toBeVisible();
  await expect(
    table.getByRole("link", { name: "烟测关闭房间", exact: true }),
  ).toHaveCount(0);

  await sectionFilter.selectOption("draft");
  await expect(
    table.getByRole("link", { name: "烟测关闭房间", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("room-create")).toBeVisible();

  await table
    .getByRole("link", { name: "烟测草稿房间", exact: true })
    .click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("房间详情");
  await expect(page.locator("[data-testid^='room-tab-']")).toHaveText(
    DETAIL_TABS,
  );
  await page.getByTestId("room-edit").click();
  const draftStart = page.getByTestId("room-form-starts-at");
  await expect(draftStart).toBeEnabled();
  await expect(
    page.getByText("非草稿房间不可修改开始时间。", { exact: false }),
  ).toHaveCount(0);
  await page
    .locator("form")
    .getByRole("button", { name: "取消", exact: true })
    .click();

  await page.goto(`${baseURL}/admin/rooms?section=open`);
  await expect(
    table.getByRole("link", { name: "烟测开放房间", exact: true }),
  ).toBeVisible();
  await table
    .getByRole("link", { name: "烟测开放房间", exact: true })
    .click();
  await page.getByTestId("room-edit").click();
  const openStart = page.getByTestId("room-form-starts-at");
  await expect(openStart).toBeDisabled();
  await expect(
    page
      .getByText("非草稿房间不可修改开始时间。", { exact: false })
      .first(),
  ).toBeVisible();
  await expect(page.getByTestId("room-form-map-group")).toBeEnabled();
  await expect(page.getByTestId("room-edit-save")).toBeEnabled();
  await page
    .locator("form")
    .getByRole("button", { name: "取消", exact: true })
    .click();

  await expect
    .poll(
      async () => {
        const detail = await adminApi<{ room: { status: string } }>(
          request,
          baseURL,
          "GET",
          `/admin/api/rooms/${late.id}`,
        );
        return detail.room.status;
      },
      { timeout: 30_000, message: "late room should leave the open section" },
    )
    .not.toBe("open");
  await page.goto(`${baseURL}/admin/rooms?section=in_progress`);
  await expect(
    table.getByRole("link", { name: "烟测开始锁定房间", exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  await table
    .getByRole("link", { name: "烟测开始锁定房间", exact: true })
    .click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("房间详情");
  await expect(page.getByTestId("room-edit")).toHaveCount(0);
  await expect(page.getByTestId("room-form-starts-at")).toHaveCount(0);
  await expect(page.locator("[data-testid^='room-tab-']")).toHaveText(
    DETAIL_TABS,
  );

  await page.getByTestId("nav-payments").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("付款");
  await expect(page.getByTestId("payment-bulk-entry")).toBeVisible();
  await expect(page.getByTestId("payment-export-list")).toBeVisible();
  await expect(page.getByTestId("payment-export-reimbursement")).toBeVisible();
  await page.getByTestId("payment-bulk-entry").click();
  await expect(page.locator("h1.admin-page-title")).toHaveText("批量付款");
  expect(new URL(page.url()).pathname).toBe("/admin/payments/bulk");
  await expect(page.getByTestId("bulk-range-from")).toBeVisible();
  await expect(page.getByTestId("bulk-range-to")).toBeVisible();
  await expect(page.getByTestId("bulk-mark-paid")).toBeDisabled();

  await context.close();
});
