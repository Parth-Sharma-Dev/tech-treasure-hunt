import { expect,test } from '@playwright/test'

const tasks = [{ id:1,public_id:'OUTPUT',category:'OUTPUT',prompt:'Synthetic output question.',starter_code:'',languages:['TEXT'],points:'15',version:'v1' },{ id:2,public_id:'SHORT',category:'SHORT',prompt:'Synthetic coding task.',starter_code:'',languages:['PYTHON','C'],points:'30',version:'v1' }]
const base = { round_id:3,title:'Crack the Code',team_code:'CODE-A',session_id:12,clock:{ round_id:3,state:'LIVE',play_mode:'ONLINE',remaining_ms:60000,server_time:'2026-10-08T12:00:00Z',deadline_at:null,active_elapsed_ms:0 },assigned:true,station:'LAB-1',eligible:true,tasks,responses:[] as Record<string,unknown>[],submission:null as Record<string,unknown> | null,can_save:true,language_versions:{ PYTHON:'Approved lab Python',C:'Approved lab C' } }

test.beforeEach(async ({ page })=>{
  await page.route('**/api/health',route=>route.fulfill({ json:{ status:'ok' } }))
  await page.route('**/api/auth/csrf',route=>route.fulfill({ json:{ csrf_token:'test-token' } }))
})

test('autosave acknowledges versions and final submission permanently locks saved work',async ({ page })=>{
  let data={ ...base }
  await page.route('**/api/rounds/3/coding/submission',route=>route.fulfill({ json:data }))
  await page.route('**/api/rounds/3/coding/tasks/1/response',async route=>{
    const request=route.request().postDataJSON()
    expect(request).toMatchObject({ body:'0008',language:'TEXT',expected_revision:0 })
    const response={ task_id:1,revision:1,body:request.body,language:'TEXT',source_hash:'source-hash',action_id:request.action_id }
    data={ ...data,responses:[response] }
    await route.fulfill({ json:response })
  })
  await page.route('**/api/rounds/3/coding/finalize',async route=>{
    expect(route.request().postDataJSON().expected_revisions).toEqual({ '1':1,'2':0 })
    const submission={ id:7,kind:'MANUAL',submitted_at:'2026-10-08T12:00:05Z',manifest_digest:'frozen-source-proof' }
    data={ ...data,submission,can_save:false }
    await route.fulfill({ json:submission })
  })
  await page.goto('/rounds/3/coding')
  await page.getByLabel('Response for OUTPUT',{ exact:true }).fill('0008')
  await expect(page.getByText('Saved response version 1.')).toBeVisible()
  await page.getByRole('checkbox',{ name:'I checked my saved responses and am ready to lock this work.' }).check()
  await page.getByRole('button',{ name:'Final submit and lock work' }).click()
  await expect(page.getByRole('heading',{ name:'Final submission recorded' })).toBeVisible()
  await expect(page.getByLabel('Response for OUTPUT',{ exact:true })).toBeDisabled()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
})

test('an unknown save survives reload and retries the original source and UUID',async ({ page })=>{
  let request:Record<string,unknown> | undefined
  let failed=false
  await page.route('**/api/rounds/3/coding/submission',route=>route.fulfill({ json:base }))
  await page.route('**/api/rounds/3/coding/tasks/1/response',async route=>{
    const body=route.request().postDataJSON()
    if (!failed) { request=body; failed=true; await route.abort('failed'); return }
    expect(body).toEqual(request)
    await route.fulfill({ json:{ task_id:1,revision:1,language:'TEXT',source_hash:'saved-hash',action_id:body.action_id } })
  })
  await page.goto('/rounds/3/coding')
  await page.getByLabel('Response for OUTPUT',{ exact:true }).fill('recover exact response')
  await expect(page.getByRole('button',{ name:'Retry same save' })).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Response for OUTPUT',{ exact:true })).toHaveValue('recover exact response')
  await page.getByRole('button',{ name:'Retry same save' }).click()
  await expect(page.getByText('Saved response version 1.')).toBeVisible()
})

test('an unassigned browser gets no tasks or save controls',async ({ page })=>{
  await page.route('**/api/rounds/3/coding/submission',route=>route.fulfill({ json:{ ...base,assigned:false,station:null,tasks:[],can_save:false } }))
  await page.goto('/rounds/3/coding')
  await expect(page.getByText('Ask the supervisor to assign this browser before the task set opens.')).toBeVisible()
  await expect(page.getByRole('button',{ name:'Save response' })).toHaveCount(0)
})

test('cutoff finalizes only server-saved responses without waiting for local edits',async ({ page })=>{
  let submitted=false
  await page.route('**/api/rounds/3/coding/submission',route=>route.fulfill({ json:{ ...base,clock:{ ...base.clock,state:'ENDED' },can_save:false,submission:submitted ? { id:9,kind:'CUTOFF',submitted_at:'2026-10-08T12:01:00Z',manifest_digest:'cutoff-proof' } : null } }))
  await page.route('**/api/rounds/3/coding/finalize',async route=>{
    submitted=true
    await route.fulfill({ json:{ id:9,kind:'CUTOFF',submitted_at:'2026-10-08T12:01:00Z',manifest_digest:'cutoff-proof' } })
  })
  await page.goto('/rounds/3/coding')
  await expect(page.getByText(/last saved responses were finalized at cutoff/)).toBeVisible()
})

