import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:8010', trace: 'retain-on-failure' },
  webServer: {
    command: 'cd .. && DATABASE_URL=sqlite:////tmp/shuttleup-e2e.db APP_SECRET=e2e-secret-at-least-sixteen SESSION_COOKIE_SECURE=false .venv/bin/uvicorn shuttleup.app:app --port 8010',
    url: 'http://127.0.0.1:8010/healthz',
    reuseExistingServer: false,
  },
  projects: [
    { name: 'mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } } },
  ],
})
