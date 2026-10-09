import { expect, test } from '@playwright/test'

const window = { id: 7, version: 1, stage: 1, question_id: 11, question_label: 'S1Q1', accepting: false, opened_at: '2026-10-09T07:00:00Z', closed_at: '2026-10-09T07:00:01Z' }
const press = { id: '612adbb4-3fcb-4269-a4ab-8e15c741424c', window_id: 7, received_at: '2026-10-09T07:00:00.123456Z', admitted_at: '2026-10-09T07:00:00.124456Z', team_code: 'TEAM-A', team_name: 'Alpha', team_status: 'ACTIVE', position: 1 }
const desk = { actor_id: 1, round_id: 5, title: 'Final', state: 'LIVE', control_version: 3, can_control: true, can_record_answers: true, answers: [] as unknown[], window, entries: [press], first_team_codes: ['TEAM-A'], timestamp_tie: false, order_final: true, questions: [{ id: 11, stage: 1, public_id: 'S1Q1', version: 'v1' }], history: [] }

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'synthetic' } }))
})

test('host records offline verdict without supplying a completion timestamp', async ({ page }) => {
  let recorded = false
  await page.route('**/api/staff/buzzer/rounds', route => route.fulfill({ json: { rounds: [{ id: 5, title: 'Final', attempt_no: 1, is_demo: true }] } }))
  await page.route('**/api/staff/rounds/5/buzzer', route => route.fulfill({ json: { ...desk, answers: recorded ? [{ id: 4, team__code: 'TEAM-A', verdict: 'CORRECT', answer: 'biometric authentication', completed_at: '2026-10-09T07:00:03.000123Z', priority_evidence: { order: ['TEAM-A'], adjudication_reference: '' } }] : [] } }))
  await page.route('**/api/staff/rounds/5/buzzer/answer', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ window_id: 7, press_id: press.id, verdict: 'CORRECT', answer: 'biometric authentication', source_reference: 'host-sheet', reason: 'Observed offline reply' })
    expect(route.request().postDataJSON()).not.toHaveProperty('completed_at')
    recorded = true; await route.fulfill({ json: { answer_evidence_id: 4, completed_at: '2026-10-09T07:00:03.000123Z' } })
  })
  await page.goto('/staff/buzzer')
  await page.getByLabel('Original spoken answer').fill('biometric authentication')
  await page.getByLabel('Private host sheet reference').fill('host-sheet')
  await page.getByLabel('Host record reason').fill('Observed offline reply')
  await page.getByRole('button', { name: 'Record observed offline answer' }).click()
  await expect(page.getByText(/TEAM-A · CORRECT · host record 4/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Record observed offline answer' })).toHaveCount(0)
})

const entry = { team_code: 'TEAM-A', team_name: 'Alpha', team_status: 'ACTIVE', eligible: true, score: 250, max_score: 280, rank: 1, tie_time_ms: null, round5_score: 50, carry_over_score: 200, stage_scores: { '1': 10, '2': 10, '3': 10, '4': 10, '5': 10 }, last_correct_at: '2026-10-09T07:05:00.123456Z' }
const snapshot = { id: 1, revision: 1, status: 'FINAL', entries: [entry], qualifier_codes: [], cut_count: 1, published_at: '2026-10-09T07:20:00Z', appeal_deadline: null, supersedes: null, metadata: { ranking_kind: 'BUZZER_FINAL', winner_codes: ['TEAM-A'], winner_title: 'The Winner of Tech Treasure Hunt', publication_reason: 'Reviewed final award', tie_reason: '', open_material_incidents: 0 } }

test('final publication names one event winner and shows stage and carried totals', async ({ page }) => {
  await page.route('**/api/rounds/5/results', route => route.fulfill({ json: { title: 'Final', attempt_no: 1, current_attempt: true, award_active: true, qualification_active: false, own_team_code: 'TEAM-A', snapshot, history: [snapshot] } }))
  await page.goto('/rounds/5/results')
  await expect(page.getByRole('heading', { name: 'The Winner of Tech Treasure Hunt' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Carry-over', exact: true })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Stage 5', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Winner', exact: true })).toBeVisible()
  await expect(page.getByText(/qualified for the next round/i)).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('provisional final standings do not award a winner', async ({ page }) => {
  await page.route('**/api/rounds/5/results', route => route.fulfill({ json: { title: 'Final', attempt_no: 1, current_attempt: true, award_active: false, own_team_code: 'TEAM-A', snapshot: { ...snapshot, status: 'PROVISIONAL', appeal_deadline: '2026-10-09T07:30:00Z', metadata: { ...snapshot.metadata, winner_codes: [] } }, history: [] } }))
  await page.goto('/rounds/5/results')
  await expect(page.getByText('The event winner remains pending until final review.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'The Winner of Tech Treasure Hunt' })).toHaveCount(0)
})

test('an award under review retains public history without asserting an active winner', async ({ page }) => {
  await page.route('**/api/rounds/5/results', route => route.fulfill({ json: { title: 'Final', attempt_no: 1, current_attempt: true, award_active: false, own_team_code: 'TEAM-A', snapshot, history: [snapshot] } }))
  await page.goto('/rounds/5/results')
  await expect(page.getByText('The event award is under organizer review. Published history remains available.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'The Winner of Tech Treasure Hunt' })).toHaveCount(0)
})

test('Round 5 CSV dry run sends native source references rather than imported marks', async ({ page }) => {
  const headers = ['window_id','team_code','press_id','answer_evidence_id','verdict','answer','reveal_step','buzzer_tie_order','adjudication_reference','source_reference']
  await page.route('**/api/staff/results', route => route.fulfill({ json: { rounds: [{ id: 5, number: 5, title: 'Final', attempt_no: 1 }] } }))
  await page.route('**/api/staff/rounds/5/imports', route => route.fulfill({ json: { actor_id: 1, can_prepare: true, can_review: false, round: { id: 5, number: 5, title: 'Final', state: 'ENDED', headers, schema: { version: 'round5-v1' } }, batches: [], void_proposals: [], draft_source_rows: [], carry_over_gaps: [] } }))
  await page.route('**/api/staff/rounds/5/imports/validate', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ schema_version: 'round5-v1', reason: 'Check final source ledger' })
    await route.fulfill({ json: { batch_id: 3, errors: [], preview: [] } })
  })
  await page.goto('/staff/scores?round=5')
  await page.getByLabel('Private intake or correction reason').fill('Check final source ledger')
  await page.getByLabel('CSV source').fill(headers.join(',') + '\n7,TEAM-A,' + press.id + ',4,CORRECT,biometric authentication,0,,,sheet')
  await page.getByRole('button', { name: 'Dry-run CSV' }).click()
  await expect(page.getByText(/Completion times and points cannot be imported/)).toBeVisible()
})
