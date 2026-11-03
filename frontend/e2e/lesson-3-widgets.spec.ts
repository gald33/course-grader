import { mkdirSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type Locator, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* The interactive widgets of lesson 3 (42052) and its "go deeper" lesson, in
 * the instructor's preview, on a 390 px phone and a 1280 px desktop, operated
 * by keyboard as well as by pointer:
 *   live_tokenizer     typing changes the token count (real o200k_base, in the browser)
 *   next_word_guess    a guess first, then the precomputed probabilities; switching context changes them
 *   attention_view     choosing a word changes what is highlighted; labeled as an illustration
 *   neuron_playground  a slider changes the neuron's output
 *   training_demo      a training step lowers the error
 *   embedding_map      choosing a word lists its nearest neighbours
 * No widget calls anything but our own origin. */

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

/** Problems the page reports, and any request that leaves our own origin. */
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
    const ours = url.hostname === base.hostname;
    if (!ours && !/^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname) && url.protocol.startsWith('http')) {
      problems.push(`left our origin: ${req.url()}`);
    }
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

async function noSideways(page: Page, where: string) {
  const w = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, view: window.innerWidth }));
  expect(w.doc, where).toBeLessThanOrEqual(w.view);
}

const stepButton = (page: Page, letter: string) => page.getByRole('button', { name: new RegExp(`^שלב ${letter}:`) });

async function focusAndPress(locator: Locator, key: string) {
  await locator.focus();
  await expect(locator).toBeFocused();
  await locator.press(key);
}

const DEVICES = [
  { name: 'phone', width: 390, height: 844 },
  { name: 'desktop', width: 1280, height: 900 }
];

