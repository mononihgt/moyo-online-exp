import { expect, test } from "@playwright/test";

import {
  parseAllowedOrigins,
  selectPlatformBase,
} from "../src/questionnaire/platformBase";

const base = {
  allowOverride: false,
  overrideBase: "https://attacker.example",
  allowedOrigins: [],
  configuredBase: "http://127.0.0.1:8000",
  fallbackBase: "http://127.0.0.1:9000",
  resolutionBase: "http://127.0.0.1:9000/publix/study",
};

test("生产构建忽略 base 查询参数", () => {
  expect(selectPlatformBase(base)).toBe("http://127.0.0.1:8000");
});

test("未配置平台地址时使用当前来源", () => {
  expect(
    selectPlatformBase({ ...base, configuredBase: null }),
  ).toBe("http://127.0.0.1:9000");
});

test("显式允许覆盖时使用 base", () => {
  expect(
    selectPlatformBase({ ...base, allowOverride: true }),
  ).toBe("https://attacker.example");
});

test("白名单拒绝未列出的覆盖来源", () => {
  expect(() =>
    selectPlatformBase({
      ...base,
      allowOverride: true,
      allowedOrigins: ["http://127.0.0.1:8000"],
    }),
  ).toThrow("平台地址不在允许列表");
});

test("白名单允许列出的覆盖来源", () => {
  expect(
    selectPlatformBase({
      ...base,
      allowOverride: true,
      allowedOrigins: ["https://attacker.example"],
    }),
  ).toBe("https://attacker.example");
});

test("拒绝非 HTTP 协议", () => {
  expect(() =>
    selectPlatformBase({
      ...base,
      allowOverride: true,
      overrideBase: "javascript:alert(1)",
    }),
  ).toThrow("平台地址配置无效");
});

test("解析来源白名单并拒绝非法配置", () => {
  expect(
    parseAllowedOrigins("https://a.example, http://127.0.0.1:8000/"),
  ).toEqual(["https://a.example", "http://127.0.0.1:8000"]);
  expect(() => parseAllowedOrigins("not a url")).toThrow(
    "平台地址白名单配置无效",
  );
});
