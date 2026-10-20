import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

import { E2E_DIR, SEED_FILE } from './e2e/seed';

/* Smoke test: a production build of the frontend against a real backend on a
 * freshly migrated, seeded SQLite database (backend/scripts/seed_e2e.py).
 * Ports 8100/3100 stay clear of a local dev setup on 8000/3000. */
const BACKEND_PORT = 8100;
const FRONTEND_PORT = 3100;
const backendUrl = `http://localhost:${BACKEND_PORT}`;
const workDir = E2E_DIR;
const python = process.env.PYTHON ?? 'python3';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'retain-on-failure'
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      name: 'backend',
      cwd: path.join(__dirname, '..', 'backend'),
      command: [
        `rm -rf "${workDir}" && mkdir -p "${workDir}"`,
        `${python} -m alembic upgrade head`,
        `${python} scripts/seed_e2e.py "${SEED_FILE}"`,
        `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`
      ].join(' && '),
      url: `${backendUrl}/api/health`,
      env: {
        DATABASE_URL: `sqlite:///${path.join(workDir, 'e2e.sqlite3')}`,
        DATA_DIR: path.join(workDir, 'data'),
        STORAGE_BACKEND: 'local',
        INSTRUCTOR_TOKEN: '',
        FRONTEND_ORIGIN: `http://localhost:${FRONTEND_PORT}`
      },
      reuseExistingServer: false,
      timeout: 60_000
    },
    {
      name: 'frontend',
      command: `npx next build && npx next start -H localhost -p ${FRONTEND_PORT}`,
      url: `http://localhost:${FRONTEND_PORT}`,
      env: {
        NEXT_PUBLIC_API_BASE: backendUrl,
        BACKEND_INTERNAL_URL: backendUrl,
        NEXT_TELEMETRY_DISABLED: '1'
      },
      reuseExistingServer: false,
      timeout: 300_000
    }
  ]
});
