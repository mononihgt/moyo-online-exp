import type {
  ProtectedQuestionType,
  QuestionType,
  QuestionnaireQuestion,
  QuestionnaireSchema,
} from "../shared/types";
import { isIdentityDocumentAnswer, normalizeAnswerValue, validateAnswerValue } from "./validation";

const PROTECTED_QUESTION_TYPES: ReadonlySet<QuestionType> = new Set<QuestionType>([
  "real_name",
  "alipay_phone",
  "identity_document",
]);

const REQUIRED_MESSAGES: Record<QuestionType, string> = {
  single_choice: "请选择一个选项。",
  multiple_choice: "请至少选择一个选项。",
  likert: "请选择一个评分。",
  text: "请填写此题。",
  short_text: "请填写此题。",
  number: "请填写此题。",
  real_name: "请填写真实姓名。",
  alipay_phone: "请填写支付宝手机号。",
  identity_document: "请选择证件类型并填写证件号码。",
};

export function isProtectedQuestionType(type: QuestionType): type is ProtectedQuestionType {
  return PROTECTED_QUESTION_TYPES.has(type);
}

export function flattenQuestions(schema: QuestionnaireSchema): QuestionnaireQuestion[] {
  return schema.pages.flatMap((page) => page.questions);
}

export function hasAnswer(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.length > 0;
  if (isIdentityDocumentAnswer(value)) return value.number.trim() !== "";
  return false;
}

export function isQuestionRequired(question: QuestionnaireQuestion): boolean {
  return question.required || isProtectedQuestionType(question.type);
}

export function countAnswered(
  questions: QuestionnaireQuestion[],
  answers: Record<string, unknown>,
): number {
  return questions.reduce((count, question) => (hasAnswer(answers[question.id]) ? count + 1 : count), 0);
}

export function sanitizeAnswers(
  schema: QuestionnaireSchema,
  raw: Record<string, unknown> | null | undefined,
  protectedQuestionIds: readonly string[] = [],
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (!raw) return result;
  const questions = flattenQuestions(schema);
  const knownIds = new Set(questions.map((question) => question.id));
  const excludedIds = protectedIds(questions, protectedQuestionIds);
  for (const [key, value] of Object.entries(raw)) {
    if (!knownIds.has(key) || excludedIds.has(key)) continue;
    result[key] = value;
  }
  return result;
}

export function omitProtectedAnswers(
  questions: QuestionnaireQuestion[],
  answers: Record<string, unknown>,
  protectedQuestionIds: readonly string[] = [],
): Record<string, unknown> {
  const excludedIds = protectedIds(questions, protectedQuestionIds);
  const result: Record<string, unknown> = {};
  for (const question of questions) {
    if (excludedIds.has(question.id)) continue;
    if (!(question.id in answers)) continue;
    result[question.id] = answers[question.id];
  }
  return result;
}

export function normalizeAnswers(
  questions: QuestionnaireQuestion[],
  answers: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...answers };
  for (const question of questions) {
    if (!(question.id in result)) continue;
    result[question.id] = normalizeAnswerValue(question, result[question.id]);
  }
  return result;
}

export function validateAnswers(
  questions: QuestionnaireQuestion[],
  answers: Record<string, unknown>,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const question of questions) {
    const value = answers[question.id];
    const formatError = validateAnswerValue(question, value);
    if (formatError !== null) {
      errors[question.id] = formatError;
      continue;
    }
    if (question.type === "number" && typeof value === "number" && Number.isFinite(value)) {
      if (question.min !== undefined && value < question.min) {
        errors[question.id] = numberRangeMessage(question);
        continue;
      }
      if (question.max !== undefined && value > question.max) {
        errors[question.id] = numberRangeMessage(question);
        continue;
      }
    }
    if (!hasAnswer(value) && isQuestionRequired(question)) {
      errors[question.id] = REQUIRED_MESSAGES[question.type];
    }
  }
  return errors;
}

function protectedIds(
  questions: QuestionnaireQuestion[],
  protectedQuestionIds: readonly string[],
): Set<string> {
  const ids = new Set(protectedQuestionIds);
  for (const question of questions) {
    if (isProtectedQuestionType(question.type)) ids.add(question.id);
  }
  return ids;
}

function numberRangeMessage(question: QuestionnaireQuestion): string {
  const { min, max } = question;
  if (min !== undefined && max !== undefined) return `请输入 ${min} 到 ${max} 之间的数字。`;
  if (min !== undefined) return `请输入不小于 ${min} 的数字。`;
  if (max !== undefined) return `请输入不大于 ${max} 的数字。`;
  return "请输入有效数字。";
}
