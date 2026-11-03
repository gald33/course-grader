import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Lesson 6 of the 42052 plan ("בונים שלד שעובד מקצה לקצה"), authored in the
 * repository: the instructor previews the whole draft inside the lesson's own
 * page, in Hebrew, right to left, on a desktop and a phone, by keyboard
 * (every step's goal, action, checkpoint and next step; the agent prompts;
 * the GitHub steps with their cited docs; the conflict example; the
 * fallbacks; the worked example and the exit check), and both templates
 * download with the sha256 in the lesson's assets. The seed loads FAKE keys
 * (last option "right"); the real keys are private and never in this
 * repository. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const REPO = path.join(__dirname, '..', '..');
const MATERIALS = path.join(REPO, 'content/course-42052/materials/lesson-06');
type Asset = { path: string; filename: string; sha256: string };
const FIXTURE = JSON.parse(
  readFileSync(path.join(REPO, 'backend/app/lessons/content/course-42052/lesson-06.json'), 'utf-8')
) as { assets: { readme_template: Asset; git_routine: Asset } };

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

async function expectDownload(player: Locator, name: RegExp, asset: Asset) {
  const link = player.getByRole('link', { name });
  await expect(link).toHaveAttribute('href', asset.path);
  await expect(link).toHaveAttribute('download', asset.filename);
  await link.focus();
  await expect(link).toBeFocused(); // reachable by keyboard
}

