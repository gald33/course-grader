import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* The instructor's Lessons section is an index, one row per lesson in session
 * order, and every lesson has a page of its own (versions, publish, Colab
 * link, preview, class insights). The course plan's readiness table and the
 * answer keys sit one click from the index, on their own pages. Nothing here
 * saves anything: publishing is dismissed at its confirmation and the Colab
 * link is never saved, so the other specs see the seed as it was. */

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

async function expectNoSideScroll(page: Page, where: string) {
  const width = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    view: window.innerWidth
  }));
  expect(width.doc, where).toBeLessThanOrEqual(width.view);
  expect(width.body, where).toBeLessThanOrEqual(width.view);
}

const lessonUrl = (id: number | string) => new RegExp(`/course/${seed.course.id}/lessons/${id}$`);

for (const device of [
  { name: 'desktop', width: 1280, height: 900, phone: false },
  { name: 'phone', width: 390, height: 844, phone: true }
]) {
  test(`lessons index → lesson page → preview → back, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    const installed: { id: number; title: string }[] = await (
      await page.request.get(`/api/courses/${seed.course.id}/lessons`)
    ).json();
    const four = seed.plan_lessons['lesson-04'];

    // To the section the way the instructor gets there: the sidebar, or the phone's menu.
    await page.goto(`/course/${seed.course.id}`);
    if (device.phone) {
      await expect(page.locator('aside')).toBeHidden();
      await page.locator('summary').filter({ hasText: 'Sections' }).click();
      await page.getByRole('navigation', { name: 'Course sections' }).getByRole('link', { name: 'Lessons', exact: true }).click();
    } else {
      await page.locator('.nav-step').filter({ hasText: 'Lessons' }).click();
    }
    await expect(page).toHaveURL(/[?&]section=lessons\b/);

    // The index only: a row per lesson, no lesson's detail.
    const index = page.getByTestId('lessons-index');
    await expect(index.locator('li')).toHaveCount(installed.length);
    await expect(page.getByLabel('Colab notebook link')).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Class insights' })).toHaveCount(0);
    await expect(page.getByRole('table', { name: 'Lesson readiness' })).toHaveCount(0);
    await expect(page.getByTestId('answer-keys')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Publish version/ })).toHaveCount(0);

    // In session order: plan lessons by session, a lesson no session names last.
    const sessions = await index.locator('li a > span:first-child').allTextContents();
    const numbers = sessions.filter((s) => s !== '—').map(Number);
    expect(numbers).toEqual([...numbers].sort((a, b) => a - b));
    expect(numbers.length).toBeGreaterThan(0);
    const row = index.locator(`li[data-lesson-id="${four}"]`);
    await expect(row).toContainText('draft');
    await expect(row).toContainText('keys 3/3');
    await expect(row).toContainText('drafted · not reviewed');
    await expect(index.locator(`li[data-lesson-id="${seed.lesson.id}"]`)).toContainText('published');
    await expectNoSideScroll(page, 'index');
    await shot(page, `${device.name}-instructor-lessons-index`);

    // Plan and keys: one click away each.
    await page.getByRole('link', { name: /^Course plan & readiness/ }).click();
    await expect(page).toHaveURL(lessonUrl('plan'));
    await expect(page.getByRole('table', { name: 'Lesson readiness' })).toBeVisible();
    await expectNoSideScroll(page, 'plan');
    await page.getByRole('link', { name: '← All lessons' }).click();
    await page.getByRole('link', { name: /^Answer keys/ }).click();
    await expect(page).toHaveURL(lessonUrl('keys'));
    await expect(page.getByTestId('answer-keys')).toBeVisible();
    await page.getByRole('link', { name: '← All lessons' }).click();
    await expect(page).toHaveURL(/[?&]section=lessons\b/);

    // A lesson opens on its own URL, from the keyboard too.
    await page.locator(`[data-testid="lessons-index"] li[data-lesson-id="${four}"] a`).focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(lessonUrl(four));
    const title = installed.find((l) => l.id === four)!.title;
    await expect(page.getByRole('heading', { level: 2, name: title }).first()).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Lesson navigation' })).toContainText(/Lesson \d+ of \d+/);
    // Everything the lesson card had: versions, publish (with its confirmation), the Colab link, insights.
    await expect(page.getByRole('cell', { name: 'v1' })).toBeVisible();
    let confirmed = '';
    page.once('dialog', (d) => {
      confirmed = d.message();
      void d.dismiss();
    });
    await page.getByRole('button', { name: 'Publish version 1' }).first().click();
    expect(confirmed).toContain('Publish version 1 of');
    await expect(page.getByRole('row').filter({ hasText: 'v1' })).toContainText('draft');
    const colab = page.getByLabel('Colab notebook link');
    await colab.fill('https://example.com/not-colab');
    await expect(page.getByRole('button', { name: 'Save link' })).toBeDisabled();
    await colab.fill('');
    await expect(page.getByRole('region', { name: 'Class insights' })).toBeVisible();
    await expect(page.getByRole('link', { name: /^⬇ Export progress/ })).toBeVisible();
    await expectNoSideScroll(page, 'lesson page');
    await shot(page, `${device.name}-instructor-lesson-page`);

    // Preview, then back to the lesson it came from.
    await page.getByRole('link', { name: 'Preview version 1', exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/course/${seed.course.id}/lessons/${four}/preview\\?version=1(#.*)?$`));
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await page.getByRole('link', { name: '← Back to lesson' }).click();
    await expect(page).toHaveURL(lessonUrl(four));
    await expect(page.getByRole('heading', { level: 2, name: title }).first()).toBeVisible();

    // Next and previous lessons, in the index's order.
    await page.goto(`/course/${seed.course.id}?section=lessons`);
    await expect(index.locator('li')).toHaveCount(installed.length);
    const ids = await index.locator('li').evaluateAll((els) => els.map((el) => Number(el.getAttribute('data-lesson-id'))));
    const at = ids.indexOf(four);
    await page.goto(`/course/${seed.course.id}/lessons/${four}`);
    await page.getByRole('link', { name: /^Next lesson:/ }).click();
    await expect(page).toHaveURL(lessonUrl(ids[at + 1]));
    await page.getByRole('link', { name: /^Previous lesson:/ }).click();
    await expect(page).toHaveURL(lessonUrl(four));

    // Back to the index, then the browser's own back returns to the lesson.
    await page.getByRole('link', { name: '← All lessons' }).click();
    await expect(page).toHaveURL(/[?&]section=lessons\b/);
    await expect(index).toBeVisible();
    await page.goBack();
    await expect(page).toHaveURL(lessonUrl(four));

    // Leaving the section from a lesson page goes to the course page's section.
    if (device.phone) {
      await page.locator('summary').filter({ hasText: 'Sections' }).click();
      await page.getByRole('navigation', { name: 'Course sections' }).getByRole('link', { name: 'Students', exact: true }).click();
    } else {
      await page.locator('.nav-step').filter({ hasText: 'Students' }).click();
    }
    await expect(page).toHaveURL(new RegExp(`/course/${seed.course.id}\\?section=students$`));
    expect(problems).toEqual([]);
  });
}

test('a lesson id that isn’t in this course says so, with the way back', async ({ page }) => {
  await page.goto(`/course/${seed.course.id}/lessons/999999`);
  await expect(page.getByText('This lesson isn’t part of this course.')).toBeVisible();
  await page.getByRole('link', { name: '← All lessons' }).click();
  await expect(page.getByTestId('lessons-index')).toBeVisible();
});
