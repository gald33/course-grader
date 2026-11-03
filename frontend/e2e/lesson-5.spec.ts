import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Lesson 5 of the 42052 plan ("מגדירים מוצר עסקי קטן"), authored in the
 * repository: the instructor previews the whole draft inside the lesson's own
 * page, in Hebrew, right to left, on a desktop and a phone (every step's goal,
 * action, checkpoint and next step; the team prompts; the architecture map
 * worked by keyboard alone, its mapping hidden until asked for; the SPEC.md
 * template; the worked example and the exit check). The seed loads FAKE keys
 * (last option "right"); the real keys are private and never in this
 * repository. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const REPO = path.join(__dirname, '..', '..');
const SOURCE = path.join(REPO, 'content/course-42052/materials/lesson-05/SPEC.md');
const FIXTURE = JSON.parse(
  readFileSync(path.join(REPO, 'backend/app/lessons/content/course-42052/lesson-05.json'), 'utf-8')
) as { assets: { spec_template: { path: string; sha256: string } } };

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

/** The architecture map, by keyboard only: Tab to each select, arrows to choose. */
async function sortByKeyboard(page: Page, map: Locator) {
  const selects = map.getByRole('combobox');
  await expect(selects).toHaveCount(6);
  // Every select has an accessible name: the item it sorts.
  for (const name of ['כפתור שליחת הזמנה', 'בדיקה שהכמות חיובית', 'שמירת ההזמנה', 'קריאה למודל שפה לחילוץ פרטים', 'מפתח API', 'הצגת הסיכום והשעות לבירור']) {
    await expect(map.getByRole('combobox', { name })).toBeVisible();
  }
  await selects.first().focus();
  // Arrow down once picks the first part (ממשק) in each; the first item is
  // then right, and the "key" item is not, so both marks show.
  for (let i = 0; i < 6; i++) {
    await expect(selects.nth(i)).toBeFocused();
    await page.keyboard.press('ArrowDown');
    if (i < 5) await page.keyboard.press('Tab');
  }
  await expect(selects.first()).toHaveValue('frontend');
  await expect(map).toContainText('בחרתם 6 מתוך 6');
}

