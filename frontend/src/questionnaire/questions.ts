import type { QuestionType, QuestionnaireQuestion, QuestionnaireSchema } from "../shared/types";

const REQUIRED_MESSAGES: Record<QuestionType, string> = {
  single_choice: "请选择一个选项。",
  multiple_choice: "请至少选择一个选项。",
  likert: "请选择一个评分。",
  text: "请填写此题。",
  number: "请填写此题。",
};

export function flattenQuestions(schema: QuestionnaireSchema): QuestionnaireQuestion[] {
  return schema.pages.flatMap((page) => page.questions);
}

export function hasAnswer(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.length > 0;
  return false;
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
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (!raw) return result;
  const knownIds = new Set(flattenQuestions(schema).map((question) => question.id));
  for (const [key, value] of Object.entries(raw)) {
    if (knownIds.has(key)) result[key] = value;
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
    if (hasAnswer(value)) continue;
    if (question.required) errors[question.id] = REQUIRED_MESSAGES[question.type];
  }
  return errors;
}

function numberRangeMessage(question: QuestionnaireQuestion): string {
  const { min, max } = question;
  if (min !== undefined && max !== undefined) return `请输入 ${min} 到 ${max} 之间的数字。`;
  if (min !== undefined) return `请输入不小于 ${min} 的数字。`;
  if (max !== undefined) return `请输入不大于 ${max} 的数字。`;
  return "请输入有效数字。";
}
