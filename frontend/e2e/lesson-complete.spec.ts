import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* The "lesson complete" moment in the instructor preview (nothing is saved,
 * so every visit starts over): plan lesson 6, four questions, on a phone. The
 * student side (a real completion, the reload, the lessons list) is in
 * lesson.spec.ts, which owns lesson-2's student records. FAKE keys: the last
 * option counts as right. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const card = (page: Page, key: string) => page.locator(`article[aria-labelledby="q-${key}-prompt"]`);

async function finishLessonSix(page: Page) {
  await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-06']}/preview`);
  await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
  for (const key of ['l06-q1', 'l06-q2', 'l06-q3']) {
    const q = card(page, key);
    await q.getByRole('radio').last().check();
    await q.getByRole('button', { name: 'שליחת תשובה' }).click();
    await expect(q.getByRole('button', { name: 'שליחה מחדש' })).toBeVisible();
    await page.getByRole('button', { name: /^לשלב הבא/ }).click();
  }
  const exit = card(page, 'lesson-06-exit');
  await exit.getByRole('textbox').fill('שלד קטן שעובד מקצה לקצה עדיף על חלק אחד מושלם.');
  await exit.getByRole('button', { name: 'שליחת תשובה' }).click();
}

const dialog = (page: Page) => page.getByRole('dialog', { name: /^כל הכבוד! סיימתם את שיעור 6/ });

test('the preview celebrates completing a lesson, with the next lesson, on a 390px phone', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await finishLessonSix(page);

  const d = dialog(page);
  await expect(d).toBeVisible();
  await expect(d.getByRole('heading')).toHaveText('כל הכבוד! סיימתם את שיעור 6 – בונים שלד שעובד מקצה לקצה');
  await expect(d).toContainText('השלמתם 4 מתוך 4 שלבי חובה · עניתם על 4 מתוך 4 שאלות');
  await expect(d).toContainText('תצוגה מקדימה – שום דבר לא נשמר');
  await expect(d.getByTestId('celebration-confetti')).toBeAttached();
  await expect(d.getByRole('link', { name: /^לשיעור הבא: מחברים יכולת AI למוצר/ })).toHaveAttribute(
    'href',
    `/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-07']}/preview`
  );
  await expect(d.getByRole('link', { name: 'לרשימת השיעורים' })).toHaveAttribute('href', /\/course\/\d+.*lessons/);
  await expect(d.getByRole('link', { name: 'לדף הבית של הקורס' })).toHaveAttribute('href', `/course/${seed.course.id}`);
  // Fits the phone: no sideways scroll, the dialog inside the viewport.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const box = (await d.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);

  await d.getByRole('button', { name: 'סגירה וחזרה לשיעור' }).click();
  await expect(d).toHaveCount(0);
  await expect(page.getByTestId('lesson-complete-badge')).toBeVisible();
  expect(errors).toEqual([]);
});

test('with reduced motion there is no confetti, only the static badge', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await finishLessonSix(page);
  const d = dialog(page);
  await expect(d).toBeVisible();
  await expect(d.getByTestId('celebration-badge')).toBeVisible();
  await expect(page.getByTestId('celebration-confetti')).toHaveCount(0);
  expect(await d.getByTestId('celebration-badge').evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
});
