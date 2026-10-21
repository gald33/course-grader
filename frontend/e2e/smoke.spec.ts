import { expect, test, type Page } from '@playwright/test';

import { loadSeed, type Seed } from './seed';

// Written by the backend web server's seed step, so read it once tests run.
let seed: Seed;
test.beforeAll(() => {
  seed = loadSeed();
});

/* Fails the test on anything the page reports going wrong: uncaught errors,
 * console errors, API calls that fail or return an error status. Webfonts are stubbed so
 * the test never depends on the network. */
async function watchForErrors(page: Page): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', (err) => problems.push(`page error: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console error: ${msg.text()}`);
  });
  page.on('requestfailed', (req) => problems.push(`request failed: ${req.method()} ${req.url()} (${req.failure()?.errorText})`));
  page.on('response', (res) => {
    if (res.url().includes('/api/') && res.status() >= 400) problems.push(`API ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/css', body: '' })
  );
  return problems;
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

test('instructor course page loads the seeded course', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.goto(`/course/${seed.course.id}`);

  // The page shows "Loading…" until every course request has resolved, then
  // the step header (h1) and the sidebar with the course name.
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByText(seed.course.name).first()).toBeVisible();
  await expect(page.getByText('Loading…')).toHaveCount(0);
  expect(problems).toEqual([]);
});

test('student review page loads for a seeded review link', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.goto(`/r/${seed.student.token}`);

  await expect(page.getByRole('heading', { level: 1 })).toContainText(seed.student.name);
  await expect(page.getByText(seed.course.name).first()).toBeVisible();
  await expect(page.getByText(seed.student.team).first()).toBeVisible();
  expect(problems).toEqual([]);
});

test('student review page rejects an unknown link', async ({ page }) => {
  const problems = await watchForErrors(page);
  // A well-formed but unknown token: the API answers 404 and the page says so
  // instead of rendering a student's home.
  await page.goto('/r/unknown-token-0000000000');

  await expect(page.getByText('הקישור אינו תקין')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(0);
  // The browser logs the expected 404 itself; nothing else may go wrong.
  expect(problems.filter((p) => !p.includes('404'))).toEqual([]);
});

test('student portal lands on Home and keeps the active tab in the URL', async ({ page }) => {
  const problems = await watchForErrors(page);
  const tab = (name: string) => page.getByRole('tab', { name, exact: true });
  await page.goto(`/r/${seed.student.token}`);

  // Home is the default: the bare link, with the "up next" strip.
  await expect(tab('בית')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { name: 'מה הלאה' })).toBeVisible();

  // Every area is one tap away, and the tap lands in the URL.
  await tab('ציונים').click();
  await expect(page).toHaveURL(/[?&]tab=grades\b/);
  await expect(page.getByText('עדיין לא פורסמו ציונים')).toBeVisible();

  await tab('צוות').click();
  await expect(page).toHaveURL(/[?&]tab=team\b/);
  await expect(page.getByRole('tabpanel').getByText(seed.student.name)).toBeVisible();

  await tab('ביקורת עמיתים').click();
  await expect(page).toHaveURL(/[?&]tab=review\b/);
  await expect(page.getByText('מי רואה את הביקורות שלך?')).toBeVisible();

  await tab('מידע על הקורס').click();
  await expect(page).toHaveURL(/[?&]tab=info\b/);
  await expect(page.getByRole('tabpanel').getByRole('heading', { name: seed.course.name })).toBeVisible();

  // Back/forward walk the tab history; refresh stays on the tab.
  await page.goBack();
  await expect(page).toHaveURL(/[?&]tab=review\b/);
  await expect(tab('ביקורת עמיתים')).toHaveAttribute('aria-selected', 'true');
  await page.goForward();
  await expect(page).toHaveURL(/[?&]tab=info\b/);
  await expect(tab('מידע על הקורס')).toHaveAttribute('aria-selected', 'true');
  await page.reload();
  await expect(tab('מידע על הקורס')).toHaveAttribute('aria-selected', 'true');

  // Arrow keys move between tabs too; the page is RTL, so ArrowRight goes back.
  await tab('מידע על הקורס').focus();
  await page.keyboard.press('ArrowRight');
  await expect(tab('ביקורת עמיתים')).toBeFocused();
  await expect(page).toHaveURL(/[?&]tab=review\b/);

  // Home drops the parameter again.
  await tab('בית').click();
  await expect(page).not.toHaveURL(/tab=/);
  await expect(page.getByRole('heading', { name: 'מה הלאה' })).toBeVisible();
  expect(problems).toEqual([]);
});

test('instructor "view as student" opens the same portal on the linked tab', async ({ page }) => {
  const problems = await watchForErrors(page);
  await page.goto(`/course/${seed.course.id}/student-view?tab=team`);

  await expect(page.getByRole('tab', { name: 'צוות', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  // Switching the previewed student keeps the tab.
  const picker = page.getByRole('combobox');
  const other = await picker.locator('option').nth(1).getAttribute('value');
  await picker.selectOption(other!);
  await expect(page).toHaveURL(new RegExp(`student=${other}`));
  await expect(page).toHaveURL(/[?&]tab=team\b/);
  await expect(page.getByRole('tab', { name: 'צוות', exact: true })).toHaveAttribute('aria-selected', 'true');
  // Rewriting the URL makes Next cancel its prefetch of the banner's "Back to
  // course" link; a cancelled prefetch is not an error.
  expect(problems.filter((p) => !(p.includes('_rsc=') && p.includes('ERR_ABORTED')))).toEqual([]);
});

test('student portal links to the guided lessons and points at one in progress', async ({ page, context, baseURL }) => {
  const problems = await watchForErrors(page);
  const lessonUrl = `/r/${seed.student.token}/lessons/${encodeURIComponent(seed.lesson.slug)}`;

  // Course info lists the published lesson, linked to its existing route.
  await page.goto(`/r/${seed.student.token}?tab=info`);
  const lessons = page.getByRole('region', { name: 'למידה בשיעור' });
  await expect(lessons.getByRole('link', { name: new RegExp(escapeRe(seed.lesson.title)) })).toHaveAttribute('href', lessonUrl);

  // Home points at a lesson in progress. Nothing here may write lesson
  // progress (lesson.spec compares the class's insights while it runs), so
  // the portal's answer is edited to say this student is midway.
  await page.route(`**/api/r/${seed.student.token}`, async (route) => {
    const res = await route.fetch();
    const home = await res.json();
    home.lessons = home.lessons.map((l: { slug: string }) =>
      l.slug === seed.lesson.slug ? { ...l, status: 'in_progress', required_done: 1 } : l
    );
    await route.fulfill({ response: res, json: home });
  });
  await page.getByRole('tab', { name: 'בית', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('link', { name: new RegExp(`להמשיך בשיעור: ${escapeRe(seed.lesson.title)}`) })).toHaveAttribute(
    'href',
    lessonUrl
  );

  // "All lessons" opens the existing lesson list for a signed-in student.
  await context.addCookies([{ name: 'cg_student', value: seed.student.cookie, url: baseURL, httpOnly: true, sameSite: 'Lax' }]);
  await page.getByRole('tab', { name: 'מידע על הקורס', exact: true }).click();
  await lessons.getByRole('link', { name: 'כל השיעורים' }).click();
  await expect(page).toHaveURL(new RegExp(`/r/${seed.student.token}/lessons$`));
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('למידה בשיעור');
  await expect(page.getByText(seed.lesson.title).first()).toBeVisible();
  expect(problems).toEqual([]);
});

test('Home lists reviews still owed only while the review deadline is ahead', async ({ page }) => {
  const problems = await watchForErrors(page);
  // Rounds close only when the instructor closes them, so a round past its
  // review deadline still says "reviewing". The seed has no open round, so
  // the portal's answer gets two: one past its deadline, one still open.
  const day = 24 * 60 * 60 * 1000;
  const reviewing = (id: number, number: number, deadline: string) => ({
    id,
    number,
    kind: 'progress',
    title: '',
    practice: false,
    link_required: false,
    status: 'reviewing',
    released: false,
    my_presentation: null,
    selection: null,
    reviewing: {
      deadline,
      rubric: { id: 1, kind: 'progress', version: 1, criteria: [], scale: [], prompts: [], instructions: '' },
      presentations: [],
      progress: { expected: 2, completed: 0, outstanding: [9001, 9002] }
    },
    results: null
  });
  await page.route(`**/api/r/${seed.student.token}`, async (route) => {
    const res = await route.fetch();
    const home = await res.json();
    home.rounds = [
      reviewing(9101, 1, new Date(Date.now() - day).toISOString()),
      reviewing(9102, 2, new Date(Date.now() + day).toISOString())
    ];
    await route.fulfill({ response: res, json: home });
  });
  await page.goto(`/r/${seed.student.token}`);

  const upNext = page.getByRole('region', { name: 'מה הלאה' });
  await expect(upNext.getByRole('button', { name: /סבב התקדמות 2: נשארו 2 ביקורות/ })).toBeVisible();
  await expect(upNext.getByText(/סבב התקדמות 1/)).toHaveCount(0);
  expect(problems).toEqual([]);
});
