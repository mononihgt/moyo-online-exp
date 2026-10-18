import { expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

export const ADMIN_PASSWORD = "integration-admin-password";

export const SELF_EXIT_NOTICE =
  "你已主动退出本次实验，本次实验未完成，无实验报酬。你可以重新预约。";
export const EXIT_TITLE = "确认退出实验？";
export const EXIT_DETAIL =
  "退出后本次实验未完成，无实验报酬，另一名参与者也会结束实验。";
export const WAIT_EXIT_TITLE = "确认退出本次实验？";
export const WAIT_EXIT_DETAIL =
  "退出后本次实验将结束，本次实验未完成，不产生报酬。你可以返回首页重新预约其他时间段。";
export const NO_REWARD = "本次实验未完成，不产生报酬";

export interface RosterEntry {
  name: string;
  phone: string;
}

export interface ConditionConfig {
  practiceTrials?: number;
  formalTrials?: number;
  turnCount?: number;
  turnSeconds?: number;
  restSeconds?: number;
  rows?: number;
  cols?: number;
}

export interface WorldConfig {
  entries: RosterEntry[];
  startsInSeconds?: number;
  waitWindowSeconds?: number;
  reconnectWindowSeconds?: number;
  showupPayCents?: number;
  basePayCents?: number;
  performanceRateCents?: number;
  condition?: ConditionConfig;
}

export interface World {
  roomId: string;
  startsAt: string;
  entries: RosterEntry[];
}

type Json = Record<string, unknown>;

function marker(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export async function adminCsrfToken(
  request: APIRequestContext,
): Promise<string> {
  const state = await request.storageState();
  const cookie = state.cookies.find((item) => item.name === "moyo_csrf");
  if (!cookie) throw new Error("missing moyo_csrf cookie");
  return cookie.value;
}

export async function adminApi<T = Json>(
  request: APIRequestContext,
  baseURL: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await adminCsrfToken(request);
  }
  const response = await request.fetch(`${baseURL}${path}`, {
    method,
    headers,
    data: body,
  });
  if (!response.ok()) {
    throw new Error(
      `${method} ${path} -> ${response.status()}: ${await response.text()}`,
    );
  }
  return response.json() as Promise<T>;
}

export async function adminLogin(
  request: APIRequestContext,
  baseURL: string,
): Promise<void> {
  const response = await request.post(`${baseURL}/admin/api/login`, {
    data: { username: "admin", password: ADMIN_PASSWORD },
  });
  if (!response.ok()) throw new Error(await response.text());
}

export async function importRoster(
  request: APIRequestContext,
  baseURL: string,
  entries: RosterEntry[],
): Promise<void> {
  const roster = [
    "姓名,手机号",
    ...entries.map((entry) => `${entry.name},${entry.phone}`),
    "",
  ].join("\n");
  const csrf = await adminCsrfToken(request);
  const response = await request.fetch(`${baseURL}/admin/api/participants/import`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf },
    multipart: {
      file: {
        name: "roster.csv",
        mimeType: "text/csv",
        buffer: Buffer.from(roster, "utf8"),
      },
    },
  });
  if (!response.ok()) throw new Error(await response.text());
}

export async function publishConsentVersion(
  request: APIRequestContext,
  baseURL: string,
  markdown: string,
): Promise<string> {
  const created = await adminApi<{ id: string }>(
    request,
    baseURL,
    "POST",
    "/admin/api/consent-versions",
    { markdown },
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/consent-versions/${created.id}/publish`,
  );
  return created.id;
}

async function createInstruction(
  request: APIRequestContext,
  baseURL: string,
  role: 1 | 2,
): Promise<string> {
  const name = marker(`flow-p${role}`);
  const created = await adminApi<{ instruction: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/instructions",
    {
      name,
      role,
      markdown: `# 玩家${role}\n\n玩家${role}流程测试指导语。`,
      minReadingSeconds: 0,
    },
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/instructions/${created.instruction.id}/publish`,
  );
  return created.instruction.id;
}

async function createQuestionnaire(
  request: APIRequestContext,
  baseURL: string,
): Promise<string> {
  const created = await adminApi<{ questionnaire: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/questionnaires",
    {
      name: marker("flow-questionnaire"),
      schemaJson: {
        title: "流程测试后测",
        pages: [
          {
            id: "p1",
            questions: [
              {
                id: "q1",
                type: "single_choice",
                label: "流程测试选项",
                required: true,
                options: [
                  { value: "a", label: "A" },
                  { value: "b", label: "B" },
                ],
              },
            ],
          },
        ],
      },
    },
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/questionnaires/${created.questionnaire.id}/publish`,
  );
  return created.questionnaire.id;
}

