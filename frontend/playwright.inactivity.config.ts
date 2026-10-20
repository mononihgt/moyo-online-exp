import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const configDir = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: "./e2e",
  testMatch: /inactivity\.e2e\.ts/,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8050",
    headless: true,
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    launchOptions: {
      executablePath:
        process.env.CHROME_PATH ??
        (process.platform === "darwin"
          ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
          : "/usr/bin/google-chrome"),
    },
  },
  webServer: {
    command: `bash ${resolve(configDir, "../tests/e2e/start_node_e2e_server.sh")}`,
    url: "http://127.0.0.1:8050/healthz",
    timeout: 60_000,
    reuseExistingServer: false,
    env: {
      INACTIVITY_TIMEOUT_SECONDS: "20",
      INACTIVITY_WARNING_SECONDS: "10",
    },
  },
});
