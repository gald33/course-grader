import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type BrowserContext, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed, type SignedInStudent } from './seed';

/* The guided lesson (fixture lesson-2), end to end against the real backend:
 * a signed-in student working through steps, resuming, downloading the data,
 * tracing both trees, logging experiments and committing before the final
 * test, keyboard-only and phone-width use, and the instructor's insights and
 * no-save preview. Each test that saves something signs in as its own seeded
 * student (seed.lesson_students), so no test depends on another's progress.
 * The tests run in order in one worker: the preview test compares the whole
 * class's insights before and after, so nothing else may write meanwhile.
 *
 * Set E2E_SCREENSHOTS_DIR to also save screenshots of representative steps. */

test.describe.configure({ mode: 'default' });

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

/* ---------------- Helpers ---------------- */

type Allowed = { status: number; url: RegExp };

/** Problems the page reports: uncaught errors, console errors, failed
 * requests, and API answers >= 400 other than the ones a test expects. */
async function watchForErrors(page: Page, allowed: Allowed[] = []): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    // A 4xx/5xx is also logged by the browser; it's judged by its response below.
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) problems.push(`console error: ${msg.text()}`);
  });
  page.on('requestfailed', (req) => {
    const reason = req.failure()?.errorText ?? '';
    // Navigating away (reload, a new step's page) cancels requests still in flight.
    if (!reason.includes('ERR_ABORTED')) problems.push(`request failed: ${req.method()} ${req.url()} (${reason})`);
  });
  page.on('response', (res) => {
    const url = res.url();
    if (!url.includes('/api/') || res.status() < 400) return;
    if (allowed.some((a) => a.status === res.status() && a.url.test(url))) return;
    problems.push(`API ${res.status()}: ${res.request().method()} ${url}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

async function signIn(context: BrowserContext, student: SignedInStudent) {
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([{ name: 'cg_student', value: student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }]);
}

function lessonPath(student: SignedInStudent, step?: string) {
  return `/r/${student.token}/lessons/${seed.lesson.slug}${step ? `#step=${step}` : ''}`;
}

const stepHeading = (page: Page) => page.locator('#lesson-step-title');
const questionCard = (page: Page, key: string) => page.locator(`article[aria-labelledby="q-${key}-prompt"]`);
const saveStatus = (page: Page) => page.getByRole('status').first();
const checklist = (page: Page) => page.getByRole('region', { name: 'מה נדרש כדי להשלים את השלב' });

async function waitSaved(page: Page) {
  await expect(saveStatus(page)).toHaveText('✓ נשמר');
}

/** One question: pick an option (by part of its text) and send it. */
async function answer(card: Locator, option: RegExp, button: RegExp = /^(שליחת תשובה|שליחה מחדש)$/) {
  await card.getByRole('radio', { name: option }).check();
  await card.getByRole('button', { name: button }).click();
}

/** The leaf a sample reaches in the exported tree: sklearn's rule, value <= threshold goes left. */
type JsonNode = {
  id: number;
  is_leaf: boolean;
  feature: string | null;
  threshold: number | null;
  left: number | null;
  right: number | null;
  prediction: 0 | 1;
  training_examples: number;
  class_counts: [number, number];
};
function traverse(tree: { root: number; nodes: JsonNode[] }, sample: Record<string, number>) {
  const byId = new Map(tree.nodes.map((n) => [n.id, n]));
  const path: { feature: string; value: number; left: boolean }[] = [];
  let node = byId.get(tree.root)!;
  while (!node.is_leaf) {
    const value = sample[node.feature!];
    const left = value <= node.threshold!;
    path.push({ feature: node.feature!, value, left });
    node = byId.get(left ? node.left! : node.right!)!;
  }
  return { leaf: node, path };
}

function parseCsv(text: string): string[][] {
  return text
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter((line) => line.length > 0)
    .map((line) => line.split(','));
}

/* ---------------- Student ---------------- */

test('signed out: the lesson asks to sign in, and signing in returns to the same step', async ({ page, context }) => {
  const student = seed.lesson_students.trees;
  const problems = await watchForErrors(page, [
    { status: 401, url: /\/api\/r\/[^/]+\/lessons\// },
    { status: 401, url: /\/api\/student-auth\/me$/ }
  ]);
  const target = lessonPath(student, 'data');
  await page.goto(target);

  await expect(page.getByRole('heading', { name: 'צריך להתחבר' })).toBeVisible();
  const login = page.getByRole('link', { name: 'כניסה לחשבון' });
  await expect(login).toHaveAttribute('href', `/login?next=${encodeURIComponent(target)}`);
  // Nothing of the lesson is shown to a signed-out visitor.
  await expect(stepHeading(page)).toHaveCount(0);

  await login.click();
  await expect(page).toHaveURL(/\/login\?next=/);
  // Signing in (the session cookie the login sets) sends the student back.
  await signIn(context, student);
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`${target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`));
  await expect(stepHeading(page)).toContainText('בודקים את הנתונים עם הצ׳טבוט');
  expect(problems).toEqual([]);
});

test('a student completes two steps, reloads, and resumes with answers and feedback kept', async ({ page, context }) => {
  const student = seed.student;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  // The way in: the student's course page links to the published lesson.
  await page.goto(`/r/${student.token}`);
  const entry = page.locator('section').filter({ has: page.getByRole('heading', { name: 'למידה בשיעור' }) });
  await entry.getByRole('link', { name: new RegExp(seed.lesson.title) }).click();
  await expect(page).toHaveURL(new RegExp(`/r/${student.token}/lessons/${seed.lesson.slug}`));

  // A fresh start opens step A.
  await expect(stepHeading(page)).toContainText('מנתונים לחיזוי');
  await expect(page.getByRole('navigation', { name: 'מפת השיעור' })).toContainText('0 מתוך 7 שלבי חובה הושלמו');
  await shot(page, 'desktop-A-orientation');

  // A wrong answer gets feedback for that choice only; the retry is right.
  const target = questionCard(page, 'q_target');
  await answer(target, /מספר הביקורים/);
  await expect(target).toContainText('✗ לא בדיוק');
  await expect(target).not.toContainText('התשובה הנכונה');
  await expect(target).not.toContainText('הסבר:');
  await answer(target, /bought_next_week/);
  await expect(target).toContainText('✓ נכון');
  await expect(target).toContainText('הסבר:');
  await expect(target).toContainText('ניסיונות ששלחת: 2');
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');

  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
  await expect(stepHeading(page)).toContainText('בודקים את הנתונים עם הצ׳טבוט');
  await expect(page).toHaveURL(/#step=data$/);

  // Step B: the self-reported action, a choice and a written answer.
  await page.getByRole('checkbox', { name: /הורדתי את הקובץ/ }).check();
  const missing = questionCard(page, 'q_missing_zero');
  await answer(missing, /תא ריק אינו אפס/);
  await expect(missing).toContainText('✓ נכון');
  const finding = questionCard(page, 'q_data_finding');
  const findingText = 'ראיתי שתי שורות של לקוח 1031 עם אותם ערכים. לפני תיקון הייתי בודק אם זו כפילות או מדידה חוזרת.';
  await finding.getByRole('textbox').fill(findingText);
  await finding.getByRole('button', { name: 'שליחת תשובה' }).click();
  await expect(finding).toContainText('דוגמה לנימוק — לא ציון');
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  await expect(page.getByRole('navigation', { name: 'מפת השיעור' })).toContainText('2 מתוך 7 שלבי חובה הושלמו');
  await waitSaved(page);
  // Acknowledged by the server, so nothing waits in the device's outbox.
  const mirrorKey = `cg-lesson-draft:${student.token}:${seed.lesson.slug}`;
  expect(await page.evaluate((k) => localStorage.getItem(k), mirrorKey)).toBeNull();

  // Open the lesson again without the #step: it resumes at the saved step.
  await page.goto(lessonPath(student));
  await expect(stepHeading(page)).toContainText('בודקים את הנתונים עם הצ׳טבוט');
  await expect(page).toHaveURL(/#step=data$/);
  await expect(page.getByRole('checkbox', { name: /הורדתי את הקובץ/ })).toBeChecked();
  await expect(missing.getByRole('radio', { name: /תא ריק אינו אפס/ })).toBeChecked();
  await expect(missing).toContainText('✓ נכון');
  await expect(finding.getByRole('textbox')).toHaveValue(findingText);
  await expect(finding).toContainText('דוגמה לנימוק — לא ציון');
  await expect(page.getByRole('navigation', { name: 'מפת השיעור' })).toContainText('2 מתוך 7 שלבי חובה הושלמו');

  // And a plain reload keeps step A's answers: the latest is the right one, both tries counted.
  await page.getByRole('button', { name: /^שלב A:/ }).click();
  await page.reload();
  await expect(stepHeading(page)).toContainText('מנתונים לחיזוי');
  await expect(target.getByRole('radio', { name: /bought_next_week/ })).toBeChecked();
  await expect(target).toContainText('✓ נכון');
  await expect(target).toContainText('ניסיונות ששלחת: 2');

  // The lesson list shows where the student stands.
  await page.goto(`/r/${student.token}/lessons`);
  const card = page.getByRole('link', { name: new RegExp(seed.lesson.title) });
  await expect(card).toContainText('בתהליך');
  await expect(card).toContainText('2 מתוך 7 שלבי חובה');
  await expect(card).toContainText('להמשיך');
  expect(problems).toEqual([]);
});

test('the data step downloads the full CSV, and every lesson asset is served as declared', async ({ page, context }) => {
  const student = seed.lesson_students.trees;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  await page.goto(lessonPath(student, 'data'));
  await expect(stepHeading(page)).toContainText('בודקים את הנתונים עם הצ׳טבוט');

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: /הורדת הטבלה המלאה/ }).click()
  ]);
  expect(download.suggestedFilename()).toBe('lesson2-customer-data.csv');
  const rows = parseCsv(readFileSync((await download.path())!, 'utf8'));
  const [header, ...records] = rows;
  expect(header).toEqual(['customer_id', 'visits_30d', 'days_since_purchase', 'bought_next_week']);
  expect(records).toHaveLength(1201);
  expect(records.every((r) => r.length === 4)).toBe(true);
  // Two missing cells.
  expect(records.flat().filter((cell) => cell.trim() === '')).toHaveLength(2);
  // One extra duplicate record (1,201 rows, 1,200 ids): customer 1031.
  const ids = records.map((r) => r[0]);
  expect(new Set(ids).size).toBe(1200);
  expect(ids.filter((id) => id === '1031')).toHaveLength(2);
  // Two rows outside the exercise's declared ranges (visits 0–20, days 0–60).
  const outside = records.filter((r) => {
    const visits = r[1] === '' ? null : Number(r[1]);
    const days = r[2] === '' ? null : Number(r[2]);
    return (visits != null && (visits < 0 || visits > 20)) || (days != null && (days < 0 || days > 60));
  });
  expect(outside.map((r) => r[0]).sort()).toEqual(['1010', '1022']);

  // Every asset the lesson names is there, with its type and exact bytes.
  const payload = await (await page.request.get(`/api/r/${student.token}/lessons/${seed.lesson.slug}`)).json();
  const assets = Object.values(payload.content.assets) as { path: string; filename: string; mime: string; sha256: string }[];
  expect(assets).toHaveLength(6);
  for (const asset of assets) {
    const res = await page.request.get(asset.path);
    expect(res.status(), asset.path).toBe(200);
    expect(res.headers()['content-type'], asset.path).toContain(asset.mime);
    expect(createHash('sha256').update(await res.body()).digest('hex'), asset.path).toBe(asset.sha256);
  }
  const csv = await page.request.get('/lessons/lesson-2/v1/lesson2-customer-data.csv');
  expect(csv.headers()['content-type']).toBe('text/csv; charset=utf-8');
  const notebook = await page.request.get('/lessons/lesson-2/v1/lesson-2-machine-learning-he.ipynb');
  expect(notebook.headers()['content-type']).toBe('application/x-ipynb+json');
  expect(notebook.headers()['content-disposition']).toBe('attachment');
  // No Colab link is configured, so none is offered — only download and upload.
  await expect(page.getByRole('link', { name: /פתיחה בקולאב/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /הורדת המחברת/ }).first()).toHaveAttribute(
    'href',
    '/lessons/lesson-2/v1/lesson-2-machine-learning-he.ipynb'
  );
  expect(problems).toEqual([]);
});

test('the hand-written tree traces customers A and B one branch at a time', async ({ page, context }) => {
  const student = seed.lesson_students.trees;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  await page.goto(lessonPath(student, 'tree'));
  await expect(stepHeading(page)).toContainText('איך עץ החלטה עובד');
  const tree = page.locator('figure').filter({ hasText: 'עץ שכתבנו ביד להמחשה' });
  const path = tree.locator('ol').last();

  // A (4 visits, 8 days): 4 <= 5 → yes, left → leaf "won't buy" after one question.
  await tree.getByRole('button', { name: /לקוח א׳/ }).click();
  await expect(tree).toContainText('לאיזה ענף נלך?');
  await expect(tree).toContainText('הערך הוא 4');
  await tree.getByRole('button', { name: 'כן, קטן או שווה – שמאלה' }).click();
  await expect(tree).toContainText('נכון: 4 קטן מ-5 או שווה לו');
  await expect(tree).toContainText('הגענו לעלה. מה התחזית?');
  await tree.getByRole('button', { name: 'לא יקנה', exact: true }).click();
  await expect(tree).toContainText('נכון: בעלה כתוב ״לא יקנה״.');
  await expect(tree).toContainText('עומק העץ הזה: 2');
  await expect(tree).toContainText('עבר/ה שאלה אחת');
  await expect(path.locator('li')).toHaveCount(1);

  // B (12 visits, 7 days): a wrong branch is caught, then 12 > 5 → right; 7 <= 10 → left → "will buy".
  await tree.getByRole('button', { name: /לקוח ב׳/ }).click();
  await expect(tree).toContainText('הערך הוא 12');
  await tree.getByRole('button', { name: 'כן, קטן או שווה – שמאלה' }).click();
  await expect(tree).toContainText('לא בדיוק. בדקו שוב: האם 12 קטן מ-5 או שווה לו?');
  await tree.getByRole('button', { name: 'לא, גדול – ימינה' }).click();
  await expect(tree).toContainText('נכון: 12 גדול מ-5');
  await expect(tree).toContainText('הערך הוא 7');
  await tree.getByRole('button', { name: 'כן, קטן או שווה – שמאלה' }).click();
  await expect(tree).toContainText('נכון: 7 קטן מ-10 או שווה לו');
  await tree.getByRole('button', { name: 'יקנה', exact: true }).click();
  await expect(tree).toContainText('נכון: בעלה כתוב ״יקנה״.');
  await expect(path.locator('li')).toHaveCount(2);
  await expect(path.locator('li').nth(0)).toContainText('הערך 12 ← לא ← ימינה');
  await expect(path.locator('li').nth(1)).toContainText('הערך 7 ← כן ← שמאלה');
  await shot(page, 'desktop-C-manual-tree');
  expect(problems).toEqual([]);
});

test('the actual tree follows decision-tree-actual.json exactly at the split boundaries', async ({ page, context }) => {
  const student = seed.lesson_students.trees;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  const snapshot = await (await page.request.get('/lessons/lesson-2/v1/decision-tree-actual.json')).json();
  await page.goto(lessonPath(student, 'actual-tree'));
  await expect(stepHeading(page)).toContainText('העץ שהמודל למד בפועל');
  await expect(page.getByText('צילום מצב של המודל')).toBeVisible();
  // The snapshot says what it was trained with, and that Colab doesn't change it.
  await expect(page.getByText('שינוי הגדרות בקולאב לא משנה אותה')).toBeVisible();
  await expect(page.locator('dl').first()).toContainText('max_depth');
  await expect(page.locator('dl').first()).toContainText('data_seed=42');

  const tracer = page.getByRole('region', { name: 'מעקב אחרי לקוח בעץ שנלמד' });
  const leafName = (p: 0 | 1) => snapshot.class_labels_he[String(p)] as string;
  for (const visits of [5, 6, 13, 14]) {
    for (const days of [7, 10, 59, 60]) {
      const expected = traverse(snapshot, { visits_30d: visits, days_since_purchase: days });
      await tracer.locator('#tracer-visits-tree_json').fill(String(visits));
      await tracer.locator('#tracer-days-tree_json').fill(String(days));
      await tracer.getByRole('button', { name: 'מתחילים מעקב' }).click();
      await tracer.getByRole('button', { name: 'כל המסלול' }).click();
      const where = `visits ${visits}, days ${days}`;
      const [no, yes] = expected.leaf.class_counts;
      await expect(tracer, where).toContainText(`הגענו לעלה: ${leafName(expected.leaf.prediction)}.`);
      await expect(tracer, where).toContainText(
        `הגיעו אליו ${expected.leaf.training_examples} דוגמאות אימון: ${no} לא קנו ו-${yes} קנו`
      );
      const steps = tracer.locator('ol li');
      await expect(steps, where).toHaveCount(expected.path.length);
      for (const [i, s] of expected.path.entries()) {
        await expect(steps.nth(i), where).toContainText(s.feature);
        await expect(steps.nth(i), where).toContainText(`הערך ${s.value} ← ${s.left ? 'כן ← שמאלה' : 'לא ← ימינה'}`);
      }
    }
  }

  // The lesson's own examples: (12,7) reaches the second leaf, (14,7) the purchase leaf.
  await tracer.getByRole('button', { name: /14 ביקורים, 7 ימים/ }).click();
  await tracer.getByRole('button', { name: 'מתחילים מעקב' }).click();
  await tracer.getByRole('button', { name: 'הצעד הבא' }).click();
  await expect(tracer.locator('ol li')).toHaveCount(1);
  await expect(tracer).toContainText('השאלה הבאה');
  await tracer.getByRole('button', { name: 'הצעד הבא' }).click();
  await expect(tracer).toContainText('הגענו לעלה: יקנה.');
  await expect(tracer).toContainText('הגיעו אליו 35 דוגמאות אימון: 3 לא קנו ו-32 קנו');
  await shot(page, 'desktop-D-actual-tree');
  await tracer.getByRole('button', { name: /12 ביקורים, 7 ימים/ }).click();
  await tracer.getByRole('button', { name: 'מתחילים מעקב' }).click();
  await tracer.getByRole('button', { name: 'כל המסלול' }).click();
  await expect(tracer).toContainText('הגיעו אליו 36 דוגמאות אימון: 24 לא קנו ו-12 קנו');
  expect(problems).toEqual([]);
});

test('experiments: an impossible percentage is refused per field, keeps the form, then saves; commitment then final result', async ({
  page,
  context
}) => {
  const student = seed.lesson_students.experiments;
  await signIn(context, student);
  const problems = await watchForErrors(page, [{ status: 422, url: /\/experiments\/[0-9a-f-]+$/ }]);
  await page.goto(lessonPath(student, 'colab'));
  await expect(stepHeading(page)).toContainText('ניסויים בקולאב');
  // The two settings to edit are marked in the notebook cell.
  await expect(page.getByText('tree_depth = 2 # @param')).toBeVisible();
  await expect(page.getByText('training_examples = 100 # @param')).toBeVisible();

  // The innermost section with the heading (the step's own section wraps it).
  const log = page.locator('section').filter({ has: page.getByRole('heading', { name: 'יומן הניסויים שלי' }) }).last();
  const form = log.locator('form');
  const hypothesis = 'אני משער שעומק 2 יתאים לצילום המצב משלב D.';
  const observation = 'האימון 83%, האימות 76.2%, וקו הבסיס 54.2%.';
  await form.getByLabel(/^השערה/).fill(hypothesis);
  await form.getByLabel(/^עומק מרבי/).selectOption('2');
  await form.getByLabel(/^דוגמאות אימון/).fill('100');
  await form.getByLabel(/^דיוק אימון/).fill('83');
  await form.getByLabel(/^דיוק אימות/).fill('176.2'); // a typo: not a percentage
  await form.getByLabel(/^קו בסיס/).fill('54.2');
  await form.getByLabel(/^תצפית/).fill(observation);
  await form.getByRole('button', { name: 'שמירת הריצה' }).click();

  await expect(log).toContainText('שום דבר לא נשמר, והטופס נשאר כפי שהוא.');
  await expect(form.getByText('הזינו אחוז בין 0 ל-100')).toBeVisible();
  await expect(form.getByLabel(/^דיוק אימות/)).toHaveAttribute('aria-invalid', 'true');
  await expect(form.getByLabel(/^דיוק אימון/)).toHaveAttribute('aria-invalid', 'false');
  // Every other input is kept as typed.
  await expect(form.getByLabel(/^השערה/)).toHaveValue(hypothesis);
  await expect(form.getByLabel(/^עומק מרבי/)).toHaveValue('2');
  await expect(form.getByLabel(/^דוגמאות אימון/)).toHaveValue('100');
  await expect(form.getByLabel(/^דיוק אימון/)).toHaveValue('83');
  await expect(form.getByLabel(/^דיוק אימות/)).toHaveValue('176.2');
  await expect(form.getByLabel(/^קו בסיס/)).toHaveValue('54.2');
  await expect(form.getByLabel(/^תצפית/)).toHaveValue(observation);
  await expect(log).toContainText('עוד אין ריצות ביומן');

  await form.getByLabel(/^דיוק אימות/).fill('76.2');
  await form.getByRole('button', { name: 'שמירת הריצה' }).click();
  await expect(log).toContainText('✓ הריצה נשמרה ביומן.');
  const run1 = log.locator('li').filter({ hasText: 'ריצה 1' });
  await expect(run1).toContainText('✓ ריצה מלאה');
  await expect(run1).toContainText('76.2%');
  await expect(run1).toContainText('האימות גבוה מקו הבסיס ב-22 נקודות אחוז');
  await expect(form.getByLabel(/^השערה/)).toHaveValue('');

  // A hypothesis alone is saved before the next run (unlimited depth = Colab's 0).
  await log.getByText('ריצות מוצעות').click();
  await log.locator('li').filter({ hasText: 'ללא הגבלת עומק' }).getByRole('button', { name: 'למלא בטופס' }).click();
  await expect(form.getByLabel(/^עומק מרבי/)).toHaveValue('unlimited');
  await form.getByLabel(/^השערה/).fill('בלי הגבלת עומק העץ ישנן את האימון, והאימות ירד.');
  await form.getByRole('button', { name: 'שמירת הריצה' }).click();
  const run2 = log.locator('li').filter({ hasText: 'ריצה 2' });
  await expect(run2).toContainText('חלקית – חסר:');
  await expect(run2).toContainText('ללא הגבלה');
  await shot(page, 'desktop-E-experiments');

  // A half-typed next run is a draft: it is saved (not as a run) and survives
  // leaving for Colab and coming back.
  const draftHypothesis = 'השערה לריצה הבאה: עם 300 דוגמאות הפער יקטן.';
  await form.getByLabel(/^השערה/).fill(draftHypothesis);
  await expect(form).toContainText('✓ הטיוטה נשמרה (הריצה עוד לא נשמרה ביומן)');
  await page.goto('about:blank');
  await page.goto(lessonPath(student));
  await expect(stepHeading(page)).toContainText('ניסויים בקולאב');
  await expect(form.getByLabel(/^השערה/)).toHaveValue(draftHypothesis);
  // Saved on the server: both records, in order.
  await expect(log.locator('li').filter({ hasText: 'ריצה 1' })).toContainText('✓ ריצה מלאה');
  await expect(log.locator('li').filter({ hasText: 'ריצה 2' })).toContainText('חלקית');
  await expect(log.locator('li').filter({ hasText: 'ריצה 3' })).toHaveCount(0);

  // Step F: commit to settings before the final test, then record its result.
  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
  await expect(stepHeading(page)).toContainText('בודקים בהגינות');
  const panel = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: 'הבחירה שלי לפני המבחן הסופי' }) })
    .last();
  await expect(panel).toContainText('האתר לא רואה את קולאב ולא יכול לאכוף מה קורה שם');
  const fromRun = panel.getByLabel(/^בחירה מריצה שמורה/);
  const run1Value = await fromRun.locator('option', { hasText: /^ריצה 1:/ }).getAttribute('value');
  await fromRun.selectOption(run1Value!);
  await expect(panel.getByLabel(/^עומק מרבי/)).toHaveValue('2');
  await expect(panel.getByLabel(/^דוגמאות אימון/)).toHaveValue('100');
  await panel.getByLabel(/^נימוק/).fill('דיוק האימות הגבוה ביותר ביומן, והפער מהאימון קטן.');
  await panel.getByRole('button', { name: 'שמירת הבחירה' }).click();
  await expect(panel).toContainText('✓ הבחירה נשמרה.');
  await expect(panel.locator('li').filter({ hasText: 'בחירה 1' })).toContainText('ממתינה לתוצאת המבחן');

  await panel.getByLabel(/^דיוק/).fill('74');
  await panel.getByRole('button', { name: 'שמירת התוצאה' }).click();
  await expect(panel).toContainText('✓ תוצאת המבחן נשמרה.');
  const choice1 = panel.locator('li').filter({ hasText: 'בחירה 1' });
  await expect(choice1).toContainText('נרשמה תוצאת מבחן');
  await expect(choice1).toContainText('דיוק 74%');

  // Choosing again after seeing the final result keeps the first choice and flags the new one.
  await panel.getByRole('button', { name: /^שינוי הבחירה/ }).click();
  await expect(panel).toContainText('כבר רשמת תוצאה של המבחן הסופי');
  await panel.getByLabel(/^עומק מרבי/).selectOption('3');
  await panel.getByLabel(/^דוגמאות אימון/).fill('100');
  await panel.getByLabel(/^נימוק/).fill('אחרי המבחן רציתי לנסות עומק 3.');
  await panel.getByRole('button', { name: 'שמירת הבחירה' }).click();
  const choice2 = panel.locator('li').filter({ hasText: 'בחירה 2' });
  await expect(choice2).toContainText('נבחר אחרי שנחשפת לתוצאת המבחן — המבחן כבר אינו בדיקה עצמאית');
  await expect(choice1).not.toContainText('נבחר אחרי שנחשפת');
  await shot(page, 'desktop-F-commitment');
  expect(problems).toEqual([]);
});

test('a lost connection and a stale second tab never lose work', async ({ page, context }) => {
  const student = seed.lesson_students.resilience;
  await signIn(context, student);
  const problems = await watchForErrors(page, [{ status: 409, url: /\/progress$/ }]);
  const mirrorKey = `cg-lesson-draft:${student.token}:${seed.lesson.slug}`;
  await page.goto(lessonPath(student, 'data'));
  await expect(stepHeading(page)).toContainText('בודקים את הנתונים עם הצ׳טבוט');
  await waitSaved(page);

  // A second tab opens the same step, then falls behind the first one.
  const tab2 = await context.newPage();
  await tab2.goto(lessonPath(student, 'data'));
  await expect(stepHeading(tab2)).toContainText('בודקים את הנתונים עם הצ׳טבוט');
  const firstDraft = 'טיוטה מהלשונית הראשונה: יש שורה כפולה.';
  const finding = questionCard(page, 'q_data_finding');
  await finding.getByRole('textbox').fill(firstDraft);
  await expect(finding).toContainText('✓ הטיוטה נשמרה (עדיין לא נשלחה כתשובה)');

  // The stale tab saves: the server answers 409, the tab takes the newer state,
  // puts its own change on top and saves again — both changes are kept.
  const stale = tab2.waitForResponse((r) => r.url().endsWith('/progress') && r.status() === 409);
  await tab2.getByRole('checkbox', { name: /הורדתי את הקובץ/ }).check();
  await stale;
  await waitSaved(tab2);
  await expect(questionCard(tab2, 'q_data_finding').getByRole('textbox')).toHaveValue(firstDraft);
  await tab2.close();
  await page.reload();
  await expect(page.getByRole('checkbox', { name: /הורדתי את הקובץ/ })).toBeChecked();
  await expect(finding.getByRole('textbox')).toHaveValue(firstDraft);

  // The connection drops: the change is not shown as saved, stays on the device
  // (also across a reload) and goes out with the retry once the server is back.
  let offline = true;
  await page.route('**/progress', (route) => (offline ? route.abort('internetdisconnected') : route.continue()));
  const offlineDraft = 'כתבתי את זה בלי חיבור לשרת.';
  await finding.getByRole('textbox').fill(offlineDraft);
  await expect(saveStatus(page)).toContainText('לא נשמר – נסו שוב');
  await expect(finding).toContainText('הטיוטה לא נשמרה בשרת – היא שמורה במכשיר הזה');
  expect(await page.evaluate((k) => localStorage.getItem(k), mirrorKey)).toContain(offlineDraft);
  await page.reload();
  await expect(finding.getByRole('textbox')).toHaveValue(offlineDraft);
  await expect(saveStatus(page)).toContainText('לא נשמר – נסו שוב');
  // "Try again" sends it again at once (still offline here, so it fails again, losing nothing)…
  const resent = page.waitForRequest((r) => r.url().endsWith('/progress'));
  await page.getByRole('button', { name: 'ניסיון חוזר' }).click();
  await resent;
  await expect(saveStatus(page)).toContainText('לא נשמר – נסו שוב');
  // …and once the server is reachable again, the automatic retry delivers it.
  offline = false;
  await expect(saveStatus(page)).toHaveText('✓ נשמר', { timeout: 15_000 });
  expect(await page.evaluate((k) => localStorage.getItem(k), mirrorKey)).toBeNull();
  const saved = await (await page.request.get(`/api/r/${student.token}/lessons/${seed.lesson.slug}`)).json();
  expect(saved.progress.drafts['q:q_data_finding']).toBe(offlineDraft);
  expect(saved.progress.acks).toEqual(['csv_downloaded']);
  // A draft is not an answer.
  expect(saved.questions.q_data_finding.attempts).toBe(0);
  expect(problems.filter((p) => !p.includes('ERR_INTERNET_DISCONNECTED'))).toEqual([]);
});

test('keyboard only: the lesson map, the manual tree, and next/back', async ({ page, context }) => {
  const student = seed.lesson_students.navigation;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  await page.goto(lessonPath(student, 'orientation'));
  await expect(stepHeading(page)).toContainText('מנתונים לחיזוי');

  type Focused = { label: string; text: string; outline: string };
  const focused = () =>
    page.evaluate((): Focused => {
      const el = document.activeElement as HTMLElement | null;
      return {
        label: el?.getAttribute('aria-label') ?? '',
        text: (el?.textContent ?? '').replace(/\s+/g, ' ').trim(),
        outline: el ? getComputedStyle(el).outlineStyle : ''
      };
    });
  const tabTo = async (match: (f: Focused) => boolean, key = 'Tab', max = 250) => {
    for (let i = 0; i < max; i++) {
      await page.keyboard.press(key);
      const f = await focused();
      if (match(f)) return f;
    }
    throw new Error('the keyboard never reached the expected control');
  };

  // The lesson map: Tab to step C, Enter. The focus moves to the new step's heading.
  const mapC = await tabTo((f) => f.label.startsWith('שלב C:'));
  expect(mapC.outline).not.toBe('none'); // a visible focus ring
  await page.keyboard.press('Enter');
  await expect(stepHeading(page)).toContainText('איך עץ החלטה עובד');
  await expect(stepHeading(page)).toBeFocused();
  await expect(page).toHaveURL(/#step=tree$/);

  // The manual tree works from the keyboard too.
  await tabTo((f) => f.text.includes('לקוח א׳'));
  await page.keyboard.press('Space');
  await tabTo((f) => f.label === 'כן, קטן או שווה – שמאלה');
  await page.keyboard.press('Enter');
  await tabTo((f) => f.text === 'לא יקנה');
  await page.keyboard.press('Enter');
  await expect(page.getByText('נכון: בעלה כתוב ״לא יקנה״.')).toBeVisible();

  // Next (on the left in RTL), then back.
  const next = await tabTo((f) => f.text.includes('לשלב הבא'));
  expect(next.text).toContain('D ·');
  await page.keyboard.press('Enter');
  await expect(stepHeading(page)).toContainText('העץ שהמודל למד בפועל');
  await expect(stepHeading(page)).toBeFocused();
  await tabTo((f) => f.text.includes('הקודם') && f.text.includes('C ·'));
  await page.keyboard.press('Enter');
  await expect(stepHeading(page)).toContainText('איך עץ החלטה עובד');

  // The full map list, opened from the keyboard, reaches the optional extension.
  await tabTo((f) => f.text === 'כל השלבים', 'Shift+Tab');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: 'תצוגה מקוצרת' })).toHaveAttribute('aria-expanded', 'true');
  await tabTo((f) => f.text.includes('הרחבה: אשכול לקוחות'));
  await page.keyboard.press('Enter');
  await expect(stepHeading(page)).toContainText('הרחבה: אשכול לקוחות');
  await expect(page.locator('article').first()).toContainText('הרחבה לבחירה');
  await expect(page).toHaveURL(/#step=clustering$/);
  expect(problems).toEqual([]);
});

test('a 375px-wide phone never scrolls the page sideways, on any step', async ({ page, context }) => {
  const student = seed.lesson_students.navigation;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(lessonPath(student, 'orientation'));
  await expect(stepHeading(page)).toContainText('מנתונים לחיזוי');

  const steps: { key: string; title: string }[] = [
    { key: 'orientation', title: 'מנתונים לחיזוי' },
    { key: 'data', title: 'בודקים את הנתונים עם הצ׳טבוט' },
    { key: 'tree', title: 'איך עץ החלטה עובד' },
    { key: 'actual-tree', title: 'העץ שהמודל למד בפועל' },
    { key: 'colab', title: 'ניסויים בקולאב' },
    { key: 'evaluate', title: 'בודקים בהגינות' },
    { key: 'wrap-up', title: 'בדיקת הבנה אישית וסיכום' },
    { key: 'clustering', title: 'הרחבה: אשכול לקוחות' }
  ];
  for (const s of steps) {
    await page.getByRole('button', { name: new RegExp(`^שלב ${s.key === 'clustering' ? '\\+' : '[A-G]'}: ${s.title}`) }).click();
    await expect(stepHeading(page)).toContainText(s.title);
    if (s.key === 'actual-tree') await expect(page.getByText('צילום מצב של המודל')).toBeVisible();
    // Expanders open too: nothing hidden inside them may push the page wider.
    await page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
    if (s.key === 'tree') {
      await page.getByRole('button', { name: /לקוח ב׳/ }).click();
      await page.getByRole('button', { name: 'לא, גדול – ימינה' }).click();
    }
    if (s.key === 'actual-tree') {
      await page.getByRole('button', { name: 'מתחילים מעקב' }).click();
      await page.getByRole('button', { name: 'כל המסלול' }).click();
    }
    const width = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      view: window.innerWidth
    }));
    expect(width.doc, `step ${s.key}`).toBeLessThanOrEqual(width.view);
    expect(width.body, `step ${s.key}`).toBeLessThanOrEqual(width.view);
    if (['orientation', 'tree', 'actual-tree', 'colab', 'evaluate'].includes(s.key)) await shot(page, `mobile-${s.key}`);
  }
  expect(problems).toEqual([]);
});

/* ---------------- Instructor ---------------- */

test('instructor insights show a student’s first wrong answer, kept apart from the later right one', async ({
  page,
  context,
  browser
}) => {
  const student = seed.lesson_students.insights;
  await signIn(context, student);
  const problems = await watchForErrors(page);
  await page.goto(lessonPath(student, 'tree'));
  const depth = questionCard(page, 'q_depth');
  await answer(depth, /כי ללקוח א׳ הספיקה שאלה אחת/);
  await expect(depth).toContainText('✗ לא בדיוק');
  await answer(depth, /זה מספר השאלות המרבי במסלול אחד/);
  await expect(depth).toContainText('✓ נכון');

  // The instructor: a separate browser session, no student cookie.
  const instructorContext = await browser.newContext();
  const instructor = await instructorContext.newPage();
  const instructorProblems = await watchForErrors(instructor);
  await instructor.setViewportSize({ width: 1440, height: 1000 });
  await instructor.goto(`/course/${seed.course.id}`);
  await instructor.locator('.nav-step').filter({ hasText: 'Lessons' }).click();
  const breakdown = instructor
    .locator('div')
    .filter({ has: instructor.getByRole('heading', { name: 'Where understanding breaks down' }) })
    .filter({ hasText: 'Lowest first-try results' })
    .last();
  await expect(breakdown).toBeVisible();
  const row = breakdown.getByRole('button').filter({ hasText: 'q_depth' });
  await expect(row).toContainText('0 of 1 right first try (0%)');
  await expect(row).toContainText('depth=one-customer-path');

  const table = instructor.locator('#lesson-q-q_depth');
  await expect(table).toContainText('0/1');
  await table.getByRole('button', { name: /^Details/ }).click();
  const detail = instructor.locator('#lesson-q-detail-q_depth');
  await expect(detail).toContainText('depth=one-customer-path');

  // The student's path: the first try is marked, the correction is "after feedback".
  await instructor.getByRole('button', { name: student.name, exact: true }).click();
  const drawer = instructor.getByRole('dialog');
  await expect(drawer).toContainText(student.name);
  const tries = drawer.locator('li').filter({ hasText: 'q_depth' });
  await expect(tries).toHaveCount(2);
  await expect(tries.nth(0)).toContainText('first try');
  await expect(tries.nth(0)).toContainText('✗ incorrect');
  await expect(tries.nth(1)).toContainText('after feedback');
  await expect(tries.nth(1)).toContainText('✓ correct');
  await instructor.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await shot(instructor, 'desktop-instructor-insights');
  await instructorContext.close();
  expect(problems).toEqual([]);
  expect(instructorProblems).toEqual([]);
});

test('instructor preview renders the lesson with real feedback and creates no student records', async ({ page }) => {
  const problems = await watchForErrors(page);
  const insights = `/api/courses/${seed.course.id}/lessons/${seed.lesson.id}/insights?include_test=true`;
  const before = await (await page.request.get(insights)).json();

  const calls: string[] = [];
  page.on('request', (req) => {
    if (req.url().includes('/api/')) calls.push(`${req.method()} ${new URL(req.url()).pathname}`);
  });
  await page.goto(`/course/${seed.course.id}/lessons/${seed.lesson.id}/preview?version=${seed.lesson.version_number}`);
  await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
  await expect(page.getByText('תצוגה מקדימה – שום דבר לא נשמר')).toBeVisible();
  await expect(stepHeading(page)).toContainText('מנתונים לחיזוי');

  const target = questionCard(page, 'q_target');
  await answer(target, /customer_id/);
  await expect(target).toContainText('✗ לא בדיוק');
  await answer(target, /bought_next_week/);
  await expect(target).toContainText('✓ נכון');
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
  await page.getByRole('checkbox', { name: /הורדתי את הקובץ/ }).check();
  await questionCard(page, 'q_data_finding').getByRole('textbox').fill('טיוטה בתצוגה המקדימה – לא נשמרת בשום מקום.');
  // The peer-review link leads nowhere in the preview.
  await page.getByRole('button', { name: /^שלב A:/ }).click();
  await expect(page.getByText('(בתצוגה המקדימה הקישור לא פעיל)')).toBeVisible();

  expect(calls.filter((c) => c.includes('/api/r/'))).toEqual([]);
  expect(calls.filter((c) => !c.startsWith('GET ') && !c.endsWith('/preview/evaluate'))).toEqual([]);
  expect(calls.filter((c) => c.endsWith('/preview/evaluate')).length).toBeGreaterThanOrEqual(2);
  expect(await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('cg-lesson-draft')))).toEqual([]);

  const after = await (await page.request.get(insights)).json();
  expect(after).toEqual(before);
  expect(problems).toEqual([]);
});
