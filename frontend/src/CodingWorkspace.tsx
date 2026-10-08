import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { RoundClock, pollInterval, type Clock } from './RoundClock'
import { dateLabel } from './Results'

type Task = { id: number; public_id: string; category: string; prompt: string; starter_code: string; languages: string[]; points: string; version: string }
type Response = { task_id: number; revision: number; body: string; language: string; source_hash: string; action_id: string }
type Final = { id: number; kind: string; submitted_at: string; manifest_digest: string }
type Workspace = { round_id: number; title: string; team_code: string; session_id: number; clock: Clock; assigned: boolean; station: string | null; eligible: boolean; tasks: Task[]; responses: Response[]; submission: Final | null; can_save: boolean; language_versions: Record<string,string> }
type SaveRequest = { action_id: string; body: string; language: string; expected_revision: number }
type FinalRequest = { action_id: string; expected_revisions: Record<string,number> }
function saved<T>(key: string): T | null { try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as T | null } catch { return null } }
const categories: Record<string,string> = { OUTPUT:'Output prediction', DEBUG:'Debugging', FILL:'Fill the missing code', SHORT:'Short coding task', LOGIC:'Code logic puzzle' }

export function CodingWorkspace() {
  const roundId = Number(location.pathname.split('/')[2])
  const query = useQuery({ queryKey:['coding-workspace',roundId], queryFn:async ({ signal }) => ({ ...await getJson<Workspace>(`/api/rounds/${roundId}/coding/submission`,signal), receivedAt:performance.now() }), retry:false, refetchInterval:pollInterval, refetchIntervalInBackground:false, refetchOnWindowFocus:'always' })
  if (query.isPending) return <section className="participant-page"><h1>Loading coding workspace…</h1></section>
  if (query.isError) return <section className="participant-page"><h1>Coding workspace unavailable</h1><p role="alert">{query.error.message}</p><a href={query.error instanceof ApiError && query.error.status===401 ? `/login?next=${encodeURIComponent(location.pathname)}` : '/lobby'}>{query.error instanceof ApiError && query.error.status===401 ? 'Team sign in' : 'Return to dashboard'}</a></section>
  return <WorkspaceBody key={`${roundId}:${query.data.team_code}`} data={query.data} syncing={query.isFetching} receivedAt={query.data.receivedAt} refresh={() => void query.refetch()} />
}

function WorkspaceBody({ data,syncing,receivedAt,refresh }: { data:Workspace; syncing:boolean; receivedAt:number; refresh:()=>void }) {
  const [busyTasks,setBusyTasks] = useState<Record<number,boolean>>({})
  const [confirmed,setConfirmed] = useState(false)
  const [localFinal,setLocalFinal] = useState<Final | null>(null)
  const key = `tth:codingfinal:${data.team_code}:${data.round_id}`
  const [pending,setPending] = useState<FinalRequest | null>(() => saved(key))
  const final = useMutation({ mutationFn:(request:FinalRequest)=>postJson<Final>(`/api/rounds/${data.round_id}/coding/finalize`,request), onSuccess:result=>{ setLocalFinal(result); sessionStorage.removeItem(key); setPending(null); refresh() }, onError:error=>{ if (error instanceof ApiError && error.status<500) { sessionStorage.removeItem(key); setPending(null); refresh() } } })
  const submitted = data.submission ?? localFinal
  function submit() {
    const request = pending ?? { action_id:crypto.randomUUID(), expected_revisions:Object.fromEntries(data.tasks.map(task=>[String(task.id),data.responses.find(item=>item.task_id===task.id)?.revision ?? 0])) }
    sessionStorage.setItem(key,JSON.stringify(request)); setPending(request); final.mutate(request)
  }
  useEffect(()=>{ if (data.clock.state==='ENDED' && data.assigned && data.eligible && !submitted && data.tasks.length && !pending && !final.isPending && !final.isError) submit() })
  useEffect(()=>{ if (data.submission && pending) { sessionStorage.removeItem(key); setPending(null) } },[data.submission,pending,key])
  const busy = Object.values(busyTasks).some(Boolean)
  return <section className="participant-page"><p className="eyebrow">ROUND 3 · {data.team_code}</p><h1>{data.title}</h1><p><a href={`/rounds/${data.round_id}`}>Round information</a> · <a href="/lobby">Dashboard</a></p><RoundClock clock={data.clock} receivedAt={receivedAt} />
    <section className="panel"><h2>Supervised lab workspace</h2><p>Use the approved lab Python/C tools, then paste or upload your response here for judging. Follow your supervisor’s internet and AI restrictions.</p><p>Browser reference: <strong>{data.session_id}</strong> · Workstation: {data.station ?? 'Awaiting supervisor assignment'}</p>{!data.assigned && !submitted && <p>Ask the supervisor to assign this browser before the task set opens.</p>}{Object.entries(data.language_versions).map(([language,version])=><p key={language}>{language}: {version}</p>)}</section>
    {submitted && <section className="panel"><h2>Final submission recorded</h2><p role="status">Your work is locked. {submitted.kind==='CUTOFF' ? 'The last saved responses were finalized at cutoff.' : submitted.kind==='NO_SUBMISSION' ? 'No saved responses were recorded.' : 'Your final submitted versions are preserved.'}</p><p>Final time: {dateLabel(submitted.submitted_at)}</p><p className="portal-text">Keep this confirmation: {submitted.manifest_digest}</p><a href={`/rounds/${data.round_id}/results`}>Published results</a></section>}
    {data.tasks.map(task=><TaskResponse key={task.id} task={task} response={data.responses.find(item=>item.task_id===task.id)} roundId={data.round_id} teamCode={data.team_code} enabled={data.can_save && !pending && !submitted} locked={!!submitted} refresh={refresh} onBusy={value=>{ if (value) setConfirmed(false); setBusyTasks(old=>old[task.id]===value ? old : { ...old,[task.id]:value }) }} />)}
    {!submitted && data.tasks.length>0 && <section className="panel"><h2>Final submission</h2><p>Final submit permanently locks your saved response versions. At cutoff, the last server-confirmed saved work is finalized automatically. Unsaved local edits do not count.</p><label className="check-row"><input type="checkbox" checked={confirmed} disabled={!data.can_save} onChange={event=>setConfirmed(event.target.checked)} />I checked my saved responses and am ready to lock this work.</label><button disabled={final.isPending || (!pending && (!confirmed || busy || syncing || !data.can_save))} onClick={submit}>{pending ? 'Retry same final submission' : 'Final submit and lock work'}</button>{pending && !final.isPending && <p>The outcome is unconfirmed. Retry the same submission to recover its confirmation.</p>}{final.isError && <p role="alert">{final.error.message}</p>}</section>}
  </section>
}

