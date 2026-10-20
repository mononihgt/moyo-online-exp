export interface PlatformBaseOptions {
  allowOverride: boolean;
  overrideBase: string | null;
  allowedOrigins: string[];
  configuredBase: string | null;
  fallbackBase: string;
  resolutionBase: string;
}

export function parseAllowedOrigins(raw: string | undefined): string[] {
  if (raw === undefined || raw.trim() === "") return [];
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter((value) => value !== "")
    .map((value) => {
      let url: URL;
      try {
        url = new URL(value);
      } catch {
        throw new Error("问卷配置异常，请联系实验工作人员。");
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") {
        throw new Error("问卷配置异常，请联系实验工作人员。");
      }
      return url.origin;
    });
}

export function selectPlatformBase(options: PlatformBaseOptions): string {
  const useOverride =
    options.allowOverride &&
    options.overrideBase !== null &&
    options.overrideBase.trim() !== "";
  const raw = useOverride
    ? (options.overrideBase as string)
    : options.configuredBase ?? options.fallbackBase;
  let url: URL;
  try {
    url = new URL(raw, options.resolutionBase);
  } catch {
    throw new Error("问卷配置异常，请联系实验工作人员。");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("问卷配置异常，请联系实验工作人员。");
  }
  if (
    useOverride &&
    options.allowedOrigins.length > 0 &&
    !options.allowedOrigins.includes(url.origin)
  ) {
    throw new Error("问卷配置异常，请联系实验工作人员。");
  }
  return url.href.replace(/\/+$/, "");
}
