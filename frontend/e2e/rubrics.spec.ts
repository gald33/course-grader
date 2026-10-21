import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

/* Uncaught errors, console errors and failing API calls fail the test. */
async function watchForErrors(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console error: ${msg.text()}`);
  });
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

async function openRubrics(page: Page) {
  await page.goto(`/course/${seed.rubrics.course_id}`);
  await page.getByRole('button', { name: /Rubrics/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Rubrics' })).toBeVisible();
}

test('instructor authors, reorders and saves a rubric', async ({ page }) => {
  const problems = await watchForErrors(page);
  await openRubrics(page);
  await page.getByRole('button', { name: /HW2 · HW2 smoke/ }).click();
  await expect(page.getByText('No custom rubric')).toBeVisible();

  await page.getByRole('button', { name: '+ Add criterion' }).click();
  await page.getByRole('button', { name: '+ Add criterion' }).click();
  const cards = page.getByTestId('rubric-criterion');
  await expect(cards).toHaveCount(2);
  await cards.nth(0).getByLabel('Criterion name').fill('ניקוי נתונים');
  await cards.nth(0).getByLabel('Max points').fill('30');
  await cards.nth(0).getByLabel('What earns full or partial credit').fill('ערכים חסרים מטופלים ומוסברים');
  await cards.nth(1).getByLabel('Criterion name').fill('Models');
  await cards.nth(1).getByLabel('Max points').fill('70');
  await cards.nth(1).getByRole('button', { name: '+ Level' }).click();
  await cards.nth(1).getByLabel('Level points').fill('70');
  await cards.nth(1).getByLabel('Level description').fill('Three models compared');
  await expect(page.getByTestId('rubric-total')).toHaveText('100');

  // Move "Models" first, then save.
  await cards.nth(1).getByRole('button', { name: 'Move up' }).click();
  await expect(cards.nth(0).getByLabel('Criterion name')).toHaveValue('Models');
  await page.getByRole('button', { name: 'Save rubric' }).click();
  await expect(page.getByText('Rubric saved')).toBeVisible();

  // Persisted, in the new order, with the Hebrew criterion right-to-left.
  await page.reload();
  await page.getByRole('button', { name: /HW2 · HW2 smoke/ }).click();
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0).getByLabel('Criterion name')).toHaveValue('Models');
  await expect(cards.nth(0).getByLabel('Level description')).toHaveValue('Three models compared');
  await expect(cards.nth(1).getByLabel('Criterion name')).toHaveValue('ניקוי נתונים');
  await expect(cards.nth(1).getByLabel('Criterion name')).toHaveAttribute('dir', 'auto');
  expect(problems).toEqual([]);
});

test('instructor reviews LLM criterion scores and overrides one', async ({ page }) => {
  const problems = await watchForErrors(page);
  const [scored, unscored] = seed.rubrics.criteria;
  await page.goto(`/course/${seed.rubrics.course_id}/submission/${seed.rubrics.project_submission_id}`);

  const card = page.getByTestId('custom-rubric');
  await expect(card).toBeVisible();
  const rows = card.getByTestId('custom-criterion');
  await expect(rows.nth(0)).toContainText(scored.name);
  await expect(rows.nth(0)).toContainText('Claude · 14/20');
  await expect(rows.nth(0)).toContainText('[cell 3]');
  await expect(rows.nth(1)).toContainText('Not scored');
  await expect(card).toContainText('1 of 2 criteria not scored');

  await rows.nth(1).getByLabel(`Override score for ${unscored.name}`).fill('8');
  await rows.nth(1).getByLabel(`Override note for ${unscored.name}`).fill('Plots in the report');
  await rows.nth(1).getByRole('button', { name: 'Save' }).click();
  await expect(rows.nth(1)).toContainText('override');
  await expect(card).toContainText('22 / 30');
  await expect(card).not.toContainText('criteria not scored');
  expect(problems).toEqual([]);
});