function TaskResponse({ task,response,roundId,teamCode,enabled,locked,refresh,onBusy }: { task:Task; response?:Response; roundId:number; teamCode:string; enabled:boolean; locked:boolean; refresh:()=>void; onBusy:(value:boolean)=>void }) {
  const key = `tth:coding:${teamCode}:${roundId}:${task.id}`
  const [pending,setPending] = useState<SaveRequest | null>(()=>saved(key))
  const [body,setBody] = useState(pending?.body ?? response?.body ?? task.starter_code ?? '')
  const [language,setLanguage] = useState(pending?.language ?? response?.language ?? task.languages[0])
  const [revision,setRevision] = useState(response?.revision ?? 0)
  const [dirty,setDirty] = useState(!!pending)
  const [fileError,setFileError] = useState('')
  const save = useMutation({ mutationFn:(request:SaveRequest)=>postJson<Response>(`/api/rounds/${roundId}/coding/tasks/${task.id}/response`,request), onSuccess:data=>{ setRevision(data.revision); setDirty(false); setPending(null); sessionStorage.removeItem(key); refresh() }, onError:error=>{ if (error instanceof ApiError && error.status<500) { setPending(null); sessionStorage.removeItem(key); refresh() } } })
  function send() {
    const request = pending ?? { action_id:crypto.randomUUID(), body, language, expected_revision:revision }
    sessionStorage.setItem(key,JSON.stringify(request)); setPending(request); save.mutate(request)
  }
  useEffect(()=>{ onBusy(dirty || !!pending || save.isPending) },[dirty,pending,save.isPending,onBusy])
  useEffect(()=>{ if (enabled && dirty && !pending && !save.isPending && !save.isError) { const timer=setTimeout(send,1200); return ()=>clearTimeout(timer) } })
  useEffect(()=>{ if (response && pending?.action_id===response.action_id) { setRevision(response.revision); setBody(response.body); setLanguage(response.language); setDirty(false); setPending(null); sessionStorage.removeItem(key) } },[response,pending,key])
  useEffect(()=>{ if (!pending && response && ((!dirty && response.revision!==revision) || locked)) { setBody(response.body); setLanguage(response.language); setRevision(response.revision); setDirty(false) } },[response,dirty,pending,revision,locked])
  return <section className="panel"><p className="eyebrow">{categories[task.category]} · {task.points} marks · {task.public_id}</p><h2>{task.public_id}</h2><p className="portal-text">{task.prompt}</p>{task.starter_code && <pre className="coding-source">{task.starter_code}</pre>}<label htmlFor={`coding-language-${task.id}`}>Response language for {task.public_id}</label><select id={`coding-language-${task.id}`} disabled={!enabled || !!pending} value={language} onChange={event=>{ setLanguage(event.target.value); setDirty(true); save.reset() }}>{task.languages.map(item=><option key={item}>{item}</option>)}</select><label htmlFor={`coding-response-${task.id}`}>Response for {task.public_id}</label><textarea id={`coding-response-${task.id}`} className="coding-editor" spellCheck={false} rows={10} disabled={!enabled || !!pending} value={body} onChange={event=>{ setBody(event.target.value); setDirty(true); save.reset() }} />
    <label>Upload response for {task.public_id}<input type="file" accept=".py,.c,.txt" disabled={!enabled || !!pending} onChange={async event=>{ const file=event.target.files?.[0]; if (!file) return; setFileError(''); if (file.size>65536) { setFileError('Choose a source/response file of at most 64 KiB.'); return } setBody(await file.text()); setDirty(true); save.reset() }} /></label>
    <p role="status">{pending ? 'Save outcome unconfirmed.' : dirty ? 'Unsaved local edits.' : revision ? `Saved response version ${revision}.` : 'No response saved yet.'}</p><button disabled={save.isPending || (!pending && (!enabled || (!dirty && revision>0)))} onClick={send}>{pending ? 'Retry same save' : 'Save response'}</button>
    {save.isError && <p role="alert">{save.error.message}</p>}{fileError && <p role="alert">{fileError}</p>}
    <button className="secondary" disabled={!!pending || save.isPending || locked} onClick={()=>{ setBody(response?.body ?? task.starter_code ?? ''); setLanguage(response?.language ?? task.languages[0]); setRevision(response?.revision ?? 0); setDirty(false); save.reset(); refresh() }}>Load confirmed saved response</button>
  </section>
}
