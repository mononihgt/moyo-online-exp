import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  adminLoginPage,
  bookRoom,
  completeInstructionsPair,
  continueFromRestPair,
  enterRoom,
  expectBothBooked,
  expectTurnLabel,
  identityAnswers,
  listPayments,
  loginParticipant,
  markPaymentPaid,
  prepareWorld,
  startMatchingPair,
  submitQuestionnaire,
  submitRoundPair,
  waitBothEntered,
  waitForQuestionnaire,
  waitForRest,
} from "./support";
import type { IdentityAnswers, World } from "./support";

const COMPLETED_DETAIL =
  "双方已完成全部实验并提交后测问卷。你可以查看报酬信息，确认金额、支付状态和支付截止日期。";

const PRACTICE_A = 7;
const PRACTICE_B = 7;
const FORMAL_ONE_A = 8;
const FORMAL_ONE_B = 9;
const FORMAL_TWO_A = 6;
const FORMAL_TWO_B = 5;

function beijingDate(daysAgo: number): string {
  return new Date(Date.now() + 8 * 3600 * 1000 - daysAgo * 86400 * 1000)
    .toISOString()
    .slice(0, 10);
}

function clockSeconds(label: string | null): number {
  if (label === null) throw new Error("missing countdown label");
  const match = /(\d{2}):(\d{2})/.exec(label);
  if (match === null) throw new Error(`unexpected countdown label: ${label}`);
  return Number(match[1]) * 60 + Number(match[2]);
}

async function expectCountdown(page: Page, configured: number): Promise<void> {
  const countdown = page.getByTestId("game-countdown");
  await expect(countdown).toBeVisible();
  const label = await countdown.getAttribute("aria-label");
  const seconds = clockSeconds(label);
  expect(seconds).toBeLessThanOrEqual(configured + 1);
  expect(seconds).toBeGreaterThan(configured - 15);
}

async function expectBadge(page: Page, a: number, b: number): Promise<void> {
  const badge = page.getByTestId("trial-info-badge");
  await expect(badge).toBeVisible({ timeout: 20000 });
  await expect(badge).toHaveAttribute(
    "aria-label",
    `本局初始兵力与每格收益：玩家 A +${a}，玩家 B +${b}`,
  );
  await expect(badge).toHaveAttribute("role", "img");
  await expect(badge.locator("title")).toHaveCount(0);
  await expect(badge.getByText(/玩家/)).toHaveCount(0);

  const circle = badge.locator("circle");
  await expect(circle).toHaveCount(1);
  await expect(circle).toHaveAttribute("cx", "40");
  await expect(circle).toHaveAttribute("cy", "26");
  await expect(circle).toHaveAttribute("r", "21");
  await expect(circle).toHaveAttribute("fill", "none");
  await expect(circle).toHaveAttribute("stroke", "#000000");
  await expect(circle).toHaveAttribute("stroke-width", "1");

  const diamond = badge.locator("polygon");
  await expect(diamond).toHaveCount(1);
  await expect(diamond).toHaveAttribute("fill", "none");
  await expect(diamond).toHaveAttribute("stroke", "#000000");
  await expect(diamond).toHaveAttribute("stroke-width", "1");
  await expect(diamond).toHaveAttribute(
    "points",
    "40,55 61,76 40,97 19,76",
  );

  const numbers = badge.locator("text");
  await expect(numbers).toHaveCount(2);
  await expect(numbers.nth(0)).toHaveText(`+${a}`);
  await expect(numbers.nth(1)).toHaveText(`+${b}`);
  for (const text of [numbers.nth(0), numbers.nth(1)]) {
    await expect(text).toHaveAttribute("font-size", "20");
    await expect(text).toHaveAttribute("fill", "#000000");
    const fontFamily = await text.getAttribute("font-family");
    expect(fontFamily).toContain("Times New Roman");
    expect(fontFamily).toContain("serif");
  }
  const badgeText = await badge.evaluate((element) => element.textContent?.trim());
  expect(badgeText).toBe(`+${a}+${b}`);

  const badgeBox = await badge.boundingBox();
  const boardBox = await page.getByTestId("game-canvas").boundingBox();
  if (badgeBox === null || boardBox === null) {
    throw new Error("missing badge or board bounding box");
  }
  const horizontallyOutside =
    badgeBox.x + badgeBox.width <= boardBox.x || badgeBox.x >= boardBox.x + boardBox.width;
  const verticallyOutside =
    badgeBox.y + badgeBox.height <= boardBox.y || badgeBox.y >= boardBox.y + boardBox.height;
  expect(horizontallyOutside || verticallyOutside).toBe(true);
  expect(badgeBox.x).toBeGreaterThanOrEqual(boardBox.x + boardBox.width - 1);
  expect(badgeBox.y).toBeLessThanOrEqual(boardBox.y + 40);
}

