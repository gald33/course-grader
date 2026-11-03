import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Lesson 4 of the 42052 plan ("סוכן קוד: מתכנון להרצה ובדיקה"), authored in
 * the repository: the instructor previews the whole draft in Hebrew, right to
 * left, on a desktop and a phone (every step's goal, explanation, action,
 * checkpoint and next step, the Antigravity prompts, the labeled fallback,
 * the worked example and the exit check), and the starter project downloads,
 * opens from the unzipped folder in a browser and shows the documented check
 * output. The seed loads FAKE keys (last option "right"); the real keys are
 * private and never in this repository. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const REPO = path.join(__dirname, '..', '..');
const FIXTURE = JSON.parse(
  readFileSync(path.join(REPO, 'backend/app/lessons/content/course-42052/lesson-04.json'), 'utf-8')
) as {
  assets: { starter: { path: string; sha256: string } };
  steps: { blocks: unknown[] }[];
};
const EXPECTED_OUTPUT: string = (function find(blocks: unknown[]): string | undefined {
  for (const b of blocks as { type: string; code?: string; blocks?: unknown[] }[]) {
    if (b.type === 'code') return b.code;
    const inner = b.blocks ? find(b.blocks) : undefined;
    if (inner) return inner;
  }
  return undefined;
})(FIXTURE.steps.flatMap((s) => s.blocks))!;

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
const checklist = (page: Page) => page.getByRole('region', { name: 'מה נדרש כדי להשלים את השלב' });
const SEND = /^(שליחת תשובה|שליחה מחדש)$/;

/** A check question: a first wrong answer shows the right option, then the right one. */
async function answerCheck(page: Page, key: string) {
  const card = questionCard(page, key);
  const radios = card.getByRole('radio');
  await radios.first().check();
  await card.getByRole('button', { name: SEND }).click();
  await expect(card).toContainText('✗ לא בדיוק');
  await expect(card).toContainText('התשובה הנכונה');
  await radios.last().check();
  await card.getByRole('button', { name: SEND }).click();
  await expect(card).toContainText('✓ נכון');
}

/** The same, with the keyboard only: focus, Space to choose, Enter to send. */
async function answerCheckByKeyboard(page: Page, key: string) {
  const card = questionCard(page, key);
  const radios = card.getByRole('radio');
  const send = card.getByRole('button', { name: SEND });
  await radios.first().focus();
  await page.keyboard.press('Space');
  await expect(radios.first()).toBeChecked();
  await send.focus();
  await page.keyboard.press('Enter');
  await expect(card).toContainText('✗ לא בדיוק');
  await radios.last().focus();
  await page.keyboard.press('Space');
  await expect(radios.last()).toBeChecked();
  await send.focus();
  await page.keyboard.press('Enter');
  await expect(card).toContainText('✓ נכון');
}

async function answerText(page: Page, key: string, text: string) {
  const card = questionCard(page, key);
  await card.getByRole('textbox').fill(text);
  await card.getByRole('button', { name: 'שליחת תשובה' }).click();
  await expect(card).toContainText('✓ זו התשובה ששלחת');
}

async function expectNoSidewaysScroll(page: Page, where: string) {
  await page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
  const width = await page.evaluate(() => ({
    doc: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
    view: window.innerWidth
  }));
  expect(width.doc, where).toBeLessThanOrEqual(width.view);
  expect(width.body, where).toBeLessThanOrEqual(width.view);
}

async function completeAndContinue(page: Page) {
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
}

async function expectStepContract(page: Page, title: string, goal: string, player: Locator) {
  await expect(stepHeading(page)).toContainText(title);
  await expect(player.getByText(goal)).toBeVisible();
}

const ltr = (player: Locator, text: string | RegExp) => player.locator('bdi[dir="ltr"]').filter({ hasText: text }).first();

