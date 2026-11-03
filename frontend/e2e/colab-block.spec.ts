import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* A Colab block shows the step line and ONE action — the instructor's Colab
 * link when set, otherwise the notebook download. Everything else (the
 * download/upload how-to, sign in, run cells, CPU, the secondary download and
 * colab.research.google.com, the return note) is in a collapsed "עזרה וחלופות" expander that
 * opens by keyboard. Instructor previews only: nothing is saved. */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

async function openPreview(page: Page, lessonId: number, step: string, colabUrl?: string) {
  if (colabUrl) {
    // Inject an instructor-set link into this page's preview payload only, so
    // the shared seeded lesson keeps no Colab link for the other tests.
    await page.route(/\/api\/courses\/\d+\/lessons\/\d+\/preview/, async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      await route.fulfill({ response: res, json: { ...body, colab_url: colabUrl } });
    });
  }
  await page.goto(`/course/${seed.course.id}/lessons/${lessonId}/preview#step=${step}`);
  await expect(page.getByText('Lesson preview — nothing is saved')).toBeVisible();
  const block = page.getByTestId('colab-block').first();
  await expect(block).toBeVisible();
  return block;
}

test('lesson 3 part 1: the download is the visible action; the how-to is collapsed and opens by keyboard', async ({ page }) => {
  const block = await openPreview(page, seed.plan_lessons['lesson-03'], 'neuron');
  await expect(block.getByRole('heading')).toContainText('עובדים בקולאב');
  await expect(block.getByRole('link', { name: /פתיחה בקולאב/ })).toHaveCount(0);
  const download = block.getByRole('link', { name: /הורדת המחברת/ });
  await expect(download).toHaveCount(1);
  await expect(download).toBeVisible();

  const help = block.getByTestId('colab-help');
  const summary = help.locator('summary');
  await expect(summary).toHaveText('עזרה וחלופות');
  await expect(help).not.toHaveAttribute('open', '');
  const howTo = block.getByText(/מריצים תא בלחיצה על ▶/);
  await expect(howTo).toBeHidden();
  await expect(block.getByRole('link', { name: /colab\.research\.google\.com/ })).toBeHidden();
  await expect(block.getByText('חזרו ללשונית הזו – המקום שלכם נשמר')).toBeHidden();

  await summary.focus();
  await expect(summary).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(help).toHaveAttribute('open', '');
  await expect(howTo).toBeVisible();
  await expect(block.getByRole('link', { name: /colab\.research\.google\.com/ })).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(howTo).toBeHidden();
});

test('lesson 2: an instructor Colab (Drive) link stays visible; download and how-to move into the expander', async ({ page }) => {
  const drive = 'https://drive.google.com/file/d/e2e-fake-id/view';
  const block = await openPreview(page, seed.lesson.id, 'data', drive);
  await expect(block.getByRole('heading')).toContainText('סעיף 1, סעיף 1א וסעיף 1ב');
  const openLink = block.getByRole('link', { name: /פתיחה בקולאב/ });
  await expect(openLink).toBeVisible();
  await expect(openLink).toHaveAttribute('href', drive);
  await expect(openLink).toHaveAttribute('target', '_blank');
  const returnNote = block.getByText('חזרו ללשונית הזו – המקום שלכם נשמר');
  await expect(returnNote).toBeHidden();

  const download = block.getByRole('link', { name: /הורדת המחברת/ });
  const stepOnly = block.getByText(/בשלב הזה מריצים רק את תחילת המחברת/);
  await expect(download).toBeHidden();
  await expect(stepOnly).toBeHidden();

  const summary = block.getByTestId('colab-help').locator('summary');
  await summary.focus();
  await page.keyboard.press(' ');
  // Nothing lost: every instruction, the download and colab.research.google.com are inside.
  await expect(block.locator('details ol > li')).toHaveCount(5);
  await expect(stepOnly).toBeVisible();
  await expect(returnNote).toBeVisible();
  await expect(download).toBeVisible();
  await expect(download).toHaveAttribute('href', '/lessons/lesson-2/v1/lesson-2-machine-learning-he.ipynb');
  await expect(block.getByRole('link', { name: /colab\.research\.google\.com/ })).toBeVisible();
});
