import { expect, test } from '@playwright/test'

const entries = [{ team_code: 'TEAM-A', team_name: 'Alpha', team_status: 'ACTIVE', eligible: true, score: 1, max_score: 2, tie_time_ms: 10_000, rank: 1 }, { team_code: 'TEAM-B', team_name: 'Beta', team_status: 'ACTIVE', eligible: true, score: 0, max_score: 2, tie_time_ms: null, rank: 2 }]
const preview = { round_id: 1, number: 1, attempt_no: 1, title: 'Synthetic hunt', state: 'ENDED', control_version: 4, evidence_digest: 'test-digest', entries, cut_count: 1, cutoff_tie: [], max_score: 2, evidence_gaps: [], configuration_errors: [], finalization_blockers: ['Publish provisional results before finalization.'], appeal_deadline: null, actor_id: 1, can_propose: true, can_approve: false, can_close_incident: false, proposals: [], incidents: [], history: [] }
const snapshot = { id: 1, revision: 1, status: 'PROVISIONAL', entries, qualifier_codes: [] as string[], cut_count: 1, published_at: '2026-10-06T12:00:00Z', appeal_deadline: '2026-10-06T12:10:00Z', supersedes: null as number | null, metadata: { publication_reason: 'Round reviewed', tie_reason: '', open_material_incidents: 0 } }

test('correction proposal submits the mission and private evidence for independent review', async ({ page }) => {
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, can_correct: true, missions: [{ id: 3, public_id: 'CLUE-3', is_void: false }], corrections: [] } }))
  await page.route('**/api/staff/rounds/1/resolutions', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'propose', correction_type: 'ALTERNATE', mission_id: 3, answer: '0042', expected_version: 4, evidence_refs: ['clue-sheet-3'] })
    await route.fulfill({ json: { correction_proposal_id: 1 } })
  })
  await page.goto('/staff/results')
  await page.getByLabel('Alternate four-digit answer').fill('0042')
  await page.getByLabel('Private correction reason').fill('Reviewed alternate interpretation')
  await page.getByLabel('Public correction summary').fill('Clue three accepts an alternate answer')
  await page.getByLabel('Private correction evidence (one reference per line)').fill('clue-sheet-3')
  await page.getByRole('button', { name: 'Propose score correction' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Results action confirmed' })).toBeVisible()
})

test('stale correction can be rejected but cannot be applied', async ({ page }) => {
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, actor_id: 2, can_close_incident: true, corrections: [{ id: 7, mission_id: 3, correction_type: 'VOID', maker_id: 1, reason: 'Synthetic void', stale: true, resolution_id: null, payload: { public_summary: 'Clue withdrawn', evidence_refs: ['sheet-3'] } }] } }))
  await page.route('**/api/staff/rounds/1/resolutions', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'approve', proposal_id: 7, reject: true, evidence_confirmed: true })
    await route.fulfill({ json: { resolution_id: 1, rejected: true } })
  })
  await page.goto('/staff/results')
  await page.getByText('Correction 7 · void · stale').click()
  await page.getByLabel('Correction review reason').fill('Evidence has changed; remake proposal')
  await page.getByRole('checkbox', { name: 'I independently reviewed the correction and supporting evidence.' }).check()
  await expect(page.getByRole('button', { name: 'Approve correction 7' })).toBeDisabled()
  await page.getByRole('button', { name: 'Reject correction 7' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Results action confirmed' })).toBeVisible()
})

test('paper activation records desks and isolation evidence before independent approval', async ({ page }) => {
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, state: 'FROZEN', play_mode: 'ONLINE', paper_window: null, paper_proposals: [], paper_slips: [] } }))
  await page.route('**/api/staff/rounds/1/paper', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'propose', kind: 'ACTIVATE', assigned_desks: { 'TEAM-A': 'North desk', 'TEAM-B': 'South desk' }, clock_evidence: ['clock-log'], writer_isolation_evidence: ['isolation-log'] })
    await route.fulfill({ json: { paper_proposal_id: 1 } })
  })
  await page.goto('/staff/results')
  await page.getByLabel('Paper desk for TEAM-A').fill('North desk')
  await page.getByLabel('Paper desk for TEAM-B').fill('South desk')
  await page.getByLabel('Official clock evidence').fill('clock-log')
  await page.getByLabel('Online writer isolation evidence').fill('isolation-log')
  await page.getByLabel('Paper activation reason').fill('Outage rehearsal')
  await page.getByLabel('Paper activation references').fill('incident-log')
  await page.getByRole('button', { name: 'Propose paper activation' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Results action confirmed' })).toBeVisible()
})

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }))
  await page.route('**/api/auth/csrf', route => route.fulfill({ json: { csrf_token: 'test-token' } }))
  await page.route('**/api/staff/results', route => route.fulfill({ json: { rounds: [{ id: 1, number: 1, attempt_no: 1, title: 'Synthetic hunt', state: 'ENDED', is_demo: true }] } }))
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: preview }))
})

