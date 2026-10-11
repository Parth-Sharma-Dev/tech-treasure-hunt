import { expect, test } from '@playwright/test'

const token = 'abcdefghijklmnopqrstuv'
const url = `/missions/${token}`
const clock = { round_id: 1, state: 'LIVE', play_mode: 'ONLINE', control_version: 2, server_time: '2026-10-06T12:00:00Z', remaining_ms: 120_000, active_budget_ms: 120_000, active_elapsed_ms: 0, deadline_at: '2026-10-06T12:02:00Z' }
const mission = { team_code: 'TEST-01', token, mission_id: 'TEST-M1', round_id: 1, clock, opened: false, hint: null as string | null, symbol: '✦', completed: false, voided: false, keyword: null as string | null, wrong_count: 0, cooldown_remaining_ms: 0 }
const decision = { outcome: 'accepted', decision_id: 'test-decision', keyword: 'START', points_awarded: 1, receipt: 'signed-test-receipt', cooldown_remaining_ms: 0 }
const clueImage = { url: `/api/missions/${token}/image`, alt: 'Approved green symbol', sha256: 'a'.repeat(64), width: 40, height: 24 }
const cluePng = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAACgAAAAYCAIAAAAH5iiXAAAAOElEQVR4nO3NQQEAMAwCMYrySe8bA9fHiIGMnk74plVjjsErNMaYq1JjjLkqNcaYq1JjjLkqNcaYq1JjjLlKn8cLxvIAsIO9ec0AAAAASUVORK5CYII=', 'base64')

test('image clue appears only after explicit open and stays within the viewport', async ({ page }) => {
  let opened = false
  let downloads = 0
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: { ...mission, opened, image: opened ? clueImage : null } }))
  await page.route(`**/api/missions/${token}/image?*`, route => { downloads++; return route.fulfill({ contentType: 'image/png', body: cluePng }) })
  await page.route('**/api/missions/open', route => { opened = true; return route.fulfill({ json: { ...mission, opened, image: clueImage } }) })
  await page.goto(url)
  await expect(page.getByRole('button', { name: 'Open mission', exact: true })).toBeVisible()
  await expect(page.getByAltText(clueImage.alt)).toHaveCount(0)
  expect(downloads).toBe(0)
  await page.getByRole('button', { name: 'Open mission', exact: true }).click()
  const image = page.getByAltText(clueImage.alt)
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(40)
  expect(downloads).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('a failed image can be retried without opening or submitting the mission again', async ({ page }) => {
  let downloads = 0
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: { ...mission, opened: true, image: clueImage } }))
  await page.route(`**/api/missions/${token}/image?*`, route => ++downloads === 1 ? route.fulfill({ status: 503, json: { error: { message: 'Image temporarily unavailable.' } } }) : route.fulfill({ contentType: 'image/png', body: cluePng }))
  await page.goto(url)
  await expect(page.getByRole('alert')).toContainText('The clue image could not be loaded.')
  await page.getByRole('button', { name: 'Retry clue image' }).click()
  await expect.poll(() => page.getByAltText(clueImage.alt).evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(40)
  expect(downloads).toBe(2)
})

test('independent punctuation codes share one clue and stop after three claims', async ({ page }) => {
  let claims = 0
  const codes = ['!ab3@x', 'X,y;Z!', 'T3$xx?']
  await page.route(`**/api/missions/${token}`, route => route.fulfill({ json: {
    ...mission, opened: true, hint: 'Find the next location.', code_mode: 'independent_pool',
    answer_format: 'six_printable_ascii', successful_claims: claims, max_code_claims: 3,
  } }))
  await page.route('**/api/rounds/1/state', route => route.fulfill({ json: {
    code_mode: 'independent_pool', score: claims, max_score: 3,
    completions: codes.slice(0, claims).map((_, index) => ({ mission_id: 'TEST-M1', claim_id: index + 1, keyword: `WORD${index}`, voided: false })),
  } }))
  await page.route(`**/api/missions/${token}/submit`, async route => {
    expect(route.request().postDataJSON()).toEqual({ answer: codes[claims] })
    claims++
    await route.fulfill({ json: { ...decision, keyword: `WORD${claims - 1}`, claim_id: claims } })
  })
  await page.goto(url)
  for (let index = 0; index < 3; index++) {
    await page.getByLabel('Six-character answer code').fill(codes[index])
    await page.getByRole('button', { name: 'Claim code', exact: true }).click()
    await expect(page.getByText(`Code claim ${index + 1}: WORD${index}`, { exact: true })).toBeVisible()
  }
  await expect(page.getByRole('button', { name: 'Claim code', exact: true })).toHaveCount(0)
  await expect(page.getByText('Your team has claimed all three codes.', { exact: true })).toBeVisible()
  await expect(page.getByText('Current score: 3 / 3')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

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
