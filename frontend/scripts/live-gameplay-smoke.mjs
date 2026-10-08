// Invoked by the opt-in pytest test against its isolated PostgreSQL database.
import { chromium, expect } from '@playwright/test';

const backend = process.env.TTH_BACKEND_URL;
const token = process.env.TTH_MISSION_TOKEN;
if (!backend || !token) throw new Error('Run through the isolated pytest browser integration test.');
const origin = 'http://127.0.0.1:5173';
const browser = await chromium.launch();
const contexts = [];
try {
  async function context() {
    const result = await browser.newContext();
    contexts.push(result);
    await result.route(`${origin}/api/**`, async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: `${backend}${url.pathname}${url.search}`, maxRedirects: 0 });
      await route.fulfill({ response });
    });
    await result.route(`${origin}/admin/**`, async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: `${backend}${url.pathname}${url.search}`, maxRedirects: 0 });
      await route.fulfill({ response });
    });
    return result;
  }
  const staff = await context();
  const desk = await staff.newPage();
  await desk.goto(`${origin}/staff/rounds`);
  await desk.getByRole('link', { name: 'Staff sign in', exact: true }).click();
  await desk.locator('#id_username').fill('browser-controller');
  await desk.locator('#id_password').fill('synthetic-test-only');
  await desk.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(desk.getByText('Ready for the lobby', { exact: true })).toBeVisible();
  await desk.getByLabel('Reason', { exact: true }).fill('Open synthetic browser rehearsal');
  await desk.getByRole('button', { name: 'Apply: Open lobby', exact: true }).click();
  await expect(desk.getByText('Waiting for the start', { exact: true })).toBeVisible();
  await desk.getByLabel('Reason', { exact: true }).fill('Start synthetic browser rehearsal');
  await desk.getByRole('button', { name: 'Apply: Start round', exact: true }).click();
  await expect(desk.getByText('Round live', { exact: true })).toBeVisible();
  const team = await context();
  const page = await team.newPage();
  await page.goto(`${origin}/login`);
  await page.getByLabel('Team code').fill('BROWSER-01');
  await page.getByLabel('Password').fill('synthetic-test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/lobby`);
  await page.goto(`${origin}/missions/${token}`);
  await page.getByRole('button', { name: 'Open mission', exact: true }).click();
  await page.getByLabel('Four-digit mission answer').fill('0042');
  await page.getByRole('button', { name: 'Submit mission answer' }).click();
  await expect(page.getByText('Correct! One point recorded.')).toBeVisible();
  await expect(page.getByText('Current score: 1', { exact: true })).toBeVisible();
  await desk.getByLabel('Reason', { exact: true }).fill('Pause synthetic browser rehearsal');
  await desk.getByRole('button', { name: 'Apply: Pause round', exact: true }).click();
  await expect(desk.getByText('Round paused', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Round paused', { exact: true })).toBeVisible();
  await expect(page.getByText('Current score: 1', { exact: true })).toBeVisible();
  const receipts = await page.request.get(`${backend}/api/me/receipts`);
  expect(receipts.status()).toBe(200);
  expect((await receipts.json()).receipts).toHaveLength(1);
  await page.goto(`${origin}/lobby`);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/`);
  console.log('Live organizer start, team login, QR open, solve, score, pause, receipt and logout passed.');
} finally {
  for (const context of contexts) await context.unrouteAll({ behavior: 'wait' });
  await browser.close();
}