for (const device of [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 }
]) {
  test(`lesson 6 previews end to end in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    const lessonPage = `/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-06']}`;
    await page.goto(`${lessonPage}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /Back to lesson/ })).toHaveAttribute('href', lessonPage);
    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();
    // Every prompt in this lesson is a request to the coding agent (the
    // content has no chatbot task; test_lesson_6_content.py checks the text).
    await expect(player.getByText(/^בקשה לצ׳טבוט/)).toHaveCount(0);

    // A: one path through all parts, the AI step a labelled stub.
    await expectStepContract(page, 'מסלול אחד שעובר בכל החלקים', 'מה הגרסה הראשונה שרצה באמת – מהקלט של המשתמש ועד התוצאה במסך?', player);
    await expect(player.getByText('מה צריך לפני שמתחילים')).toBeVisible();
    await expect(ltr(player, 'vertical slice')).toBeVisible();
    await expect(page.getByRole('table', { name: 'דוגמה: הפרוסה של המאפייה' })).toContainText('הדגמה ללא מודל חי');
    await expect(player.getByText('בקשה לסוכן: שלד לפי האפיון, תוכנית קודם')).toBeVisible();
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await expect(player.getByText('מסלול חלופי: אין לי Antigravity במחשב')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step A');
    await answerText(page, 'l06-slice-log', 'קלט: דנה, 4 לחמניות ו-2 עוגיות ב-09:00. פלט: טבלה עם אותם פריטים ותווית. הבדלים: אין.');
    await answerCheckByKeyboard(page, 'l06-q1');
    await answerCheck(page, 'l06-stub');
    await shot(page, `${device.name}-lesson-06-A-slice`);
    await completeAndContinue(page);

    // B: what the agent created; one line per folder in README.
    await expectStepContract(page, 'מבינים את מבנה הפרויקט', 'מה כל חלק בתיקיית הפרויקט, ואיך מפעילים את המוצר?', player);
    await expect(ltr(player, 'package.json').first()).toBeVisible();
    const tree = player.locator('pre').filter({ hasText: 'bakery-skeleton/' });
    await expect(tree).toBeVisible();
    await expect(tree).toHaveAttribute('dir', 'ltr');
    await expectDownload(player, /תבנית README/, FIXTURE.assets.readme_template);
    await expectNoSidewaysScroll(page, 'step B');
    await page.getByRole('checkbox', { name: /כל אחד כתב ב-README.md שורה/ }).check();
    await answerCheck(page, 'l06-deps');
    await shot(page, `${device.name}-lesson-06-B-structure`);
    await completeAndContinue(page);

    // C: a shared version on GitHub; pull before push; a conflict.
    await expectStepContract(page, 'מחברים עבודה של צוות', 'איך כל הצוות עובד על אותה גרסה – ויודע שהיא רצה?', player);
    await expect(player.getByText('התחברות ל-GitHub מהמחשב', { exact: true })).toBeVisible();
    await expect(ltr(player, 'gh auth login').first()).toBeVisible();
    await expect(ltr(player, 'cli.github.com/manual/gh_auth_login')).toBeVisible();
    const conflict = player.locator('pre').filter({ hasText: '<<<<<<< HEAD' });
    await expect(conflict).toBeVisible();
    await expect(conflict).toHaveAttribute('dir', 'ltr');
    await expectDownload(player, /שגרת git של הצוות/, FIXTURE.assets.git_routine);
    for (const title of ['בקשה לסוכן: חיבור למאגר ודחיפה ראשונה', 'בקשה לסוכן: עותק, שינוי אחד ודחיפה', 'בקשה לסוכן: פתרון קונפליקט יחד']) {
      await expect(player.getByText(title)).toBeVisible();
    }
    await expect(player.getByText('מסלול חלופי: לא מצליחים להתקין או להתחבר')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step C');
    await page.getByRole('checkbox', { name: /כל חבר\/ת צוות דחף\/ה שינוי אחד/ }).check();
    await answerCheck(page, 'l06-q2');
    await answerCheck(page, 'l06-pull');
    await answerCheckByKeyboard(page, 'l06-conflict');
    await shot(page, `${device.name}-lesson-06-C-version`);
    await completeAndContinue(page);

    // D: someone who did not set it up runs it from a fresh clone.
    await expectStepContract(page, 'הרצה חוזרת היא חלק מהמוצר', 'האם מי שלא בנה את השלד מצליח להריץ אותו לבד?', player);
    await expect(player.getByText('בקשה לסוכן: README רק ממה שהורץ')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step D');
    await answerText(page, 'l06-fresh-run', 'הריצה נועה. חסר: פקודת npm install. תיקנו ב-README. בסוף: התשובה הצפויה.');
    await answerCheck(page, 'l06-q3');
    await answerCheck(page, 'l06-proof');
    await shot(page, `${device.name}-lesson-06-D-run`);
    await completeAndContinue(page);

    // E: wrap-up. The worked example, the exit check (no chatbot), the work product.
    await expectStepContract(page, 'מסכמים', 'מה הצוות יכול להראות: מה רץ, איפה הוא שמור, ומי עוד יכול להריץ אותו?', player);
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await expect(questionCard(page, 'lesson-06-exit')).toContainText('הסבירו במילים שלכם מה ניסיתם, מה ראיתם ומה עדיין אינו ידוע.');
    await expectNoSidewaysScroll(page, 'step E');
    await answerText(page, 'lesson-06-exit', 'בנינו שלד עם stub מסומן, דחפנו ל-GitHub וחבר הריץ מעותק חדש; לא ידוע איך יתנהג מודל אמיתי.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).not.toContainText('קישור למאגר'); // the homework proposal is not shown
    await shot(page, `${device.name}-lesson-06-E-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('both lesson 6 templates download with the sha256 in the lesson assets', async ({ page }) => {
  for (const asset of [FIXTURE.assets.readme_template, FIXTURE.assets.git_routine]) {
    const res = await page.request.get(asset.path);
    expect(res.status(), asset.path).toBe(200);
    const body = await res.body();
    expect(createHash('sha256').update(body).digest('hex')).toBe(asset.sha256);
    expect(body.equals(readFileSync(path.join(MATERIALS, asset.filename)))).toBe(true);
  }
});

test('students can’t reach lesson 6 while it is a draft', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-06`);
  expect(draft.status()).toBe(404);
});
