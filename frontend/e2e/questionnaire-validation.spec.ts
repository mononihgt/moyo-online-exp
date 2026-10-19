import { expect, test } from "@playwright/test";

import { validateAnswerValue } from "../src/questionnaire/validation";
import type { QuestionnaireQuestion } from "../src/shared/types";

const ID_CARD_QUESTION: QuestionnaireQuestion = {
  id: "identity_document",
  type: "identity_document",
  label: "身份证件",
  required: true,
};

const BIRTH_DATE_MESSAGE = "身份证号码中的出生日期无效。";

function idCardWithBirth(birth: string): { documentType: "id_card"; number: string } {
  return { documentType: "id_card", number: `110105${birth}002X` };
}

test("身份证出生日期校验与服务端一致", () => {
  expect(
    validateAnswerValue(ID_CARD_QUESTION, {
      documentType: "id_card",
      number: "11010519491231002X",
    }),
  ).toBeNull();

  for (const birth of ["20991231", "18991231", "19000230"]) {
    expect(
      validateAnswerValue(ID_CARD_QUESTION, idCardWithBirth(birth)),
      `出生日期 ${birth}`,
    ).toBe(BIRTH_DATE_MESSAGE);
  }
});