function conditionPayload(config: ConditionConfig): Json {
  const rows = config.rows ?? 2;
  const cols = config.cols ?? 2;
  const total = rows * cols;
  const practiceTrials = config.practiceTrials ?? 0;
  const formalTrials = config.formalTrials ?? 1;
  const turnCount = config.turnCount ?? 1;
  const cells = Array.from({ length: total }, (_, index) => ({
    row: Math.floor(index / cols),
    col: index % cols,
    initialOwner: index === 0 ? 1 : index === total - 1 ? 2 : 0,
    initialSoldiers: 0,
    reinforcementA: 2,
    reinforcementB: 2,
  }));
  const visual = Array.from({ length: total }, () => ({
    color: "#E8F0FF",
    backgroundAssetId: null,
  }));
  const trialParams = Array.from(
    { length: practiceTrials + formalTrials },
    (_, index) => ({
      sourceIndex: index,
      isPractice: index < practiceTrials,
      formalTrial: index < practiceTrials ? 0 : index - practiceTrials + 1,
      baseSoldiersA: 8,
      baseSoldiersB: 8,
      reinforcementOverrides: null,
    }),
  );
  return {
    name: marker(`flow-condition-${rows}x${cols}`),
    description: "参与者流程浏览器测试条件",
    rows,
    cols,
    cells,
    visuals: {
      player1: visual,
      player2: visual.map((item) => ({ ...item })),
    },
    baseAIndex: 0,
    baseBIndex: total - 1,
    practiceTrials,
    formalTrials,
    turnCount,
    turnSeconds: config.turnSeconds ?? 60,
    restSeconds: config.restSeconds ?? 30,
    randomizeFormal: false,
    trialParams,
    metadata: { source: "participant-flow-e2e" },
  };
}

export async function prepareConsentBase(
  request: APIRequestContext,
  baseURL: string,
  entries: RosterEntry[],
): Promise<void> {
  await adminLogin(request, baseURL);
  await importRoster(request, baseURL, entries);
  await publishConsentVersion(
    request,
    baseURL,
    "# 知情同意\n\n流程测试知情同意书。",
  );
}

export async function prepareWorld(
  request: APIRequestContext,
  baseURL: string,
  config: WorldConfig,
): Promise<World> {
  await prepareConsentBase(request, baseURL, config.entries);
  const instructionP1Id = await createInstruction(request, baseURL, 1);
  const instructionP2Id = await createInstruction(request, baseURL, 2);
  const questionnaireVersionId = await createQuestionnaire(request, baseURL);
  const condition = await adminApi<{ condition: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/conditions",
    conditionPayload(config.condition ?? {}),
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/conditions/${condition.condition.id}/publish`,
  );
  const startsAt = new Date(
    Date.now() + (config.startsInSeconds ?? 20) * 1000,
  ).toISOString();
  const room = await adminApi<{ room: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/rooms",
    {
      internalLabel: marker("flow-room"),
      startsAt,
      conditionVersionId: condition.condition.id,
      instructionVersionP1Id: instructionP1Id,
      instructionVersionP2Id: instructionP2Id,
      questionnaireVersionId,
      basePayCents: config.basePayCents ?? 1000,
      performanceRateCents: config.performanceRateCents ?? 1,
      showupPayCents: config.showupPayCents ?? 500,
      waitWindowSeconds: config.waitWindowSeconds ?? 120,
      reconnectWindowSeconds: config.reconnectWindowSeconds ?? 60,
    },
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/rooms/${room.room.id}/publish`,
  );
  return { roomId: room.room.id, startsAt, entries: config.entries };
}

export async function adminLoginPage(page: Page): Promise<void> {
  await page.goto("/admin/login");
  await page.getByTestId("admin-login-username").fill("admin");
  await page.getByTestId("admin-login-password").fill(ADMIN_PASSWORD);
  await page.getByTestId("admin-login-submit").click();
  await expect(page).toHaveURL(/\/admin$/, { timeout: 20000 });
}

export async function openAdminRoom(page: Page, roomId: string): Promise<void> {
  await page.goto(`/admin/rooms/${roomId}`);
  await page.getByRole("tab", { name: "监控" }).click();
  await expect(page.locator("#archive-reason")).toBeVisible({
    timeout: 20000,
  });
}

export async function archiveReasonOptions(page: Page): Promise<string[]> {
  const options = await page.locator("#archive-reason option").allTextContents();
  return options.map((option) => option.trim());
}

export async function loginParticipant(
  page: Page,
  name: string,
  phone: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-name").fill(name);
  await page.getByTestId("login-phone").fill(phone);
  await page.getByTestId("login-submit").click();
  await page.waitForURL(
    (url) => url.pathname === "/" || url.pathname === "/consent",
    { timeout: 20000 },
  );
  if (new URL(page.url()).pathname === "/consent") {
    await page.getByTestId("consent-agree").click();
    await page.waitForURL((url) => url.pathname === "/", { timeout: 20000 });
  }
  await expect(page.getByTestId("current-booking")).toBeVisible({
    timeout: 20000,
  });
}

