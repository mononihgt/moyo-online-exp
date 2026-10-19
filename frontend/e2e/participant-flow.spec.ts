import { expect, test } from "@playwright/test";

import {
  NO_REWARD,
  adminApi,
  adminLoginPage,
  archiveReasonOptions,
  bookRoom,
  cancelExperimentExit,
  cancelWaitingExit,
  completeInstructionsPair,
  confirmExperimentExit,
  confirmWaitingExit,
  enterRoom,
  expectArchiveView,
  expectBothBooked,
  expectNoRewardComplete,
  loginParticipant,
  openAdminRoom,
  prepareConsentBase,
  prepareWorld,
  publishConsentVersion,
  startMatchingPair,
  submitCellPair,
  submitQuestionnaire,
  waitBothEntered,
  waitForQuestionnaire,
  waitForRest,
} from "./support";
import type { RosterEntry } from "./support";

const WAIT_PARTNER_NOT_ENTERED_DETAIL =
  "另一名参与者尚未进入实验。本次实验需要两名参与者。等待时间结束后若仍未到齐，本次实验将结束，本次实验未完成，不产生报酬。你可以继续等待，或点击下方“退出本次实验”返回首页并重新预约其他时间。实验开始后无法取消预约。";
const WAIT_EXIT_PARTNER_BUTTON =
  "另一名被试可能放鸽子了，我退出本次实验";
const WAIT_BOTH_ENTERED_DETAIL =
  "双方均已到场后不能退出；如果等待时间结束时仍未开始，本次实验将自动结束，不产生报酬。";

const ABANDONED_SELF_TITLE = "你已退出实验";
const ABANDONED_SELF_DETAIL =
  "你已主动退出本次实验，本次实验未完成，无实验报酬。你可以重新预约。";
const ABANDONED_PARTNER_TITLE = "实验已中止";
const ABANDONED_PARTNER_DETAIL =
  "另一名参与者已主动退出，实验被迫中止，无法计算报酬。你可以重新预约其他时间段参与实验";
const ABANDONED_REASON_LABEL = "参与者主动退出";

const ADMIN_CANCELLED_DETAIL =
  "本次实验在开始前已取消，实验未完成，不产生报酬。你可以重新预约其他时间段参与实验。";

const QUESTIONNAIRE_INCOMPLETE_TITLE = "待补交后测问卷";
const QUESTIONNAIRE_INCOMPLETE_ARCHIVE_DETAIL =
  "房间已归档，你的后测问卷尚未提交。本次实验未完成，不产生报酬。完成问卷前，你无法预约新的实验。继续填写问卷是获得报酬的唯一方式。";
const PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL =
  "本次实验已归档。你已完成本次正式实验，但后测问卷尚未提交。本次实验未完成，不产生报酬；继续填写问卷是获得报酬的唯一方式。完成问卷前，你无法预约新的实验。";
const COMPLETE_PENDING_ARCHIVED_DETAIL =
  "你已完成本次正式实验，但后测问卷尚未提交，本次实验未完成，不产生报酬。房间已归档，你仍可以继续填写并提交问卷；提交后将按完成实验结算基础费与绩效费。完成问卷前，你无法预约新的实验。";
const COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE =
  "房间归档原因：问卷未完成。房间归档后仍可继续填写并提交问卷。";
const COMPLETE_ARCHIVED_SUBMITTED_NOTE =
  "你已提交后测问卷，归档不影响你的完成状态与报酬。";
const HISTORY_ARCHIVED_SUBMITTED_NOTE = "归档不影响你的完成状态与报酬。";
const HISTORY_QUESTIONNAIRE_LOCK_NOTE = "完成问卷前，你无法预约新的实验。";
const ACCOUNT_PENDING_QUESTIONNAIRE =
  "你已完成正式实验但尚未提交后测问卷。完成问卷后才能结束本次实验；不能预约新的场次。";
