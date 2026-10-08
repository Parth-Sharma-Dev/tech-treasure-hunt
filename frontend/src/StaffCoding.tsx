import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { dateLabel } from './Results'

type Task = { id:number; public_id:string; category:string; version:string; points:string; prompt:string; private_rubric:{ test_cases?:{ id:string; input:unknown; expected:unknown }[]; [key:string]:unknown } }
type Submission = { id:number; team_code:string; kind:string; submitted_at:string; supervisor_id:number | null; score:string | null }
type Proposal = { id:number; team_code:string; maker_id:number; reason:string; payload:Record<string,unknown>; reviewed:boolean }
type Desk = { round_id:number; state:string; actor_id:number; can_assign:boolean; can_judge:boolean; can_review:boolean; sessions:{ id:number; team__code:string }[]; stations:{ team__code:string; version:number; label:string }[]; submissions:Submission[]; proposals:Proposal[] }
type Bundle = { submission:{ id:number; submitted_at:string }; supervisor_id:number; team_code:string; tasks:Task[]; responses:{ task_id:number; body:string; source_hash:string; language:string }[] }
type Pending = { endpoint:'workstation' | 'judgment'; data:Record<string,unknown> }

export function StaffCoding() {
  const [selected,setSelected] = useState(new URLSearchParams(location.search).get('round') ?? '')
  const rounds = useQuery({ queryKey:['staff-coding-rounds'],queryFn:({ signal })=>getJson<{ rounds:{ id:number; title:string; attempt_no:number; state:string }[] }>('/api/staff/coding/rounds',signal),retry:false })
  const requested = Number(selected)
  const id = rounds.data?.rounds.some(round=>round.id===requested) ? requested : rounds.data?.rounds[0]?.id ?? 0
  return <section className="participant-page"><p className="eyebrow">SUPERVISED LAB</p><h1>Coding review desk</h1><p><a href="/staff/rounds">Round controls</a> · <a href="/staff/results">Results publication</a> · <a href="/admin/competition/codingtask/">Task preparation</a></p>{rounds.isPending ? <p>Loading coding rounds…</p> : rounds.isError ? <><p role="alert">{rounds.error.message}</p><a href="/admin/login/?next=/staff/coding">Staff sign in</a></> : !id ? <p>Prepare a native Round 3 coding attempt and its verified task set in Django admin.</p> : <><label>Coding attempt<select value={id} onChange={event=>setSelected(event.target.value)}>{rounds.data.rounds.map(round=><option value={round.id} key={round.id}>{round.title} · attempt {round.attempt_no} · {round.state}</option>)}</select></label><DeskView key={id} roundId={id} /></>}</section>
}

function DeskView({ roundId }: { roundId:number }) {
  const query = useQuery({ queryKey:['coding-desk',roundId],queryFn:({ signal })=>getJson<Desk>(`/api/staff/rounds/${roundId}/coding`,signal),retry:false })
  if (query.isPending) return <p>Loading supervised evidence…</p>
  if (query.isError) return <p role="alert">{query.error.message}</p>
  return <DeskBody key={query.data.actor_id} desk={query.data} refresh={()=>void query.refetch()} />
}