test('controller assigns the selected supervised browser with a station version',async ({ page })=>{
  await page.route('**/api/staff/coding/rounds',route=>route.fulfill({ json:{ rounds:[{ id:3,title:'Coding',attempt_no:1,state:'READY' }] } }))
  await page.route('**/api/staff/rounds/3/coding',route=>route.fulfill({ json:{ round_id:3,state:'READY',actor_id:1,can_assign:true,can_judge:true,can_review:false,sessions:[{ id:12,team__code:'CODE-A' }],stations:[],submissions:[],proposals:[] } }))
  await page.route('**/api/staff/rounds/3/coding/workstation',async route=>{
    expect(route.request().postDataJSON()).toMatchObject({ session_id:12,label:'LAB-1',expected_version:0,evidence_refs:['station-sheet'] })
    await route.fulfill({ json:{ station_id:1 } })
  })
  await page.goto('/staff/coding')
  await page.getByLabel('Team browser session').selectOption('12')
  await page.getByLabel('Workstation label').fill('LAB-1')
  await page.getByLabel('Assignment reason').fill('Checked the lab machine')
  await page.getByLabel('Supervisor station evidence').fill('station-sheet')
  await page.getByRole('button',{ name:'Assign workstation' }).click()
  await expect(page.getByText('Coding action confirmed.')).toBeVisible()
})

test('lab judging binds pass IDs, source hashes and supervisor evidence to the final bundle',async ({ page })=>{
  await page.route('**/api/staff/coding/rounds',route=>route.fulfill({ json:{ rounds:[{ id:3,title:'Coding',attempt_no:1,state:'ENDED' }] } }))
  await page.route('**/api/staff/rounds/3/coding',route=>route.fulfill({ json:{ round_id:3,state:'ENDED',actor_id:1,can_assign:true,can_judge:true,can_review:false,sessions:[],stations:[],submissions:[{ id:7,team_code:'CODE-A',kind:'MANUAL',submitted_at:'2026-10-08T12:00:05Z',supervisor_id:1,score:null }],proposals:[] } }))
  await page.route('**/api/staff/rounds/3/coding/submissions/7',route=>route.fulfill({ json:{ submission:{ id:7,submitted_at:'2026-10-08T12:00:05Z' },supervisor_id:1,team_code:'CODE-A',tasks:tasks.map(task=>({ ...task,private_rubric:task.category==='SHORT' ? { test_cases:[{ id:'a',input:'private input',expected:'private output' },{ id:'b',input:'hidden input',expected:'hidden output' }] } : { expected:'8' } })),responses:tasks.map(task=>({ task_id:task.id,body:task.id===1 ? '8' : 'print(8)',source_hash:`hash-${task.id}`,language:task.languages[0] })) } }))
  await page.route('**/api/staff/rounds/3/coding/judgment',async route=>{
    expect(route.request().postDataJSON()).toMatchObject({ action:'propose',submission_id:7,supervisor_id:1,supervisor_time:'2026-10-08T12:00:05Z',time_evidence:['supervisor-log'],grades:[{ task_id:1,task_version:'v1',source_hash:'hash-1',correct:true },{ task_id:2,task_version:'v1',source_hash:'hash-2',passed_tests:['a'] }] })
    await route.fulfill({ json:{ judgment_proposal_id:4 } })
  })
  await page.goto('/staff/coding')
  await page.getByText('CODE-A · manual · awaiting judgment marks').click()
  await page.getByRole('checkbox',{ name:'Fully correct: OUTPUT' }).check()
  await page.getByRole('checkbox',{ name:'Passed hidden test a for SHORT' }).check()
  await page.getByLabel('Private judging reason').fill('Compared the fixed lab tests')
  await page.getByLabel('Lab execution evidence references').fill('lab-output-log')
  await page.getByLabel('Supervisor final-time evidence').fill('supervisor-log')
  await page.getByRole('button',{ name:'Propose lab judgment' }).click()
  await expect(page.getByText('Coding action confirmed.')).toBeVisible()
})

test('independent lab review requires an explicit evidence confirmation',async ({ page })=>{
  await page.route('**/api/staff/coding/rounds',route=>route.fulfill({ json:{ rounds:[{ id:3,title:'Coding',attempt_no:1,state:'ENDED' }] } }))
  await page.route('**/api/staff/rounds/3/coding',route=>route.fulfill({ json:{ round_id:3,state:'ENDED',actor_id:2,can_assign:false,can_judge:false,can_review:true,sessions:[],stations:[],submissions:[],proposals:[{ id:4,team_code:'CODE-A',maker_id:1,reason:'Lab execution record',payload:{ score:'30.000' },reviewed:false }] } }))
  await page.route('**/api/staff/rounds/3/coding/judgment',async route=>{
    expect(route.request().postDataJSON()).toMatchObject({ action:'approve',proposal_id:4,evidence_confirmed:true })
    await route.fulfill({ json:{ judgment_id:1 } })
  })
  await page.goto('/staff/coding')
  await page.getByText('Judgment 4 · CODE-A · awaiting review').click()
  await expect(page.getByRole('button',{ name:'Approve lab judgment 4' })).toBeDisabled()
  await page.getByLabel('Lab review reason').fill('Independently checked the frozen bundle')
  await page.getByRole('checkbox',{ name:'I independently checked source versions, lab tests, marks and supervisor time.' }).check()
  await page.getByRole('button',{ name:'Approve lab judgment 4' }).click()
  await expect(page.getByText('Coding action confirmed.')).toBeVisible()
})
