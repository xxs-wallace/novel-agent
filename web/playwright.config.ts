import { defineConfig, devices } from "@playwright/test";

const isCI = Boolean(process.env.CI);
const apiPort = Number(process.env.NOVEL_AGENT_WEB_E2E_API_PORT ?? 18080);
const webPort = Number(process.env.NOVEL_AGENT_WEB_E2E_WEB_PORT ?? 15173);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30 * 60_000,
  expect: {
    timeout: 30_000
  },
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "on-first-retry",
    video: "retain-on-failure"
  },
  reporter: [["list"], ["html", { open: "never" }]],
  webServer: [
    {
      command:
        `bash -lc 'set -a; source ~/.bash_profile >/dev/null 2>&1 || true; set +a; unset NOVEL_AGENT_WEB_JOB_MODE; cd .. && PYTHON_BIN="\${PYTHON_BIN:-.venv/bin/python}"; if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN=python3; fi; "$PYTHON_BIN" -m uvicorn novel_agent.app.web.main:app --host 127.0.0.1 --port ${apiPort}'`,
      url: `http://127.0.0.1:${apiPort}/api/tasks`,
      reuseExistingServer: false,
      timeout: 30_000
    },
    {
      command: `VITE_API_PROXY_TARGET=http://127.0.0.1:${apiPort} npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
      timeout: 30_000
    }
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
