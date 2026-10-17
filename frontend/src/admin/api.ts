import { ApiError, api, download } from "../shared/api";

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function notifyUnauthorized(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) {
    unauthorizedHandler?.();
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    return await api<T>(`/admin/api${path}`, options);
  } catch (error) {
    notifyUnauthorized(error);
    throw error;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "请求失败";
}

export const adminApi = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  },
  patch<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  },
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: "DELETE" });
  },
  upload<T>(path: string, formData: FormData): Promise<T> {
    return request<T>(path, { method: "POST", body: formData });
  },
};

export async function adminDownload(path: string, filename: string): Promise<void> {
  try {
    await download(`/admin/api${path}`, filename);
  } catch (error) {
    notifyUnauthorized(error);
    throw error;
  }
}

export function imageUploadForm(file: File, kind: string): FormData {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return form;
}

export function fileUploadForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}
