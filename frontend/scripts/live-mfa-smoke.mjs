// Runs only against the isolated pytest database; credentials are synthetic.
import { chromium, expect } from '@playwright/test';
import { createHmac } from 'node:crypto';
const origin = process.env.TTH_BACKEND_URL;
if (!origin || !process.env.TTH_MFA_INVITE) throw new Error('Run through pytest.');
const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${origin}/staff-mfa/enroll/`);
  await page.locator('#id_username').fill('mfa-staff');
  await page.locator('#id_password').fill('synthetic-staff-test-password');
  await page.locator('#id_invitation').fill(process.env.TTH_MFA_INVITE);
  await page.getByRole('button', { name: 'Start enrollment' }).click();
  const qr = page.getByAltText('Staff authenticator setup QR code');
  await expect(qr).toBeVisible();
  await expect.poll(() => qr.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  const key = await page.locator('code').textContent();
  const bits = [...key.replace(/=/g, '')].map(c => 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(c).toString(2).padStart(5, '0')).join('');
  const bytes = Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac('sha1', bytes).update(counter).digest();
  const offset = digest[19] & 15;
  const token = ((digest.readUInt32BE(offset) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
  await page.locator('#id_token').fill(token);
  await page.getByRole('button', { name: 'Confirm authenticator' }).click();
  await expect(page.getByRole('heading', { name: 'MFA enabled', exact: true }).first()).toBeVisible();
  const codes = await page.locator('li code').allTextContents();
  expect(codes).toHaveLength(10);
  expect((await context.request.get(`${origin}/api/staff/rounds`)).status()).toBe(200);
  // A new browser has no prior MFA proof. Password alone cannot grant staff access.
  const second = await browser.newContext();
  const login = await second.newPage();
  await login.goto(`${origin}/admin/login/`);
  await login.locator('#id_username').fill('mfa-staff');
  await login.locator('#id_password').fill('synthetic-staff-test-password');
  await login.locator('#id_factor').selectOption('recovery');
  await login.locator('#id_otp_token').fill(codes[0]);
  await login.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(login).toHaveURL(/\/admin\/$/);
  expect((await second.request.get(`${origin}/api/staff/rounds`)).status()).toBe(200);
  console.log('Real browser enrollment, QR, TOTP confirmation, admin/API access and recovery login passed.');
} finally { await browser.close(); }