for (const device of [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 }
]) {
  test(`lesson 4 previews end to end in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-04']}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    // Back to the course page's lessons section (the ?section= URLs).
    await expect(page.getByRole('link', { name: /Back to course/ })).toHaveAttribute(
      'href',
      `/course/${seed.course.id}?section=lessons`
    );
    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();

    // A: chatbot vs coding agent. Words first, then install, open, describe.
    await expectStepContract(page, 'מה נוסף לסוכן קוד?', 'במה סוכן קוד שונה מצ׳טבוט, ומה מותר לו לעשות במחשב שלכם?', player);
    await expect(player.getByText('מה צריך לפני שמתחילים')).toBeVisible();
    await expect(page.getByRole('table', { name: 'צ׳טבוט לעומת סוכן קוד' })).toBeVisible();
    await expect(ltr(player, 'antigravity.google/download')).toBeVisible();
    await expect(ltr(player, 'node check.js')).toBeVisible();
    const download = player.getByRole('link', { name: /פרויקט הפתיחה/ });
    await expect(download).toHaveAttribute('href', FIXTURE.assets.starter.path);
    await download.focus();
    await expect(download).toBeFocused(); // reachable by keyboard
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await expect(player.getByText('מסלול חלופי: אין אפשרות להתקין')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step A');
    await page.getByRole('checkbox', { name: /הסוכן תיאר את הפרויקט/ }).check();
    await answerCheckByKeyboard(page, 'l04-q1');
    await answerCheck(page, 'l04-permission');
    await shot(page, `${device.name}-lesson-04-A-agent`);
    await completeAndContinue(page);

    // B: a save point before any change.
    await expectStepContract(page, 'נקודת שמירה לפני שינוי', 'איך חוזרים למצב שעבד, אם שינוי מקלקל משהו?', player);
    await expect(ltr(player, 'commit').first()).toBeVisible();
    await expect(player.getByText('מסלול חלופי: אי אפשר להתקין Git')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step B');
    await page.getByRole('checkbox', { name: /יש לי נקודת שמירה/ }).check();
    await answerCheck(page, 'l04-commit');
    await shot(page, `${device.name}-lesson-04-B-save`);
    await completeAndContinue(page);

    // C: the loop. Expected result before the change; the documented output.
    await expectStepContract(page, 'שינוי קטן עם תשובה צפויה', 'איך יודעים שהשינוי עשה בדיוק את מה שרציתם – ולא יותר?', player);
    await answerText(page, 'l04-expected', 'לוחצים סימון כמוכנה אצל דנה; מופיעה הודעת אישור; סך הכול נשאר 10 ו-5.');
    await expect(player.getByText('בקשה לסוכן: שינוי קטן, תוכנית קודם')).toBeVisible();
    const output = player.locator('pre').filter({ hasText: '5 of 5 checks passed' });
    await expect(output).toBeVisible();
    await expect(output).toHaveAttribute('dir', 'ltr');
    expect((await output.innerText()).replace(/^\s*\d+\s?/gm, '')).toContain('PASS total rolls = 10');
    await expectNoSidewaysScroll(page, 'step C');
    await page.getByRole('checkbox', { name: /פתחתי בעצמי את האפליקציה/ }).check();
    await answerText(page, 'l04-loop-log', 'קבצים: app.js. פלט: 5 of 5 checks passed. בדפדפן ראיתי את ההודעה. לא נבדק: טלפון.');
    await answerCheck(page, 'l04-q2');
    await answerCheck(page, 'l04-diff');
    await shot(page, `${device.name}-lesson-04-C-loop`);
    await completeAndContinue(page);

    // D: the instructions file, no secrets.
    await expectStepContract(page, 'נותנים הקשר ואילוצים', 'איך הסוכן יודע את כללי הפרויקט בלי שתחזרו עליהם בכל בקשה?', player);
    await expect(ltr(player, 'AGENTS.md')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step D');
    await page.getByRole('checkbox', { name: /יצרתי AGENTS.md/ }).check();
    await answerCheck(page, 'l04-q3');
    await answerCheck(page, 'l04-secret');
    await shot(page, `${device.name}-lesson-04-D-context`);
    await completeAndContinue(page);

    // E: wrap-up. When the agent is wrong; the worked example; exit check.
    await expectStepContract(page, 'מסכמים', 'מה תוכלו להראות ולהסביר על השינוי שעשיתם?', player);
    await expect(player.getByText('כשהסוכן טועה')).toBeVisible();
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await expect(player.getByText('אותה לולאה בסוכנים אחרים')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step E');
    await answerCheck(page, 'l04-claim');
    await answerText(page, 'lesson-04-exit', 'ביקשתי תוכנית, שמרתי commit, הוספתי הודעה וקראתי את ה-diff; לא בדקתי בטלפון.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).not.toContainText('יישמו שינוי קטן'); // the homework proposal is not shown
    await shot(page, `${device.name}-lesson-04-E-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('the starter project downloads, opens from its folder and shows the documented check output', async ({ page }) => {
  const res = await page.request.get(FIXTURE.assets.starter.path);
  expect(res.status()).toBe(200);
  const zip = await res.body();
  expect(createHash('sha256').update(zip).digest('hex')).toBe(FIXTURE.assets.starter.sha256);

  // Unzipped as a student would (Python's zipfile: no extra tool needed).
  const dir = mkdtempSync(path.join(tmpdir(), 'lesson-04-starter-'));
  const zipPath = path.join(dir, 'bakery-orders-starter.zip');
  writeFileSync(zipPath, zip);
  execFileSync(process.env.PYTHON ?? 'python3', ['-I', '-m', 'zipfile', '-e', zipPath, dir]);
  const folder = path.join(dir, 'bakery-orders-starter');

  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(pathToFileURL(path.join(folder, 'index.html')).href);
  await expect(page.locator('#totals')).toHaveText('לחמניות: 10 · עוגיות: 5');
  await expect(page.getByText('⚠ חסרה שעת איסוף – צריך לברר עם מיכל.')).toBeVisible();
  const ready = page.getByRole('button', { name: 'סימון כמוכנה' });
  await expect(ready).toHaveCount(3);
  await ready.first().focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: '✓ מוכנה' })).toHaveCount(1);
  await expect(page.locator('#totals')).toHaveText('לחמניות: 10 · עוגיות: 5');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.goto(pathToFileURL(path.join(folder, 'check.html')).href);
  await expect(page.locator('#output')).toHaveText(EXPECTED_OUTPUT.replace(/\n$/, ''));
  expect(errors).toEqual([]);
});

test('students can’t reach lesson 4 while it is a draft', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-04`);
  expect(draft.status()).toBe(404);
});