async function expectBadgeHidden(page: Page): Promise<void> {
  await expect(page.getByTestId("trial-info-badge")).toHaveCount(0);
}

async function submitInvalidQuestionnaire(
  page: Page,
  baseURL: string,
  roomId: string,
  identity: IdentityAnswers,
): Promise<number> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "moyo_csrf");
  if (!csrf) throw new Error("missing moyo_csrf cookie");
  const response = await page.request.fetch(
    `${baseURL}/api/questionnaire/complete`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrf.value },
      data: {
        roomId,
        answers: {
          q1: "a",
          q2: "缺少真实姓名",
          alipay_phone: identity.alipay_phone,
          identity_document: {
            documentType: identity.documentType,
            number: identity.documentNumber,
          },
        },
        jatosWorkerId: "node-e2e-invalid-worker",
        jatosStudyResultId: "node-e2e-invalid-study",
        jatosComponentResultId: "node-e2e-invalid-component",
      },
    },
  );
  return response.status();
}

async function loadRoomSection(
  page: Page,
  baseURL: string,
  section: string,
): Promise<void> {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(`/admin/api/rooms?section=${section}`) &&
      response.ok(),
    { timeout: 20000 },
  );
  await page.goto(`${baseURL}/admin/rooms?section=${section}`);
  await responsePromise;
}

