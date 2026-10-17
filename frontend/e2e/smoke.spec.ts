import { expect, test } from "@playwright/test";
import type { APIRequestContext, Browser } from "@playwright/test";

const ADMIN_PASSWORD = "integration-admin-password";

async function csrfToken(request: APIRequestContext, baseURL: string): Promise<string> {
  const state = await request.storageState();
  const cookie = state.cookies.find((item) => item.name === "moyo_csrf" && item.domain.includes("127.0.0.1"));
  if (!cookie) throw new Error("missing moyo_csrf cookie");
  return cookie.value;
}

async function api(
  request: APIRequestContext,
  baseURL: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  multipart?: Record<string, unknown>,
) {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-CSRF-Token"] = await csrfToken(request, baseURL);
  const response = await request.fetch(`${baseURL}${path}`, {
    method,
    headers,
    data: multipart ? undefined : body,
    multipart: multipart as never,
  });
  if (!response.ok()) {
    throw new Error(`${method} ${path} -> ${response.status()}: ${await response.text()}`);
  }
  return response.json();
}

function conditionPayload(rows: number, cols: number) {
  const total = rows * cols;
  const cells = Array.from({ length: total }, (_, index) => ({
    row: Math.floor(index / cols),
    col: index % cols,
    initialOwner: index === 0 ? 1 : index === total - 1 ? 2 : 0,
    initialSoldiers: 0,
    reinforcementA: 2,
    reinforcementB: 2,
  }));
  const visual = Array.from({ length: total }, () => ({ color: "#E8F0FF", backgroundAssetId: null }));
  return {
    name: `node-e2e-${rows}x${cols}`,
    description: "Node Playwright smoke condition",
    rows,
    cols,
    cells,
    visuals: { player1: visual, player2: visual.map((item) => ({ ...item })) },
    baseAIndex: 0,
    baseBIndex: total - 1,
    practiceTrials: 0,
    formalTrials: 1,
    turnCount: 2,
    turnSeconds: 30,
    restSeconds: 1,
    randomizeFormal: false,
    trialParams: [
      {
        sourceIndex: 0,
        isPractice: false,
        formalTrial: 1,
        baseSoldiersA: 8,
        baseSoldiersB: 8,
        reinforcementOverrides: null,
      },
    ],
    metadata: { source: "node-e2e" },
  };
}

async function setup(baseURL: string, request: APIRequestContext) {
  await request.post(`${baseURL}/admin/api/login`, {
    data: { username: "admin", password: ADMIN_PASSWORD },
  }).then(async (response) => {
    if (!response.ok()) throw new Error(await response.text());
  });
  const roster = "姓名,手机号\n节点甲,13300000001\n节点乙,13300000002\n";
  await api(request, baseURL, "POST", "/admin/api/participants/import", undefined, {
    file: { name: "roster.csv", mimeType: "text/csv", buffer: Buffer.from(roster, "utf8") },
  });
  await api(request, baseURL, "POST", "/admin/api/consent-versions", {
    markdown: "# 知情同意\n\nNode E2E 同意书。",
  }).then((created) => api(request, baseURL, "POST", `/admin/api/consent-versions/${created.id}/publish`));
  const instructionOne = await api(request, baseURL, "POST", "/admin/api/instructions", {
    name: "node-p1",
    role: 1,
    markdown: "# 玩家1\n\nNode E2E 玩家1。",
    minReadingSeconds: 0,
  });
  const instructionTwo = await api(request, baseURL, "POST", "/admin/api/instructions", {
    name: "node-p2",
    role: 2,
    markdown: "# 玩家2\n\nNode E2E 玩家2。",
    minReadingSeconds: 0,
  });
  await api(request, baseURL, "POST", `/admin/api/instructions/${instructionOne.instruction.id}/publish`);
  await api(request, baseURL, "POST", `/admin/api/instructions/${instructionTwo.instruction.id}/publish`);
  const questionnaire = await api(request, baseURL, "POST", "/admin/api/questionnaires", {
    name: "node-questionnaire",
    schemaJson: {
      title: "Node 后测",
      pages: [
        {
          id: "p1",
          questions: [
            {
              id: "q1",
              type: "single_choice",
              label: "选项",
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
  });
  await api(request, baseURL, "POST", `/admin/api/questionnaires/${questionnaire.questionnaire.id}/publish`);
  const condition = await api(request, baseURL, "POST", "/admin/api/conditions", conditionPayload(3, 4));
  await api(request, baseURL, "POST", `/admin/api/conditions/${condition.condition.id}/publish`);
  const room = await api(request, baseURL, "POST", "/admin/api/rooms", {
    internalLabel: "Node E2E Room",
    startsAt: new Date(Date.now() + 3600_000).toISOString(),
    conditionVersionId: condition.condition.id,
    instructionVersionP1Id: instructionOne.instruction.id,
    instructionVersionP2Id: instructionTwo.instruction.id,
    questionnaireVersionId: questionnaire.questionnaire.id,
    basePayCents: 1000,
    performanceRateCents: 1,
    showupPayCents: 500,
    waitWindowSeconds: 60,
    reconnectWindowSeconds: 60,
  });
  await api(request, baseURL, "POST", `/admin/api/rooms/${room.room.id}/publish`);
}

async function loginAndConsent(page: import("@playwright/test").Page, name: string, phone: string) {
  await page.goto("/login");
  await page.getByTestId("login-name").fill(name);
  await page.getByTestId("login-phone").fill(phone);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("consent-agree")).toBeVisible();
  await page.getByTestId("consent-agree").click();
  await expect(page.getByTestId("room-option").first()).toBeVisible();
}

test("两名被试在两个浏览器上下文登录报名，管理员可查看", async ({ browser, request, baseURL }) => {
  if (!baseURL) throw new Error("baseURL missing");
  await setup(baseURL, request);

  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  const pageOne = await contexts[0].newPage();
  const pageTwo = await contexts[1].newPage();
  await loginAndConsent(pageOne, "节点甲", "13300000001");
  await loginAndConsent(pageTwo, "节点乙", "13300000002");

  await pageOne.getByTestId("room-option").first().click();
  await pageOne.getByTestId("book-room").click();
  await expect(pageOne.getByTestId("current-booking")).toBeVisible();
  await pageTwo.getByTestId("room-option").first().click();
  await pageTwo.getByTestId("book-room").click();
  await expect(pageTwo.getByTestId("current-booking")).toContainText("2/2");

  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  await adminPage.goto("/admin/login");
  await adminPage.getByTestId("admin-login-username").fill("admin");
  await adminPage.getByTestId("admin-login-password").fill(ADMIN_PASSWORD);
  await adminPage.getByTestId("admin-login-submit").click();
  await expect(adminPage).toHaveURL(/\/admin$/);
  await expect(adminPage.locator("h1.admin-page-title")).toContainText("仪表盘");
  await adminPage.getByTestId("nav-participants").click();
  await expect(adminPage.locator("table")).toContainText("节点甲");

  await contexts[0].close();
  await contexts[1].close();
  await adminContext.close();
});