test('controller proposes the reviewed evidence without publishing it', async ({ page }) => {
  await page.route('**/api/staff/rounds/1/publish', async route => {
    const data = route.request().postDataJSON()
    expect(data.action).toBe('propose'); expect(data.status).toBe('PROVISIONAL')
    expect(data.evidence_digest).toBe('test-digest'); expect(data.expected_version).toBe(4)
    expect(data.action_id).toMatch(/^[a-f0-9-]{36}$/)
    await route.fulfill({ json: { proposal_id: 1, status: 'PROVISIONAL' } })
  })
  await page.goto('/staff/results')
  await page.getByLabel('Public publication summary', { exact: true }).fill('Reviewed the synthetic standings')
  await page.getByRole('button', { name: 'Submit result proposal' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Results action confirmed' })).toBeVisible()
  await expect(page.getByText('No publication proposals yet.')).toBeVisible()
})

test('independent reviewer publishes a proposal and sees its preserved standings', async ({ page }) => {
  const proposal = { id: 1, status: 'PROVISIONAL', maker_id: 1, maker_name: 'content-controller', reason: 'Reviewed', stale: false, publication_id: null as number | null, payload: { qualifiers: [], preview: { entries, cut_count: 1 }, tie_order: [], tie_evidence: [], tie_reason: '' } }
  let published = false
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, actor_id: 2, can_propose: false, can_approve: true, proposals: [{ ...proposal, publication_id: published ? 1 : null }] } }))
  await page.route('**/api/staff/rounds/1/publish', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'approve', proposal_id: 1, evidence_confirmed: true })
    published = true
    await route.fulfill({ json: { snapshot_id: 1, revision: 1, status: 'PROVISIONAL' } })
  })
  await page.goto('/staff/results')
  await page.getByText('Review the proposed standings and evidence').click()
  await page.getByLabel('Public review summary', { exact: true }).fill('Independent evidence checked')
  await page.getByRole('checkbox', { name: 'I independently checked the standings, roster, cut and supporting evidence.' }).check()
  await page.getByRole('button', { name: 'Approve and publish proposal 1' }).click()
  await expect(page.getByText('Published.', { exact: true })).toBeVisible()
})

