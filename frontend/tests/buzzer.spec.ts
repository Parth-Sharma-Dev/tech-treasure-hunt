import { expect, test } from '@playwright/test'
import { portalRound } from './portal-fixtures'

const window = { id: 7, version: 1, stage: 2, question_id: 51, question_label: 'KEYWORD-Q1', accepting: true, opened_at: '2026-10-09T07:00:00Z', closed_at: null as string | null }
const receipt = { id: 'f9bac205-f70d-4a44-a14c-cf27c96a4f39', window_id: 7, received_at: '2026-10-09T07:00:01.123456Z', admitted_at: '2026-10-09T07:00:01.124456Z' }
const status = { round_id: 5, team_code: 'TEAM-A', state: 'LIVE', eligible: true, eligibility_reason: 'Your team is eligible.', window, own_press: null as typeof receipt | null, can_press: true }
const overview = portalRound({ id: 5, number: 5, title: 'Synthetic buzzer final', state: 'LIVE', eligible: true,
  clock: { state: 'LIVE', play_mode: 'ONLINE', remaining_ms: 60000, server_time: '2026-10-09T07:00:00Z', deadline_at: null, active_elapsed_ms: 0 } })

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic-csrf' } }))
  await page.route('**/api/me', route => route.fulfill({ json: { team: { code: 'TEAM-A', name: 'Synthetic team', member_count: 3, status: 'ACTIVE', is_demo: true }, session: { active_count: 1, max_active: 4 }, rounds: [] } }))
  await page.route('**/api/rounds/5/overview', route => route.fulfill({ json: { ...overview, capabilities: { ...overview.capabilities, buzzer_supported: true }, buzzer_stages: [{ number: 2, title: 'Answer from keywords', description: 'Find the concept.' }] } }))
  await page.route('**/api/rounds/5/buzzer', route => route.fulfill({ json: status }))
})

