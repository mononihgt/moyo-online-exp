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

export const ID_CARD_SAMPLE = "11010519491231002X";
export const PASSPORT_SAMPLE = "E12345678";

export const DEFAULT_TROOP_ROWS: TroopRow[] = [
  { soldiersA: 7, soldiersB: 7 },
  { soldiersA: 8, soldiersB: 9 },
  { soldiersA: 6, soldiersB: 5 },
];

export interface RosterEntry {
  name: string;
  phone: string;
}

export interface TroopRow {
  soldiersA: number;
  soldiersB: number;
}

export interface MapGroupConfig {
  mode?: "both" | "ab";
  rows?: number;
  cols?: number;
  formalTrials?: number;
  description?: string;
  factorLevel?: string;
  images?: (string | null)[];
  imagesBySlot?: { a?: (string | null)[]; b?: (string | null)[] };
  spawns?: { A: number; B: number };
  practiceTurnCap?: number;
  practiceTurnSeconds?: number;
  formalTurnCap?: number;
  formalTurnSeconds?: number;
  restSeconds?: number;
  randomizeFormal?: boolean;
  basePayCents?: number;
  performanceRateCents?: number;
  performanceFloorCents?: number;
  performanceCapCents?: number;
  showupPayCents?: number;
}

export interface WorldConfig {
  entries: RosterEntry[];
  startsInSeconds?: number;
  waitWindowSeconds?: number;
  reconnectWindowSeconds?: number;
  troopRows?: TroopRow[];
  map?: MapGroupConfig;
  roomLabel?: string;
  instructionMarkdownP1?: string;
  instructionMarkdownP2?: string;
  minReadingSecondsP1?: number;
  minReadingSecondsP2?: number;
  questionnaireName?: string;
}

export interface World {
  roomId: string;
  roomLabel: string;
  startsAt: string;
  entries: RosterEntry[];
  troopRows: TroopRow[];
  mapGroupVersionId: string;
  mapGroupName: string;
  instructionP1Id: string;
  instructionP2Id: string;
  questionnaireVersionId: string;
  rows: number;
  cols: number;
}

export interface IdentityAnswers {
  real_name: string;
  alipay_phone: string;
  documentType: "id_card" | "passport";
  documentNumber: string;
}

export interface PaymentListEntry {
  id: string;
  participantId: string;
  name: string;
  totalCents: number;
  status: "pending" | "paid";
  roomStartsAt: string;
}

export interface MediaUpload {
  data: Buffer;
  filename: string;
  mimeType: string;
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

export async function uploadMedia(
  request: APIRequestContext,
  baseURL: string,
  upload: MediaUpload,
  kind = "map",
): Promise<string> {
  const csrf = await adminCsrfToken(request);
  const response = await request.fetch(`${baseURL}/admin/api/media`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrf },
    multipart: {
      file: {
        name: upload.filename,
        mimeType: upload.mimeType,
        buffer: upload.data,
      },
      kind,
    },
  });
  if (!response.ok()) {
    throw new Error(`POST /admin/api/media -> ${response.status()}: ${await response.text()}`);
  }
  const body = (await response.json()) as { asset: { id: string } };
  return body.asset.id;
}

async function createTroopProfile(
  request: APIRequestContext,
  baseURL: string,
  rows: TroopRow[],
): Promise<string> {
  const created = await adminApi<{ troopProfile: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/troop-profiles",
    { name: marker("浏览器兵力"), rows },
  );
  const published = await adminApi<{ troopProfile: { id: string } }>(
    request,
    baseURL,
    "POST",
    `/admin/api/troop-profiles/${created.troopProfile.id}/publish`,
  );
  return published.troopProfile.id;
}

function mapCells(
  images: (string | null)[] | undefined,
  total: number,
): (string | null)[] {
  return Array.from({ length: total }, (_, index) => images?.[index] ?? null);
}

