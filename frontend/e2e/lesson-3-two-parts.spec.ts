import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* Session 3 of the 42052 plan in two REQUIRED lessons, previewed by the
 * instructor in order, on a 390 px phone and a 1280 px desktop:
 *   part 1 = lesson-03         neuron → a network that learns → embeddings → wrap-up
 *   part 2 = lesson-03-deeper  tokens → next token → attention → transformer → chatbot → grounding → wrap-up
 * Each step: its goal, one required action on the page (a widget, operated by
 * keyboard where it matters), the checks, the next step. The chatbot appears
 * only in part 2's grounding step. The seed loads FAKE keys (last option
 * "right"); the real keys are private. No widget leaves our own origin. */

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

async function watch(page: Page): Promise<string[]> {
  const problems: string[] = [];
  const base = new URL(test.info().project.use.baseURL!);
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) problems.push(`console error: ${msg.text()}`);
  });
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.url()}`);
  });
  page.on('request', (req) => {
    const url = new URL(req.url());
    if (url.hostname !== base.hostname && !/^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname) && url.protocol.startsWith('http')) {
      problems.push(`left our origin: ${req.url()}`);
    }
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

const heading = (page: Page) => page.locator('#lesson-step-title');
const questionCard = (page: Page, key: string) => page.locator(`article[aria-labelledby="q-${key}-prompt"]`);
const checklist = (page: Page) => page.getByRole('region', { name: 'מה נדרש כדי להשלים את השלב' });
const SEND = /^(שליחת תשובה|שליחה מחדש)$/;
const copyPrompt = (page: Page) => page.getByRole('button', { name: 'העתקת הבקשה' });

/** FAKE keys: the last option is "right". With `wrongFirst`, a wrong answer first shows the right option. */
async function answer(page: Page, key: string, wrongFirst = false) {
  const card = questionCard(page, key);
  const radios = card.getByRole('radio');
  if (wrongFirst) {
    await radios.first().check();
    await card.getByRole('button', { name: SEND }).click();
    await expect(card).toContainText('✗ לא בדיוק');
    await expect(card).toContainText('התשובה הנכונה');
  }
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

async function noSideways(page: Page, where: string) {
  await page.evaluate(() => document.querySelectorAll('details').forEach((d) => (d.open = true)));
  const w = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, body: document.body.scrollWidth, view: window.innerWidth }));
  expect(w.doc, where).toBeLessThanOrEqual(w.view);
  expect(w.body, where).toBeLessThanOrEqual(w.view);
}

async function next(page: Page) {
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
}

async function step(page: Page, player: Locator, title: string, goal: string) {
  await expect(heading(page)).toContainText(title);
  await expect(player.getByText(goal)).toBeVisible();
  await expect(player.getByText('**הפעולה:**')).toHaveCount(0); // markup rendered, never shown raw
}

async function focusAndPress(locator: Locator, key: string) {
  await locator.focus();
  await expect(locator).toBeFocused();
  await locator.press(key);
}

const COLAB_GITHUB = 'https://colab.research.google.com/github/gald33/course-grader/blob/main/frontend/public';

/** The step's Colab block: a visible "open in Colab" button straight to THIS
 * step's notebook (which exists in the repository), and its download. */
async function colabStep(page: Page, player: Locator, notebook: string) {
  const block = player.locator('section[data-colab-block]');
  await expect(block).toHaveCount(1);
  const button = block.getByRole('link', { name: /פתיחה בקולאב/ });
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute('href', `${COLAB_GITHUB}${notebook}`);
  await expect(button).toHaveAttribute('target', '_blank');
  await expect(block.getByRole('link', { name: /הורדת המחברת/ })).toHaveAttribute('href', notebook);
  const res = await page.request.get(notebook);
  expect(res.status(), notebook).toBe(200);
  expect((await res.json()).cells.length, notebook).toBeGreaterThan(3);
  await expect(player).toContainText('מחברת לשלב הזה בלבד');
}

async function open(page: Page, slug: string, device: { width: number; height: number }) {
  await page.setViewportSize({ width: device.width, height: device.height });
  await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons[slug]}/preview`);
  await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
  const player = page.locator('div[dir="rtl"][lang="he"]').first();
  await expect(player).toBeVisible();
  return player;
}

const DEVICES = [
  { name: 'phone', width: 390, height: 844 },
  { name: 'desktop', width: 1280, height: 900 }
];

