import { expect, test } from "@playwright/test";

import type { Browser } from "@playwright/test";

import {
  adminLoginPage,
  bookRoom,
  loginParticipant,
  prepareConsentBase,
  prepareWorld,
} from "./support";

async function createAccount(browser: Browser, name: string, phone: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
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
  await context.close();
}

test("管理端录入身份并创建手工补偿", async ({ browser, request, baseURL }) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  const entries = [
    { name: "手工补偿甲", phone: "13700000071" },
    { name: "手工补偿乙", phone: "13700000072" },
  ];
  const world = await prepareWorld(request, baseURL, {
    entries,
    startsInSeconds: 8,
    waitWindowSeconds: 2,
    troopRows: [
      { soldiersA: 7, soldiersB: 7 },
      { soldiersA: 8, soldiersB: 9 },
    ],
    map: {
      rows: 2,
      cols: 2,
      formalTrials: 1,
      practiceTurnCap: 2,
      practiceTurnSeconds: 45,
      formalTurnCap: 2,
      formalTurnSeconds: 60,
      restSeconds: 2,
      randomizeFormal: false,
    },
    roomLabel: "手工补偿房间",
  });

  const participantContext = await browser.newContext();
  const participantPage = await participantContext.newPage();
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  try {
    await loginParticipant(participantPage, entries[0].name, entries[0].phone);
    await bookRoom(participantPage, world.roomId);
    await adminLoginPage(adminPage);
    await expect
      .poll(
        async () => {
          const response = await adminPage.request.get(
            `${baseURL}/admin/api/rooms/${world.roomId}`,
          );
          const payload = await response.json();
          return payload.room?.status;
        },
        { timeout: 30_000 },
      )
      .toBe("archived");
    await adminPage.goto(`/admin/rooms/${world.roomId}`);
    await adminPage.getByTestId("room-tab-bookings").click();
    await adminPage.getByRole("button", { name: "身份信息" }).first().click();
    await adminPage.getByLabel("真实姓名").fill("测试补偿身份");
    await adminPage.getByLabel("支付宝手机号").fill("13900009991");
    await adminPage.getByLabel("证件号码").fill("11010519491231002X");
    await adminPage.getByTestId("identity-reason").fill("参与者无法自行填写");
    await adminPage.getByTestId("identity-save").click();
    await expect(adminPage.getByText("身份信息已保存")).toBeVisible({
      timeout: 15_000,
    });

    await adminPage.getByRole("button", { name: "身份信息" }).first().click();
    await expect(adminPage.getByLabel("真实姓名")).toHaveValue("测试补偿身份");
    await expect(adminPage.getByLabel("支付宝手机号")).toHaveValue(
      "13900009991",
    );
    await adminPage.getByRole("button", { name: "取消" }).click();

    await adminPage.getByTestId("room-tab-payments").click();
    await adminPage.getByTestId("payment-manual-open").click();
    await adminPage.getByTestId("payment-manual-booking").selectOption({
      index: 1,
    });
    await expect(adminPage.getByText("已有身份记录")).toBeVisible({
      timeout: 15_000,
    });
    await adminPage.getByTestId("payment-manual-amount").fill("12.00");
    await adminPage
      .getByTestId("payment-manual-note")
      .fill("等待不足两人的场次补偿");
    await adminPage.getByTestId("payment-manual-submit").click();
    await adminPage
      .getByRole("button", { name: "创建付款" })
      .last()
      .click();
    await expect(adminPage.getByText("手工付款已创建")).toBeVisible({
      timeout: 15_000,
    });
    await expect(adminPage.getByText("手工补偿", { exact: true })).toBeVisible();
    await expect(
      adminPage.locator(".admin-total", { hasText: "¥12.00" }),
    ).toBeVisible();

    await participantPage.goto(`/complete?room=${world.roomId}`);
    await expect(participantPage.getByTestId("reward-info")).toBeVisible({
      timeout: 20_000,
    });
    await expect(participantPage.getByText("补偿金额")).toBeVisible();
    await expect(participantPage.getByTestId("complete-total")).toHaveText(
      "¥12.00",
    );
    await expect(
      participantPage.getByText("本场补偿由实验工作人员发放", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(participantPage.getByTestId("rebook")).toHaveCount(0);
  } finally {
    await participantContext.close();
    await adminContext.close();
  }
});

test("管理端可以合并重复账号并在名单中看到已合并记录", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(120_000);
  if (!baseURL) throw new Error("baseURL missing");
  await prepareConsentBase(request, baseURL);
  const source = { name: "合并界面来源", phone: "13700000081" };
  const target = { name: "合并界面目标", phone: "13700000082" };
  await createAccount(browser, source.name, source.phone);
  await createAccount(browser, target.name, target.phone);
  const adminContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  try {
    await adminLoginPage(adminPage);
    await adminPage.goto("/admin/participants");
    await adminPage.getByTestId("participants-merge-open").click();
    await adminPage
      .getByTestId("participants-merge-source-query")
      .fill(source.phone);
    await adminPage.getByRole("button", { name: "查找" }).nth(0).click();
    await adminPage
      .getByRole("button", { name: new RegExp(source.name) })
      .first()
      .click();
    await adminPage
      .getByTestId("participants-merge-target-query")
      .fill(target.phone);
    await adminPage.getByRole("button", { name: "查找" }).nth(1).click();
    await adminPage
      .getByRole("button", { name: new RegExp(target.name) })
      .first()
      .click();
    await adminPage
      .getByTestId("participants-merge-reason")
      .fill("手机号输错产生重复账号");
    await adminPage.getByTestId("participants-merge-submit").click();
    await adminPage.getByRole("button", { name: "确认合并" }).last().click();
    await expect(adminPage.getByText("账号已合并")).toBeVisible({
      timeout: 15000,
    });
    await adminPage.getByTestId("participants-search").fill(source.phone);
    await adminPage.getByRole("button", { name: "搜索" }).click();
    const row = adminPage.getByRole("row", { name: new RegExp(source.name) });
    await expect(row).toContainText("已合并");
  } finally {
    await adminContext.close();
  }
});