const ACCOUNT_COMPLETED = "你已完成全部实验，无法再预约新的场次。";
const COMPLETE_TRANSFER_NOTE =
  "报酬将在提交后测问卷后的第一个周日 24:00 前通过支付宝完成转账。如逾期未收到，请通过“联系主试”与实验组织者核对。";

const COMPLETED_TITLE = "实验已完成";
const COMPLETED_DETAIL =
  "双方已完成全部实验并提交后测问卷。你可以查看报酬信息，确认金额、支付状态和支付截止日期。";
const COMPLETED_REASON_LABEL = "正常完成";

const CONTACT_SCENARIOS = [
  "另一名参与者缺席、断线后无法重新连接，或实验被意外中止。",
  "你主动退出后发现状态或报酬记录不正确。",
  "后测问卷无法打开、提交失败，或提交后仍显示待填写。",
  "到场费、报酬金额、支付状态或支付截止日期与预期不符。",
  "无法登录、预约、取消预约，或无法重新预约。",
];
const CONTACT_DEADLINE_NOTE =
  "技术中止的到场费支付截止日期为中止后的第一个周日 24:00（北京时间）；如逾期未收到，请通过以上方式联系实验主试。";

function roster(names: string[], prefix: string): RosterEntry[] {
  return names.map((name, index) => ({
    name,
    phone: `${prefix}${String(index + 1).padStart(4, "0")}`,
  }));
}

test("登录校验、拒绝知情同意与版本更新", async ({ browser, request, baseURL }) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["流程登录"], "1340000");
  await prepareConsentBase(request, baseURL, entries);

  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByTestId("login-submit").click();
  await expect(
    page.getByText("请填写姓名和手机号。", { exact: true }),
  ).toBeVisible();

  await page.getByTestId("login-name").fill(entries[0].name);
  await page.getByTestId("login-phone").fill("13499999999");
  await page.getByTestId("login-submit").click();
  await expect(
    page.getByText("姓名或手机号不正确", { exact: true }),
  ).toBeVisible();

  await page.getByTestId("login-phone").fill(entries[0].phone);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("consent-agree")).toBeVisible({
    timeout: 20000,
  });

  await page.getByTestId("consent-decline").click();
  await expect(page).toHaveURL((url) => url.pathname === "/login");
  await expect(
    page.getByText("你已拒绝知情同意并退出登录。", { exact: true }),
  ).toBeVisible();

  await page.getByTestId("login-name").fill(entries[0].name);
  await page.getByTestId("login-phone").fill(entries[0].phone);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("consent-agree")).toBeVisible({
    timeout: 20000,
  });

  await publishConsentVersion(
    request,
    baseURL,
    "# 更新后的知情同意\n\n刷新后同意书。",
  );
  await page.getByTestId("consent-agree").click();
  await expect(
    page.getByText("知情同意书版本已更新，请刷新页面", { exact: true }),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByText("刷新后同意书。", { exact: true })).toBeVisible({
    timeout: 20000,
  });
  await page.getByTestId("consent-agree").click();
  await expect(page).toHaveURL((url) => url.pathname === "/", {
    timeout: 20000,
  });
  await expect(page.getByTestId("current-booking")).toContainText(
    "你当前没有预约",
  );
  await expect(page.getByTestId("room-option")).toHaveCount(0);

  await page.goto("/contact");
  await expect(
    page.getByRole("heading", { name: "联系实验主试", exact: true }),
  ).toBeVisible({ timeout: 20000 });
  for (const scenario of CONTACT_SCENARIOS) {
    await expect(page.getByText(scenario, { exact: true })).toBeVisible();
  }
  await expect(
    page.getByText(CONTACT_DEADLINE_NOTE, { exact: true }),
  ).toBeVisible();

  await context.close();
});