export async function bookRoom(page: Page, roomId: string): Promise<void> {
  const option = page.locator(
    `[data-testid="room-option"][data-room-id="${roomId}"]`,
  );
  await expect(option).toBeEnabled({ timeout: 30000 });
  await option.click();
  await expect(page.getByTestId("book-room")).toBeEnabled();
  await page.getByTestId("book-room").click();
  await expect(page.getByTestId("current-booking")).toContainText("开始时间", {
    timeout: 20000,
  });
}

export async function expectBothBooked(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  await Promise.all([pageOne.reload(), pageTwo.reload()]);
  await expect(pageOne.getByTestId("current-booking")).toContainText("2/2", {
    timeout: 20000,
  });
  await expect(pageTwo.getByTestId("current-booking")).toContainText("2/2", {
    timeout: 20000,
  });
}

export async function enterRoom(page: Page): Promise<void> {
  const enter = page.getByTestId("enter-room");
  await expect(enter).toBeVisible({ timeout: 45000 });
  await enter.click();
  await expect(page.getByTestId("start-matching")).toBeVisible({
    timeout: 30000,
  });
}

export async function waitBothEntered(pageOne: Page, pageTwo: Page): Promise<void> {
  await Promise.all([
    expect(pageOne.getByTestId("hud-partner")).toContainText("另一名参与者已进入", {
      timeout: 30000,
    }),
    expect(pageTwo.getByTestId("hud-partner")).toContainText("另一名参与者已进入", {
      timeout: 30000,
    }),
  ]);
}

export async function startMatchingPair(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  const startOne = pageOne.getByTestId("start-matching");
  const startTwo = pageTwo.getByTestId("start-matching");
  await expect(startOne).toBeEnabled({ timeout: 20000 });
  await expect(startTwo).toBeEnabled({ timeout: 20000 });
  await startOne.click();
  await expect(startTwo).toBeEnabled({ timeout: 20000 });
  await startTwo.click();
  await Promise.all([
    expect(pageOne.getByTestId("instruction-content")).toBeVisible({
      timeout: 30000,
    }),
    expect(pageTwo.getByTestId("instruction-content")).toBeVisible({
      timeout: 30000,
    }),
  ]);
}

export async function completeInstructionsPair(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  const completeOne = pageOne.getByTestId("instruction-complete");
  const completeTwo = pageTwo.getByTestId("instruction-complete");
  await expect(completeOne).toBeEnabled({ timeout: 20000 });
  await expect(completeTwo).toBeEnabled({ timeout: 20000 });
  await Promise.all([completeOne.click(), completeTwo.click()]);
  const enterOne = pageOne.getByTestId("enter-game");
  const enterTwo = pageTwo.getByTestId("enter-game");
  await expect(enterOne).toBeVisible({ timeout: 20000 });
  await expect(enterTwo).toBeVisible({ timeout: 20000 });
  await expect(enterOne).toBeEnabled();
  await expect(enterTwo).toBeEnabled();
  await Promise.all([enterOne.click(), enterTwo.click()]);
  await Promise.all([
    expect(pageOne.getByTestId("game-canvas")).toBeVisible({ timeout: 30000 }),
    expect(pageTwo.getByTestId("game-canvas")).toBeVisible({ timeout: 30000 }),
  ]);
}

async function submitCell(page: Page): Promise<void> {
  const canvas = page.getByTestId("game-canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("game canvas has no bounding box");
  await page.mouse.click(box.x + box.width * 0.25, box.y + box.height * 0.25);
  const confirm = page.getByTestId("confirm-selection");
  await expect(confirm).toBeEnabled({ timeout: 10000 });
  await confirm.click();
}

export async function submitCellPair(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  await Promise.all([submitCell(pageOne), submitCell(pageTwo)]);
}

export async function waitForRest(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  await Promise.all([
    expect(pageOne.getByTestId("rest-view")).toBeVisible({ timeout: 30000 }),
    expect(pageTwo.getByTestId("rest-view")).toBeVisible({ timeout: 30000 }),
  ]);
}

export async function waitForQuestionnaire(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  await Promise.all([
    expect(
      pageOne.getByRole("heading", { name: "请填写后测问卷", exact: true }),
    ).toBeVisible({ timeout: 30000 }),
    expect(
      pageTwo.getByRole("heading", { name: "请填写后测问卷", exact: true }),
    ).toBeVisible({ timeout: 30000 }),
  ]);
}

export async function openExperimentExitDialog(page: Page) {
  const button = page.getByTestId("exit-experiment");
  await expect(button).toBeVisible({ timeout: 20000 });
  await button.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: EXIT_TITLE, exact: true }),
  ).toBeVisible();
  await expect(dialog.getByText(EXIT_DETAIL, { exact: true })).toBeVisible();
  return dialog;
}

