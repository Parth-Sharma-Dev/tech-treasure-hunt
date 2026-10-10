import { expect, test } from '@playwright/test'
import { portalRound } from './portal-fixtures'

const headers = ['team_code','correct_question_ids','official_finish_active_ms','source_reference']
const desk = { actor_id: 1, can_prepare: true, can_review: true, round: { id: 2, number: 2, title: 'Synthetic quiz', state: 'ENDED', headers, schema: { version: 'round2-v1', question_ids: ['Q01','Q02'] } }, batches: [] as unknown[], void_proposals: [] }
const roster = { actor_id: 1, can_prepare: true, can_review: true, headers: ['code','name','leader_name','member_count','roster_reference','status'], teams: [], proposals: [] }

test('Round 4 takes only recipient names and requires complete-list confirmation', async ({ page }) => {
  await page.route('**/api/staff/results', route => route.fulfill({ json: { rounds: [{ id: 2, number: 4, title: 'Green Cards', attempt_no: 1 }] } }))
  await page.route('**/api/staff/rounds/2/imports', route => route.fulfill({ json: { ...desk, round: { ...desk.round, number: 4, headers: ['team_name'], schema: { version: 'round4-green-card-v2' } } } }))
  let body: unknown
  await page.route('**/api/staff/rounds/2/imports/validate', async route => { body = route.request().postDataJSON(); await route.fulfill({ json: { batch_id: 1, preview: [], errors: [] } }) })
  await page.goto('/staff/scores')
  await page.getByLabel('Private intake or correction reason').fill('Reviewed professor card list')
  await page.getByLabel('Green Card recipient team names (one per line)').fill('Alpha\nTEAM-B')
  await expect(page.getByRole('button', { name: 'Dry-run Green Cards' })).toBeDisabled()
  await expect(page.getByLabel('CSV source')).toHaveCount(0)
  await page.getByRole('checkbox', { name: 'This is the complete Green Card list; all unlisted teams did not receive a card.' }).check()
  await page.getByRole('button', { name: 'Dry-run Green Cards' }).click()
  await expect.poll(() => body).toMatchObject({ schema_version: 'round4-green-card-v2', complete_list_confirmed: true, rows: [{ team_name: 'Alpha' }, { team_name: 'TEAM-B' }] })
})

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic' } }))
  await page.route('**/api/staff/results', route => route.fulfill({ json: { rounds: [{ id: 2, number: 2, title: 'Synthetic quiz', attempt_no: 1 }] } }))
  await page.route('**/api/staff/rounds/2/imports', route => route.fulfill({ json: desk }))
  await page.route('**/api/staff/roster', route => route.fulfill({ json: roster }))
})

test('CSV intake only dry-runs and records the frozen schema', async ({ page }) => {
  let body: Record<string,unknown> | undefined
  await page.route('**/api/staff/rounds/2/imports/validate', async route => { body = route.request().postDataJSON(); await route.fulfill({ json: { batch_id: 1, errors: [], preview: [] } }) })
  await page.goto('/staff/scores')
  await page.getByLabel('Private intake or correction reason').fill('Synthetic sheet checking')
  await page.getByLabel('CSV source').fill(headers.join(',') + '\nTEAM-A,Q01,1000,sheet-1')
  await page.getByRole('button', { name: 'Dry-run CSV' }).click()
  await expect.poll(() => body).toMatchObject({ schema_version: 'round2-v1', reason: 'Synthetic sheet checking' })
  await expect(page.getByRole('button', { name: 'Retry saved action' })).toHaveCount(0)
})

test('manual source rows use the same reviewed intake endpoint', async ({ page }) => {
  let body: Record<string,unknown> | undefined
  await page.route('**/api/staff/rounds/2/imports/validate', async route => { body = route.request().postDataJSON(); await route.fulfill({ json: { batch_id: 1 } }) })
  await page.goto('/staff/scores')
  await page.getByText('Enter source rows manually', { exact: true }).click()
  await page.getByLabel('Private intake or correction reason').fill('Original sheet marks')
  await page.getByLabel('team code', { exact: true }).fill('TEAM-A')
  await page.getByLabel('correct question ids', { exact: true }).fill('Q01|Q02')
  await page.getByLabel('official finish active ms', { exact: true }).fill('1000')
  await page.getByLabel('source reference', { exact: true }).fill('sheet-1')
  await page.getByRole('button', { name: 'Dry-run manual rows' }).click()
  await expect.poll(() => body).toMatchObject({ rows: [{ team_code: 'TEAM-A', correct_question_ids: 'Q01|Q02' }] })
})