for (const device of DEVICES) {
  test(`lesson 3 widgets work by keyboard on a ${device.name}`, async ({ page }) => {
    const problems = await watch(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-03']}/preview`);
    await expect(page.locator('div[dir="rtl"][lang="he"]').first()).toBeVisible();

    // A: live tokenizer — real o200k_base, client-side, labeled by name.
    const tok = page.getByTestId('live-tokenizer');
    await expect(tok).toContainText('o200k_base');
    const count = tok.getByTestId('token-count');
    await expect(count).toContainText('11 טוקנים'); // the notebook's measurement of the same sentence
    await tok.getByRole('button', { name: 'Michal wants three cookies for tomorrow' }).click();
    await expect(count).toContainText('7 טוקנים');
    const box = tok.getByRole('textbox');
    await box.fill('');
    await box.focus();
    await page.keyboard.type('שלום');
    await expect(count).not.toContainText('7 טוקנים');
    await expect(count).toContainText(/\d+ טוקנים · 4 תווים/);
    await noSideways(page, 'A');
    await shot(page, `${device.name}-widgets-tokenizer`);

    // B: guess the next word — guess first, then measured bars with their source.
    await stepButton(page, 'B').click();
    const guess = page.getByTestId('next-word-guess');
    await expect(guess).toContainText('בבוקר, לפני העבודה, אני שותה כוס');
    await expect(guess.getByTestId('next-word-result')).toHaveCount(0);
    const reveal = guess.getByRole('button', { name: /בחרו ניחוש קודם|הצגת ההסתברויות/ });
    await expect(reveal).toBeDisabled();
    const coffee = guess.getByRole('radio', { name: 'קפה' });
    await coffee.focus();
    await page.keyboard.press('Space');
    await expect(coffee).toBeChecked();
    await focusAndPress(guess.getByRole('button', { name: 'הצגת ההסתברויות של המודל' }), 'Enter');
    const result = guess.getByTestId('next-word-result');
    await expect(result).toContainText('הניחוש שלכם');
    await expect(result.getByTestId('top-tokens').locator('li')).toHaveCount(10);
    await expect(guess.getByTestId('measured-source')).toContainText('Qwen/Qwen2.5-0.5B');
    await expect(guess.getByTestId('measured-source')).toContainText('scripts/lesson-03/generate_next_word.py');
    await expect(guess.getByTestId('measured-source')).toContainText('לא מהצ׳טבוט');
    // Switching the context (arrow keys along the sentence buttons) resets and changes the bars.
    const morningEn = guess.getByRole('button', { name: /משפט 3/ });
    await focusAndPress(guess.getByRole('button', { name: /משפט 1/ }), 'ArrowLeft'); // RTL: left is next
    await focusAndPress(guess.getByRole('button', { name: /משפט 2/ }), 'ArrowLeft');
    await expect(morningEn).toHaveAttribute('aria-pressed', 'true');
    await expect(guess.getByTestId('next-word-context')).toContainText('Every morning before work');
    await guess.getByRole('radio', { name: 'wine' }).check();
    await guess.getByRole('button', { name: 'הצגת ההסתברויות של המודל' }).click();
    const first = guess.getByTestId('next-word-result').locator('ul').first().locator('li').first();
    await expect(first).toContainText('coffee');
    await guess.getByRole('button', { name: 'לנחש שוב' }).click();
    await guess.getByRole('button', { name: /משפט 4/ }).click();
    await guess.getByRole('radio', { name: 'wine' }).check();
    await guess.getByRole('button', { name: 'הצגת ההסתברויות של המודל' }).click();
    await expect(guess.getByTestId('next-word-result').locator('ul').first().locator('li').first()).toContainText('wine');
    // The temperature slider is labeled as an illustration and moves the bars.
    const before = await guess.getByTestId('top-tokens').locator('li').first().innerText();
    const slider = guess.getByRole('slider', { name: /טמפרטורה/ });
    await slider.focus();
    for (let i = 0; i < 8; i += 1) await page.keyboard.press('ArrowUp');
    await expect(guess).toContainText('המחשה: הטמפרטורה');
    await expect(guess.getByTestId('top-tokens').locator('li').first()).not.toHaveText(before);
    await noSideways(page, 'B');
    await shot(page, `${device.name}-widgets-next-word`);

    // C: click-to-see attention — an illustration, operated with the keyboard.
    await stepButton(page, 'C').click();
    const att = page.getByTestId('attention-view');
    await expect(att.getByTestId('illustration-label')).toHaveText('המחשה, לא מדידה');
    const big = att.getByTestId('attention-cake-big');
    const bigWord = big.getByRole('button', { name: /^גדולה/ });
    await expect(bigWord).toHaveAttribute('aria-pressed', 'true');
    const cakeInBig = big.getByRole('button', { name: /^העוגה/ });
    const boxInBig = big.getByRole('button', { name: /^לקופסה/ });
    expect(Number(await cakeInBig.getAttribute('data-weight'))).toBeGreaterThan(Number(await boxInBig.getAttribute('data-weight')));
    const small = att.getByTestId('attention-cake-small');
    expect(Number(await small.getByRole('button', { name: /^לקופסה/ }).getAttribute('data-weight'))).toBeGreaterThan(
      Number(await small.getByRole('button', { name: /^העוגה/ }).getAttribute('data-weight'))
    );
    // Arrow keys move the selection; what is highlighted changes.
    await focusAndPress(bigWord, 'ArrowRight'); // RTL: right is back, to «היא»
    const she = big.getByRole('button', { name: /^היא/ });
    await expect(she).toHaveAttribute('aria-pressed', 'true');
    await expect(she).toBeFocused();
    expect(await cakeInBig.getAttribute('data-weight')).toBe(await boxInBig.getAttribute('data-weight')); // «היא» alone can't tell
    await expect(big.getByRole('button', { name: /^מדי/ })).toHaveAttribute('data-weight', ''); // later words get nothing
    const summary = big.locator('xpath=..').getByTestId('attention-summary');
    await expect(summary).toContainText('מילים שאחריה מסומנות ב-—, כי המודל מסתכל רק אחורה.');
    await expect(summary).not.toContainText('،');
    await noSideways(page, 'C');
    await shot(page, `${device.name}-widgets-attention`);
    expect(problems).toEqual([]);
  });
}

const questionCard = (page: Page, key: string) => page.locator(`article[aria-labelledby="q-${key}-prompt"]`);
const checklist = (page: Page) => page.getByRole('region', { name: 'מה נדרש כדי להשלים את השלב' });
const SEND = /^(שליחת תשובה|שליחה מחדש)$/;

/** FAKE keys: the last option is "right". */
async function answerRight(page: Page, key: string) {
  const card = questionCard(page, key);
  await card.getByRole('radio').last().check();
  await card.getByRole('button', { name: SEND }).click();
  await expect(card).toContainText('✓ נכון');
}

async function nextStep(page: Page) {
  await expect(checklist(page)).toContainText('✓ השלב הושלם.');
  await page.getByRole('button', { name: /^לשלב הבא/ }).click();
}

for (const device of DEVICES) {
  test(`the "go deeper" lesson previews end to end, widgets by keyboard, on a ${device.name}`, async ({ page }) => {
    const problems = await watch(page);
    await page.setViewportSize({ width: device.width, height: device.height });
    await page.goto(`/course/${seed.course.id}/lessons/${seed.plan_lessons['lesson-03-deeper']}/preview`);
    await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'No answer key loaded' })).toHaveCount(0);
    const heading = page.locator('#lesson-step-title');

    // A: one neuron — a slider moved by keyboard flips the decision.
    await expect(heading).toContainText('נוירון אחד');
    const neuron = page.getByTestId('neuron-playground');
    const out = neuron.getByTestId('neuron-output');
    await expect(out).toHaveAttribute('data-on', '0'); // 0.5×6 − 1×3 − 2 = −2
    await expect(neuron.getByTestId('neuron-sum')).toContainText('= −2');
    const orders = neuron.getByRole('slider', { name: /^הזמנות מראש למחר/ });
    await expect(orders).toHaveAttribute('dir', 'ltr'); // higher is to the right, also on an RTL page
    await orders.focus();
    for (let i = 0; i < 4; i += 1) await page.keyboard.press('ArrowUp'); // 10 orders: 5 − 3 − 2 = 0
    await expect(neuron.getByTestId('neuron-sum')).toContainText('= 0');
    await expect(out).toHaveAttribute('data-on', '1');
    await expect(out).toContainText('לאפות עוד מגש');
    await noSideways(page, 'A');
    await shot(page, `${device.name}-deeper-A-neuron`);
    await answerRight(page, 'd-neuron-weight');
    await answerRight(page, 'd-neuron-who');
    await nextStep(page);

    // B: a tiny classifier — training steps lower the errors.
    await expect(heading).toContainText('רשת שלומדת');
    const demo = page.getByTestId('training-demo');
    const status = demo.getByTestId('training-status');
    await expect(status).toContainText('צעדי אימון: 0');
    await expect(status).toContainText('טעויות: 22 מתוך 24');
    await demo.getByRole('button', { name: 'צעד אימון אחד' }).focus();
    await page.keyboard.press('Enter');
    await expect(status).toContainText('צעדי אימון: 1');
    await demo.getByRole('button', { name: '10 צעדים' }).click();
    await expect(status).toContainText('צעדי אימון: 11');
    const errors = Number((await status.innerText()).match(/טעויות: (\d+)/)![1]);
    expect(errors).toBeLessThanOrEqual(3);
    await demo.getByRole('button', { name: 'איפוס' }).click();
    await expect(status).toContainText('טעויות: 22 מתוך 24');
    await noSideways(page, 'B');
    await shot(page, `${device.name}-deeper-B-training`);
    await answerRight(page, 'd-train-step');
    await answerRight(page, 'd-after-training');
    await nextStep(page);

    // C: the embedding map — neighbours by full-dimension cosine, chosen by keyboard.
    await expect(heading).toContainText('ייצוגים');
    const map = page.getByTestId('embedding-map');
    await expect(map).toContainText('הטלה ל-2 ממדים: מרחקים משוערים');
    const neighbours = map.getByTestId('embedding-neighbors');
    await expect(neighbours).toContainText('לחם');
    await expect(neighbours.locator('li').first()).toContainText('bread');
    await expect(neighbours.locator('li')).toHaveCount(5);
    await map.getByRole('button', { name: 'לחם', exact: true }).focus();
    await page.keyboard.press('ArrowLeft'); // RTL: next word, «עוגה»
    await expect(map.getByRole('button', { name: 'עוגה', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(neighbours.locator('li').first()).toContainText('cake');
    await map.getByRole('button', { name: 'tomorrow', exact: true }).click();
    await expect(neighbours.locator('li').first()).toContainText('מחר');
    // Every visible label sits inside the drawing, even next to its right edge ("tomorrow").
    const clipped = await map.locator('svg[role="img"]').evaluate((svg) => {
      const vb = (svg as SVGSVGElement).viewBox.baseVal;
      return Array.from(svg.querySelectorAll('text'))
        .map((t) => ({ text: t.textContent, box: (t as SVGTextElement).getBBox() }))
        .filter(({ box }) => box.x < vb.x - 0.5 || box.x + box.width > vb.x + vb.width + 0.5)
        .map(({ text }) => text);
    });
    expect(clipped, 'map labels cut off at the edge').toEqual([]);
    await expect(map).toContainText('הצבעים: נושא שקבענו ביד');
    await expect(map.getByTestId('measured-source')).toContainText('paraphrase-multilingual-MiniLM-L12-v2');
    await noSideways(page, 'C');
    await shot(page, `${device.name}-deeper-C-embeddings`);
    await answerRight(page, 'd-emb-close');
    await answerRight(page, 'd-emb-2d');
    await answerRight(page, 'd-emb-odd');
    await nextStep(page);

    // D: the transformer pipeline diagram and the reused attention illustration.
    await expect(heading).toContainText('transformer');
    const diagram = page.getByRole('img', { name: /תרשים זרימה/ });
    await expect(diagram).toBeVisible();
    expect(await diagram.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    const att = page.getByTestId('attention-view');
    await expect(att.getByTestId('illustration-label')).toHaveText('המחשה, לא מדידה');
    await expect(att.getByTestId('attention-cake-big').getByRole('button', { name: /^היא/ })).toHaveAttribute('aria-pressed', 'true');
    await noSideways(page, 'D');
    await answerRight(page, 'd-pipeline-order');
    await answerRight(page, 'd-pronoun');
    await nextStep(page);

    // E: from model to chatbot; F: wrap-up with a free-text exit check.
    await expect(heading).toContainText('ממודל שפה לצ׳טבוט');
    await expect(page.getByRole('button', { name: 'העתקת הבקשה' }).first()).toBeVisible();
    await answerRight(page, 'd-instruction-tuning');
    await answerRight(page, 'd-params');
    await answerRight(page, 'd-still-invents');
    await nextStep(page);
    await expect(heading).toContainText('מסכמים');
    const exit = questionCard(page, 'lesson-03-deeper-exit');
    await exit.getByRole('textbox').fill('ההודעה נחתכת לטוקנים, כל טוקן הופך לייצוג, השכבות מעבדות, ובסוף יש הסתברות לטוקן הבא.');
    await exit.getByRole('button', { name: 'שליחת תשובה' }).click();
    await expect(checklist(page)).toContainText('✓ השלב הושלם.');
    await noSideways(page, 'F');
    await shot(page, `${device.name}-deeper-F-wrap-up`);
    expect(problems).toEqual([]);
  });
}

test('the readiness table shows the "go deeper" lesson beside session 3, and students can’t open it', async ({ page, context }) => {
  await page.goto(`/course/${seed.course.id}`);
  await page.locator('.nav-step').filter({ hasText: 'Lessons' }).click();
  await expect(page.getByTestId('enrichment-3')).toContainText('lesson-03-deeper');
  await expect(page.getByTestId('enrichment-3')).toContainText('move it after lesson-03');
  const baseURL = test.info().project.use.baseURL!;
  await context.addCookies([{ name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }]);
  expect((await page.request.get(`/api/r/${seed.student.token}/lessons/lesson-03-deeper`)).status()).toBe(404);
});
