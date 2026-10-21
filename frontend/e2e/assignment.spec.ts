import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Assignment pages: each assignment opens its own page from the portal, shows
 * its rubric, and shows scores only once its grade is released (the seeded
 * HW2 is, HW1 is not). The instructor's "view as student" shows the same page. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

async function watchForErrors(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console error: ${msg.text()}`);
  });
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

const tab = (page: Page, name: string) => page.getByRole('tab', { name, exact: true });

test('a released assignment opens from Course info with its score breakdown, and back', async ({ page }) => {
  const problems = await watchForErrors(page);
  const { student, hw2 } = seed.assignments;
  await page.goto(`/r/${student.token}?tab=info`);

  await page.getByRole('link', { name: new RegExp(hw2.name) }).click();
  await expect(page).toHaveURL(new RegExp(`/r/${student.token}/assignments/${hw2.id}\\?from=info$`));
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(hw2.name);
  await expect(page.getByText('✓ הוגש')).toBeVisible();
  await expect(page.getByTestId('assignment-score')).toHaveText(String(hw2.score));
  // Every fixed dimension, scored out of its points.
  await expect(page.getByTestId('criterion')).toHaveCount(12);
  await expect(page.getByTestId('criterion').filter({ hasText: 'איכות הקוד' })).toContainText('6.4 / 8');
  await expect(page.getByText(hw2.feedback)).toBeVisible();

  await page.getByRole('link', { name: 'חזרה לעמוד הקורס' }).click();
  await expect(page).toHaveURL(new RegExp(`/r/${student.token}\\?tab=info$`));
  await expect(tab(page, 'מידע על הקורס')).toHaveAttribute('aria-selected', 'true');
  expect(problems).toEqual([]);
});

test('an unreleased assignment shows its rubric and no scores', async ({ page }) => {
  const problems = await watchForErrors(page);
  const { student, hw1 } = seed.assignments;
  await page.goto(`/r/${student.token}?tab=grades`);

  await page.getByRole('link', { name: new RegExp(hw1.name) }).click();
  await expect(page).toHaveURL(new RegExp(`/assignments/${hw1.id}\\?from=grades$`));
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(hw1.name);
  await expect(page.getByText('לא נמצאה הגשה')).toBeVisible();
  await expect(page.getByText('טרם פורסם')).toBeVisible();
  await expect(page.getByTestId('assignment-score')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'הציון שלך' })).toHaveCount(0);

  await page.getByRole('link', { name: 'חזרה לעמוד הקורס' }).click();
  await expect(tab(page, 'ציונים')).toHaveAttribute('aria-selected', 'true');
  expect(problems).toEqual([]);
});

test('view as student opens the same assignment page', async ({ page }) => {
  const problems = await watchForErrors(page);
  const { course_id, student, hw2 } = seed.assignments;
  await page.goto(`/course/${course_id}/student-view?student=${student.id}&tab=info`);

  await page.getByRole('link', { name: new RegExp(hw2.name) }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${course_id}/student-view/assignments/${hw2.id}\\?student=${student.id}&from=info$`));
  await expect(page.getByText('Student view · preview only')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(hw2.name);
  await expect(page.getByTestId('assignment-score')).toHaveText(String(hw2.score));
  await expect(page.getByText(hw2.feedback)).toBeVisible();

  await page.getByRole('link', { name: 'חזרה לעמוד הקורס' }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${course_id}/student-view\\?student=${student.id}&tab=info$`));
  await expect(tab(page, 'מידע על הקורס')).toHaveAttribute('aria-selected', 'true');
  expect(problems).toEqual([]);
});
