import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* A Colab block shows its lead (what to do in THIS notebook for THIS step) and
 * ONE action — the instructor's Colab link when set, otherwise the step's own
 * notebook opened in Colab from the public repository. Everything else (the
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

test('lesson 3 part 1: the lead and the per-step Colab button are visible; the how-to is collapsed and opens by keyboard', async ({ page }) => {
  const block = await openPreview(page, seed.plan_lessons['lesson-03'], 'neuron');
  await expect(block.getByRole('heading')).toContainText('עובדים בקולאב');
  await expect(block.getByTestId('colab-lead')).toBeVisible();
  await expect(block.getByTestId('colab-lead')).toContainText('שנו משקל אחד');
  const open = block.getByRole('link', { name: /פתיחה בקולאב/ });
  await expect(open).toBeVisible();
  await expect(open).toHaveAttribute(
    'href',
    'https://colab.research.google.com/github/gald33/course-grader/blob/main/frontend/public/lessons/lesson-03/v3/lesson-3-part-1-a-neuron-he.ipynb'
  );
  const download = block.getByRole('link', { name: /הורדת המחברת/ });
  await expect(download).toBeHidden();

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
  await expect(download).toBeVisible();
  await expect(download).toHaveAttribute('href', '/lessons/lesson-03/v3/lesson-3-part-1-a-neuron-he.ipynb');
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

  // What to run now is the lead: visible, outside the help.
  await expect(block.getByTestId('colab-lead')).toBeVisible();
  await expect(block.getByTestId('colab-lead')).toContainText('הריצו עכשיו רק את תחילת המחברת');
  const download = block.getByRole('link', { name: /הורדת המחברת/ });
  await expect(download).toBeHidden();

  const summary = block.getByTestId('colab-help').locator('summary');
  await summary.focus();
  await page.keyboard.press(' ');
  // Nothing lost: every instruction, the download and colab.research.google.com are inside.
  await expect(block.locator('details ol > li')).toHaveCount(4); // generic how-to only
  await expect(returnNote).toBeVisible();
  await expect(download).toBeVisible();
  await expect(download).toHaveAttribute('href', '/lessons/lesson-2/v1/lesson-2-machine-learning-he.ipynb');
  await expect(block.getByRole('link', { name: /colab\.research\.google\.com/ })).toBeVisible();
});
