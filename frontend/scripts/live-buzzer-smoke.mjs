// Run only through the isolated PostgreSQL pytest fixture, never the application's database.
import { chromium, expect } from '@playwright/test';
const backend = process.env.TTH_BACKEND_URL;
const round = process.env.TTH_BUZZER_ROUND;
if (!backend || !round) throw new Error('Run through the isolated buzzer integration.');
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
  const staff = await context();
  const controls = await staff.newPage();
  await controls.goto(`${origin}/staff/rounds`);
  await controls.getByRole('link', { name: 'Staff sign in', exact: true }).click();
  await controls.locator('#id_username').fill('buzzer-maker');
  await controls.locator('#id_password').fill('test-only');
  await controls.getByRole('button', { name: 'Log in', exact: true }).click();
  await controls.getByLabel('Reason', { exact: true }).fill('Open synthetic buzzer lobby');
  await controls.getByRole('button', { name: 'Apply: Open lobby', exact: true }).click();
  await expect(controls.getByText('Waiting for the start', { exact: true })).toBeVisible();
  await controls.getByLabel('Reason', { exact: true }).fill('Start synthetic buzzer final');
  await controls.getByRole('button', { name: 'Apply: Start round', exact: true }).click();
  await expect(controls.getByText('Round live', { exact: true })).toBeVisible();
  const desk = await staff.newPage();
  await desk.goto(`${origin}/staff/buzzer`);
  await desk.getByLabel('Buzzer action reason').fill('Open verified stage one question');
  await desk.getByRole('button', { name: 'Open question buzzer', exact: true }).click();
  await expect(desk.getByText(/Stage 1 · STAGE-1-Q1 · window 1 · Open/)).toBeVisible();
  const team = await context();
  let lost = false;
  await team.route('**/buzzer/press', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${backend}${url.pathname}` });
    if (!lost) { lost = true; await route.abort('connectionfailed'); }
    else await route.fulfill({ response });
  });
  const page = await team.newPage();
  await page.goto(`${origin}/login`);
  await page.getByLabel('Team code').fill('BUZZ-0');
  await page.getByLabel('Password').fill('test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/lobby`);
  await page.getByRole('link', { name: 'Open Round 5', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'The five final stages' })).toBeVisible();
  await page.getByRole('button', { name: 'Press Round 5 buzzer' }).click();
  await expect(page.getByRole('button', { name: 'Recover saved press' })).toBeEnabled();
  await page.reload();
  await page.getByRole('button', { name: 'Recover saved press' }).click();
  await expect(page.getByText(/Your press is recorded at/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Recover saved press' })).toHaveCount(0);
  await desk.getByLabel('Buzzer action reason').fill('Close after all admitted presses');
  await desk.getByRole('button', { name: 'Close buzzer and confirm order', exact: true }).click();
  await expect(desk.getByText(/First team to answer offline: BUZZ-0/)).toBeVisible();
  await desk.getByLabel('Frozen question').selectOption({ label: 'Stage 2 · STAGE-2-Q1 · question-v1' });
  await desk.getByLabel('Buzzer action reason').fill('Open verified stage two question');
  await desk.getByRole('button', { name: 'Open question buzzer', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Press Round 5 buzzer' })).toBeEnabled();
  await page.getByRole('button', { name: 'Press Round 5 buzzer' }).click();
  await expect(page.getByText(/Your press is recorded at/)).toBeVisible();
  await desk.getByLabel('Buzzer action reason').fill('Close second synthetic question');
  await desk.getByRole('button', { name: 'Close buzzer and confirm order', exact: true }).click();
  await expect(desk.getByText(/Stage 2 · STAGE-2-Q1 · window 2 · Closed/)).toBeVisible();
  if (await page.locator('body').innerText().then(text => text.includes('SECRET-ANSWER'))) throw new Error('Private answer leaked.');
  console.log('Actual HTTP/PostgreSQL buzzer open, press, lost-response recovery, close and next-window journey passed.');
} finally {
  for (const context of contexts) {
    await context.unrouteAll({ behavior: 'wait' });
    await context.close();
  }
  await browser.close();
}
