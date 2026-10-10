import { expect, test } from '@playwright/test'

const token = 'abcdefghijklmnopqrstuv'
const url = `/missions/${token}`
const clock = { round_id: 1, state: 'LIVE', play_mode: 'ONLINE', control_version: 2, server_time: '2026-10-06T12:00:00Z', remaining_ms: 120_000, active_budget_ms: 120_000, active_elapsed_ms: 0, deadline_at: '2026-10-06T12:02:00Z' }
const mission = { team_code: 'TEST-01', token, mission_id: 'TEST-M1', round_id: 1, clock, opened: false, hint: null as string | null, symbol: '✦', completed: false, voided: false, keyword: null as string | null, wrong_count: 0, cooldown_remaining_ms: 0 }
const decision = { outcome: 'accepted', decision_id: 'test-decision', keyword: 'START', points_awarded: 1, receipt: 'signed-test-receipt', cooldown_remaining_ms: 0 }

test('six-character mission accepts letters and preserves leading zeros', async ({ page }) => {
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: { ...mission, opened: true, answer_format: 'six_ascii_alphanumeric', hint: 'Enter AB0042.' } }))
  await page.route(`**/api/missions/${token}/submit`, async route => {
    expect(route.request().postDataJSON()).toEqual({ answer: 'ab0042' })
    await route.fulfill({ json: decision })
  })
  await page.goto(url)
  const code = page.getByLabel('Six-character answer code')
  await expect(code).toHaveAttribute('maxlength', '6')
  await expect(code).toHaveAttribute('inputmode', 'text')
  await code.fill('ab0042')
  await page.getByRole('button', { name: 'Submit mission answer' }).click()
  await expect(page.getByText('Correct! One point recorded.')).toBeVisible()
})

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'test-token' } }))
  await page.route('**/api/rounds/1/state', route => route.fulfill({ json: { ...clock, score: 0, completions: [] } }))
})

test('QR landing records no open until explicit action then submits leading zeros', async ({ page }) => {
  let current = mission
  let opens = 0
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: current }))
  await page.route('**/api/missions/open', async route => {
    opens++
    expect(route.request().postDataJSON()).toEqual({ token })
    current = { ...current, opened: true, hint: 'Synthetic clue: enter 0042.' }
    await route.fulfill({ json: current })
  })
  await page.route(`**/api/missions/${token}/submit`, async route => {
    expect(route.request().postDataJSON()).toEqual({ answer: '0042' })
    expect(route.request().headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/)
    current = { ...current, completed: true, keyword: 'START' }
    await route.fulfill({ json: decision })
  })
  await page.goto(url)
  await expect(page.getByRole('button', { name: 'Open mission', exact: true })).toBeVisible()
  expect(opens).toBe(0)
  await expect(page.getByText('Synthetic clue: enter 0042.')).toHaveCount(0)
  await page.getByRole('button', { name: 'Open mission', exact: true }).click()
  await expect(page.getByText('Synthetic clue: enter 0042.', { exact: false })).toBeVisible()
  await page.getByLabel('Four-digit mission answer').fill('0042')
  await page.getByRole('button', { name: 'Submit mission answer' }).click()
  await expect(page.getByText('Correct! One point recorded.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Save accepted receipts' })).toHaveAttribute('download', 'treasure-hunt-receipts.json')
  expect(opens).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('lost response recovers recorded acceptance after reload without a second submission', async ({ page }) => {
  let submits = 0
  let key = ''
  let recovered = 0
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: { ...mission, opened: true, hint: 'Synthetic clue' } }))
  await page.route(`**/api/missions/${token}/submit`, async route => {
    submits++; key = route.request().headers()['idempotency-key']
    await route.abort('connectionreset')
  })
  await page.route('**/api/rounds/1/attempts/*', async route => {
    expect(route.request().url().split('/').at(-1)).toBe(key)
    recovered++
    await route.fulfill({ json: { status: 'recorded', decision } })
  })
  await page.goto(url)
  await page.getByLabel('Four-digit mission answer').fill('0042')
  await page.getByRole('button', { name: 'Submit mission answer' }).click()
  await expect(page.getByRole('alert')).toContainText('preserved for recovery')
  await page.reload()
  await page.getByRole('button', { name: 'Check saved attempt' }).click()
  await expect(page.getByText('Correct! One point recorded.')).toBeVisible()
  expect(submits).toBe(1); expect(recovered).toBe(1)
  expect(await page.evaluate(({ token }) => sessionStorage.getItem(`tth:attempt:TEST-01:${token}`), { token })).toBeNull()
})

test('unknown status retries the saved answer with its original attempt key', async ({ page }) => {
  let firstKey = ''
  let submits = 0
  let statusChecks = 0
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: { ...mission, opened: true, hint: 'Synthetic clue' } }))
  await page.route('**/api/rounds/1/attempts/*', async route => { statusChecks++; await route.fulfill({ json: { status: 'unknown', decision: null } }) })
  await page.route(`**/api/missions/${token}/submit`, async route => {
    submits++
    expect(route.request().postDataJSON()).toEqual({ answer: '0042' })
    if (submits === 1) { firstKey = route.request().headers()['idempotency-key']; await route.abort('connectionreset') }
    else {
      expect(statusChecks).toBe(1)
      expect(route.request().headers()['idempotency-key']).toBe(firstKey)
      await route.fulfill({ json: decision })
    }
  })
  await page.goto(url)
  await page.getByLabel('Four-digit mission answer').fill('0042')
  await page.getByRole('button', { name: 'Submit mission answer' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Check saved attempt' }).click()
  await expect(page.getByText('Correct! One point recorded.')).toBeVisible()
  expect(submits).toBe(2)
})

test('paused rounds cannot unlock new clues and opened clues remain readable', async ({ page }) => {
  let current = { ...mission, clock: { ...clock, state: 'FROZEN' } }
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: current }))
  await page.goto(url)
  await expect(page.getByRole('button', { name: 'Open mission', exact: true })).toBeDisabled()
  current = { ...current, opened: true, hint: 'Previously opened synthetic clue' }
  await page.reload()
  await expect(page.getByText('Previously opened synthetic clue', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Submit mission answer' })).toHaveCount(0)
})