async function createMapGroup(
  request: APIRequestContext,
  baseURL: string,
  profileVersionId: string,
  config: MapGroupConfig,
  troopRows: TroopRow[],
): Promise<{ id: string; name: string; rows: number; cols: number }> {
  const mode = config.mode ?? "both";
  const rows = config.rows ?? 3;
  const cols = config.cols ?? 3;
  const total = rows * cols;
  const formalTrials = config.formalTrials ?? troopRows.length - 1;
  const description = config.description ?? "浏览器验证";
  const factorLevel = config.factorLevel ?? "标准";
  const slots = mode === "both" ? (["Both"] as const) : (["A", "B"] as const);
  const maps = slots.map((slot) => ({
    slot,
    description,
    factorLevel,
    cells:
      slot === "B"
        ? mapCells(config.imagesBySlot?.b ?? config.images, total)
        : mapCells(config.imagesBySlot?.a ?? config.images, total),
  }));
  const created = await adminApi<{ mapGroup: { id: string; name: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/map-groups",
    {
      mode,
      rows,
      cols,
      spawns: config.spawns ?? { A: 0, B: total - 1 },
      troopProfileVersionId: profileVersionId,
      practiceTrials: 1,
      formalTrials,
      practiceTurnCap: config.practiceTurnCap ?? 2,
      practiceTurnSeconds: config.practiceTurnSeconds ?? 30,
      formalTurnCap: config.formalTurnCap ?? 2,
      formalTurnSeconds: config.formalTurnSeconds ?? 30,
      restSeconds: config.restSeconds ?? 1,
      randomizeFormal: config.randomizeFormal ?? false,
      payment: {
        basePayCents: config.basePayCents ?? 4500,
        performanceRateCents: config.performanceRateCents ?? 1,
        performanceFloorCents: config.performanceFloorCents ?? 0,
        performanceCapCents: config.performanceCapCents ?? 2000,
        showupPayCents: config.showupPayCents ?? 1000,
      },
      maps,
    },
  );
  const published = await adminApi<{ mapGroup: { id: string; name: string } }>(
    request,
    baseURL,
    "POST",
    `/admin/api/map-groups/${created.mapGroup.id}/publish`,
  );
  return {
    id: published.mapGroup.id,
    name: published.mapGroup.name,
    rows,
    cols,
  };
}

async function createInstruction(
  request: APIRequestContext,
  baseURL: string,
  mapGroupVersionId: string,
  role: 1 | 2,
  markdown: string,
  minReadingSeconds: number,
): Promise<string> {
  const created = await adminApi<{ instruction: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/instructions",
    { mapGroupVersionId, role, markdown, minReadingSeconds },
  );
  const published = await adminApi<{ instruction: { id: string } }>(
    request,
    baseURL,
    "POST",
    `/admin/api/instructions/${created.instruction.id}/publish`,
  );
  return published.instruction.id;
}

async function createQuestionnaire(
  request: APIRequestContext,
  baseURL: string,
  name: string,
): Promise<string> {
  const created = await adminApi<{ questionnaire: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/questionnaires",
    {
      name,
      schemaJson: {
        title: "浏览器流程后测",
        pages: [
          {
            id: "page1",
            questions: [
              {
                id: "q1",
                type: "single_choice",
                label: "本次实验中的体验",
                required: true,
                options: [
                  { value: "a", label: "顺利" },
                  { value: "b", label: "一般" },
                ],
              },
              {
                id: "q2",
                type: "short_text",
                label: "实验感受",
                required: true,
                maxLength: 200,
              },
              {
                id: "real_name",
                type: "real_name",
                label: "真实姓名",
                required: true,
              },
              {
                id: "alipay_phone",
                type: "alipay_phone",
                label: "支付宝手机号",
                required: true,
              },
              {
                id: "identity_document",
                type: "identity_document",
                label: "身份证件",
                required: true,
              },
            ],
          },
        ],
      },
    },
  );
  const published = await adminApi<{ questionnaire: { id: string } }>(
    request,
    baseURL,
    "POST",
    `/admin/api/questionnaires/${created.questionnaire.id}/publish`,
  );
  return published.questionnaire.id;
}

async function createRoom(
  request: APIRequestContext,
  baseURL: string,
  materials: {
    mapGroupVersionId: string;
    instructionP1Id: string;
    instructionP2Id: string;
    questionnaireVersionId: string;
  },
  options: {
    label: string;
    startsInSeconds: number;
    waitWindowSeconds: number;
    reconnectWindowSeconds: number;
    publish: boolean;
  },
): Promise<{ id: string; startsAt: string }> {
  const startsAt = new Date(
    Date.now() + options.startsInSeconds * 1000,
  ).toISOString();
  const created = await adminApi<{ room: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/rooms",
    {
      internalLabel: options.label,
      startsAt,
      mapGroupVersionId: materials.mapGroupVersionId,
      instructionVersionP1Id: materials.instructionP1Id,
      instructionVersionP2Id: materials.instructionP2Id,
      questionnaireVersionId: materials.questionnaireVersionId,
      waitWindowSeconds: options.waitWindowSeconds,
      reconnectWindowSeconds: options.reconnectWindowSeconds,
    },
  );
  if (options.publish) {
    await adminApi(
      request,
      baseURL,
      "POST",
      `/admin/api/rooms/${created.room.id}/publish`,
    );
  }
  return { id: created.room.id, startsAt };
}

export async function prepareConsentBase(
  request: APIRequestContext,
  baseURL: string,
): Promise<void> {
  await adminLogin(request, baseURL);
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
  await prepareConsentBase(request, baseURL);
  const troopRows = config.troopRows ?? DEFAULT_TROOP_ROWS;
  const profileVersionId = await createTroopProfile(request, baseURL, troopRows);
  const mapConfig = config.map ?? {};
  const mapGroup = await createMapGroup(
    request,
    baseURL,
    profileVersionId,
    mapConfig,
    troopRows,
  );
  const instructionP1Id = await createInstruction(
    request,
    baseURL,
    mapGroup.id,
    1,
    config.instructionMarkdownP1 ??
      "# 玩家 A\n\n请阅读本页指导语，完成后点击继续。",
    config.minReadingSecondsP1 ?? 0,
  );
  const instructionP2Id = await createInstruction(
    request,
    baseURL,
    mapGroup.id,
    2,
    config.instructionMarkdownP2 ??
      "# 玩家 B\n\n请阅读本页指导语，完成后点击继续。",
    config.minReadingSecondsP2 ?? 0,
  );
  const questionnaireVersionId = await createQuestionnaire(
    request,
    baseURL,
    config.questionnaireName ?? marker("浏览器问卷"),
  );
  const roomLabel = config.roomLabel ?? marker("浏览器房间");
  const room = await createRoom(
    request,
    baseURL,
    {
      mapGroupVersionId: mapGroup.id,
      instructionP1Id,
      instructionP2Id,
      questionnaireVersionId,
    },
    {
      label: roomLabel,
      startsInSeconds: config.startsInSeconds ?? 25,
      waitWindowSeconds: config.waitWindowSeconds ?? 90,
      reconnectWindowSeconds: config.reconnectWindowSeconds ?? 30,
      publish: true,
    },
  );
  return {
    roomId: room.id,
    roomLabel,
    startsAt: room.startsAt,
    entries: config.entries,
    troopRows,
    mapGroupVersionId: mapGroup.id,
    mapGroupName: mapGroup.name,
    instructionP1Id,
    instructionP2Id,
    questionnaireVersionId,
    rows: mapGroup.rows,
    cols: mapGroup.cols,
  };
}

export async function createAdditionalRoom(
  request: APIRequestContext,
  baseURL: string,
  world: World,
  options: {
    label: string;
    startsInSeconds?: number;
    waitWindowSeconds?: number;
    reconnectWindowSeconds?: number;
    publish?: boolean;
  },
): Promise<{ id: string; startsAt: string }> {
  return createRoom(
    request,
    baseURL,
    {
      mapGroupVersionId: world.mapGroupVersionId,
      instructionP1Id: world.instructionP1Id,
      instructionP2Id: world.instructionP2Id,
      questionnaireVersionId: world.questionnaireVersionId,
    },
    {
      label: options.label,
      startsInSeconds: options.startsInSeconds ?? 3600,
      waitWindowSeconds: options.waitWindowSeconds ?? 90,
      reconnectWindowSeconds: options.reconnectWindowSeconds ?? 30,
      publish: options.publish ?? true,
    },
  );
}

export function identityAnswers(
  tag: string,
  options: {
    phone?: string;
    documentType?: "id_card" | "passport";
  } = {},
): IdentityAnswers {
  const documentType = options.documentType ?? "id_card";
  return {
    real_name: `测试${tag}`,
    alipay_phone: options.phone ?? "13900001111",
    documentType,
    documentNumber:
      documentType === "passport" ? PASSPORT_SAMPLE : ID_CARD_SAMPLE,
  };
}

export function questionnaireAnswers(
  identity: IdentityAnswers,
  extra: Json = {},
): Json {
  return {
    q1: "a",
    q2: "浏览器端流程测试答卷",
    ...extra,
    real_name: identity.real_name,
    alipay_phone: identity.alipay_phone,
    identity_document: {
      documentType: identity.documentType,
      number: identity.documentNumber,
    },
  };
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

export async function roleMarker(page: Page): Promise<"circle" | "diamond"> {
  const text = await page.locator(".exp-hud-role").innerText();
  return text.includes("○") ? "circle" : "diamond";
}

export async function clickBoardCell(
  page: Page,
  index: number,
  rows: number,
  cols: number,
): Promise<void> {
  const canvas = page.getByTestId("game-canvas");
  await expect(canvas).toBeVisible({ timeout: 30000 });
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("game canvas has no bounding box");
  const row = Math.floor(index / cols);
  const col = index % cols;
  await page.mouse.click(
    box.x + ((col + 0.5) * box.width) / cols,
    box.y + ((row + 0.5) * box.height) / rows,
  );
}

async function submitCell(page: Page, index: number, rows: number, cols: number): Promise<void> {
  await clickBoardCell(page, index, rows, cols);
  const confirm = page.getByTestId("confirm-selection");
  await expect(confirm).toBeEnabled({ timeout: 10000 });
  await confirm.click();
}

export async function submitRoundPair(
  pageOne: Page,
  pageTwo: Page,
  rows: number,
  cols: number,
): Promise<void> {
  const markerOne = await roleMarker(pageOne);
  const markerTwo = await roleMarker(pageTwo);
  const circleIndex = 1;
  const diamondIndex = Math.max(2, rows * cols - 2);
  await Promise.all([
    submitCell(
      pageOne,
      markerOne === "circle" ? circleIndex : diamondIndex,
      rows,
      cols,
    ),
    submitCell(
      pageTwo,
      markerTwo === "circle" ? circleIndex : diamondIndex,
      rows,
      cols,
    ),
  ]);
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

export async function continueFromRestPair(
  pageOne: Page,
  pageTwo: Page,
): Promise<void> {
  const readyOne = pageOne.getByTestId("rest-ready");
  const readyTwo = pageTwo.getByTestId("rest-ready");
  await expect(readyOne).toBeEnabled({ timeout: 20000 });
  await expect(readyTwo).toBeEnabled({ timeout: 20000 });
  await Promise.all([readyOne.click(), readyTwo.click()]);
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
  await expect(
    pageOne.getByText("未提交后测问卷前", { exact: false }),
  ).toHaveCount(0);
  await expect(
    pageTwo.getByText("未提交后测问卷前", { exact: false }),
  ).toHaveCount(0);
}

export async function expectTurnLabel(
  pageOne: Page,
  pageTwo: Page,
  label: string,
): Promise<void> {
  await Promise.all([
    expect(pageOne.locator(".exp-hud-left")).toContainText(label, {
      timeout: 30000,
    }),
    expect(pageTwo.locator(".exp-hud-left")).toContainText(label, {
      timeout: 30000,
    }),
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
  identity: IdentityAnswers = identityAnswers(tag),
): Promise<Json> {
  return participantPost(page, baseURL, "/api/questionnaire/complete", {
    roomId,
    answers: questionnaireAnswers(identity),
    jatosWorkerId: `node-e2e-${tag}`,
    jatosStudyResultId: `node-e2e-study-${tag}`,
    jatosComponentResultId: `node-e2e-component-${tag}`,
  });
}

export async function listPayments(
  request: APIRequestContext,
  baseURL: string,
): Promise<PaymentListEntry[]> {
  const response = await adminApi<{ payments: PaymentListEntry[] }>(
    request,
    baseURL,
    "GET",
    "/admin/api/payments",
  );
  return response.payments;
}

export async function markPaymentPaid(
  request: APIRequestContext,
  baseURL: string,
  paymentId: string,
): Promise<void> {
  await adminApi(
    request,
    baseURL,
    "PATCH",
    `/admin/api/payments/${paymentId}`,
    { status: "paid" },
  );
}
