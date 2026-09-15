import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./src",
  testMatch: "**/*.e2e.spec.ts",
  use: {
    baseURL: "http://localhost:3001",
    browserName: "chromium",
    channel: "chrome",
    headless: true,
  },
  webServer: {
    command: "npm run dev -- --port 3001",
    env: {
      AGENT_HUB_API_URL: "http://127.0.0.1:8000",
    },
    reuseExistingServer: !process.env.CI,
    url: "http://localhost:3001",
  },
});
