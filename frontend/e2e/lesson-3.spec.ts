import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Lesson 3 of the 42052 plan ("איך מודלי שפה עובדים?"), authored in the
 * repository: the instructor previews the whole draft in Hebrew, right to
 * left, on a desktop and a phone — every step's goal, explanation, action,
 * checkpoint and next step, the chatbot prompts, the notebook downloads, the
 * worked example and the exit check. The seed loads FAKE keys (last option
 * "right"); the real keys are private and never in this repository. */

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

for (const device of [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 }
]) {
  test(`lesson 3 previews end to end in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-03']}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();

    // A: tokens. Prerequisites first, then explain, act (chatbot + notebook), check.
    await expectStepContract(page, 'המודל מקבל רצף יחידות', 'מה בעצם מגיע למודל כשאתם כותבים לצ׳טבוט?', player);
    await expect(player.getByText('מה צריך לפני שמתחילים')).toBeVisible();
    await expect(player.locator('bdi[dir="ltr"]').filter({ hasText: 'tokenizer' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await expect(player.getByText('עובדים בקולאב: תא ההכנה וסעיף 1')).toBeVisible();
    for (const file of ['lesson-3-language-models-he.ipynb', 'lesson-3-language-models-he-executed.ipynb']) {
      const res = await page.request.get(`/lessons/lesson-03/v1/${file}`);
      expect(res.status(), file).toBe(200);
      expect((await res.json()).cells.length, file).toBeGreaterThan(10);
    }
    // No Colab link is invented: the notebook is downloaded and uploaded.
    await expect(player.getByRole('link', { name: /פתיחה בקולאב/ })).toHaveCount(0);
    await expectNoSidewaysScroll(page, 'step A');
    await page.getByRole('checkbox', { name: /השוויתי בין הניחוש/ }).check();
    await answerCheck(page, 'l03-q1');
    await answerCheck(page, 'l03-tokens-ratio');
    await shot(page, `${device.name}-lesson-03-A-tokens`);
    await completeAndContinue(page);

    // B: next token, with the small open model's limits stated.
    await expectStepContract(page, 'המודל בוחר את ההמשך', 'איך מודל שפה מגיע לתשובה, טוקן אחרי טוקן?', player);
    await expect(player.getByText('המודל במחברת אינו הצ׳טבוט שלכם')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step B');
    await page.getByRole('checkbox', { name: /הרצתי את סעיף 2/ }).check();
    await answerCheck(page, 'l03-context-shift');
    await answerCheck(page, 'l03-probability-meaning');
    await shot(page, `${device.name}-lesson-03-B-next-token`);
    await completeAndContinue(page);

    // C: representation and attention; the picture is an illustration.
    await expectStepContract(page, 'ייצוג ומשמעות תלויים בהקשר', 'איך אותה מילה מקבלת משמעות אחרת במשפט אחר?', player);
    await expect(page.getByRole('table', { name: /המחשה רעיונית/ })).toBeVisible();
    await expectNoSidewaysScroll(page, 'step C');
    await answerCheck(page, 'l03-q2');
    await answerCheck(page, 'l03-illustration');
    await shot(page, `${device.name}-lesson-03-C-attention`);
    await completeAndContinue(page);

    // D: grounding: two prompts, two input-based checks, the worked example.
    await expectStepContract(page, 'תשובה רהוטה עדיין דורשת ראיות', 'איך בודקים שהצ׳טבוט לא השלים פרט שלא נמסר לו?', player);
    await expect(player.getByText('בקשה 1 (פשוטה)')).toBeVisible();
    await expect(player.getByText('בקשה 2 (עם כללים)')).toBeVisible();
    await expect(page.getByRole('table', { name: 'שתי הבדיקות – לכל אחת משתי התשובות' })).toBeVisible();
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.locator('pre').filter({ hasText: '"pickup_time": null' })).toBeVisible();
    await expectNoSidewaysScroll(page, 'step D');
    await answerText(page, 'l03-grounding-log', 'בקשה 1 השלימה שעה 10:00; בקשה 2 השאירה null. בלי כמות: סומנה כחסרה.');
    await answerCheck(page, 'l03-q3');
    await answerCheck(page, 'l03-source');
    await shot(page, `${device.name}-lesson-03-D-grounding`);
    await completeAndContinue(page);

    // E: wrap-up. The exit check is free text; the homework proposal is not shown.
    await expectStepContract(page, 'מסכמים', 'מה תוכלו להסביר לבד, במילים שלכם?', player);
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step E');
    await answerText(page, 'lesson-03-exit', 'ניסיתי שתי בקשות; ראיתי שהבקשה עם הכללים לא המציאה שעה.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).not.toContainText('הכינו בצוות הוראות');
    await shot(page, `${device.name}-lesson-03-E-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('students can’t reach lesson 3 while it is a draft', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-03`);
  expect(draft.status()).toBe(404);
});
