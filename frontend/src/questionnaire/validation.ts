import { formatShanghaiDate } from "../shared/format";
import type { IdentityDocumentAnswer, QuestionnaireQuestion } from "../shared/types";

const ALIPAY_PHONE_PATTERN = /^1[3-9]\d{9}$/;
const ID_CARD_PATTERN = /^\d{17}[\dX]$/;
const PASSPORT_PATTERN = /^[A-Za-z0-9]{5,20}$/;

const ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
const ID_CARD_CHECK_CODES = "10X98765432";

const REAL_NAME_MESSAGE = "请填写真实姓名。";
const ALIPAY_PHONE_MESSAGE = "请输入有效的中国大陆手机号。";
const IDENTITY_DOCUMENT_MESSAGE = "请选择证件类型并填写证件号码。";
const ID_CARD_MESSAGE = "请输入有效的 18 位身份证号码。";
const ID_CARD_BIRTH_MESSAGE = "身份证号码中的出生日期无效。";
const PASSPORT_MESSAGE = "请输入 5 到 20 位字母或数字的护照号码。";

export function isIdentityDocumentAnswer(value: unknown): value is IdentityDocumentAnswer {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (record.documentType !== "id_card" && record.documentType !== "passport") return false;
  return typeof record.number === "string";
}

export function isValidAlipayPhone(value: string): boolean {
  return ALIPAY_PHONE_PATTERN.test(value.trim());
}

export function isValidPassportNumber(value: string): boolean {
  return PASSPORT_PATTERN.test(value.trim());
}

export function isValidIdCardNumber(value: string): boolean {
  const normalized = value.trim().toUpperCase();
  if (!ID_CARD_PATTERN.test(normalized)) return false;
  if (!isValidBirthDate(normalized.slice(6, 14))) return false;
  let weightedSum = 0;
  for (let index = 0; index < 17; index += 1) {
    weightedSum += Number(normalized[index]) * ID_CARD_WEIGHTS[index];
  }
  return ID_CARD_CHECK_CODES[weightedSum % 11] === normalized[17];
}

export function normalizeAnswerValue(question: QuestionnaireQuestion, value: unknown): unknown {
  switch (question.type) {
    case "real_name":
    case "alipay_phone":
      return typeof value === "string" ? value.trim() : value;
    case "identity_document": {
      if (!isIdentityDocumentAnswer(value)) return value;
      const number = value.number.trim();
      return {
        documentType: value.documentType,
        number: value.documentType === "id_card" ? number.toUpperCase() : number,
      };
    }
    default:
      return value;
  }
}

export function validateAnswerValue(question: QuestionnaireQuestion, value: unknown): string | null {
  switch (question.type) {
    case "real_name": {
      if (value === undefined || value === null) return null;
      if (typeof value !== "string" || value.trim() === "") return REAL_NAME_MESSAGE;
      return null;
    }
    case "alipay_phone": {
      if (value === undefined || value === null || value === "") return null;
      if (typeof value !== "string" || value.trim() === "") return ALIPAY_PHONE_MESSAGE;
      return isValidAlipayPhone(value) ? null : ALIPAY_PHONE_MESSAGE;
    }
    case "identity_document": {
      if (value === undefined || value === null) return null;
      if (!isIdentityDocumentAnswer(value)) return IDENTITY_DOCUMENT_MESSAGE;
      const number = value.number.trim();
      if (number === "") return null;
      if (value.documentType === "id_card") {
        if (!/^\d{17}[\dXx]$/.test(number)) return ID_CARD_MESSAGE;
        if (!isValidBirthDate(number.slice(6, 14))) return ID_CARD_BIRTH_MESSAGE;
        return isValidIdCardNumber(number) ? null : ID_CARD_MESSAGE;
      }
      return isValidPassportNumber(number) ? null : PASSPORT_MESSAGE;
    }
    default:
      return null;
  }
}

function isValidBirthDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  if (year < 1900) return false;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return false;
  }
  return value <= formatShanghaiDate(new Date(), "");
}
