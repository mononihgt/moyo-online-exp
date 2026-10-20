import type { QuestionnaireContext } from "../shared/types";

const REQUEST_TIMEOUT_MS = 20000;

export class PlatformError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "PlatformError";
    this.status = status;
  }
}

export interface QuestionnaireCompletePayload {
  token: string;
  answers: Record<string, unknown>;
  jatosWorkerId: string | null;
  jatosStudyResultId: string;
  jatosComponentResultId: string;
}

export interface QuestionnaireCompleteResult {
  saved: boolean;
  canonical?: boolean;
  redirectUrl?: string;
}

export function fetchQuestionnaireContext(base: string, token: string): Promise<QuestionnaireContext> {
  return requestJson<QuestionnaireContext>(
    base,
    `/api/jatos/questionnaire?token=${encodeURIComponent(token)}`,
    { method: "GET", cache: "no-store" },
  );
}

export function saveQuestionnaireDraft(
  base: string,
  token: string,
  answers: Record<string, unknown>,
): Promise<{ saved: boolean; updatedAt?: string }> {
  return requestJson(
    base,
    "/api/jatos/questionnaire/draft",
    {
      method: "POST",
      body: JSON.stringify({ token, answers }),
    },
  );
}

export function completeQuestionnaire(
  base: string,
  payload: QuestionnaireCompletePayload,
): Promise<QuestionnaireCompleteResult> {
  return requestJson(
    base,
    "/api/jatos/questionnaire/complete",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

async function requestJson<T>(base: string, path: string, init: RequestInit): Promise<T> {
  const url = `${base}${path}`;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined && init.body !== null) {
    headers.set("Content-Type", "application/json");
  }
  const sameOrigin = new URL(url, window.location.href).origin === window.location.origin;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers,
      signal: controller.signal,
      credentials: sameOrigin ? "include" : "omit",
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new PlatformError("平台服务器响应超时，请重试。", 0);
    }
    throw new PlatformError("无法连接平台服务器，请检查网络后重试。", 0);
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    throw new PlatformError(await readErrorDetail(response), response.status);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new PlatformError("平台返回了无法解析的数据，请重试。", response.status);
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      const payload: unknown = await response.json();
      const detail = extractDetail(payload);
      if (detail !== "") return detail;
    } catch {
      // 响应不是合法 JSON 时使用状态码说明。
    }
  }
  return "平台暂时无法处理请求，请重试。";
}

function extractDetail(payload: unknown): string {
  if (typeof payload !== "object" || payload === null) return "";
  const record = payload as Record<string, unknown>;
  if (typeof record.detail === "string" && record.detail.trim() !== "") return record.detail;
  if (Array.isArray(record.detail)) return "请求内容未通过平台校验。";
  if (typeof record.message === "string" && record.message.trim() !== "") return record.message;
  return "";
}