test("开始前管理端只能选择主试取消，取消记录进入历史", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["流程取消"], "1341000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 120,
  });

  const participantContext = await browser.newContext();
  const page = await participantContext.newPage();
  await loginParticipant(page, entries[0].name, entries[0].phone);
  await bookRoom(page, world.roomId);
  await expect(page.getByTestId("current-booking")).toContainText("1/2");

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminLoginPage(adminPage);
  await openAdminRoom(adminPage, world.roomId);
  expect(await archiveReasonOptions(adminPage)).toEqual(["主试取消"]);
  await expect(
    adminPage.locator("#archive-reason option", { hasText: "技术中断" }),
  ).toHaveCount(0);

  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/rooms/${world.roomId}/archive`,
    { reason: "admin_cancelled" },
  );

  await page.reload();
  await expect(page.getByTestId("current-booking")).toContainText(
    "你当前没有预约",
  );
  await expect(
    page.locator(
      `[data-testid="room-option"][data-room-id="${world.roomId}"]`,
    ),
  ).toHaveCount(0);

  await page.goto("/history");
  const history = page.getByTestId("history-list");
  await expect(history).toContainText("已取消", { timeout: 20000 });
  await expect(history).toContainText("主试取消");
  await expect(history).toContainText(NO_REWARD);
  await expect(page.getByTestId("reward-info")).toBeVisible();
  await expect(page.getByTestId("rebook")).toBeVisible();

  await expectNoRewardComplete(
    page,
    world.roomId,
    ADMIN_CANCELLED_DETAIL,
    { rebook: true, archiveReason: "主试取消" },
  );

  await participantContext.close();
  await adminContext.close();
});

test("等待阶段搭档未进入时退出并返回首页", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["等待甲", "等待乙"], "1342000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
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

  await enterRoom(pageOne);
  await expect(pageOne.getByTestId("hud-partner")).toContainText(
    "等待另一名参与者进入",
  );
  await expect(pageOne.getByTestId("start-matching")).toBeDisabled();
  await expect(pageOne.getByTestId("waiting-exit")).toHaveText(
    WAIT_EXIT_PARTNER_BUTTON,
  );
  await expect(
    pageOne.getByText(WAIT_PARTNER_NOT_ENTERED_DETAIL, { exact: true }),
  ).toBeVisible();

  await cancelWaitingExit(pageOne);
  await expect(pageOne.getByTestId("start-matching")).toBeDisabled();
  await confirmWaitingExit(pageOne);

  await pageOne.goto(`/room/${world.roomId}`);
  await expectArchiveView(
    pageOne,
    ABANDONED_SELF_TITLE,
    ABANDONED_SELF_DETAIL,
    { rebook: true, continueQuestionnaire: false },
  );
  await expectNoRewardComplete(
    pageOne,
    world.roomId,
    ABANDONED_SELF_DETAIL,
    { rebook: true, archiveReason: ABANDONED_REASON_LABEL },
  );
  await pageOne.goto("/history");
  const selfHistory = pageOne.getByTestId("history-list");
  await expect(selfHistory).toContainText("已退出", { timeout: 20000 });
  await expect(selfHistory).toContainText(ABANDONED_REASON_LABEL);
  await expect(selfHistory).toContainText(NO_REWARD);
  await expect(selfHistory.getByTestId("rebook")).toBeVisible();
  await expect(selfHistory.getByTestId("reward-info")).toBeVisible();
  await expect(selfHistory.getByTestId("payment-status")).toHaveCount(0);

  await pageTwo.reload();
  await expect(pageTwo.getByTestId("current-booking")).toContainText(
    "你当前没有预约",
  );
  await expect(
    pageTwo.locator(
      `[data-testid="room-option"][data-room-id="${world.roomId}"]`,
    ),
  ).toHaveCount(0);
  await pageTwo.goto("/history");
  const partnerHistory = pageTwo.getByTestId("history-list");
  await expect(partnerHistory).toContainText("未到场", {
    timeout: 20000,
  });
  await expect(partnerHistory).toContainText(ABANDONED_REASON_LABEL);
  await expect(partnerHistory).toContainText(NO_REWARD);
  await expect(partnerHistory.getByTestId("rebook")).toBeVisible();
  await expect(partnerHistory.getByTestId("payment-status")).toHaveCount(0);
  await expectNoRewardComplete(
    pageTwo,
    world.roomId,
    ABANDONED_PARTNER_DETAIL,
    { rebook: true, archiveReason: ABANDONED_REASON_LABEL },
  );

  await contextOne.close();
  await contextTwo.close();
});

test("指导语阶段退出并让搭档看到中止归档页", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["指导甲", "指导乙"], "1343000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
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
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await expect(
    pageOne.getByText(WAIT_BOTH_ENTERED_DETAIL, { exact: true }),
  ).toBeVisible();
  await expect(pageOne.getByTestId("waiting-exit")).toHaveCount(0);
  await expect(pageTwo.getByTestId("waiting-exit")).toHaveCount(0);
  await startMatchingPair(pageOne, pageTwo);

  await expect(pageOne.getByTestId("exit-experiment")).toBeVisible();
  await expect(pageTwo.getByTestId("exit-experiment")).toBeVisible();

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminLoginPage(adminPage);
  await openAdminRoom(adminPage, world.roomId);
  expect(await archiveReasonOptions(adminPage)).toEqual(["主试中止"]);

  await cancelExperimentExit(pageOne);
  await expect(pageOne.getByTestId("instruction-content")).toBeVisible();

  await confirmExperimentExit(pageOne);
  await expectArchiveView(
    pageTwo,
    ABANDONED_PARTNER_TITLE,
    ABANDONED_PARTNER_DETAIL,
    { rebook: true, continueQuestionnaire: false },
  );
  await expect(pageTwo.getByTestId("game-canvas")).toHaveCount(0);
  await expectNoRewardComplete(
    pageTwo,
    world.roomId,
    ABANDONED_PARTNER_DETAIL,
    { rebook: true, archiveReason: ABANDONED_REASON_LABEL },
  );

  await pageOne.goto("/history");
  const ownHistory = pageOne.getByTestId("history-list");
  await expect(ownHistory).toContainText("已退出", { timeout: 20000 });
  await expect(ownHistory).toContainText(ABANDONED_REASON_LABEL);
  await expect(ownHistory.getByTestId("rebook")).toBeVisible();

  await pageTwo.goto("/history");
  const partnerHistory = pageTwo.getByTestId("history-list");
  await expect(partnerHistory).toContainText("已中止", { timeout: 20000 });
  await expect(partnerHistory).toContainText(ABANDONED_REASON_LABEL);
  await expect(partnerHistory.getByTestId("rebook")).toBeVisible();

  await contextOne.close();
  await contextTwo.close();
  await adminContext.close();
});

test("回合阶段退出并让搭档看到中止归档页", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["回合甲", "回合乙"], "1344000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition: { formalTrials: 1, turnCount: 1 },
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
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);
  await completeInstructionsPair(pageOne, pageTwo);

  await expect(pageOne.getByTestId("game-canvas")).toBeVisible();
  await expect(pageOne.getByTestId("exit-experiment")).toBeVisible();
  await expect(pageOne.getByTestId("confirm-selection")).toBeVisible();

  await confirmExperimentExit(pageOne);
  await expectArchiveView(
    pageTwo,
    ABANDONED_PARTNER_TITLE,
    ABANDONED_PARTNER_DETAIL,
    { rebook: true, continueQuestionnaire: false },
  );
  await expect(pageTwo.getByTestId("game-canvas")).toHaveCount(0);

  await contextOne.close();
  await contextTwo.close();
});

test("休息阶段退出并让搭档看到中止归档页", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["休息甲", "休息乙"], "1345000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition: {
      practiceTrials: 1,
      formalTrials: 2,
      turnCount: 1,
      restSeconds: 60,
      turnSeconds: 60,
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
  await Promise.all([
    bookRoom(pageOne, world.roomId),
    bookRoom(pageTwo, world.roomId),
  ]);
  await expectBothBooked(pageOne, pageTwo);
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);
  await completeInstructionsPair(pageOne, pageTwo);
  await submitCellPair(pageOne, pageTwo);
  await waitForRest(pageOne, pageTwo);

  await expect(pageOne.getByTestId("rest-title")).toHaveText("练习结束");
  await expect(pageOne.getByTestId("rest-view")).toContainText("对局间休息");
  await expect(pageOne.getByTestId("rest-summary")).toBeVisible();
  await expect(pageOne.getByTestId("rest-trial-chip")).toHaveText("练习局");
  await expect(pageOne.getByTestId("rest-score-player2")).toHaveText(/^\d+$/);
  await expect(pageOne.getByTestId("rest-score-player1")).toHaveText(/^\d+$/);
  await expect(pageOne.getByTestId("rest-ready")).toHaveText(
    "我休息好了，可以继续",
  );
  await expect(pageOne.getByTestId("exit-experiment")).toBeVisible();

  await Promise.all([
    pageOne.getByTestId("rest-ready").click(),
    pageTwo.getByTestId("rest-ready").click(),
  ]);
  await expect(pageOne.locator(".exp-hud-left")).toContainText("正式 1/2");
  await submitCellPair(pageOne, pageTwo);
  await waitForRest(pageOne, pageTwo);
  await expect(pageOne.getByTestId("rest-title")).toHaveCount(0);
  await expect(pageOne.getByTestId("rest-trial-chip")).toHaveText(
    /对局\s*1\/2/,
  );
  await expect(pageOne.getByTestId("rest-score-player2")).toHaveText(/^\d+$/);
  await expect(pageOne.getByTestId("rest-score-player1")).toHaveText(/^\d+$/);
  await expect(pageOne.getByTestId("rest-ready")).toHaveText(
    "我休息好了，可以继续",
  );

  await confirmExperimentExit(pageOne);
  await expectArchiveView(
    pageTwo,
    ABANDONED_PARTNER_TITLE,
    ABANDONED_PARTNER_DETAIL,
    { rebook: true, continueQuestionnaire: false },
  );
  await expect(pageTwo.getByTestId("rest-view")).toHaveCount(0);

  await contextOne.close();
  await contextTwo.close();
});

test("问卷阶段归档后按人显示状态并允许补交", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(240_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["问卷甲", "问卷乙"], "1346000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition: {
      formalTrials: 1,
      turnCount: 1,
      restSeconds: 1,
      turnSeconds: 60,
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
  await Promise.all([
    bookRoom(pageOne, world.roomId),
    bookRoom(pageTwo, world.roomId),
  ]);
  await expectBothBooked(pageOne, pageTwo);
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);
  await completeInstructionsPair(pageOne, pageTwo);
  await submitCellPair(pageOne, pageTwo);
  await waitForQuestionnaire(pageOne, pageTwo);

  await expect(
    pageOne.getByText("全部对局已完成", { exact: true }),
  ).toBeVisible();
  await expect(
    pageOne.getByText(
      "请完成实验后测问卷。完成实验并提交问卷后，才会计算实验报酬",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    pageOne.getByText("问卷状态：未成功提交问卷", { exact: true }),
  ).toBeVisible();
  await expect(pageOne.getByTestId("exit-experiment")).toHaveCount(0);
  await expect(pageTwo.getByTestId("exit-experiment")).toHaveCount(0);
  await expect(pageOne.getByTestId("questionnaire-button")).toBeVisible();
  await expect(pageTwo.getByTestId("questionnaire-button")).toBeVisible();
  await expect(pageOne.getByTestId("reward-info")).toBeVisible();
  await expect(pageTwo.getByTestId("reward-info")).toBeVisible();

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminLoginPage(adminPage);
  await openAdminRoom(adminPage, world.roomId);
  expect(await archiveReasonOptions(adminPage)).toEqual(["问卷未完成"]);
  await expect(
    adminPage.locator("#archive-reason option", { hasText: "技术中断" }),
  ).toHaveCount(0);

  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/rooms/${world.roomId}/archive`,
    { reason: "questionnaire_incomplete" },
  );

  await Promise.all([
    expectArchiveView(
      pageOne,
      QUESTIONNAIRE_INCOMPLETE_TITLE,
      QUESTIONNAIRE_INCOMPLETE_ARCHIVE_DETAIL,
      { rebook: false, continueQuestionnaire: true },
    ),
    expectArchiveView(
      pageTwo,
      QUESTIONNAIRE_INCOMPLETE_TITLE,
      QUESTIONNAIRE_INCOMPLETE_ARCHIVE_DETAIL,
      { rebook: false, continueQuestionnaire: true },
    ),
  ]);

  await pageOne.goto("/");
  await expect(pageOne.getByTestId("pending-questionnaire-card")).toContainText(
    "已归档",
  );
  await expect(
    pageOne.getByText(PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL, { exact: true }),
  ).toBeVisible();
  await expect(
    pageOne.getByText(ACCOUNT_PENDING_QUESTIONNAIRE, { exact: true }),
  ).toBeVisible();
  await expect(pageOne.getByTestId("bookable-hidden")).toBeVisible();
  await expect(pageOne.getByTestId("current-booking")).toHaveCount(0);
  await expect(pageOne.getByTestId("continue-questionnaire")).toBeVisible();
  await expect(pageOne.getByTestId("reward-info")).toBeVisible();

  await pageOne.goto("/history");
  const pendingHistory = pageOne.getByTestId("history-list");
  await expect(pendingHistory).toContainText("待填写问卷", {
    timeout: 20000,
  });
  await expect(pendingHistory).toContainText("正式实验已完成");
  await expect(pendingHistory).toContainText("未提交");
  await expect(pendingHistory).toContainText(NO_REWARD);
  await expect(pendingHistory).toContainText("问卷未完成");
  await expect(pendingHistory).toContainText(HISTORY_QUESTIONNAIRE_LOCK_NOTE);
  await expect(pageOne.getByTestId("continue-questionnaire")).toBeVisible();
  await expect(pageOne.getByTestId("rebook")).toHaveCount(0);
  await expect(pageOne.getByTestId("payment-status")).toHaveCount(0);

  await pageOne.goto(`/complete?room=${encodeURIComponent(world.roomId)}`);
  await expect(pageOne.getByRole("heading", { name: "报酬信息" })).toBeVisible({
    timeout: 20000,
  });
  await expect(pageOne.getByText(NO_REWARD, { exact: true })).toBeVisible();
  await expect(
    pageOne.getByText(COMPLETE_PENDING_ARCHIVED_DETAIL, { exact: true }),
  ).toBeVisible();
  await expect(
    pageOne.getByText(COMPLETE_QUESTIONNAIRE_ARCHIVE_NOTE, { exact: true }),
  ).toBeVisible();
  await expect(pageOne.getByTestId("continue-questionnaire")).toBeVisible();
  await expect(pageOne.getByTestId("complete-total")).toHaveCount(0);
  await expect(pageOne.getByTestId("payment-status")).toHaveCount(0);
  await expect(pageOne.getByText("支付截止日期", { exact: true })).toHaveCount(
    0,
  );

  await submitQuestionnaire(pageOne, baseURL, world.roomId, "incomplete-a");

  await pageOne.goto(`/complete?room=${encodeURIComponent(world.roomId)}`);
  await expect(pageOne.getByTestId("complete-total")).toBeVisible({
    timeout: 20000,
  });
  await expect(pageOne.getByTestId("payment-status")).toContainText("待支付");
  await expect(
    pageOne.getByText(COMPLETE_ARCHIVED_SUBMITTED_NOTE, { exact: true }),
  ).toBeVisible();
  await expect(pageOne.getByText("问卷未完成", { exact: true })).toBeVisible();
  await expect(pageOne.getByTestId("continue-questionnaire")).toHaveCount(0);
  await expect(pageOne.getByTestId("rebook")).toHaveCount(0);

  await pageOne.goto("/");
  await expect(
    pageOne.getByText(ACCOUNT_COMPLETED, { exact: true }),
  ).toBeVisible({ timeout: 20000 });
  await expect(pageOne.getByTestId("pending-questionnaire-card")).toHaveCount(
    0,
  );
  await expect(pageOne.getByTestId("bookable-hidden")).toHaveCount(0);
  await expect(pageOne.getByTestId("current-booking")).toContainText(
    "你当前没有预约",
  );

  await pageOne.goto("/history");
  const completedHistory = pageOne.getByTestId("history-list");
  await expect(completedHistory).toContainText("已完成", {
    timeout: 20000,
  });
  await expect(completedHistory).toContainText("问卷未完成");
  await expect(completedHistory).toContainText(
    HISTORY_ARCHIVED_SUBMITTED_NOTE,
  );
  await expect(pageOne.getByTestId("payment-status")).toHaveText("待支付");
  await expect(pageOne.getByTestId("continue-questionnaire")).toHaveCount(0);
  await expect(pageOne.getByTestId("rebook")).toHaveCount(0);

  await pageTwo.goto("/");
  await expect(pageTwo.getByTestId("pending-questionnaire-card")).toContainText(
    "已归档",
  );
  await expect(
    pageTwo.getByText(PENDING_QUESTIONNAIRE_ARCHIVED_DETAIL, { exact: true }),
  ).toBeVisible();
  await expect(
    pageTwo.getByText(ACCOUNT_PENDING_QUESTIONNAIRE, { exact: true }),
  ).toBeVisible();
  await expect(pageTwo.getByTestId("bookable-hidden")).toBeVisible();
  await expect(pageTwo.getByTestId("continue-questionnaire")).toBeVisible();

  await contextOne.close();
  await contextTwo.close();
  await adminContext.close();
});

