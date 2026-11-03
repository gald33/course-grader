import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* The whole-course plan (42052 handoff): the seed imports it into the course
 * as 13 draft lessons and loads FAKE answer keys for them (the real keys are
 * private: last option "right", first "wrong", texts say FAKE; see fake_keys
 * in backend/scripts/seed_e2e.py). Here: the instructor's readiness table
 * keeps its five states apart, a draft lesson previews in Hebrew RTL on a
 * desktop and a phone, and students can't reach any of the drafts. Lesson 3
 * is authored in the repository and has its own walkthrough (lesson-3.spec.ts);
 * the generated drafts are represented here by lesson 4. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const SHOTS = process.env.E2E_SCREENSHOTS_DIR;
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

async function watchForErrors(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) problems.push(`console error: ${msg.text()}`);
  });
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.url()}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

const stepHeading = (page: Page) => page.locator('#lesson-step-title');
const questionCard = (page: Page, key: string) => page.locator(`article[aria-labelledby="q-${key}-prompt"]`);

test('the readiness table keeps drafted, reviewed, runnable, published and live verified apart', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/course/${seed.course.id}`);
  await page.locator('.nav-step').filter({ hasText: 'Lessons' }).click();

  const plan = page.getByTestId('course-plan');
  await expect(plan).toContainText('Course plan');
  await expect(plan).toContainText('does not change');
  const table = plan.getByRole('table', { name: 'Lesson readiness' });
  await expect(table.locator('tbody tr')).toHaveCount(13);
  for (const column of ['Drafted', 'Reviewed', 'Runnable', 'Published', 'Live verified', 'Answer keys']) {
    await expect(table.getByRole('columnheader', { name: new RegExp(`^${column}$`, 'i') })).toBeVisible();
  }
  // No badge sums the states up.
  await expect(plan.locator('.pill').filter({ hasText: /ready/i })).toHaveCount(0);

  // Sessions 2-9 are presentation rounds, 12-13 the finals; nothing else is invented.
  const row = (n: number) => table.locator(`tr[data-session="${n}"]`);
  await expect(row(2)).toContainText('Round 1');
  await expect(row(9)).toContainText('Round 4');
  await expect(row(10)).toContainText('No formal presentations');
  await expect(row(13)).toContainText('Finals, part 2');
  // Session 2 also names the existing, live lesson 2.
  await expect(row(2)).toContainText(`also the existing lesson ${seed.lesson.slug}`);

  // Drafted, but not published or verified; the seed's FAKE keys are loaded.
  // Lesson 3 was built here (its notebook ran); a generated lesson was not.
  const three = row(3);
  await expect(three).toContainText('✓ v1');
  await expect(three).toContainText('built here, not reviewed');
  await expect(three).toContainText('8/8 loaded');
  await expect(row(4)).toContainText('not built');
  await expect(row(4)).toContainText('3/3 loaded');
  // Lesson 3's homework stays a proposal, visible to the instructor only.
  const proposal = page.getByTestId('homework-proposal-3');
  await expect(proposal).toContainText('proposal not yet assigned');
  await expect(proposal).toContainText('no deadline or weight');
  await expect(three.getByRole('checkbox', { name: 'Session 3 reviewed' })).not.toBeChecked();
  await expect(three.getByRole('checkbox', { name: 'Session 3 live verified' })).not.toBeChecked();

  // Marking it reviewed changes that state only.
  await three.getByRole('checkbox', { name: 'Session 3 reviewed' }).click(); // saved, then shown
  await expect(three.getByRole('checkbox', { name: 'Session 3 reviewed' })).toBeChecked();
  await expect(three.getByRole('checkbox', { name: 'Session 3 live verified' })).not.toBeChecked();
  await expect(three.locator('td').nth(7)).toHaveText('no'); // published
  await three.getByRole('checkbox', { name: 'Session 3 reviewed' }).click();
  await expect(three.getByRole('checkbox', { name: 'Session 3 reviewed' })).not.toBeChecked();

  const keys = page.getByTestId('answer-keys');
  await expect(keys).toContainText('every installed lesson has its keys');
  await expect(keys).not.toContainText('FAKE');
  await shot(page, 'desktop-instructor-course-plan');
  expect(problems).toEqual([]);
});

for (const device of [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 }
]) {
  test(`a draft plan lesson previews in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-04']}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();

    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();
    await expect(stepHeading(page)).toContainText(/./);
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);

    // A check question: no explanation before answering; after a wrong
    // answer, the right option and the (FAKE) explanation.
    const card = questionCard(page, 'l04-q1');
    await expect(card).not.toContainText('התשובה הנכונה');
    await expect(card.getByRole('button', { name: 'הצג הסבר' })).toHaveCount(0);
    const radios = card.getByRole('radio');
    await expect(radios).toHaveCount(3);
    await radios.first().check();
    await card.getByRole('button', { name: /^(שליחת תשובה|שליחה מחדש)$/ }).click();
    await expect(card).toContainText('✗ לא בדיוק');
    await expect(card).toContainText('התשובה הנכונה');
    await expect(card).toContainText('FAKE');
    await radios.last().check();
    await card.getByRole('button', { name: /^(שליחת תשובה|שליחה מחדש)$/ }).click();
    await expect(card).toContainText('✓ נכון');

    // Every step, on this screen: never wider than the viewport.
    for (const letter of ['A', 'B', 'C', 'D']) {
      await page.getByRole('button', { name: new RegExp(`^שלב ${letter}:`) }).click();
      await page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
      const width = await page.evaluate(() => ({
        doc: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        view: window.innerWidth
      }));
      expect(width.doc, `step ${letter}`).toBeLessThanOrEqual(width.view);
      expect(width.body, `step ${letter}`).toBeLessThanOrEqual(width.view);
    }
    await expect(stepHeading(page)).toContainText('מסכמים');
    await expect(page.getByText('דוגמה פתורה')).toBeVisible();
    // Latin terms sit in left-to-right islands inside the Hebrew text.
    await expect(player.locator('bdi[dir="ltr"]').filter({ hasText: /diff/i }).first()).toBeVisible();
    await shot(page, `${device.name}-plan-lesson-04-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('students can’t reach a draft plan lesson', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const list = await (await page.request.get(`/api/r/${seed.student.token}/lessons`)).json();
  expect(list.lessons.map((l: { slug: string }) => l.slug)).toEqual([seed.lesson.slug]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-03`);
  expect(draft.status()).toBe(404);
  const home = await page.request.get(`/api/r/${seed.student.token}`);
  expect(await home.text()).not.toContain('FAKE');
});
