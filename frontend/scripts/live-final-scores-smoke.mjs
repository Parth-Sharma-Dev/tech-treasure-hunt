// Isolated pytest fixture only; never run against the event database.
import { chromium, expect } from '@playwright/test';
const backend = process.env.TTH_BACKEND_URL;
const round = process.env.TTH_FINAL_ROUND;
if (!backend || !round) throw new Error('Use the isolated final-score integration.');
const origin = 'http://127.0.0.1:5173';
const browser = await chromium.launch();
const contexts = [];
try {
  async function context() {
    const ctx = await browser.newContext(); contexts.push(ctx);
    for (const path of ['api', 'admin']) await ctx.route(`${origin}/${path}/**`, async route => {
      const url = new URL(route.request().url());
      await route.fulfill({ response: await route.fetch({ url: `${backend}${url.pathname}${url.search}`, maxRedirects: 0 }) });
    });
    return ctx;
  }
  async function login(ctx, username) {
    const page = await ctx.newPage();
    await page.goto(`${origin}/admin/login/?next=/staff/buzzer`);
    await page.locator('#id_username').fill(username);
    await page.locator('#id_password').fill('test-only');
    await page.getByRole('button', { name: 'Log in', exact: true }).click();
    return page;
  }
  const staff = await context();
  const host = await login(staff, 'buzzer-maker');
  const team = await context();
  const participant = await team.newPage();
  await participant.goto(`${origin}/login`);
  await participant.getByLabel('Team code').fill('BUZZ-0');
  await participant.getByLabel('Password').fill('test-only');
  await participant.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(participant).toHaveURL(`${origin}/lobby`);
  await participant.goto(`${origin}/rounds/${round}`);
  await participant.getByRole('button', { name: 'Press Round 5 buzzer' }).click();
  await expect(participant.getByText(/Your press is recorded at/)).toBeVisible();
  await host.getByLabel('Buzzer action reason').fill('Close final synthetic question');
  await host.getByRole('button', { name: 'Close buzzer and confirm order', exact: true }).click();
  await expect(host.getByText(/First team to answer offline: BUZZ-0/)).toBeVisible();
  await host.getByLabel('Original spoken answer').fill('private answer');
  await host.getByLabel('Private host sheet reference').fill('synthetic-host-sheet');
  await host.getByLabel('Host record reason').fill('Observed final offline response');
  await host.getByRole('button', { name: 'Record observed offline answer' }).click();
  await expect(host.getByText(/BUZZ-0 · CORRECT · host record/)).toBeVisible();
  await host.goto(`${origin}/staff/rounds`);
  await host.getByLabel('Round action').selectOption('end');
  await host.getByLabel('Reason', { exact: true }).fill('End synthetic final for review');
  await host.getByRole('button', { name: 'Apply: End round', exact: true }).click();
  await expect(host.getByText('Round ended', { exact: true })).toBeVisible();
  const source = await host.request.get(`${backend}/api/staff/rounds/${round}/imports`);
  const data = await source.json();
  if (!data.draft_source_rows?.length) throw new Error('Native draft ledger missing.');
  const rows = data.draft_source_rows.map(row => ({ ...row, verdict: row.verdict || 'NO_BUZZ', source_reference: row.source_reference || 'synthetic-no-buzz-sheet' }));
  const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const csv = [data.round.headers.join(','), ...rows.map(row => data.round.headers.map(field => quote(row[field])).join(','))].join('\n');
  await host.goto(`${origin}/staff/scores?round=${round}`);
  await host.getByLabel('Private intake or correction reason').fill('Reviewed synthetic final source sheets');
  await host.getByLabel('CSV source').fill(csv);
  const batchResponse = host.waitForResponse(response => response.url().endsWith('/imports/validate') && response.request().method() === 'POST');
  await host.getByRole('button', { name: 'Dry-run CSV', exact: true }).click();
  const batch = await (await batchResponse).json();
  if (batch.errors.length) throw new Error(JSON.stringify(batch.errors));
  const verifier = await context();
  const review = await login(verifier, 'buzzer-reviewer');
  await review.goto(`${origin}/staff/scores?round=${round}`);
  await review.getByText(`Batch ${batch.batch_id} · awaiting review`, { exact: true }).click();
  await review.getByLabel('Private review decision').fill('Independent native source and carry-over check');
  await review.getByRole('checkbox', { name: 'I checked every original score sheet, team, mark and tie metric.' }).check();
  await review.getByRole('button', { name: `Commit reviewed batch ${batch.batch_id}`, exact: true }).click();
  await expect(review.getByText(`Batch ${batch.batch_id} · committed`, { exact: true })).toBeVisible();
  async function publish(status) {
    await host.goto(`${origin}/staff/results?round=${round}`);
    await host.getByLabel('Publication type').selectOption(status);
    await host.getByLabel('Public publication summary', { exact: true }).fill(`Synthetic ${status} final standings`);
    if (status === 'FINAL') await host.getByRole('checkbox', { name: 'I checked the roster, cut count, exclusions and evidence coverage.' }).check();
    const proposedResponse = host.waitForResponse(response => response.url().endsWith('/publish') && response.request().method() === 'POST');
    await host.getByRole('button', { name: 'Submit result proposal', exact: true }).click();
    const proposal = await (await proposedResponse).json();
    await review.goto(`${origin}/staff/results?round=${round}`);
    await review.getByLabel('Public review summary', { exact: true }).fill('Independent final event award check');
    await review.getByRole('checkbox', { name: 'I independently checked the standings, roster, cut and supporting evidence.' }).check();
    const publishedResponse = review.waitForResponse(response => response.url().endsWith('/publish') && response.request().method() === 'POST');
    await review.getByRole('button', { name: `Approve and publish proposal ${proposal.proposal_id}`, exact: true }).click();
    const published = await (await publishedResponse).json();
    if (published.status !== status) throw new Error(`Publication failed: ${JSON.stringify(published)}`);
  }
  await publish('PROVISIONAL');
  await participant.goto(`${origin}/rounds/${round}/results`);
  await expect(participant.getByText('The event winner remains pending until final review.')).toBeVisible();
  // Only the Python fixture advances its publication clock; production cannot skip appeals.
  await publish('FINAL');
  await participant.reload();
  await expect(participant.getByRole('heading', { name: 'The Winner of Tech Treasure Hunt' })).toBeVisible();
  await expect(participant.getByRole('cell', { name: 'Winner', exact: true }).first()).toBeVisible();
  if ((await participant.locator('body').innerText()).includes('private answer')) throw new Error('Private answer leaked.');
  console.log('Actual host completion, independent ledger review, provisional/final publication and one event winner passed.');
} finally {
  for (const ctx of contexts) await ctx.unrouteAll({ behavior: 'wait' });
  await browser.close();
}