test("双方提交问卷后正常归档并显示完成报酬", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(240_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = roster(["完成甲", "完成乙"], "1347000");
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 20,
    condition: {
      formalTrials: 1,
      turnCount: 1,
      restSeconds: 1,
      turnSeconds: 60,
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
  await Promise.all([
    bookRoom(pageOne, world.roomId),
    bookRoom(pageTwo, world.roomId),
  ]);
  await expectBothBooked(pageOne, pageTwo);
  await Promise.all([enterRoom(pageOne), enterRoom(pageTwo)]);
  await waitBothEntered(pageOne, pageTwo);
  await startMatchingPair(pageOne, pageTwo);
  await completeInstructionsPair(pageOne, pageTwo);
  await submitCellPair(pageOne, pageTwo);
  await waitForQuestionnaire(pageOne, pageTwo);

  await Promise.all([
    submitQuestionnaire(pageOne, baseURL, world.roomId, "completed-a"),
    submitQuestionnaire(pageTwo, baseURL, world.roomId, "completed-b"),
  ]);

  await Promise.all([
    expectArchiveView(pageOne, COMPLETED_TITLE, COMPLETED_DETAIL, {
      rebook: false,
      continueQuestionnaire: false,
    }),
    expectArchiveView(pageTwo, COMPLETED_TITLE, COMPLETED_DETAIL, {
      rebook: false,
      continueQuestionnaire: false,
    }),
  ]);

  for (const page of [pageOne, pageTwo]) {
    await page.goto(`/complete?room=${encodeURIComponent(world.roomId)}`);
    await expect(page.getByTestId("complete-total")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByTestId("payment-status")).toContainText("待支付");
    await expect(
      page.getByText(COMPLETE_TRANSFER_NOTE, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(COMPLETED_REASON_LABEL, { exact: true })).toBeVisible();
    await expect(page.getByTestId("rebook")).toHaveCount(0);

    await page.goto("/history");
    const history = page.getByTestId("history-list");
    await expect(history).toContainText("已完成", { timeout: 20000 });
    await expect(history).toContainText(COMPLETED_REASON_LABEL);
    await expect(page.getByTestId("payment-status")).toHaveText("待支付");
    await expect(page.getByTestId("rebook")).toHaveCount(0);
  }

  await contextOne.close();
  await contextTwo.close();
});
