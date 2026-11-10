import { expect, type Page, test } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

/* The Feedback button is on every page, a student's (Hebrew) and the
 * instructor's (English). A report files a tickets-core ticket that shows what
 * the page attached, with the student's link token cut out, and a student can
 * send without their name. The tickets are read back through the ticket API
 * org-core's roles use (/api/admin/feedback; open here, as the e2e backend runs
 * with no instructor token). */

let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

type Ticket = {
  id: string;
  source: string;
  reporter_ref: string | null;
  course_id: number | null;
  feedback_text: string;
  status: string;
  kinds: string[];
  refs: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

async function noFonts(page: Page) {
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
}

async function ticketWithText(page: Page, text: string): Promise<Ticket> {
  const res = await page.request.get('/api/admin/feedback?limit=1000');
  expect(res.ok()).toBe(true);
  const found = ((await res.json()) as Ticket[]).filter((t) => t.feedback_text === text);
  expect(found, `one ticket reading "${text}"`).toHaveLength(1);
  return found[0];
}

test('a student sends feedback without their name, and the ticket shows the page, never the link', async ({ page }) => {
  await noFonts(page);
  await page.goto(`/r/${seed.student.token}?tab=grades`);
  await expect(page.getByText('עדיין לא פורסמו ציונים')).toBeVisible();

  await page.getByRole('button', { name: 'משוב' }).click();
  const dialog = page.getByRole('dialog', { name: 'משוב על האתר' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute('dir', 'rtl');

  await dialog.getByRole('button', { name: 'משהו מבלבל' }).click();
  await expect(dialog.getByRole('button', { name: 'משהו מבלבל' })).toHaveAttribute('aria-pressed', 'true');

  // Too short is said, not sent.
  await dialog.getByRole('button', { name: 'שליחה' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('כתבו כמה מילים');

  const text = `לא ברור איפה רואים את הציון הסופי ${Date.now()}`;
  await dialog.getByLabel('ספרו לנו במה מדובר').fill(text);
  await dialog.getByLabel('לשלוח בלי השם שלי').check();
  await expect(dialog.getByText('השם שלכם לא יצורף')).toBeVisible();

  // What is attached is shown in full before Send: the page without the token, and no name.
  await dialog.getByText('מה מצורף אוטומטית').click();
  const attached = dialog.getByRole('definition');
  await expect(dialog.getByText('לא מצורף')).toBeVisible();
  await expect(attached.filter({ hasText: '/r/…?tab=grades' })).toHaveCount(1);
  expect(await dialog.innerText()).not.toContain(seed.student.token);

  await dialog.getByRole('button', { name: 'שליחה' }).click();
  await expect(dialog.getByRole('status')).toContainText('תודה! המשוב נשלח.');
  await dialog.getByRole('button', { name: 'סגירה' }).first().click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('button', { name: 'משוב' })).toBeFocused();

  const ticket = await ticketWithText(page, text);
  expect(ticket.source).toBe('student');
  expect(ticket.reporter_ref).toBeNull();
  expect(ticket.status).toBe('open');
  expect(ticket.kinds).toEqual([]);
  expect(ticket.course_id).toBe(seed.course.id);
  expect(ticket.refs).toMatchObject({
    category: 'confusing',
    path: '/r/…?tab=grades',
    tab: 'grades'
  });
  expect(ticket.metadata).toMatchObject({ anonymous: true });
  expect(JSON.stringify(ticket)).not.toContain(seed.student.token);
  expect(JSON.stringify(ticket)).not.toContain(seed.student.name);
});

test('the instructor sends feedback from a lesson preview, with the lesson and section attached', async ({ page }) => {
  await noFonts(page);
  await page.goto(`/course/${seed.course.id}?section=lessons&tab=insights`);
  await expect(page.getByRole('region', { name: 'Class insights' })).toBeVisible();

  // The button keeps clear of the sidebar's last links (it sits bottom-right on instructor pages).
  const button = await page.getByRole('button', { name: 'Feedback' }).boundingBox();
  const settings = await page.getByText('Course settings', { exact: true }).filter({ visible: true }).first().boundingBox();
  expect(button && settings).toBeTruthy();
  expect(button!.x > settings!.x + settings!.width || button!.y > settings!.y + settings!.height + 40).toBe(true);

  // An idea from the course page.
  await page.getByRole('button', { name: 'Feedback' }).click();
  let dialog = page.getByRole('dialog', { name: 'Feedback about the site' });
  await dialog.getByRole('button', { name: 'I have an idea' }).click();
  const idea = `Show open feedback on the overview ${Date.now()}`;
  await dialog.getByLabel('What happened, or what should change?').fill(idea);
  await expect(dialog.getByRole('checkbox')).toHaveCount(0); // no 'without my name' for the instructor
  await dialog.getByRole('button', { name: 'Send' }).click();
  await expect(dialog.getByRole('status')).toContainText("Thanks — it's in the ticket queue.");
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  const ticket = await ticketWithText(page, idea);
  expect(ticket.source).toBe('instructor');
  expect(ticket.reporter_ref).toBe('instructor');
  expect(ticket.kinds).toEqual(['feature_request']);
  expect(ticket.course_id).toBe(seed.course.id);
  expect(ticket.refs).toMatchObject({
    category: 'idea',
    section: 'lessons',
    tab: 'insights'
  });

  // Something broken, from a lesson's preview: the lesson is attached.
  await page.goto(`/course/${seed.course.id}/lessons/${seed.lesson.id}/preview`);
  await page.getByRole('button', { name: 'Feedback' }).click();
  dialog = page.getByRole('dialog', { name: 'Feedback about the site' });
  const broken = `The preview's next button is cut off ${Date.now()}`;
  await dialog.getByLabel('What happened, or what should change?').fill(broken);
  await dialog.getByRole('button', { name: 'Send' }).click();
  await expect(dialog.getByRole('status')).toBeVisible();
  const bug = await ticketWithText(page, broken);
  expect(bug.kinds).toEqual(['bug']);
  expect(bug.refs).toMatchObject({
    category: 'broken',
    lesson: String(seed.lesson.id)
  });
});

test('the button fits a phone-width student page without pushing it sideways, and is not on sign-in', async ({ page }) => {
  await noFonts(page);
  await page.setViewportSize({ width: 375, height: 740 });
  await page.goto(`/r/${seed.student.token}`);
  const button = page.getByRole('button', { name: 'משוב' });
  await expect(button).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  const box = await button.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 375).toBe(true);

  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'משוב' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Feedback' })).toHaveCount(0);
});

test('the grading page opens the same dialog from its toolbar instead of a floating button over the rubric', async ({ page }) => {
  await noFonts(page);
  await page.goto(`/course/${seed.rubrics.course_id}/submission/${seed.rubrics.project_submission_id}`);
  const toolbar = page.getByRole('button', { name: 'Feedback', exact: true });
  await expect(toolbar).toHaveCount(1); // the toolbar's; no floating one
  await toolbar.click();
  const dialog = page.getByRole('dialog', { name: 'Feedback about the site' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(toolbar).toBeFocused();
});