for (const device of DEVICES) {
  test(`part 1 (lesson-03) previews end to end, widgets by keyboard, on a ${device.name}`, async ({ page }) => {
    const problems = await watch(page);
    const player = await open(page, 'lesson-03', device);
    await expect(player).toContainText('חלק 1');
    await expect(player).not.toContainText('רשות – נסו בעצמכם');

    // A: one neuron — the slider moved by keyboard flips the decision.
    await step(page, player, 'נוירון אחד', 'מה בעצם מחשב «נוירון» בתוכנה?');
    await expect(player).toContainText('שני חלקים, ושניהם חובה');
    const neuron = page.getByTestId('neuron-playground');
    const out = neuron.getByTestId('neuron-output');
    await expect(out).toHaveAttribute('data-on', '0'); // 0.5×6 − 1×3 − 2 = −2
    const orders = neuron.getByRole('slider', { name: /^הזמנות מראש למחר/ });
    await expect(orders).toHaveAttribute('dir', 'ltr');
    await orders.focus();
    for (let i = 0; i < 4; i += 1) await page.keyboard.press('ArrowUp'); // 10 orders: 5 − 3 − 2 = 0
    await expect(neuron.getByTestId('neuron-sum')).toContainText('= 0');
    await expect(out).toHaveAttribute('data-on', '1');
    await colabStep(page, player, '/lessons/lesson-03/v3/lesson-3-part-1-a-neuron-he.ipynb');
    await expect(copyPrompt(page)).toHaveCount(0); // no chatbot task in part 1
    await noSideways(page, '1A');
    await shot(page, `${device.name}-part1-A-neuron`);
    await answer(page, 'd-neuron-weight', true);
    await answer(page, 'd-neuron-who');
    await next(page);

    // B: a network that learns — parameters defined here; training steps lower the errors.
    await step(page, player, 'רשת שלומדת', 'איך המשקלים נקבעים בלי שמישהו כותב אותם?');
    await colabStep(page, player, '/lessons/lesson-03/v3/lesson-3-part-1-b-network-he.ipynb');
    await expect(player).toContainText('נקראים **פרמטרים**'.replace(/\*\*/g, ''));
    const status = page.getByTestId('training-demo').getByTestId('training-status');
    await expect(status).toContainText('טעויות: 22 מתוך 24');
    await focusAndPress(page.getByRole('button', { name: 'צעד אימון אחד' }), 'Enter');
    await expect(status).toContainText('צעדי אימון: 1');
    await page.getByRole('button', { name: '10 צעדים' }).click();
    expect(Number((await status.innerText()).match(/טעויות: (\d+)/)![1])).toBeLessThanOrEqual(3);
    await expect(copyPrompt(page)).toHaveCount(0);
    await noSideways(page, '1B');
    await shot(page, `${device.name}-part1-B-network`);
    await answer(page, 'd-train-step');
    await answer(page, 'd-after-training');
    await answer(page, 'd-params');
    await next(page);

    // C: embeddings — neighbours by full-dimension cosine, chosen by keyboard.
    await step(page, player, 'ייצוגים', 'איך מודל יודע שמילים «דומות»?');
    await colabStep(page, player, '/lessons/lesson-03/v3/lesson-3-part-1-c-embeddings-he.ipynb');
    const map = page.getByTestId('embedding-map');
    const neighbours = map.getByTestId('embedding-neighbors');
    await expect(neighbours.locator('li').first()).toContainText('bread');
    await map.getByRole('button', { name: 'לחם', exact: true }).focus();
    await page.keyboard.press('ArrowLeft'); // RTL: next word, «עוגה»
    await expect(neighbours.locator('li').first()).toContainText('cake');
    await map.getByRole('button', { name: 'tomorrow', exact: true }).click();
    const clipped = await map.locator('svg[role="img"]').evaluate((svg) => {
      const vb = (svg as SVGSVGElement).viewBox.baseVal;
      return Array.from(svg.querySelectorAll('text'))
        .filter((t) => {
          const b = (t as SVGTextElement).getBBox();
          return b.x < vb.x - 0.5 || b.x + b.width > vb.x + vb.width + 0.5;
        })
        .map((t) => t.textContent);
    });
    expect(clipped, 'map labels cut off at the edge').toEqual([]);
    await expect(copyPrompt(page)).toHaveCount(0);
    await noSideways(page, '1C');
    await shot(page, `${device.name}-part1-C-embeddings`);
    await answer(page, 'd-emb-close');
    await answer(page, 'd-emb-2d');
    await answer(page, 'd-emb-odd');
    await next(page);

    // D: wrap-up — a recap check, the exit check, and the way on to part 2.
    await step(page, player, 'מסכמים את חלק 1', 'מה תוכלו להסביר לבד, במילים שלכם?');
    await answer(page, 'l03-q2', true);
    await answerText(page, 'lesson-03-exit', 'ניסיתי נוירון ורשת קטנה; ראיתי שהשגיאה יורדת באימון.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await expect(player).toContainText('משם לחלק 2');
    await expect(player).not.toContainText('הכינו בצוות הוראות'); // the homework proposal stays in the plan
    await noSideways(page, '1D');
    await shot(page, `${device.name}-part1-D-wrap-up`);
    expect(problems).toEqual([]);
  });

  test(`part 2 (lesson-03-deeper) previews end to end, widgets by keyboard, on a ${device.name}`, async ({ page }) => {
    const problems = await watch(page);
    const player = await open(page, 'lesson-03-deeper', device);
    await expect(player).toContainText('חלק 2');

    // A: tokens — the live tokenizer (real o200k_base in the browser) is the action.
    await step(page, player, 'המודל מקבל רצף יחידות', 'מה בעצם מגיע למודל כשאתם כותבים לצ׳טבוט?');
    await expect(player).toContainText('זוכרים מחלק 1');
    const tok = page.getByTestId('live-tokenizer');
    const count = tok.getByTestId('token-count');
    await expect(count).toContainText('11 טוקנים');
    await tok.getByRole('button', { name: 'Michal wants three cookies for tomorrow' }).click();
    await expect(count).toContainText('7 טוקנים');
    await tok.getByRole('textbox').fill('');
    await tok.getByRole('textbox').focus();
    await page.keyboard.type('שלום');
    await expect(count).toContainText(/\d+ טוקנים · 4 תווים/);
    await colabStep(page, player, '/lessons/lesson-03-deeper/v3/lesson-3-part-2-a-tokens-he.ipynb');
    await expect(copyPrompt(page)).toHaveCount(0);
    await page.getByRole('checkbox', { name: /השוויתי בכלי/ }).check();
    await noSideways(page, '2A');
    await shot(page, `${device.name}-part2-A-tokens`);
    await answer(page, 'l03-q1', true);
    await answer(page, 'l03-tokens-ratio');
    await next(page);

    // B: next token — guess first, then the measured bars; context switch and temperature.
    await step(page, player, 'המודל בוחר את ההמשך', 'איך מודל שפה מגיע לתשובה, טוקן אחרי טוקן?');
    await colabStep(page, player, '/lessons/lesson-03-deeper/v3/lesson-3-part-2-b-next-token-he.ipynb');
    await expect(player).toContainText('**טמפרטורה**'.replace(/\*\*/g, ''));
    const guess = page.getByTestId('next-word-guess');
    await expect(guess.getByRole('button', { name: /בחרו ניחוש קודם|הצגת ההסתברויות/ })).toBeDisabled();
    const coffee = guess.getByRole('radio', { name: 'קפה' });
    await coffee.focus();
    await page.keyboard.press('Space');
    await focusAndPress(guess.getByRole('button', { name: 'הצגת ההסתברויות של המודל' }), 'Enter');
    await expect(guess.getByTestId('top-tokens').locator('li')).toHaveCount(10);
    await expect(guess.getByTestId('measured-source')).toContainText('Qwen/Qwen2.5-0.5B');
    await guess.getByRole('button', { name: /משפט 4/ }).click();
    await guess.getByRole('radio', { name: 'wine' }).check();
    await guess.getByRole('button', { name: 'הצגת ההסתברויות של המודל' }).click();
    await expect(guess.getByTestId('next-word-result').locator('ul').first().locator('li').first()).toContainText('wine');
    const before = await guess.getByTestId('top-tokens').locator('li').first().innerText();
    await guess.getByRole('slider', { name: /טמפרטורה/ }).focus();
    for (let i = 0; i < 8; i += 1) await page.keyboard.press('ArrowUp');
    await expect(guess.getByTestId('top-tokens').locator('li').first()).not.toHaveText(before);
    await expect(copyPrompt(page)).toHaveCount(0);
    await noSideways(page, '2B');
    await shot(page, `${device.name}-part2-B-next-token`);
    await answer(page, 'l03-context-shift');
    await answer(page, 'l03-probability-meaning');
    await next(page);

    // C: attention — the illustration, by keyboard, and the pointer to the real measurement.
    await step(page, player, 'ייצוג ומשמעות תלויים בהקשר', 'איך אותה מילה מקבלת משמעות אחרת במשפט אחר?');
    await colabStep(page, player, '/lessons/lesson-03-deeper/v3/lesson-3-part-2-c-attention-he.ipynb');
    const att = page.getByTestId('attention-view');
    await expect(att.getByTestId('illustration-label')).toHaveText('המחשה, לא מדידה');
    const big = att.getByTestId('attention-cake-big');
    await focusAndPress(big.getByRole('button', { name: /^גדולה/ }), 'ArrowRight'); // RTL: right is back, «היא»
    await expect(big.getByRole('button', { name: /^היא/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(player).toContainText('משקלי הקשב האמיתיים');
    await expect(copyPrompt(page)).toHaveCount(0);
    await noSideways(page, '2C');
    await shot(page, `${device.name}-part2-C-attention`);
    await answer(page, 'l03-illustration');
    await answer(page, 'd-pronoun');
    await next(page);

    // D: the transformer pipeline: many layers, one after another.
    await step(page, player, 'transformer', 'איך כל החלקים מתחברים למודל שחוזה את הטוקן הבא?');
    const diagram = page.getByRole('img', { name: /תרשים זרימה/ });
    await expect(diagram).toBeVisible();
    expect(await diagram.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    await noSideways(page, '2D');
    await answer(page, 'd-pipeline-order');
    await next(page);

    // E: from model to chatbot — sort what the model knows from training vs context; no chatbot task.
    await step(page, player, 'ממודל שפה לצ׳טבוט', 'מה הופך מודל שחוזה טוקנים לצ׳טבוט – ולמה הוא עדיין ממציא?');
    await expect(page.getByRole('table', { name: 'מאיפה המודל יודע?' })).toBeVisible();
    await expect(copyPrompt(page)).toHaveCount(0);
    await noSideways(page, '2E');
    await answer(page, 'd-instruction-tuning');
    await answer(page, 'd-still-invents');
    await next(page);

    // F: grounding — the one chatbot exercise, with its purpose stated.
    await step(page, player, 'תשובה רהוטה עדיין דורשת ראיות', 'איך בודקים שהצ׳טבוט לא השלים פרט שלא נמסר לו?');
    await colabStep(page, player, '/lessons/lesson-03-deeper/v3/lesson-3-part-2-f-grounding-he.ipynb');
    await expect(player).toContainText('למה בצ׳טבוט:');
    await expect(copyPrompt(page)).toHaveCount(2);
    const checks = page.getByRole('table', { name: 'שתי הבדיקות – לכל אחת משתי התשובות' });
    const fit = await checks.evaluate((t) => ({ table: t.scrollWidth, box: (t.parentElement as HTMLElement).clientWidth }));
    expect(fit.table, 'the check table fits its box').toBeLessThanOrEqual(fit.box + 1);
    await expect(player.getByText('דוגמה פתורה')).toBeVisible();
    await expect(player.locator('pre').filter({ hasText: '"pickup_time": null' })).toBeVisible();
    await noSideways(page, '2F');
    await shot(page, `${device.name}-part2-F-grounding`);
    await answerText(page, 'l03-grounding-log', 'בקשה 1 השלימה שעה 10:00; בקשה 2 השאירה null. בלי כמות: סומנה כחסרה.');
    await answer(page, 'l03-q3', true);
    await answer(page, 'l03-source');
    await next(page);

    // G: wrap-up.
    await step(page, player, 'מסכמים את שיעור 3', 'מה תוכלו להסביר לבד, במילים שלכם?');
    await expect(player.getByText('התוצר של השיעור')).toBeVisible();
    await answerText(page, 'lesson-03-deeper-exit', 'ההודעה נחתכת לטוקנים, כל טוקן הופך לייצוג, השכבות מעבדות, ובסוף יש הסתברות לטוקן הבא.');
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await noSideways(page, '2G');
    await shot(page, `${device.name}-part2-G-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('the readiness table lists part 2 as required, in order, and students can’t open either draft', async ({ page, context }) => {
  await page.goto(`/course/${seed.course.id}`);
  await page.locator('.nav-step').filter({ hasText: 'Lessons' }).click();
  const part = page.getByTestId('part-3');
  await expect(part).toContainText('lesson-03-deeper');
  await expect(part).toContainText('part 2 (required)');
  await expect(page.getByText('enrichment')).toHaveCount(0);
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([{ name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }]);
  for (const slug of ['lesson-03', 'lesson-03-deeper']) {
    expect((await page.request.get(`/api/r/${seed.student.token}/lessons/${slug}`)).status(), slug).toBe(404);
  }
});
