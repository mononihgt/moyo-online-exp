import { expect, test } from "@playwright/test";

import { adminApi, adminLoginPage, prepareWorld } from "./support";

interface MapGroupDetail {
  id: string;
  versionId: string;
  mode: "both" | "ab";
  rows: number;
  cols: number;
  spawns: { A: number; B: number };
  practiceTrials: number;
  formalTrials: number;
  practiceTurnCap: number;
  practiceTurnSeconds: number;
  formalTurnCap: number;
  formalTurnSeconds: number;
  restSeconds: number;
  randomizeFormal: boolean;
  payment: {
    basePayCents: number;
    performanceRateCents: number;
    performanceFloorCents: number;
    performanceCapCents: number;
    showupPayCents: number;
  };
  profile: { versionId: string };
  maps: {
    slot: "A" | "B" | "Both";
    description: string;
    factorLevel: string;
    cells: (string | null)[];
    colors: (string | null)[];
  }[];
}

interface QuestionnaireDetail {
  id: string;
  name: string;
  schema: Record<string, unknown>;
}

test("Room 编辑配置保留已归档的材料版本", async ({
  browser,
  request,
  baseURL,
}) => {
  test.setTimeout(180_000);
  if (!baseURL) throw new Error("baseURL missing");

  const world = await prepareWorld(request, baseURL, {
    entries: [
      { name: "归档选项甲", phone: "13100000011" },
      { name: "归档选项乙", phone: "13100000012" },
    ],
    startsInSeconds: 3600,
  });

  const v1MapGroup = (
    await adminApi<{ mapGroup: MapGroupDetail }>(
      request,
      baseURL,
      "GET",
      `/admin/api/map-groups/${world.mapGroupVersionId}`,
    )
  ).mapGroup;
  const createdMapGroup = await adminApi<{ mapGroup: { id: string } }>(
    request,
    baseURL,
    "POST",
    "/admin/api/map-groups",
    {
      mode: v1MapGroup.mode,
      rows: v1MapGroup.rows,
      cols: v1MapGroup.cols,
      spawns: v1MapGroup.spawns,
      troopProfileVersionId: v1MapGroup.profile.versionId,
      practiceTrials: v1MapGroup.practiceTrials,
      formalTrials: v1MapGroup.formalTrials,
      practiceTurnCap: v1MapGroup.practiceTurnCap,
      practiceTurnSeconds: v1MapGroup.practiceTurnSeconds,
      formalTurnCap: v1MapGroup.formalTurnCap,
      formalTurnSeconds: v1MapGroup.formalTurnSeconds,
      restSeconds: v1MapGroup.restSeconds,
      randomizeFormal: v1MapGroup.randomizeFormal,
      payment: v1MapGroup.payment,
      maps: v1MapGroup.maps.map((map) => ({
        slot: map.slot,
        description: map.description,
        factorLevel: map.factorLevel,
        cells: map.cells,
      })),
    },
  );
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/map-groups/${createdMapGroup.mapGroup.id}/publish`,
  );

  for (const role of [1, 2] as const) {
    const createdInstruction = await adminApi<{ instruction: { id: string } }>(
      request,
      baseURL,
      "POST",
      "/admin/api/instructions",
      {
        mapGroupVersionId: createdMapGroup.mapGroup.id,
        role,
        markdown: `# 玩家 ${role === 1 ? "A" : "B"}\n\n新版本指导语。`,
        minReadingSeconds: 0,
      },
    );
    await adminApi(
      request,
      baseURL,
      "POST",
      `/admin/api/instructions/${createdInstruction.instruction.id}/publish`,
    );
  }

  const v1Questionnaire = (
    await adminApi<{ questionnaire: QuestionnaireDetail }>(
      request,
      baseURL,
      "GET",
      `/admin/api/questionnaires/${world.questionnaireVersionId}`,
    )
  ).questionnaire;
  const createdQuestionnaire = await adminApi<{
    questionnaire: { id: string };
  }>(request, baseURL, "POST", "/admin/api/questionnaires", {
    name: v1Questionnaire.name,
    schemaJson: v1Questionnaire.schema,
  });
  await adminApi(
    request,
    baseURL,
    "POST",
    `/admin/api/questionnaires/${createdQuestionnaire.questionnaire.id}/publish`,
  );

  const context = await browser.newContext();
  const page = await context.newPage();
  await adminLoginPage(page);
  await page.goto(`${baseURL}/admin/rooms/${world.roomId}`);
  await expect(page.getByTestId("room-edit")).toBeVisible({ timeout: 20000 });
  await page.getByTestId("room-edit").click();

  const archivedSelections = [
    { testId: "room-form-map-group", value: world.mapGroupVersionId },
    { testId: "room-form-instruction-p1", value: world.instructionP1Id },
    { testId: "room-form-instruction-p2", value: world.instructionP2Id },
    { testId: "room-form-questionnaire", value: world.questionnaireVersionId },
  ];
  for (const selection of archivedSelections) {
    const select = page.getByTestId(selection.testId);
    await expect(select).toHaveValue(selection.value);
    await expect(
      select.locator(`option[value="${selection.value}"]`),
    ).toContainText("（已归档）");
  }

  await page.getByTestId("room-edit-save").click();
  await expect(
    page
      .getByRole("status")
      .getByText("房间配置已保存", { exact: true }),
  ).toBeVisible();
  await context.close();
});
