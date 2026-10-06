import { expect, test } from '@playwright/test'

const clock = { round_id: 1, state: 'LIVE', play_mode: 'ONLINE', control_version: 2, server_time: '2026-10-06T12:00:00Z', remaining_ms: 120_000, active_budget_ms: 120_000, active_elapsed_ms: 0, deadline_at: '2026-10-06T12:02:00Z' }
const round = { ...clock, title: 'Synthetic hunt', number: 1, attempt_no: 1, is_demo: true }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'test-token' } }))
  await page.route('**/api/rounds/1/state', route => route.fulfill({ json: { ...clock, score: 0, completions: [] } }))
})

test('countdown ignores wall-clock changes and paused time stays fixed', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-06T12:00:00Z') })
  await page.route('**/api/me', route => route.fulfill({ json: {
    team: { code: 'DEMO-01', name: 'Clock team', member_count: 3, status: 'DISQUALIFIED', is_demo: true },
    session: { active_count: 1, max_active: 4 },
    rounds: [{ id: 1, number: 1, title: 'Synthetic hunt', eligible: false, rules: null, state: 'LIVE', clock }],
  } }))
  await page.goto('/lobby')
  const timer = page.getByLabel('Round time remaining')
  await expect(timer).toHaveText('02:00')
  await page.clock.setSystemTime(new Date('2030-01-01T00:00:00Z'))
  await expect(timer).toHaveText('02:00')
  await page.clock.fastForward(2000)
  await expect(timer).toHaveText('01:58')
  await page.route('**/api/staff/rounds', route => route.fulfill({ json: { rounds: [{ ...round, state: 'FROZEN', remaining_ms: 90_000 }] } }))
  await page.goto('/staff/rounds')
  await expect(timer).toHaveText('01:30')
  await page.clock.fastForward(3000)
  await expect(timer).toHaveText('01:30')
  await expect(page.getByText('Paused · active time is stopped')).toBeVisible()
})

test('organizer pause sends reason and version then refreshes the round', async ({ page }) => {
  let state = round
  await page.route('**/api/staff/rounds', route => route.fulfill({ json: { rounds: [state] } }))
  await page.route('**/api/staff/rounds/1/control', async route => {
    const body = route.request().postDataJSON()
    expect(body.action).toBe('freeze')
    expect(body.expected_version).toBe(2)
    expect(body.reason).toBe('Volunteer pause requested')
    expect(body.action_id).toMatch(/^[a-f0-9-]{36}$/)
    state = { ...state, state: 'FROZEN', control_version: 3 }
    await route.fulfill({ json: { ...state, deadline_reached: false } })
  })
  await page.goto('/staff/rounds')
  await page.getByLabel('Reason', { exact: true }).fill('Volunteer pause requested')
  await page.getByRole('button', { name: 'Apply: Pause round', exact: true }).click()
  await expect(page.getByText('Round paused', { exact: true })).toBeVisible()
  await expect(page.getByText('Control version 3')).toBeVisible()
  await expect(page.getByLabel('Round action')).toHaveValue('resume')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('unknown control outcome survives reload and retries identical payload', async ({ page }) => {
  let original: unknown
  let calls = 0
  await page.route('**/api/staff/rounds', route => route.fulfill({ json: { rounds: [round] } }))
  await page.route('**/api/staff/rounds/1/control', async route => {
    calls++
    if (calls === 1) { original = route.request().postDataJSON(); await route.abort('connectionreset') }
    else { expect(route.request().postDataJSON()).toEqual(original); await route.fulfill({ json: { ...round, state: 'FROZEN', control_version: 3, deadline_reached: false } }) }
  })
  await page.goto('/staff/rounds')
  await page.getByLabel('Reason', { exact: true }).fill('Pause with uncertain response')
  await page.getByRole('button', { name: 'Apply: Pause round', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Retry same action' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('textbox', { name: 'Reason', exact: true })).toHaveValue('Pause with uncertain response')
  await page.getByRole('button', { name: 'Retry same action' }).click()
  await expect(page.getByText('Action confirmed. Current state has been refreshed.')).toBeVisible()
  expect(calls).toBe(2)
  expect(await page.evaluate(() => sessionStorage.getItem('tth:control:1'))).toBeNull()
})

test('stale control rejection refreshes and enables a new request', async ({ page }) => {
  await page.route('**/api/staff/rounds', route => route.fulfill({ json: { rounds: [round] } }))
  await page.route('**/api/staff/rounds/1/control', route => route.fulfill({ status: 409, json: { error: { message: 'Round changed. Refresh before applying this action.' } } }))
  await page.goto('/staff/rounds')
  await page.getByLabel('Reason', { exact: true }).fill('Stale pause')
  await page.getByRole('button', { name: 'Apply: Pause round', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Round changed')
  await expect(page.getByLabel('Round action')).toBeEnabled()
  expect(await page.evaluate(() => sessionStorage.getItem('tth:control:1'))).toBeNull()
})

test('participant cannot access organizer controls', async ({ page }) => {
  await page.route('**/api/staff/rounds', route => route.fulfill({ status: 403, json: { error: { message: 'Access is not permitted.' } } }))
  await page.goto('/staff/rounds')
  await expect(page.getByRole('alert')).toHaveText('Access is not permitted.')
  await expect(page.getByRole('link', { name: 'Staff sign in' })).toHaveAttribute('href', '/admin/login/?next=/staff/rounds')
  await expect(page.getByLabel('Round action')).toHaveCount(0)
})