function DeskBody({ desk,refresh }: { desk:Desk; refresh:()=>void }) {
  const key = `tth:codingreview:${desk.actor_id}:${desk.round_id}`
  const [pending,setPending] = useState<Pending | null>(()=>{ try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as Pending | null } catch { return null } })
  const action = useMutation({ mutationFn:(request:Pending)=>postJson(`/api/staff/rounds/${desk.round_id}/coding/${request.endpoint}`,request.data),onSuccess:()=>{ sessionStorage.removeItem(key); setPending(null); refresh() },onError:error=>{ if (error instanceof ApiError && error.status<500) { sessionStorage.removeItem(key); setPending(null); refresh() } } })
  function send(endpoint:Pending['endpoint'],data:Record<string,unknown>) { const request={ endpoint,data:{ ...data,action_id:crypto.randomUUID() } }; setPending(request); sessionStorage.setItem(key,JSON.stringify(request)); action.mutate(request) }
  const disabled = !!pending || action.isPending
  const [session,setSession] = useState('')
  const [label,setLabel] = useState('')
  const [reason,setReason] = useState('')
  const [refs,setRefs] = useState('')
  return <><button className="secondary" onClick={refresh}>Refresh coding desk</button>{action.isError && <p role="alert">{action.error.message}</p>}{action.isSuccess && <p role="status">Coding action confirmed.</p>}{pending && !action.isPending && <section className="panel"><p>The original coding desk action is unconfirmed. Retry its saved request.</p><button onClick={()=>action.mutate(pending)}>Retry same coding action</button></section>}
    {desk.can_assign && ['READY','LOBBY','LIVE','FROZEN'].includes(desk.state) && <section className="panel"><h2>Assign a supervised workstation</h2><form className="form-stack" onSubmit={event=>{ event.preventDefault(); const chosen=desk.sessions.find(item=>item.id===Number(session)); const old=desk.stations.find(item=>item.team__code===chosen?.team__code); send('workstation',{ session_id:Number(session),label,expected_version:old?.version ?? 0,reason,evidence_refs:refs.split('\n').map(item=>item.trim()).filter(Boolean) }) }}><fieldset disabled={disabled}><label>Team browser session<select required value={session} onChange={event=>setSession(event.target.value)}><option value="">Choose the browser reference</option>{desk.sessions.map(item=><option key={item.id} value={item.id}>{item.team__code} · browser {item.id}</option>)}</select></label><label>Workstation label<input required maxLength={100} value={label} onChange={event=>setLabel(event.target.value)} /></label><label>Assignment reason<textarea required maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} /></label><label>Supervisor station evidence<textarea required value={refs} onChange={event=>setRefs(event.target.value)} /></label><button>Assign workstation</button></fieldset></form></section>}
    <section className="panel"><h2>Frozen submissions and lab judgments</h2>{desk.submissions.length ? desk.submissions.map(item=><SubmissionPanel key={item.id} item={item} desk={desk} disabled={disabled} send={data=>send('judgment',data)} />) : <p>No final bundles recorded yet.</p>}</section>
    <section className="panel"><h2>Independent lab review</h2>{desk.proposals.map(item=><details key={item.id}><summary>Judgment {item.id} · {item.team_code} · {item.reviewed ? 'reviewed' : 'awaiting review'}</summary><p>{item.reason}</p><pre className="paper-evidence">{JSON.stringify(item.payload,null,2)}</pre>{!item.reviewed && desk.can_review && item.maker_id!==desk.actor_id && <ReviewJudgment item={item} disabled={disabled} send={data=>send('judgment',data)} />}{!item.reviewed && item.maker_id===desk.actor_id && <p>A different verifier must review these marks.</p>}</details>)}</section>
  </>
}

function SubmissionPanel({ item,desk,disabled,send }: { item:Submission; desk:Desk; disabled:boolean; send:(data:Record<string,unknown>)=>void }) {
  const [opened,setOpened]=useState(false)
  return <details onToggle={event=>{ if (event.currentTarget.open) setOpened(true) }}><summary>{item.team_code} · {item.kind.toLowerCase()} · {item.score ?? (item.kind==='NO_SUBMISSION' ? '0' : 'awaiting judgment')} marks</summary><p>Final time: {dateLabel(item.submitted_at)}</p>{item.kind!=='NO_SUBMISSION' && <><a href={`/api/staff/rounds/${desk.round_id}/coding/submissions/${item.id}`} download={`coding-${item.team_code}-bundle.json`}>Download frozen source and private lab rubric</a>{opened && <JudgeBundle roundId={desk.round_id} item={item} disabled={disabled} canJudge={desk.can_judge && ['ENDED','PROVISIONAL'].includes(desk.state)} send={send} />}</>}</details>
}

