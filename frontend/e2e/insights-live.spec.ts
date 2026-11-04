import { expect, test } from '@playwright/test';

import { loadSeed, type Seed, type SignedInStudent } from './seed';

/* Class insights update live: an instructor who keeps the insights open sees a
 * student's progress arrive without reloading. Uses its own seeded student
 * (seed.lesson_students.live), who only opens the lesson and moves a step, so
 * the question statistics other tests read are untouched. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

test('class insights update while the instructor watches, without a reload', async ({ page, browser, baseURL }) => {
  test.setTimeout(90_000);
  // Seeded as lesson_students.live (backend/scripts/seed_e2e.py); read untyped so
  // this spec doesn't edit the shared Seed type other open work also extends.
  const student = (seed.lesson_students as Record<string, SignedInStudent>).live;
  expect(student, 'seed.lesson_students.live').toBeTruthy();
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/course/${seed.course.id}?section=lessons&tab=insights`);

  const insights = page.getByRole('region', { name: 'Class insights' });
  const row = insights.getByRole('row').filter({ hasText: student.name });
  await expect(row).toContainText('not started');
  await expect(insights.getByRole('button', { name: 'Live' })).toHaveAttribute('aria-pressed', 'true');
  // Set on this document only: a reload would lose it.
  await page.evaluate(() => ((window as unknown as { __watching: boolean }).__watching = true));

  // The student opens the lesson and moves on a step, in their own browser.
  const studentContext = await browser.newContext();
  await studentContext.addCookies([{ name: 'cg_student', value: student.cookie, url: baseURL!, httpOnly: true, sameSite: 'Lax' }]);
  const studentPage = await studentContext.newPage();
  await studentPage.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  await studentPage.goto(`/r/${student.token}/lessons/${seed.lesson.slug}`);
  await studentPage.getByRole('button', { name: /^לשלב הבא/ }).click();
  await expect(studentPage.getByRole('status').first()).toHaveText('✓ נשמר');
  await studentContext.close();

  // The open page picks it up on its own: a check every few seconds, a refetch at most every 10 s.
  await expect(row).toContainText('in progress', { timeout: 30_000 });
  expect(await page.evaluate(() => (window as unknown as { __watching?: boolean }).__watching)).toBe(true);

  // Paused, it stops asking.
  await insights.getByRole('button', { name: 'Live' }).click();
  await expect(insights.getByRole('button', { name: 'Paused' })).toHaveAttribute('aria-pressed', 'false');
  const asked: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/insights')) asked.push(req.url());
  });
  await page.waitForTimeout(9_000);
  expect(asked).toEqual([]);
});