test("双方完成练习与正式对局、问卷身份、报酬及批量付款", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(300_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = [
    { name: "流程甲", phone: "13700000001" },
    { name: "流程乙", phone: "13700000002" },
  ];
  const practiceSeconds = 45;
  const formalSeconds = 60;
  const world: World = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 30,
    troopRows: [
      { soldiersA: PRACTICE_A, soldiersB: PRACTICE_B },
      { soldiersA: FORMAL_ONE_A, soldiersB: FORMAL_ONE_B },
      { soldiersA: FORMAL_TWO_A, soldiersB: FORMAL_TWO_B },
    ],
    map: {
      rows: 3,
      cols: 3,
      formalTrials: 2,
      practiceTurnCap: 2,
      practiceTurnSeconds: practiceSeconds,
      formalTurnCap: 2,
      formalTurnSeconds: formalSeconds,
      restSeconds: 2,
      randomizeFormal: false,
      basePayCents: 4500,
      performanceRateCents: 1,
      performanceCapCents: 2000,
      showupPayCents: 1000,
    },
    roomLabel: "浏览器完整流程房间",
    instructionMarkdownP1:
      "# 玩家 A 指导语\n\n这是玩家 A 的指导语，完成后点击继续。",
    instructionMarkdownP2:
      "# 玩家 B 指导语\n\n这是玩家 B 的指导语，完成后点击继续。",
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
  await expectBothBooked(pageOne, pageTwo);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);

  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);

  await startMatchingPair(pageOne, pageTwo);
  const instructions = await Promise.all(
    [pageOne, pageTwo].map(async (page) =>
      page.getByTestId("instruction-content").innerText(),
    ),
  );
  expect(
    instructions.filter((text) => text.includes("这是玩家 A 的指导语")),
  ).toHaveLength(1);
  expect(
    instructions.filter((text) => text.includes("这是玩家 B 的指导语")),
  ).toHaveLength(1);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);

  await completeInstructionsPair(pageOne, pageTwo);
  await expectTurnLabel(pageOne, pageTwo, "练习 1/2");
  await expect(pageOne.locator(".exp-hud-role")).toHaveText(
    /你是玩家 [○◇]/,
  );
  await expect(pageOne.getByTestId("hud-partner")).toHaveText(
    /^另一名玩家(在线|离线)$/,
  );
  await expect(pageOne.getByTestId("hud-partner")).not.toContainText(
    entries[1].name,
  );
  await expectBadge(pageOne, PRACTICE_A, PRACTICE_B);
  await expectBadge(pageTwo, PRACTICE_A, PRACTICE_B);
  await expectCountdown(pageOne, practiceSeconds);
  await expect(pageOne.getByTestId("confirm-selection")).toHaveText("确认选择");

  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);
  await expectTurnLabel(pageOne, pageTwo, "练习 2/2");
  await expectBadge(pageOne, PRACTICE_A, PRACTICE_B);
  await expectCountdown(pageOne, practiceSeconds);

  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);
  await waitForRest(pageOne, pageTwo);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);
  await expect(pageOne.getByTestId("rest-title")).toHaveText("练习结束");
  await expect(pageOne.getByTestId("rest-trial-chip")).toHaveText("练习局");
  await expect(pageOne.getByTestId("rest-summary")).toBeVisible();
  await expect(pageOne.getByTestId("rest-score-player1")).toHaveText(/^\d+$/);
  await expect(pageOne.getByTestId("rest-score-player2")).toHaveText(/^\d+$/);

  await continueFromRestPair(pageOne, pageTwo);
  await expectTurnLabel(pageOne, pageTwo, "正式 1/2 · 回合 1/2");
  await expectBadge(pageOne, FORMAL_ONE_A, FORMAL_ONE_B);
  await expectBadge(pageTwo, FORMAL_ONE_A, FORMAL_ONE_B);
  await expectCountdown(pageOne, formalSeconds);

  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);
  await expectTurnLabel(pageOne, pageTwo, "正式 1/2 · 回合 2/2");
  await expectBadge(pageOne, FORMAL_ONE_A, FORMAL_ONE_B);

  await pageOne.reload();
  await expect(pageOne.getByTestId("game-canvas")).toBeVisible({
    timeout: 30000,
  });
  await expect(pageOne.locator(".exp-hud-left")).toContainText(
    "正式 1/2 · 回合 2/2",
    { timeout: 30000 },
  );
  await expectBadge(pageOne, FORMAL_ONE_A, FORMAL_ONE_B);
  await expectCountdown(pageOne, formalSeconds);

  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);
  await waitForRest(pageOne, pageTwo);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);
  await expect(pageOne.getByTestId("rest-title")).toHaveCount(0);
  await expect(pageOne.getByTestId("rest-trial-chip")).toContainText("1/2");

  await continueFromRestPair(pageOne, pageTwo);
  await expectTurnLabel(pageOne, pageTwo, "正式 2/2 · 回合 1/2");
  await expectBadge(pageOne, FORMAL_TWO_A, FORMAL_TWO_B);
  await expectBadge(pageTwo, FORMAL_TWO_A, FORMAL_TWO_B);
  await expectCountdown(pageOne, formalSeconds);

  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);
  await expectTurnLabel(pageOne, pageTwo, "正式 2/2 · 回合 2/2");
  await expectBadge(pageOne, FORMAL_TWO_A, FORMAL_TWO_B);
  await submitRoundPair(pageOne, pageTwo, world.rows, world.cols);

  await waitForQuestionnaire(pageOne, pageTwo);
  await expectBadgeHidden(pageOne);
  await expectBadgeHidden(pageTwo);
  await expect(pageOne.getByTestId("questionnaire-button")).toBeVisible();
  await expect(pageTwo.getByTestId("questionnaire-button")).toBeVisible();
  await expect(pageOne.getByTestId("exit-experiment")).toHaveCount(0);

  const identityOne = identityAnswers("流程甲", { phone: "13900002221" });
  const identityTwo = identityAnswers("流程乙", { phone: "13900002222" });
  expect(
    await submitInvalidQuestionnaire(
      pageOne,
      baseURL,
      world.roomId,
      identityOne,
    ),
  ).toBe(400);

  await Promise.all([
    submitQuestionnaire(
      pageOne,
      baseURL,
      world.roomId,
      "participant-flow-a",
      identityOne,
    ),
    submitQuestionnaire(
      pageTwo,
      baseURL,
      world.roomId,
      "participant-flow-b",
      identityTwo,
    ),
  ]);

  for (const page of [pageOne, pageTwo]) {
    await expect(
      page.getByRole("heading", { name: "实验已完成", exact: true }),
    ).toBeVisible({ timeout: 30000 });
    await expect(page.getByText(COMPLETED_DETAIL, { exact: true })).toBeVisible();
    await expect(page.getByTestId("reward-info")).toBeVisible();
    await expect(page.getByTestId("rebook")).toHaveCount(0);
    await expectBadgeHidden(page);

    await page.goto(`/complete?room=${encodeURIComponent(world.roomId)}`);
    await expect(page.getByTestId("complete-total")).toHaveText("¥45.00", {
      timeout: 20000,
    });
    await expect(page.getByTestId("payment-status")).toContainText("待支付");
    await expect(
      page.getByText("正常完成", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("已完成", { exact: true }).first()).toBeVisible();
  }

  const payments = (await listPayments(request, baseURL)).filter((payment) =>
    entries.some((entry) => entry.name === payment.name),
  );
  expect(payments).toHaveLength(2);
  const paymentsByName = new Map(
    payments.map((payment) => [payment.name, payment]),
  );
  const paidPayment = paymentsByName.get(entries[0].name);
  const pendingPayment = paymentsByName.get(entries[1].name);
  if (paidPayment === undefined || pendingPayment === undefined) {
    throw new Error("missing payment for participant flow entries");
  }
  await markPaymentPaid(request, baseURL, paidPayment.id);

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminLoginPage(adminPage);
  const from = beijingDate(6);
  const to = beijingDate(0);
  await adminPage.goto(
    `${baseURL}/admin/payments/bulk?from=${from}&to=${to}`,
  );
  await expect(
    adminPage.getByRole("heading", { name: "批量付款", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await expect(adminPage.getByTestId("bulk-summary")).toBeVisible({
    timeout: 20000,
  });

  const paidRow = adminPage.getByTestId(
    `bulk-payment-row-${paidPayment.id}`,
  );
  const pendingRow = adminPage.getByTestId(
    `bulk-payment-row-${pendingPayment.id}`,
  );
  await expect(paidRow).toBeVisible();
  await expect(pendingRow).toBeVisible();
  await expect(paidRow).toContainText("已支付");
  await expect(pendingRow).toContainText("待支付");
  await expect(pendingRow.locator(".admin-total")).toHaveText("¥45.00");
  const paidCheckbox = adminPage.getByTestId(
    `bulk-payment-checkbox-${paidPayment.id}`,
  );
  const pendingCheckbox = adminPage.getByTestId(
    `bulk-payment-checkbox-${pendingPayment.id}`,
  );
  await expect(paidCheckbox).toBeDisabled();
  await expect(paidCheckbox).not.toBeChecked();
  await expect(pendingCheckbox).toBeChecked();
  await expect(paidRow.locator(".admin-bulk-phone")).toHaveText(
    entries[0].phone,
  );
  await expect(pendingRow.locator(".admin-bulk-phone")).toHaveText(
    entries[1].phone,
  );
  await expect(paidRow).toContainText(identityOne.real_name);
  await expect(pendingRow).toContainText(identityTwo.real_name);
  expect(
    await paidRow.locator(".admin-bulk-phone").innerText(),
  ).toHaveLength(11);
  await expect(adminPage.getByTestId("bulk-mark-paid")).toBeEnabled();
  await expect(adminPage.getByTestId("bulk-selected-total")).toHaveText(
    /^¥\d+\.\d{2}$/,
  );

  await adminPage.getByTestId("bulk-invert-selection").click();
  await expect(pendingCheckbox).not.toBeChecked();
  await adminPage.getByTestId("bulk-select-all").click();
  await expect(pendingCheckbox).toBeChecked();
  await adminPage.getByTestId("bulk-select-all").click();
  await expect(pendingCheckbox).not.toBeChecked();
  await expect(adminPage.getByTestId("bulk-mark-paid")).toBeDisabled();
  await expect(adminPage.getByTestId("bulk-selected-total")).toHaveText("¥0.00");

  await adminPage.getByTestId("bulk-select-all-button").click();
  await expect(pendingCheckbox).toBeChecked();
  await expect(adminPage.getByTestId("bulk-mark-paid")).toBeEnabled();

  await adminPage.getByTestId("bulk-mark-paid").click();
  const dialog = adminPage.getByRole("dialog", {
    name: "批量标记已支付",
  });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/合计 ¥\d+\.\d{2}/);
  await dialog.getByRole("button", { name: "标记已支付", exact: true }).click();
  await expect(
    adminPage.getByText(/已标记 \d+ 笔付款为已支付，跳过 0 笔已支付记录/),
  ).toBeVisible({ timeout: 20000 });
  await expect(paidRow).toContainText("已支付");
  await expect(pendingRow).toContainText("已支付");
  await expect(pendingCheckbox).toBeDisabled();
  await expect(adminPage.getByTestId("bulk-mark-paid")).toBeDisabled();

  await adminPage.reload();
  await expect(adminPage.getByTestId("bulk-summary")).toBeVisible({
    timeout: 20000,
  });
  await expect(
    adminPage.getByTestId(`bulk-payment-row-${pendingPayment.id}`),
  ).toContainText("已支付");
  await expect(
    adminPage.getByTestId(`bulk-payment-checkbox-${pendingPayment.id}`),
  ).toBeDisabled();

  await loadRoomSection(adminPage, baseURL, "archived");
  await expect(
    adminPage
      .locator("table")
      .getByRole("link", { name: world.roomLabel, exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await loadRoomSection(adminPage, baseURL, "unpaid");
  await expect(
    adminPage
      .locator("table")
      .getByRole("link", { name: world.roomLabel, exact: true }),
  ).toHaveCount(0);

  await contextOne.close();
  await contextTwo.close();
  await adminContext.close();
});