function JudgeBundle({ roundId,item,disabled,canJudge,send }: { roundId:number; item:Submission; disabled:boolean; canJudge:boolean; send:(data:Record<string,unknown>)=>void }) {
  const query = useQuery({ queryKey:['coding-bundle',roundId,item.id],queryFn:({ signal })=>getJson<Bundle>(`/api/staff/rounds/${roundId}/coding/submissions/${item.id}`,signal),retry:false })
  const [grades,setGrades] = useState<Record<number,{ correct?:boolean; passed_tests?:string[] }>>({})
  const [reason,setReason] = useState('')
  const [refs,setRefs] = useState('')
  const [timeRefs,setTimeRefs] = useState('')
  if (query.isPending) return <p>Loading frozen source…</p>
  if (query.isError) return <p role="alert">{query.error.message}</p>
  const bundle=query.data
  return <><p>Evaluate these exact saved versions in the approved lab tools. Keep test output and supervisor evidence.</p><form className="form-stack" onSubmit={event=>{ event.preventDefault(); send({ action:'propose',submission_id:item.id,reason,supervisor_id:bundle.supervisor_id,supervisor_time:bundle.submission.submitted_at,evidence_refs:refs.split('\n').map(value=>value.trim()).filter(Boolean),time_evidence:timeRefs.split('\n').map(value=>value.trim()).filter(Boolean),grades:bundle.tasks.map(task=>({ task_id:task.id,task_version:task.version,source_hash:bundle.responses.find(response=>response.task_id===task.id)?.source_hash ?? '',...(task.category==='SHORT' ? { passed_tests:grades[task.id]?.passed_tests ?? [] } : { correct:grades[task.id]?.correct ?? false }) })) }) }}><fieldset disabled={disabled || !canJudge}>{bundle.tasks.map(task=><section key={task.id}><h3>{task.public_id} · {task.points} marks</h3><pre className="coding-source">{bundle.responses.find(response=>response.task_id===task.id)?.body ?? 'No saved response'}</pre><details><summary>Private fixed rubric · {task.version}</summary><pre className="paper-evidence">{JSON.stringify(task.private_rubric,null,2)}</pre></details>{task.category==='SHORT' ? task.private_rubric.test_cases?.map(test=><label className="check-row" key={test.id}><input type="checkbox" checked={grades[task.id]?.passed_tests?.includes(test.id) ?? false} onChange={event=>{ const list=grades[task.id]?.passed_tests ?? []; setGrades(old=>({ ...old,[task.id]:{ passed_tests:event.target.checked ? [...list,test.id] : list.filter(value=>value!==test.id) } })) }} />Passed hidden test {test.id} for {task.public_id}</label>) : <label className="check-row"><input type="checkbox" checked={grades[task.id]?.correct ?? false} onChange={event=>setGrades(old=>({ ...old,[task.id]:{ correct:event.target.checked } }))} />Fully correct: {task.public_id}</label>}</section>)}<label>Private judging reason<textarea required maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} /></label><label>Lab execution evidence references<textarea required value={refs} onChange={event=>setRefs(event.target.value)} /></label><label>Supervisor final-time evidence<textarea required value={timeRefs} onChange={event=>setTimeRefs(event.target.value)} /></label><button>Propose lab judgment</button></fieldset></form></>
}

function ReviewJudgment({ item,disabled,send }: { item:Proposal; disabled:boolean; send:(data:Record<string,unknown>)=>void }) {
  const [reason,setReason]=useState('')
  const [checked,setChecked]=useState(false)
  return <form className="form-stack" onSubmit={event=>{ event.preventDefault(); send({ action:'approve',proposal_id:item.id,reason,evidence_confirmed:checked }) }}><fieldset disabled={disabled}><label>Lab review reason<textarea required maxLength={2000} value={reason} onChange={event=>setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={checked} onChange={event=>setChecked(event.target.checked)} />I independently checked source versions, lab tests, marks and supervisor time.</label><button disabled={!checked}>Approve lab judgment {item.id}</button><button type="button" className="secondary" disabled={!checked || !reason.trim()} onClick={()=>send({ action:'approve',proposal_id:item.id,reason,evidence_confirmed:checked,reject:true })}>Reject lab judgment {item.id}</button></fieldset></form>
}