test('one request records a press with server time and no client time', async ({ page }) => {
  let recorded = false
  let csrfRequests = 0
  await page.route('**/api/auth/csrf', route => { csrfRequests++; return route.fulfill({ json: { csrf_token: 'prefetched-csrf' } }) })
  await page.route('**/api/rounds/5/buzzer', route => route.fulfill({ json: { ...status, own_press: recorded ? receipt : null, can_press: !recorded } }))
  await page.route('**/api/rounds/5/buzzer/press', async route => {
    expect(Object.keys(route.request().postDataJSON()).sort()).toEqual(['action_id', 'window_id'])
    expect(route.request().headers()['x-csrftoken']).toBe('prefetched-csrf')
    recorded = true
    await route.fulfill({ json: { press: receipt } })
  })
  await page.goto('/rounds/5')
  const button = page.getByRole('button', { name: 'Press Round 5 buzzer' })
  await expect(button).toBeEnabled()
  const before = csrfRequests
  await button.click()
  await expect(page.getByText(/Your press is recorded at/)).toBeVisible()
  await expect(page.getByText(/\.123456 IST/)).toBeVisible()
  await expect(button).toBeDisabled()
  expect(csrfRequests).toBe(before)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('lost acknowledgment survives reload and recovers the same receipt', async ({ page }) => {
  let identity = ''
  let posts = 0
  await page.route('**/api/rounds/5/buzzer/press', async route => {
    posts++; identity = route.request().postDataJSON().action_id
    await route.abort('connectionfailed')
  })
  await page.route('**/api/rounds/5/buzzer/presses/*', route => route.fulfill({ json: { press: { ...receipt, id: identity } } }))
  await page.goto('/rounds/5')
  await page.getByRole('button', { name: 'Press Round 5 buzzer' }).click()
  await expect(page.getByRole('button', { name: 'Recover saved press' })).toBeEnabled()
  await page.reload()
  await page.getByRole('button', { name: 'Recover saved press' }).click()
  await expect(page.getByText(/Your press is recorded at/)).toBeVisible()
  expect(posts).toBe(1)
  await expect(page.getByRole('button', { name: 'Recover saved press' })).toHaveCount(0)
})

test('an unrecorded request retries the original UUID and original window', async ({ page }) => {
  const requests: Record<string, unknown>[] = []
  await page.route('**/api/rounds/5/buzzer/presses/*', route => route.fulfill({ status: 404, json: { error: { message: 'Not recorded.' } } }))
  await page.route('**/api/rounds/5/buzzer/press', async route => {
    requests.push(route.request().postDataJSON())
    if (requests.length === 1) await route.abort('connectionfailed')
    else await route.fulfill({ json: { press: { ...receipt, id: requests[0].action_id } } })
  })
  await page.goto('/rounds/5')
  await page.getByRole('button', { name: 'Press Round 5 buzzer' }).click()
  await page.getByRole('button', { name: 'Recover saved press' }).click()
  await expect(page.getByText(/Your press is recorded at/)).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
})

test('ineligible or paused teams cannot buzz', async ({ page }) => {
  await page.route('**/api/rounds/5/buzzer', route => route.fulfill({ json: { ...status, eligible: false, can_press: false, window: null, eligibility_reason: 'Your team did not qualify from Round 4.' } }))
  await page.goto('/rounds/5')
  await expect(page.getByRole('button', { name: 'Press Round 5 buzzer' })).toBeDisabled()
  await expect(page.getByText('Your team did not qualify from Round 4.')).toBeVisible()
  await page.route('**/api/rounds/5/buzzer', route => route.fulfill({ json: { ...status, state: 'FROZEN', can_press: false, window: { ...window, accepting: false } } }))
  await page.reload()
  await expect(page.getByText('Round 5 is paused.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Press Round 5 buzzer' })).toBeDisabled()
})

const desk = { round_id: 5, title: 'Synthetic buzzer final', state: 'LIVE', control_version: 4, can_control: true, window, entries: [{ ...receipt, team_code: 'TEAM-A', team_name: 'Synthetic team', team_status: 'ACTIVE', position: 1 }], first_team_codes: ['TEAM-A'], timestamp_tie: false, order_final: false,
  questions: [{ id: 51, stage: 2, public_id: 'KEYWORD-Q1', version: 'v1' }], history: [] }

test('admin closes the window and sees confirmed order at full precision', async ({ page }) => {
  let closed = false
  await page.route('**/api/staff/buzzer/rounds', route => route.fulfill({ json: { rounds: [{ id: 5, title: 'Synthetic final', attempt_no: 1, is_demo: true }] } }))
  await page.route('**/api/staff/rounds/5/buzzer', route => route.fulfill({ json: { ...desk, order_final: closed, window: closed ? { ...window, accepting: false, closed_at: '2026-10-09T07:00:05Z' } : window } }))
  await page.route('**/api/staff/rounds/5/buzzer/control', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ operation: 'close', expected_version: 4, expected_window_version: 1, reason: 'All admitted presses reviewed' })
    closed = true; await route.fulfill({ json: { window: { ...window, accepting: false } } })
  })
  await page.goto('/staff/buzzer')
  await expect(page.getByText('2026-10-09T07:00:01.123456Z UTC')).toBeVisible()
  await page.getByLabel('Buzzer action reason').fill('All admitted presses reviewed')
  await page.getByRole('button', { name: 'Close buzzer and confirm order' }).click()
  await expect(page.getByText(/First team to answer offline: TEAM-A/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('admin equal timestamps require review rather than selecting a team-code winner', async ({ page }) => {
  await page.route('**/api/staff/buzzer/rounds', route => route.fulfill({ json: { rounds: [{ id: 5, title: 'Synthetic final', attempt_no: 1, is_demo: true }] } }))
  await page.route('**/api/staff/rounds/5/buzzer', route => route.fulfill({ json: { ...desk, timestamp_tie: true, first_team_codes: ['TEAM-A', 'TEAM-B'] } }))
  await page.goto('/staff/buzzer')
  await expect(page.getByRole('alert')).toContainText('Equal server timestamps: TEAM-A, TEAM-B')
  await expect(page.getByText(/First team to answer offline:/)).toHaveCount(0)
})
