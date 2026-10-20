import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

// Written by the backend web server's seed step, so read it once tests run.
let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

/* Fails the test on anything the page reports going wrong: uncaught errors,
 * console errors, API calls that fail or return an error status. Webfonts are stubbed so
 * the test never depends on the network. */
async function watchForErrors(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console error: ${msg.text()}`);
  });
  page.on('requestfailed', (req) => problems.push(`request failed: ${req.method()} ${req.url()} (${req.failure()?.errorText})`));
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

test('instructor course page loads the seeded course', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.goto(`/course/${seed.course.id}`);

  // The page shows "Loading…" until every course request has resolved, then
  // the step header (h1) and the sidebar with the course name.
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByText(seed.course.name).first()).toBeVisible();
  await expect(page.getByText('Loading…')).toHaveCount(0);
  expect(problems).toEqual([]);
});

test('student review page loads for a seeded review link', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.goto(`/r/${seed.student.token}`);

  await expect(page.getByRole('heading', { level: 1 })).toContainText(seed.student.name);
  await expect(page.getByText(seed.course.name).first()).toBeVisible();
  await expect(page.getByText(seed.student.team).first()).toBeVisible();
  expect(problems).toEqual([]);
});

test('student review page rejects an unknown link', async ({ page }) => {
  const problems = await watchForErrors(page);
  // A well-formed but unknown token: the API answers 404 and the page says so
  // instead of rendering a student's home.
  await page.goto('/r/unknown-token-0000000000');

  await expect(page.getByText('הקישור אינו תקין')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0);
  // The browser logs the expected 404 itself; nothing else may go wrong.
  expect(problems.filter((p) => !p.includes('404'))).toEqual([]);
});