export async function cancelExperimentExit(page: Page): Promise<void> {
  const dialog = await openExperimentExitDialog(page);
  await dialog.getByTestId("exit-cancel").click();
  await expect(dialog).toBeHidden();
}

export async function confirmExperimentExit(page: Page): Promise<void> {
  const dialog = await openExperimentExitDialog(page);
  await dialog.getByTestId("exit-confirm").click();
  await expect(page).toHaveURL(
    (url) => url.pathname === "/",
    { timeout: 20000 },
  );
  await expect(page.getByText(SELF_EXIT_NOTICE, { exact: true })).toBeVisible();
}

export async function openWaitingExitDialog(page: Page) {
  const button = page.getByTestId("waiting-exit");
  await expect(button).toBeVisible();
  await button.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("heading", { name: WAIT_EXIT_TITLE, exact: true }),
  ).toBeVisible();
  await expect(dialog.getByText(WAIT_EXIT_DETAIL, { exact: true })).toBeVisible();
  return dialog;
}

export async function cancelWaitingExit(page: Page): Promise<void> {
  const dialog = await openWaitingExitDialog(page);
  await dialog.getByTestId("waiting-exit-cancel").click();
  await expect(dialog).toBeHidden();
}

export async function confirmWaitingExit(page: Page): Promise<void> {
  const dialog = await openWaitingExitDialog(page);
  await dialog.getByTestId("waiting-exit-confirm").click();
  await expect(page).toHaveURL(
    (url) => url.pathname === "/",
    { timeout: 20000 },
  );
  await expect(page.getByText(SELF_EXIT_NOTICE, { exact: true })).toBeVisible();
}

export async function expectArchiveView(
  page: Page,
  title: string,
  detail: string,
  options: { rebook: boolean; continueQuestionnaire: boolean },
): Promise<void> {
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible({ timeout: 25000 });
  await expect(page.getByText(detail, { exact: true })).toBeVisible();
  await expect(page.getByTestId("reward-info")).toBeVisible();
  if (options.rebook) {
    await expect(page.getByTestId("rebook")).toBeVisible();
  } else {
    await expect(page.getByTestId("rebook")).toHaveCount(0);
  }
  if (options.continueQuestionnaire) {
    await expect(page.getByTestId("continue-questionnaire")).toBeVisible();
  } else {
    await expect(page.getByTestId("continue-questionnaire")).toHaveCount(0);
  }
}

export async function expectNoRewardComplete(
  page: Page,
  roomId: string,
  detail: string,
  options: { rebook: boolean; archiveReason: string },
): Promise<void> {
  await page.goto(`/complete?room=${encodeURIComponent(roomId)}`);
  await expect(page.getByRole("heading", { name: "报酬信息" })).toBeVisible({
    timeout: 20000,
  });
  await expect(page.getByText(NO_REWARD, { exact: true })).toBeVisible();
  await expect(page.getByText(detail, { exact: true })).toBeVisible();
  await expect(page.getByText(options.archiveReason, { exact: true })).toBeVisible();
  await expect(page.getByTestId("complete-total")).toHaveCount(0);
  await expect(page.getByTestId("payment-status")).toHaveCount(0);
  await expect(page.getByText("支付截止日期", { exact: true })).toHaveCount(0);
  if (options.rebook) {
    await expect(page.getByTestId("rebook")).toBeVisible();
  } else {
    await expect(page.getByTestId("rebook")).toHaveCount(0);
  }
}

export async function participantPost(
  page: Page,
  baseURL: string,
  path: string,
  data: unknown,
): Promise<Json> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "moyo_csrf");
  if (!csrf) throw new Error("missing moyo_csrf cookie in participant context");
  const response = await page.request.fetch(`${baseURL}${path}`, {
    method: "POST",
    headers: {
      "X-CSRF-Token": csrf.value,
      "Content-Type": "application/json",
    },
    data,
  });
  if (!response.ok()) {
    throw new Error(
      `POST ${path} -> ${response.status()}: ${await response.text()}`,
    );
  }
  return (await response.json()) as Json;
}

export async function submitQuestionnaire(
  page: Page,
  baseURL: string,
  roomId: string,
  tag: string,
): Promise<Json> {
  return participantPost(page, baseURL, "/api/questionnaire/complete", {
    roomId,
    answers: { q1: "a" },
    jatosWorkerId: `node-e2e-${tag}`,
    jatosStudyResultId: `node-e2e-study-${tag}`,
    jatosComponentResultId: `node-e2e-component-${tag}`,
  });
}
