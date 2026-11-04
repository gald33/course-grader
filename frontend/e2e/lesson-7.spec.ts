import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Lesson 7 of the 42052 plan ("מחברים יכולת AI למוצר"), authored in the
 * repository: the instructor previews the whole draft inside the lesson's own
 * page, in Hebrew, right to left, on a desktop and a phone, by keyboard (every
 * step's goal, action, checkpoint and next step; the contract with its two
 * JSON examples; the key step with Google's docs and the labelled mock route;
 * output checks; the failure switch; the worked example and the exit check).
 * The seed loads FAKE keys (last option "right"); the real keys are private and
 * never in this repository. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

const REPO = path.join(__dirname, '..', '..');
const SOURCE_ENV = path.join(REPO, 'content/course-42052/materials/lesson-07/bakery-ai-reference/.env.example');
type AssetInfo = { path: string; filename: string; sha256: string };
const FIXTURE = JSON.parse(
  readFileSync(path.join(REPO, 'backend/app/lessons/content/course-42052/lesson-07.json'), 'utf-8')
) as { assets: { env_example: AssetInfo; reference_zip: AssetInfo } };

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
  await expect(radios).toHaveCount(3);
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

/** Free text by keyboard: type into the focused box, Tab to send, Enter. */
async function answerTextByKeyboard(page: Page, key: string, text: string) {
  const card = questionCard(page, key);
  await card.getByRole('textbox').focus();
  await page.keyboard.type(text);
  const send = card.getByRole('button', { name: 'שליחת תשובה' });
  await send.focus();
  await page.keyboard.press('Enter');
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

/** Step done; the next step is opened by keyboard. */
async function completeAndContinue(page: Page) {
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  const next = page.getByRole('button', { name: /^לשלב הבא/ });
  await next.focus();
  await page.keyboard.press('Enter');
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
  test(`lesson 7 previews end to end in Hebrew, right to left, on a ${device.name}`, async ({ page }) => {
    const problems = await watchForErrors(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    const lessonPage = `/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-07']}`;
    await page.goto(`${lessonPage}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /Back to lesson/ })).toHaveAttribute('href', lessonPage);
    const player = page.locator('div[dir="rtl"][lang="he"]').first();
    await expect(player).toBeVisible();

    // A: the contract. Two JSON examples; JSON, schema and structured output explained.
    await expectStepContract(page, 'הבקשה והפלט הם חוזה עבודה', 'מה בדיוק השרת שולח לשירות ה-AI, ומה הוא מצפה לקבל בחזרה?', player);
    await expect(player.getByText('מה צריך לפני שמתחילים')).toBeVisible();
    await expect(ltr(player, /^JSON$/)).toBeVisible();
    await expect(ltr(player, 'structured output')).toBeVisible();
    await expect(page.getByRole('table', { name: 'החוזה של המאפייה: השדות בהזמנה' })).toContainText('needs_clarification');
    await expect(player.locator('pre').filter({ hasText: '"pickup_time": null' })).toBeVisible();
    await expect(player.locator('pre').filter({ hasText: '"pickup_time": "09:00"' })).toBeVisible();
    await expect(player.getByText('בקשה לסוכן: חוזה ה-AI ב-SPEC.md, בלי קוד')).toBeVisible();
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await expectNoSidewaysScroll(page, 'step A');
    await answerTextByKeyboard(page, 'l07-contract-log', '{ "customer": "מיכל", "items": [{ "product": "עוגיות", "quantity": 3 }], "pickup_time": null, "needs_clarification": true }');
    await answerCheckByKeyboard(page, 'l07-q1');
    await answerCheckByKeyboard(page, 'l07-null');
    await shot(page, `${device.name}-lesson-07-A-contract`);
    await completeAndContinue(page);

    // B: the key, safely. Google's docs with the date checked; synthetic data only; a labelled mock route.
    await expectStepContract(page, 'מחברים שירות בלי לחשוף מפתח', 'איך השרת פונה ל-Gemini API – בלי שהמפתח יגיע לדפדפן או למאגר?', player);
    await expect(player.getByText('מה בדקנו בתיעוד של Google (4 בנובמבר 2026):')).toBeVisible();
    const facts = player.getByRole('listitem').filter({ hasText: /^(איך מקבלים מפתח|זמינות בישראל|גיל|ספרייה|מודל|פלט מובנה|מגבלות שימוש):/ });
    await expect(facts).toHaveCount(7);
    await expect(facts.nth(1)).toContainText('ישראל ברשימת האזורים');
    await expect(facts.nth(2)).toContainText('מגיל 18 ומעלה');
    await expect(facts.nth(3)).toContainText('@google/genai');
    await expect(facts.nth(6)).toContainText('aistudio.google.com/docs/rate-limits');
    await expect(player.getByText('בשכבה החינמית – רק נתונים בדויים')).toBeVisible();
    await expect(ltr(player, 'environment variable')).toBeVisible();
    const envDownload = player.getByRole('link', { name: /תבנית הגדרות/ });
    await expect(envDownload).toHaveAttribute('href', FIXTURE.assets.env_example.path);
    await expect(envDownload).toHaveAttribute('download', 'env.example');
    await envDownload.focus();
    await expect(envDownload).toBeFocused();
    await expect(player.getByText('בקשה לסוכן: קריאה אחת מהשרת במקום ה-stub')).toBeVisible();
    await expect(player.getByText('מסלול חלופי: אין לי מפתח (גיל, חשבון או זמינות)')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step B');
    await expect(player).toContainText('הדגמה ללא מודל חי'); // the fallback route, opened above
    const ack = page.getByRole('checkbox', { name: /המפתח שלי נמצא רק ב-/ });
    await ack.focus();
    await page.keyboard.press('Space');
    await expect(ack).toBeChecked();
    await answerCheck(page, 'l07-q2');
    await answerCheck(page, 'l07-key-where');
    await answerCheck(page, 'l07-free-data');
    await shot(page, `${device.name}-lesson-07-B-secrets`);
    await completeAndContinue(page);

    // C: check what came back. Validation, instruction in data, tool calling; the reference to compare with.
    await expectStepContract(page, 'בודקים מה חזר מהמודל', 'איך המוצר יודע שהתשובה מהמודל טובה מספיק כדי להציג אותה?', player);
    await expect(ltr(player, 'function calling')).toBeVisible();
    await expect(player.getByText('המודל מציע פעולה; השרת שלכם מחליט ומרשה.')).toBeVisible();
    const cases = page.getByRole('table', { name: 'ארבעה מקרים לבדיקה, בדוגמת המאפייה' });
    await expect(cases).toContainText('הוראה בתוך הנתונים');
    await expect(cases).toContainText('מיכל רוצה 3 עוגיות למחר');
    await expect(player.getByText('רשות: מימוש לדוגמה להשוואה')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step C');
    const zip = player.getByRole('link', { name: /מימוש לדוגמה: המאפייה עם AI/ });
    await expect(zip).toHaveAttribute('href', FIXTURE.assets.reference_zip.path);
    await answerText(page, 'l07-cases', 'תקין: דנה 4 לחמניות 09:00, התקבל. חסר: מיכל, null, לבירור. לא תקין: -2 נדחה. הוראה: נועה, הזמנה בלבד. מקור: הדגמה.');
    await answerCheck(page, 'l07-q3');
    await answerCheck(page, 'l07-negative');
    await shot(page, `${device.name}-lesson-07-C-output`);
    await completeAndContinue(page);

    // D: when the service fails. Error codes, timeout, rate limit, bounded retry; the labelled switch.
    await expectStepContract(page, 'כשל חיצוני הוא מצב שימוש', 'מה המשתמש רואה כששירות ה-AI עמוס, איטי או לא זמין?', player);
    await expect(ltr(player, 'rate limit')).toBeVisible();
    await expect(player.locator('pre').filter({ hasText: 'AI_FORCE_ERROR=429' })).toBeVisible();
    await expect(player.getByText('בקשה לסוכן: מתג כשל, ניסיון חוזר מוגבל ומצבי מסך')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step D');
    await answerText(page, 'l07-failure-log', 'המתנה: מעבד… כפתור: נעול. הודעה: השירות עמוס (429). ניסיונות: 3.');
    await answerCheck(page, 'l07-429');
    await answerCheck(page, 'l07-double');
    await shot(page, `${device.name}-lesson-07-D-failure`);
    await completeAndContinue(page);

    // E: wrap-up. The worked example, the concrete exit question, the work product.
    await expectStepContract(page, 'מסכמים', 'מה הצוות יכול להראות: קריאה מהשרת, פלט שנבדק, ותרחיש כשל?', player);
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.getByText('לסיום: במילים שלכם')).toBeVisible();
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await expectNoSidewaysScroll(page, 'step E');
    await answerText(page, 'lesson-07-exit', 'בדקנו שהכמות גדולה מ-0 ושהשעה כתובה בהודעה; בכשל מוצגת הודעה ברורה והכפתור נעול.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).not.toContainText('תרחיש כשל + '); // the homework proposal is not shown
    await shot(page, `${device.name}-lesson-07-E-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('lesson 7 downloads match the sha256 in the lesson assets and carry no key', async ({ page }) => {
  const env = await page.request.get(FIXTURE.assets.env_example.path);
  expect(env.status()).toBe(200);
  const envBody = await env.body();
  expect(createHash('sha256').update(envBody).digest('hex')).toBe(FIXTURE.assets.env_example.sha256);
  expect(envBody.equals(readFileSync(SOURCE_ENV))).toBe(true);
  expect(envBody.toString('utf-8')).toMatch(/^GEMINI_API_KEY=$/m);

  const zip = await page.request.get(FIXTURE.assets.reference_zip.path);
  expect(zip.status()).toBe(200);
  const zipBody = await zip.body();
  expect(createHash('sha256').update(zipBody).digest('hex')).toBe(FIXTURE.assets.reference_zip.sha256);
  expect(zipBody.toString('latin1')).not.toMatch(/AIza[0-9A-Za-z_-]{35}/);
});

test('students can’t reach lesson 7 while it is a draft', async ({ page, context }) => {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([
    { name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }
  ]);
  const draft = await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-07`);
  expect(draft.status()).toBe(404);
});
