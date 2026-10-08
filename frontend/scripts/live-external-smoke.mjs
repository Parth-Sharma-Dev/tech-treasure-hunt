// Executed only against the isolated PostgreSQL pytest live_server fixture.
import { chromium, expect } from '@playwright/test';
const backend = process.env.TTH_BACKEND_URL;
const round = process.env.TTH_EXTERNAL_ROUND;
if (!backend || !round) throw new Error('Run through the isolated external-score integration.');
const origin = 'http://127.0.0.1:5173';
const browser = await chromium.launch();
const contexts = [];
try {
  async function context() {
    const ctx = await browser.newContext();
    contexts.push(ctx);
    for (const path of ['api', 'admin']) await ctx.route(`${origin}/${path}/**`, async route => {
      const url = new URL(route.request().url());
      await route.fulfill({ response: await route.fetch({ url: `${backend}${url.pathname}${url.search}`, maxRedirects: 0 }) });
    });
    return ctx;
  }
  async function staff(username) {
    const ctx = await context();
    const page = await ctx.newPage();
    await page.goto(`${origin}/staff/scores?round=${round}`);
    await page.getByRole('link', { name: 'Staff sign in', exact: true }).click();
    await page.locator('#id_username').fill(username);
    await page.locator('#id_password').fill('test-only');
    await page.getByRole('button', { name: 'Log in', exact: true }).click();
    return page;
  }
  const maker = await staff('external-maker');
  await maker.goto(`${origin}/staff/scores?round=${round}`);
  await maker.getByLabel('Private intake or correction reason').fill('Synthetic original paper sheets');
  await maker.getByLabel('CSV source').fill('team_code,correct_question_ids,official_finish_active_ms,source_reference\nEXT-0,Q01|Q02,1000,sheet-a\nEXT-1,Q01,1100,sheet-b\nEXT-2,,1200,sheet-c\n');
  const intakeResponse = maker.waitForResponse(response => response.url().endsWith('/imports/validate') && response.request().method() === 'POST');
  await maker.getByRole('button', { name: 'Dry-run CSV' }).click();
  const batch = (await (await intakeResponse).json()).batch_id;
  await expect(maker.getByText(`Batch ${batch} · awaiting review`, { exact: true })).toBeVisible();
  await maker.getByText(`Batch ${batch} · awaiting review`, { exact: true }).click();
  await expect(maker.getByText('A different organizer must review this batch.')).toBeVisible();
  const verifier = await staff('external-reviewer');
  await verifier.goto(`${origin}/staff/scores?round=${round}`);
  await verifier.getByText(`Batch ${batch} · awaiting review`, { exact: true }).click();
  await verifier.getByLabel('Private review decision').fill('Independent paper mark and finish-time checks');
  await verifier.getByLabel('I checked every original score sheet, team, mark and tie metric.').check();
  await verifier.getByRole('button', { name: `Commit reviewed batch ${batch}`, exact: true }).click();
  await expect(verifier.getByText(`Batch ${batch} · committed`, { exact: true })).toBeVisible();
  await maker.goto(`${origin}/staff/results?round=${round}`);
  await maker.getByLabel('Public publication summary', { exact: true }).fill('Synthetic paper scores independently checked');
  const publicationResponse = maker.waitForResponse(response => response.url().endsWith('/publish') && response.request().method() === 'POST');
  await maker.getByRole('button', { name: 'Submit result proposal' }).click();
  const proposal = (await (await publicationResponse).json()).proposal_id;
  await verifier.goto(`${origin}/staff/results?round=${round}`);
  await verifier.getByLabel('Public review summary', { exact: true }).fill('Independent external publication review');
  await verifier.getByLabel('I independently checked the standings, roster, cut and supporting evidence.').check();
  await verifier.getByRole('button', { name: `Approve and publish proposal ${proposal}` }).click();
  const team = await context();
  const page = await team.newPage();
  await page.goto(`${origin}/login`);
  await page.getByLabel('Team code').fill('EXT-0');
  await page.getByLabel('Password').fill('test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/lobby`);
  await page.goto(`${origin}/rounds/${round}/results`);
  await expect(page.getByRole('heading', { name: 'Provisional results · revision 1' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Recorded hand-in' })).toBeVisible();
  await expect(page.getByRole('cell', { name: '2 / 30', exact: true })).toBeVisible();
  await maker.goto(`${origin}/staff/roster`);
  await maker.getByLabel('Private source or status reason').fill('Synthetic real-cohort application');
  await maker.getByLabel('Team code', { exact: true }).fill('REAL-BROWSER');
  await maker.getByLabel('Team name', { exact: true }).fill('Synthetic roster browser team');
  await maker.getByLabel('Leader name', { exact: true }).fill('Synthetic roster leader');
  await maker.getByLabel('Roster evidence reference').fill('synthetic-application');
  const rosterResponse = maker.waitForResponse(response => response.url().endsWith('/roster/change') && response.request().method() === 'POST');
  await maker.getByRole('button', { name: 'Propose team change', exact: true }).click();
  const rosterProposal = (await (await rosterResponse).json()).proposal_id;
  await verifier.goto(`${origin}/staff/roster`);
  await verifier.getByText(`Roster proposal ${rosterProposal} · real · pending`, { exact: true }).click();
  await verifier.getByLabel('Private roster review').fill('Independently checked membership application');
  await verifier.getByLabel('I independently verified the applications, membership and status decision.').check();
  await verifier.getByRole('button', { name: `Approve roster proposal ${rosterProposal}`, exact: true }).click();
  await expect(verifier.getByRole('heading', { name: 'REAL-BROWSER · Synthetic roster browser team' })).toBeVisible();
  await maker.reload();
  await maker.getByText('Issue credentials for REAL-BROWSER', { exact: true }).click();
  await maker.getByLabel('New team password').fill('Synthetic-Roster-Secret-921');
  await maker.getByLabel('Private access reason').fill('Issue synthetic approved team credentials');
  await maker.getByRole('button', { name: 'Issue team credentials', exact: true }).click();
  await expect(maker.getByText('Credentials saved. Password cleared from this form.')).toBeVisible();
  console.log('Real HTTP/PostgreSQL external intake → independent commit → publication → participant results passed.');
  console.log('Real HTTP/PostgreSQL roster creation → independent review → credential issuance passed.');
} finally {
  for (const ctx of contexts) await ctx.unrouteAll({ behavior: 'wait' });
  await browser.close();
}