test('participant sees provisional appeal timing then final qualification and history', async ({ page }) => {
  let final = false
  const finalized = { ...snapshot, id: 2, revision: 2, status: 'FINAL', qualifier_codes: ['TEAM-A'], supersedes: 1 }
  await page.route('**/api/rounds/1/results', route => route.fulfill({ json: { title: 'Synthetic hunt', attempt_no: 1, own_team_code: 'TEAM-A', snapshot: final ? finalized : snapshot, history: final ? [finalized, snapshot] : [snapshot] } }))
  await page.goto('/rounds/1/results')
  await expect(page.getByText('Qualification remains pending until final review.')).toBeVisible()
  await expect(page.getByText(/Appeal deadline:/)).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Provisional results · revision 1' })).toBeVisible()
  final = true
  await page.reload()
  await expect(page.getByText('Your team qualified for the next round.', { exact: true })).toBeVisible()
  await expect(page.getByText('Publication history (2 revisions)')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('unpublished results do not show private standings', async ({ page }) => {
  await page.route('**/api/rounds/1/results', route => route.fulfill({ json: { title: 'Synthetic hunt', attempt_no: 1, own_team_code: 'TEAM-A', snapshot: null, history: [] } }))
  await page.goto('/rounds/1/results')
  await expect(page.getByRole('heading', { name: 'Results are not published yet' })).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
})

test('old final results describe historical qualification after a rerun', async ({ page }) => {
  await page.route('**/api/rounds/1/results', route => route.fulfill({ json: { title: 'Synthetic hunt', attempt_no: 1, current_attempt: false, own_team_code: 'TEAM-A', snapshot: { ...snapshot, status: 'FINAL', qualifier_codes: ['TEAM-A'] }, history: [snapshot] } }))
  await page.goto('/rounds/1/results')
  await expect(page.getByText('Historical results from an earlier attempt.', { exact: false })).toBeVisible()
  await expect(page.getByText('Your team qualified for the next round.', { exact: true })).toHaveCount(0)
})

test('unknown publication outcome retries its saved payload after reload', async ({ page }) => {
  let calls = 0
  let original: unknown
  await page.route('**/api/staff/rounds/1/publish', async route => {
    calls++
    if (calls === 1) { original = route.request().postDataJSON(); await route.abort('connectionreset') }
    else { expect(route.request().postDataJSON()).toEqual(original); await route.fulfill({ json: { proposal_id: 1 } }) }
  })
  await page.goto('/staff/results')
  await page.getByLabel('Public publication summary', { exact: true }).fill('Review with uncertain response')
  await page.getByRole('button', { name: 'Submit result proposal' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Retry same results action' }).click()
  await expect(page.getByText('Results action confirmed. The desk has been refreshed.')).toBeVisible()
  expect(calls).toBe(2)
})

test('final cutoff tie proposal includes explicit reserve-clue evidence', async ({ page }) => {
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, state: 'PROVISIONAL', cutoff_tie: ['TEAM-A', 'TEAM-B'], finalization_blockers: ['A qualification cutoff tie requires reviewed reserve-clue evidence.'] } }))
  await page.route('**/api/staff/rounds/1/publish', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ status: 'FINAL', evidence_confirmed: true, tie_order: ['TEAM-B', 'TEAM-A'], tie_evidence: ['reserve-sheet-1'] })
    await route.fulfill({ json: { proposal_id: 2, status: 'FINAL' } })
  })
  await page.goto('/staff/results')
  await page.getByLabel('Publication type').selectOption('FINAL')
  await page.getByLabel('Public publication summary', { exact: true }).fill('Finalize after reserve clue')
  await page.getByRole('checkbox', { name: 'I checked the roster, cut count, exclusions and evidence coverage.' }).check()
  await page.getByLabel('Reserve-clue order (all tied team codes, comma separated)').fill('TEAM-B, TEAM-A')
  await page.getByLabel('Private reserve-clue evidence references (one per line)').fill('reserve-sheet-1')
  await page.getByLabel('Public reserve-clue summary', { exact: true }).fill('TEAM-B solved first')
  await page.getByRole('button', { name: 'Submit result proposal' }).click()
  await expect(page.getByText('Results action confirmed. The desk has been refreshed.')).toBeVisible()
})

test('independent verifier records evidence when closing an incident', async ({ page }) => {
  let closed = false
  await page.route('**/api/staff/rounds/1/results', route => route.fulfill({ json: { ...preview, actor_id: 2, can_propose: false, can_close_incident: true, incidents: [{ id: 1, category: 'APPEAL', material: true, owner_id: 1, affected_scope: { summary: 'Review appeal' }, closed_at: closed ? '2026-10-06T12:00:00Z' : null, decision: 'No scoring change required', evidence_references: [] }] } }))
  await page.route('**/api/staff/rounds/1/incidents', async route => {
    expect(route.request().postDataJSON()).toMatchObject({ action: 'close', incident_id: 1, evidence_refs: ['appeal-sheet-1'] })
    closed = true
    await route.fulfill({ json: { incident_id: 1, closed: true } })
  })
  await page.goto('/staff/results')
  await page.getByText('Incident 1 · APPEAL · open · material', { exact: true }).click()
  await page.getByLabel('Private closure decision', { exact: true }).fill('Checked appeal evidence, no score change')
  await page.getByLabel('Closure evidence references (one per line)').fill('appeal-sheet-1')
  await page.getByRole('button', { name: 'Verify and close incident 1' }).click()
  await expect(page.getByText('Incident 1 · APPEAL · closed · material', { exact: true })).toBeVisible()
})
