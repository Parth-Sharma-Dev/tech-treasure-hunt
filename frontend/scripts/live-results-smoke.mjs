// Opt-in pytest supplies an isolated PostgreSQL fixture and advances its appeal clock.
import { chromium, expect } from '@playwright/test';
const backend = process.env.TTH_BACKEND_URL;
const roundId = process.env.TTH_RESULTS_ROUND;
if (!backend || !roundId) throw new Error('Run through the isolated pytest results integration test.');
const origin = 'http://127.0.0.1:5173';
const browser = await chromium.launch();
const contexts = [];
try {
  async function page() {
    const context = await browser.newContext();
    contexts.push(context);
    for (const prefix of ['api', 'admin']) await context.route(`${origin}/${prefix}/**`, async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: `${backend}${url.pathname}${url.search}`, maxRedirects: 0 });
      await route.fulfill({ response });
    });
    return context.newPage();
  }
  async function staff(username) {
    const result = await page();
    await result.goto(`${origin}/staff/results?round=${roundId}`);
    await result.getByRole('link', { name: 'Staff sign in', exact: true }).click();
    await result.locator('#id_username').fill(username);
    await result.locator('#id_password').fill('test-only');
    await result.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(result.getByRole('heading', { name: 'Results review' })).toBeVisible();
    return result;
  }
  const team = await page();
  team.on('pageerror', error => console.error('Browser page error:', error.message));
  await team.goto(`${origin}/login`);
  await expect(team.getByRole('heading', { name: 'Team sign in', exact: true })).toBeVisible();
  await team.getByLabel('Team code').fill('TEAM-A');
  await team.getByLabel('Password').fill('test-only');
  await team.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(team).toHaveURL(`${origin}/lobby`);
  await team.goto(`${origin}/rounds/${roundId}/results`);
  await expect(team.getByText('Results are not published yet', { exact: true })).toBeVisible();
  const maker = await staff('result-maker');
  await maker.getByLabel('Public publication summary', { exact: true }).fill('Synthetic provisional standings verified');
  await maker.getByRole('button', { name: 'Submit result proposal' }).click();
  await expect(maker.getByText('A different reviewer must approve this proposal.', { exact: true })).toBeVisible();
  await team.reload();
  await expect(team.getByRole('table')).toHaveCount(0);
  const reviewer = await staff('result-reviewer');
  await reviewer.getByLabel('Public review summary', { exact: true }).fill('Independent provisional review complete');
  await reviewer.getByRole('checkbox', { name: 'I independently checked the standings, roster, cut and supporting evidence.' }).check();
  await reviewer.getByRole('button', { name: /Approve and publish proposal/ }).click();
  await expect(reviewer.getByText('Published.', { exact: true })).toBeVisible();
  await team.reload();
  await expect(team.getByText('Provisional results · revision 1', { exact: true })).toBeVisible();
  await expect(team.getByText('Qualification remains pending until final review.', { exact: true })).toBeVisible();
  let identity = await team.request.get(`${backend}/api/me`);
  expect((await identity.json()).rounds.find(round => round.number === 2).eligible).toBe(false);
  await maker.reload();
  await maker.getByLabel('Publication type').selectOption('FINAL');
  await maker.getByLabel('Public publication summary', { exact: true }).fill('Synthetic final standings after the appeal window');
  await maker.getByRole('checkbox', { name: 'I checked the roster, cut count, exclusions and evidence coverage.' }).check();
  await expect(maker.getByRole('button', { name: 'Submit result proposal' })).toBeEnabled();
  await maker.getByRole('button', { name: 'Submit result proposal' }).click();
  await expect(maker.getByText('A different reviewer must approve this proposal.', { exact: true })).toBeVisible();
  await reviewer.reload();
  await reviewer.getByLabel('Public review summary', { exact: true }).fill('Independent final evidence review complete');
  await reviewer.getByRole('checkbox', { name: 'I independently checked the standings, roster, cut and supporting evidence.' }).check();
  await reviewer.getByRole('button', { name: /Approve and publish proposal/ }).click();
  await expect(reviewer.getByText('Published.', { exact: true })).toHaveCount(2);
  await team.reload();
  await expect(team.getByText('Your team qualified for the next round.', { exact: true })).toBeVisible();
  await expect(team.getByText('Publication history (2 revisions)', { exact: true })).toBeVisible();
  identity = await team.request.get(`${backend}/api/me`);
  expect((await identity.json()).rounds.find(round => round.number === 2).eligible).toBe(true);
  console.log('Live two-person provisional/final publication, history and qualification passed.');
} finally {
  for (const context of contexts) await context.unrouteAll({ behavior: 'wait' });
  await browser.close();
}