for (const device of [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 }
]) {
  test(`lesson 5 previews end to end in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    const lessonPage = `/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-05']}`;
    await page.goto(`${lessonPage}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    // Back to the lesson's own page in the course's Lessons section.
    await expect(page.getByRole('link', { name: /Back to lesson/ })).toHaveAttribute('href', lessonPage);
    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();

    // A: who needs the product. A team prompt that asks and compares.
    await expectStepContract(page, 'מי צריך את המוצר?', 'איזו בעיה של איזה משתמש המוצר שלכם פותר – בניסוח שאפשר לבדוק?', player);
    await expect(player.getByText('מה צריך לפני שמתחילים')).toBeVisible();
    await expect(page.getByRole('table', { name: 'הבעיה של המאפייה, בשלושה חלקים' })).toBeVisible();
    await expect(player.getByText('בקשה לצ׳טבוט: שאלות הבהרה ושני כיוונים')).toBeVisible();
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await expect(player.getByText('רשות: לשאול משתמש אמיתי')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step A');
    await answerText(page, 'l05-problem', 'משתמש: מאמנת כדורסל. מצב: לפני אימון. קושי: לא יודעת מי מגיע. עובדה: היא אמרה. הנחה: הורים יענו. שאלה: כמה מגיעים?');
    await answerCheckByKeyboard(page, 'l05-q1');
    await answerCheck(page, 'l05-fact');
    await shot(page, `${device.name}-lesson-05-A-need`);
    await completeAndContinue(page);

    // B: one action end to end; expected answers before any code.
    await expectStepContract(page, 'בוחרים פעולה אחת מקצה לקצה', 'מהי הגרסה הקטנה ביותר של המוצר שאפשר לבדוק אם היא עוזרת?', player);
    await expect(ltr(player, 'MVP').first()).toBeVisible();
    await expect(page.getByRole('table', { name: 'דוגמה: שלוש הודעות בדויות למאפייה, והתשובה הצפויה' })).toContainText('10 לחמניות, 5 עוגיות');
    await expect(page.getByRole('table', { name: 'ארבעה סוגי מקרים, בדוגמת המאפייה' })).toContainText('הוראה בתוך הנתונים');
    await expectNoSidewaysScroll(page, 'step B');
    await answerText(page, 'l05-examples', 'פעולה: רשימת נוכחות. 1. קלט: דנה מגיעה ← צפוי: דנה ✓. 2. קלט: יואב? ← צפוי: לבירור. 3. ... בפנים: נוכחות. בחוץ: תשלום.');
    await answerCheck(page, 'l05-q2');
    await answerCheck(page, 'l05-scope');
    await shot(page, `${device.name}-lesson-05-B-mvp`);
    await completeAndContinue(page);

    // C: the parts. The map works by keyboard; the mapping shows only when asked.
    await expectStepContract(page, 'מבינים איפה כל חלק עובד', 'איזה חלק של המוצר עושה מה, ואיפה נכנסת הקריאה למודל השפה?', player);
    await expect(ltr(player, 'frontend').first()).toBeVisible();
    await expect(ltr(player, 'Gemini API').first()).toBeVisible();
    const map = page.getByTestId('architecture-map');
    await expect(map).toBeVisible();
    await expect(map.getByRole('group', { name: 'שיוך כל פריט לחלק במוצר' })).toBeVisible();
    await expect(map.getByTestId('arch-model')).toHaveCount(0); // hidden until asked
    await expect(map).not.toContainText('אצלנו:');
    await sortByKeyboard(page, map);
    await expect(map.getByTestId('arch-model')).toHaveCount(0); // choosing does not reveal it
    const compare = map.getByRole('button', { name: 'השוו לגרסה שלנו' });
    await expect(compare).toHaveAttribute('aria-expanded', 'false');
    await compare.focus();
    await page.keyboard.press('Enter');
    await expect(map.getByTestId('arch-model')).toHaveCount(6);
    await expect(map.getByTestId('arch-item-send-button')).toContainText('✓ כמו אצלנו');
    await expect(map.getByTestId('arch-item-api-key')).toContainText('≠ אצלנו אחרת');
    await expect(map.getByTestId('arch-item-api-key')).toContainText('אצלנו: שרת');
    await expect(map.getByTestId('arch-summary')).toContainText('2 מתוך 6 כמו בגרסה שלנו');
    const hide = map.getByRole('button', { name: 'הסתרת הגרסה שלנו' });
    await expect(hide).toHaveAttribute('aria-expanded', 'true');
    await expectNoSidewaysScroll(page, 'step C');
    await shot(page, `${device.name}-lesson-05-C-map`);
    await hide.focus();
    await page.keyboard.press('Space');
    await expect(map.getByTestId('arch-model')).toHaveCount(0);
    await answerText(page, 'l05-flow', '1. מדביקים הודעות ← ממשק 2. שולחים ← שרת 3. חילוץ ← AI API. כשה-AI נכשל: הודעה ברורה. אפשר לדחות: מסד נתונים.');
    await answerCheck(page, 'l05-q3');
    await answerCheck(page, 'l05-key-frontend');
    await completeAndContinue(page);

    // D: SPEC.md with the agent: plan first, ask before assuming, no code.
    await expectStepContract(page, 'כותבים אפיון עם הסוכן', 'איך הופכים את מה שהחלטתם למסמך שהסוכן – וגם אתם – תעבדו לפיו?', player);
    const download = player.getByRole('link', { name: /תבנית האפיון/ });
    await expect(download).toHaveAttribute('href', FIXTURE.assets.spec_template.path);
    await expect(download).toHaveAttribute('download', 'SPEC.md');
    await download.focus();
    await expect(download).toBeFocused(); // reachable by keyboard
    await expect(player.getByText('בקשה לסוכן: ראיון ואפיון, בלי קוד')).toBeVisible();
    await expect(player.getByText('מסלול חלופי: בלי Antigravity')).toBeVisible();
    await expect(ltr(player, 'AGENTS.md').first()).toBeVisible();
    await expectNoSidewaysScroll(page, 'step D');
    await page.getByRole('checkbox', { name: /בתיקיית הצוות יש SPEC.md מלא/ }).check();
    await answerCheck(page, 'l05-assume');
    await shot(page, `${device.name}-lesson-05-D-spec`);
    await completeAndContinue(page);

    // E: wrap-up. The worked example, the exit check, the work product.
    await expectStepContract(page, 'מסכמים', 'מה הצוות יכול להציג ולהסביר על המוצר שהגדיר?', player);
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await expect(player).toContainText('איך ומתי – המרצה יפרסם');
    await expectNoSidewaysScroll(page, 'step E');
    await answerText(page, 'lesson-05-exit', 'הגדרנו משתמש ובעיה, שלוש דוגמאות ומסלול; לא ידוע עדיין אם המשתמשים ירצו.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).not.toContainText('לפי התבנית'); // the homework proposal is not shown
    await shot(page, `${device.name}-lesson-05-E-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('the SPEC.md template downloads with the sha256 in the lesson assets', async ({ page }) => {
  const res = await page.request.get(FIXTURE.assets.spec_template.path);
  expect(res.status()).toBe(200);
  const body = await res.body();
  expect(createHash('sha256').update(body).digest('hex')).toBe(FIXTURE.assets.spec_template.sha256);
  expect(body.equals(readFileSync(SOURCE))).toBe(true);
  expect(body.toString('utf-8')).toContain('## 6. שאלות פתוחות');
});

test('students can’t reach lesson 5 while it is a draft', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-05`);
  expect(draft.status()).toBe(404);
});
