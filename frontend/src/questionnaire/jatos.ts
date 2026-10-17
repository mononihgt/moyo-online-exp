export interface JatosApi {
  version?: string;
  workerId?: string | number;
  studyResultId?: string | number;
  componentResultId?: string | number;
  urlQueryParameters?: Record<string, unknown> | null;
  onLoad?: (callback: () => void) => void;
  submitResultData?: (
    resultData: Record<string, unknown> | string,
    onSuccess?: () => void,
    onError?: (error?: unknown) => void,
  ) => unknown;
  endStudyAndRedirect?: (url: string) => void;
}

declare global {
  interface Window {
    jatos?: JatosApi;
  }
}

export interface JatosResultIds {
  workerId: string | null;
  studyResultId: string;
  componentResultId: string;
}

const JATOS_INIT_TIMEOUT_MS = 15000;

export function getJatos(): JatosApi | undefined {
  return window.jatos;
}

export function waitForJatos(jatos: JatosApi): Promise<JatosApi> {
  if (typeof jatos.onLoad !== "function") {
    return Promise.reject(new Error("JATOS 未能初始化，请重新打开问卷。"));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error("JATOS 初始化超时，请刷新页面或联系主试。"));
    }, JATOS_INIT_TIMEOUT_MS);
    try {
      jatos.onLoad!(() => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        resolve(jatos);
      });
    } catch (error) {
      settled = true;
      window.clearTimeout(timer);
      reject(error instanceof Error ? error : new Error("JATOS 未能初始化，请重新打开问卷。"));
    }
  });
}

export function readQueryParam(jatos: JatosApi, name: string): string | null {
  const fromJatos = jatos.urlQueryParameters?.[name];
  if (typeof fromJatos === "string" && fromJatos !== "") return fromJatos;
  if (typeof fromJatos === "number") return String(fromJatos);
  const fromLocation = new URLSearchParams(window.location.search).get(name);
  return fromLocation && fromLocation !== "" ? fromLocation : null;
}

export function resolvePlatformBase(jatos: JatosApi): string {
  const envBase = import.meta.env.VITE_PLATFORM_BASE_URL as string | undefined;
  const raw = readQueryParam(jatos, "base") ?? (envBase && envBase.trim() ? envBase : window.location.origin);
  let url: URL;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    throw new Error("平台地址配置无效，请联系主试。");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("平台地址配置无效，请联系主试。");
  }
  return url.href.replace(/\/+$/, "");
}

export function readJatosResultIds(jatos: JatosApi): JatosResultIds | null {
  const studyResultId = toId(jatos.studyResultId);
  const componentResultId = toId(jatos.componentResultId);
  if (!studyResultId || !componentResultId) return null;
  return {
    workerId: toId(jatos.workerId),
    studyResultId,
    componentResultId,
  };
}

export function submitJatosResultData(jatos: JatosApi, resultData: Record<string, unknown>): Promise<void> {
  if (typeof jatos.submitResultData !== "function") {
    return Promise.reject(new Error("JATOS 提交接口不可用，请重新打开问卷。"));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const succeed = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      reject(new Error(describeJatosError(error)));
    };
    let outcome: unknown;
    try {
      outcome = jatos.submitResultData!(
        resultData,
        () => succeed(),
        (error?: unknown) => fail(error),
      );
    } catch (error) {
      fail(error);
      return;
    }
    if (isThenable(outcome)) {
      outcome.then(
        () => succeed(),
        (error) => fail(error),
      );
    }
  });
}

export function finishJatosAndRedirect(jatos: JatosApi, url: string): void {
  if (typeof jatos.endStudyAndRedirect === "function") {
    try {
      jatos.endStudyAndRedirect(url);
      return;
    } catch {
      // JATOS 收尾失败时仍返回平台，答案已经保存。
    }
  }
  window.location.href = url;
}

function toId(value: unknown): string | null {
  if (typeof value === "string") return value !== "" ? value : null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function isThenable(value: unknown): value is PromiseLike<unknown> {
  return (
    (typeof value === "object" || typeof value === "function") &&
    value !== null &&
    typeof (value as { then?: unknown }).then === "function"
  );
}

function describeJatosError(error: unknown): string {
  if (typeof error === "string" && error.trim() !== "") return error;
  if (error instanceof Error && error.message !== "") return error.message;
  return "JATOS 未能保存问卷结果，请重试。";
}
