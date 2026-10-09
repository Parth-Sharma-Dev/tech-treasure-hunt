import { expect, test } from '@playwright/test'
import { portalRound } from './portal-fixtures'

const clock = { state: 'READY', play_mode: 'ONLINE', remaining_ms: 60000, server_time: '2026-10-08T06:00:00Z', deadline_at: null, active_elapsed_ms: 0 }
const rounds = [1,2,3,4,5].map(number => portalRound({ id: number, number, title: `Synthetic round ${number}`, state: 'READY', eligible: number === 1, clock }))
const info = { summary: 'Approved public overview', venue: 'Synthetic lab', scheduled_start: '2026-10-13T06:30:00Z', scheduled_end: '2026-10-13T07:15:00Z', contacts: [{ name: 'Approved organizer', role: 'Help desk', location: 'Lab entrance', channel: 'Speak at the desk' }] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/me', route => route.fulfill({ json: { team: { code: 'TEAM-A', name: 'Synthetic team', member_count: 3, status: 'ACTIVE', is_demo: true }, session: { active_count: 1, max_active: 4 }, rounds } }))
  await page.route('**/api/rounds', route => route.fulfill({ json: { rounds: rounds.map(round => ({ ...round, information: info })), announcements: [{ id: 1, title: 'Meet your supervisor', body: 'Go to the announced venue.', published_at: '2026-10-08T06:00:00Z' }] } }))
})

test('dashboard exposes all in-scope round pages, approved schedule and announcements', async ({ page }) => {
  await page.goto('/lobby')
  for (const number of [1,2,3,4,5]) await expect(page.getByRole('link', { name: `Open Round ${number}`, exact: true })).toHaveAttribute('href', `/rounds/${number}`)
  await expect(page.getByRole('heading', { name: 'Meet your supervisor' })).toBeVisible()
  await expect(page.getByText('13 Oct 2026, 12:00 pm IST', { exact: true }).first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('ineligible Round 3 shows approved contacts and a precise reason without coding controls', async ({ page }) => {
  await page.route('**/api/rounds/3/overview', route => route.fulfill({ json: { ...rounds[2], information: info, eligibility_reason: 'Your team did not qualify from Round 2.' } }))
  await page.goto('/rounds/3')
  await expect(page.getByRole('heading', { name: 'Approved organizer' })).toBeVisible()
  await expect(page.getByText('Your team did not qualify from Round 2.').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Participant instructions' })).toHaveCount(0)
  await expect(page.getByLabel('Mission fallback code')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /submit/i })).toHaveCount(0)
})

test('Round 2 retains published results after closing and shows released instructions', async ({ page }) => {
  await page.route('**/api/rounds/2/overview', route => route.fulfill({ json: { ...rounds[1], state: 'FINALIZED', eligible: true, information: { ...info, instructions: 'Keep your team together.' }, capabilities: { ...rounds[1].capabilities, instructions_visible: true, view_results: true }, earned_keywords: ['LOOP'] } }))
  await page.goto('/rounds/2')
  await expect(page.getByText('Keep your team together.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'View published results: Synthetic round 2' })).toHaveAttribute('href', '/rounds/2/results')
  await expect(page.getByRole('heading', { name: 'Your Round 1 keywords' })).toBeVisible()
  await expect(page.getByLabel('Mission fallback code')).toHaveCount(0)
})

test('Round 5 information is readable without granting finalist participation', async ({ page }) => {
  await page.route('**/api/rounds/5/overview', route => route.fulfill({ json: { ...rounds[4], information: info, eligibility_reason: 'Eligibility awaits final Round 4 results.' } }))
  await page.goto('/rounds/5')
  await expect(page.getByRole('heading', { name: 'The five final stages' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Approved organizer' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Press Round 5 buzzer' })).toHaveCount(0)
})