test('invalid batches cannot be committed and their maker cannot self-review', async ({ page }) => {
  await page.route('**/api/staff/rounds/2/imports', route => route.fulfill({ json: { ...desk, batches: [{ id: 1, maker_id: 2, reason: 'Invalid sheet', source_rows: [], preview: [], dry_run_errors: [{ row: 1, message: 'Missing original marks' }], committed_at: null, rejected: false }, { id: 2, maker_id: 1, reason: 'Own batch', source_rows: [], preview: [], dry_run_errors: [], committed_at: null, rejected: false }] } }))
  await page.goto('/staff/scores')
  await page.getByText('Batch 1 · invalid', { exact: true }).click()
  await page.getByText('Batch 2 · awaiting review', { exact: true }).click()
  await page.getByLabel('I checked every original score sheet, team, mark and tie metric.').check()
  await expect(page.getByRole('button', { name: 'Commit reviewed batch 1' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Commit reviewed batch 2' })).toHaveCount(0)
  await expect(page.getByText('A different organizer must review this batch.')).toBeVisible()
})

test('lost intake response survives reload with the same action UUID', async ({ page }) => {
  let original: unknown
  let attempts = 0
  await page.route('**/api/staff/rounds/2/imports/validate', async route => { const body = route.request().postDataJSON(); if (attempts++ === 0) { original = body; await route.abort() } else { expect(body).toEqual(original); await route.fulfill({ json: { batch_id: 1 } }) } })
  await page.goto('/staff/scores')
  await page.getByLabel('Private intake or correction reason').fill('Lost-response rehearsal')
  await page.getByLabel('CSV source').fill(headers.join(',') + '\nTEAM-A,Q01,1000,sheet-1')
  await page.getByRole('button', { name: 'Dry-run CSV' }).click()
  await expect(page.getByRole('button', { name: 'Retry saved action' })).toBeEnabled()
  await page.reload()
  await page.getByRole('button', { name: 'Retry saved action' }).click()
  await expect.poll(() => attempts).toBe(2)
})

test('roster creation produces an independent review proposal', async ({ page }) => {
  let body: Record<string,unknown> | undefined
  await page.route('**/api/staff/roster/change', async route => { body = route.request().postDataJSON(); await route.fulfill({ json: { proposal_id: 1 } }) })
  await page.goto('/staff/roster')
  await page.getByLabel('Private source or status reason').fill('Verified application')
  await page.getByLabel('Team code', { exact: true }).fill('REAL-01')
  await page.getByLabel('Team name', { exact: true }).fill('Synthetic team')
  await page.getByLabel('Leader name', { exact: true }).fill('Synthetic leader')
  await page.getByLabel('Roster evidence reference').fill('application-1')
  await page.getByRole('button', { name: 'Propose team change' }).click()
  await expect.poll(() => body).toMatchObject({ operation: 'propose', is_demo: false, rows: [{ code: 'REAL-01', status: 'ACTIVE', member_count: 3 }] })
})

test('Round 4 shows approved faculty and the own panel assignment', async ({ page }) => {
  const round = portalRound({ id: 4, number: 4, title: 'Synthetic interview', state: 'LIVE', eligible: true, clock: { state: 'LIVE', play_mode: 'ONLINE', remaining_ms: 60000, active_elapsed_ms: 0, server_time: '2026-10-13T07:45:00Z', deadline_at: '2026-10-13T07:46:00Z' } })
  await page.route('**/api/me', route => route.fulfill({ json: { team: { code: 'TEAM-A', name: 'Alpha', status: 'ACTIVE', member_count: 3 }, session: { active_count: 1, max_active: 4 }, rounds: [round] } }))
  await page.route('**/api/rounds/4/overview', route => route.fulfill({ json: { ...round, faculty: [{ id: 1, display_name: 'Approved Faculty', role: 'Interview panel', location: 'Interview desk', contact_channel: 'Speak at the desk', photo_url: '' }], interview_assignment: { panel: 'Panel A', faculty_ids: [1], start: '2026-10-13T07:45:00Z', end: '2026-10-13T07:55:00Z' } } }))
  await page.goto('/rounds/4')
  await expect(page.getByRole('heading', { name: 'Approved Faculty', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Your interview · Panel A' })).toBeVisible()
  await expect(page.getByText('Assigned faculty: Approved Faculty')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('faculty final results award Green Cards and link to Round 5 information', async ({ page }) => {
  const snapshot = { id: 1, revision: 1, status: 'FINAL', cut_count: 5, qualifier_codes: ['TEAM-A'], published_at: '2026-10-13T09:00:00Z', appeal_deadline: null, supersedes: null, metadata: { ranking_kind: 'FACULTY', publication_reason: 'Reviewed interview', tie_reason: '', open_material_incidents: 0 }, entries: [{ team_code: 'TEAM-A', team_name: 'Alpha', team_status: 'ACTIVE', eligible: true, score: 69, max_score: 100, tie_time_ms: null, criterion_averages: { technical: '8.000', problem_solving: '7.000', communication: '6.000', coordination: '5.000' }, rank: 1 }] }
  await page.route('**/api/rounds/4/results', route => route.fulfill({ json: { title: 'Interview', attempt_no: 1, own_team_code: 'TEAM-A', current_attempt: true, qualification_active: true, snapshot, history: [snapshot] } }))
  await page.goto('/rounds/4/results')
  await expect(page.getByText('Your team received a Green Card and qualified for Round 5. Open Round 5 from your dashboard.')).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'technical average' })).toBeVisible()
  await expect(page.getByRole('link', { name: /round 5/i })).toHaveAttribute('href', '/lobby')
})
