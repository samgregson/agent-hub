import { defineConfig } from "@playwright/test";

const port = process.env.AGENT_HUB_E2E_PORT ?? "3001";
const baseURL =
  process.env.AGENT_HUB_E2E_BASE_URL ?? `http://localhost:${port}`;

export default defineConfig({
  testDir: "./src",
  testMatch: "**/*.e2e.spec.ts",
  workers: process.env.AGENT_HUB_FOUNDATION_E2E === "1" ? 1 : undefined,
  use: {
    baseURL,
    browserName: "chromium",
    headless: true,
  },
  webServer:
    process.env.AGENT_HUB_E2E_EXTERNAL === "1"
      ? undefined
      : {
          command: `npm run dev -- --port ${port}`,
          env: {
            AGENT_HUB_API_URL:
              process.env.AGENT_HUB_E2E_API_URL ?? "http://127.0.0.1:8000",
            NEXT_TELEMETRY_DISABLED: "1",
          },
          reuseExistingServer: !process.env.CI,
          url: baseURL,
        },
});
