import { expect, test, type APIRequestContext } from '@playwright/test';

/* Auto-assigning unteamed students after teams lock: the instructor proposes,
 * nothing is saved, then approving writes the shown proposal. Uses its own
 * course so it never touches the seeded one. */
const API = `http://localhost:${process.env.E2E_BACKEND_PORT ?? 8100}`;

async function post(request: APIRequestContext, path: string, data?: unknown) {
  const res = await request.post(`${API}${path}`, { data });
  expect(res.ok(), `${path}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

test('instructor proposes, reviews and approves team placements', async ({ page, request }) => {
  const course = await post(request, '/api/courses', { code: 'E2E-TEAMS', name: 'Teams e2e', year: 2026, semester: 'A' });
  const base = `/api/courses/${course.id}/peer`;
  for (let i = 0; i < 4; i++) {
    await post(request, `/api/courses/${course.id}/students`, { national_id: `77700000${i}`, name: `Unteamed ${i}` });
  }
  await post(request, `${base}/setup`);
  const settings = await request.put(`${API}${base}/team-settings`, { data: { teams_open: false, max_team_size: 3 } });
  expect(settings.ok()).toBeTruthy();

  await page.addInitScript(() => localStorage.setItem('cg-course-step', 'peer'));
  await page.goto(`/course/${course.id}`);
  await page.getByRole('button', { name: 'Teams & links' }).click();
  await page.getByRole('button', { name: 'הצע שיבוץ' }).click();

  // A preview only: two new pairs, and the server still has nobody placed.
  await expect(page.getByText('הצעת שיבוץ (טרם נשמרה)')).toBeVisible();
  await expect(page.getByText('2/3')).toHaveCount(2);
  const before = await (await request.get(`${API}${base}/teams`)).json();
  expect(before.unassigned).toHaveLength(4);
  expect(before.teams).toHaveLength(0);

  // Edit before approving: leave one student out; they stay without a team.
  await page.getByRole('button', { name: 'השמט' }).first().click();
  await expect(page.getByText('יישארו בלי צוות:')).toBeVisible();
  await expect(page.getByText('1/3')).toHaveCount(1);

  await page.getByRole('button', { name: 'אשר ושמור' }).click();
  await expect(page.getByText('השיבוץ אושר ונשמר')).toBeVisible();
  const after = await (await request.get(`${API}${base}/teams`)).json();
  expect(after.unassigned).toHaveLength(1);
  expect(after.teams).toHaveLength(2);
});
