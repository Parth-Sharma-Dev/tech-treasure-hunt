import { expect, test } from '@playwright/test'
import { portalRound } from './portal-fixtures'

const identity = { team: { code: 'DEMO-01', name: 'Demo explorers', member_count: 4, status: 'ACTIVE', is_demo: true }, session: { active_count: 1, max_active: 1 }, rounds: [{ id: 1, number: 1, title: 'Treasure hunt', state: 'DRAFT', eligible: true, rules: null, clock: { state: 'DRAFT' } }] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'test-token' } }))
  await page.route('**/api/me', route => route.fulfill({ json: identity }))
  await page.route('**/api/rounds', route => route.fulfill({ json: { rounds: identity.rounds.map(portalRound), announcements: [] } }))
  await page.route('**/api/rounds/1/overview', route => route.fulfill({ json: portalRound(identity.rounds[0]) }))
  await page.route('**/api/practice', route => route.fulfill({ json: { hint: 'Enter 0427.', symbol: '✦' } }))
})

test('signs in and preserves leading zeros in isolated practice', async ({ page }) => {
  await page.route('**/api/auth/login', async route => {
    expect(route.request().postDataJSON()).toEqual({ team_code: 'DEMO-01', password: 'test-password', return_to: '/lobby' })
    expect(route.request().headers()['x-csrftoken']).toBe('test-token')
    await route.fulfill({ json: { ...identity, return_to: '/lobby' } })
  })
  await page.route('**/api/practice/submit', async route => {
    expect(route.request().postDataJSON()).toEqual({ answer: '0427' })
    await route.fulfill({ json: { outcome: 'accepted', keyword: 'START', points_awarded: 0 } })
  })
  await page.goto('/login')
  await page.getByLabel('Team code').fill('DEMO-01')
  await page.getByLabel('Password').fill('test-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/lobby$/)
  await expect(page.getByRole('heading', { name: 'Demo explorers' })).toBeVisible()
  await expect(page.getByText('Awaiting organizer approval')).toBeVisible()
  await expect(page.getByLabel('Four-digit answer')).toHaveCount(0)
  await page.getByRole('link', { name: 'Open Round 1' }).click()
  await expect(page).toHaveURL(/\/rounds\/1$/)
  await page.getByLabel('Four-digit answer').fill('0427')
  await page.getByRole('button', { name: 'Check practice answer' }).click()
  await expect(page.getByText('Correct! Keyword: START. No points awarded.')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).not.toContain('test-password')
})

test('shows session capacity errors without leaving sign in', async ({ page }) => {
  await page.route('**/api/auth/login', route => route.fulfill({ status: 409, json: { error: { message: 'Your team is already signed in on one browser. Contact an organizer.' } } }))
  await page.goto('/login')
  await page.getByLabel('Team code').fill('DEMO-01')
  await page.getByLabel('Password').fill('test-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('already signed in on one browser')
  await expect(page).toHaveURL(/\/login$/)
})

test('expired mission session retains its destination for sign in', async ({ page }) => {
  await page.route('**/api/missions/*', route => route.fulfill({ status: 401, json: { error: { message: 'Your session has ended.' } } }))
  const path = '/missions/abcdefghijklmnopqrstuv'
  await page.goto(path)
  await expect(page.getByRole('heading', { name: 'Sign in to continue' })).toBeVisible()
  await page.getByRole('link', { name: 'Team sign in' }).click()
  expect(new URL(page.url()).searchParams.get('next')).toBe(path)
})

test('sign out clears only application session data', async ({ page }) => {
  await page.route('**/api/auth/logout', route => route.fulfill({ json: { signed_out: true } }))
  await page.goto('/lobby')
  await page.evaluate(() => { sessionStorage.setItem('tth:pending', 'test'); sessionStorage.setItem('other', 'keep') })
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/$/)
  expect(await page.evaluate(() => sessionStorage.getItem('tth:pending'))).toBeNull()
  expect(await page.evaluate(() => sessionStorage.getItem('other'))).toBe('keep')
})

test('Round 1 fallback belongs to its live page and disappears during pause', async ({ page }) => {
  let state = 'LIVE'
  await page.route('**/api/rounds/1/overview', route => route.fulfill({ json: portalRound({ ...identity.rounds[0], state, clock: { state, play_mode: 'ONLINE', remaining_ms: 60000, server_time: new Date().toISOString(), deadline_at: null, active_elapsed_ms: 0 } }) }))
  await page.route('**/api/me', route => route.fulfill({ json: { ...identity, rounds: [{ ...identity.rounds[0], state, clock: { state, play_mode: 'ONLINE', remaining_ms: 60000, server_time: new Date().toISOString(), deadline_at: null, active_elapsed_ms: 0 } }] } }))
  await page.route('**/api/rounds/1/state', route => route.fulfill({ json: { score: 0, completions: [] } }))
  await page.goto('/lobby')
  await expect(page.getByLabel('Mission fallback code')).toHaveCount(0)
  await page.getByRole('link', { name: 'Open Round 1' }).click()
  await expect(page.getByLabel('Mission fallback code')).toBeVisible()
  state = 'FROZEN'
  await page.reload()
  await expect(page.getByLabel('Mission fallback code')).toHaveCount(0)
  await expect(page.getByText('Round paused', { exact: true })).toBeVisible()
})
