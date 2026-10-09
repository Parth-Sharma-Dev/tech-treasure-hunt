import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJson } from './api'
import { serverTime, type BuzzWindow, type BuzzReceipt } from './Buzzer'
import { StaffActionStatus, StaffNavigation, useStaffAction } from './StaffAction'

type Entry = BuzzReceipt & { team_code: string; team_name: string; team_status: string; position: number }
type Answer = { id: number; team__code: string; verdict: string; answer: string; completed_at: string; priority_evidence: { order: string[]; adjudication_reference: string } }
type Desk = { actor_id?: number; can_record_answers?: boolean; answers?: Answer[]; round_id: number; title: string; state: string; control_version: number; can_control: boolean; window: BuzzWindow | null; entries: Entry[]; first_team_codes: string[]; timestamp_tie: boolean; order_final: boolean; questions: { id: number; stage: number; public_id: string; version: string }[]; history: { window: BuzzWindow; entries: Entry[] }[] }

function HostAnswer({ desk, refresh }: { desk: Desk; refresh: () => void }) {
  const answers = desk.answers ?? []
  const [team, setTeam] = useState('')
  const [verdict, setVerdict] = useState('CORRECT')
  const [answer, setAnswer] = useState('')
  const [reference, setReference] = useState('')
  const [reason, setReason] = useState('')
  const [order, setOrder] = useState(answers[0]?.priority_evidence.order.join(',') ?? '')
  const [adjudication, setAdjudication] = useState(answers[0]?.priority_evidence.adjudication_reference ?? '')
  const action = useStaffAction(`tth:buzzer-answer:${desk.actor_id}:${desk.round_id}:${desk.window?.id}`, refresh)
  useEffect(() => { if (action.mutation.isSuccess) { setAnswer(''); setTeam(''); setVerdict('CORRECT') } }, [action.mutation.isSuccess, action.mutation.data])
  const candidates = answers.some(item => item.verdict === 'CORRECT') ? [] : desk.entries.filter(item => !answers.some(note => note.team__code === item.team_code))
  const selected = candidates.find(item => item.team_code === team) ?? candidates[0]
  const tied = new Set(desk.entries.map(item => item.received_at)).size !== desk.entries.length
  return <section className="panel"><h2>Offline answer evidence</h2><p>Record the observed answer immediately, before opening the next question. The server confirmation time becomes completion evidence; points still require independent source review.</p><StaffActionStatus action={action} />
    {answers.map(item => <p key={item.id}>{item.team__code} · {item.verdict} · host record {item.id} · {serverTime(item.completed_at)}</p>)}
    {desk.can_record_answers && desk.order_final && desk.state === 'LIVE' && selected && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send(`/api/staff/rounds/${desk.round_id}/buzzer/answer`, { window_id: desk.window!.id, press_id: selected.id, verdict, answer: verdict === 'NO_ANSWER' ? '' : answer, source_reference: reference, reason,
      ...(tied ? { buzzer_order: order.split(',').map(code => code.trim()).filter(Boolean), adjudication_reference: adjudication } : {}) }) }}>
      <fieldset disabled={action.disabled}><label>Responding team<select value={selected.team_code} onChange={event => setTeam(event.target.value)}>{candidates.map(item => <option key={item.id} value={item.team_code}>{item.team_code} · queue position {item.position}</option>)}</select></label><label>Observed verdict<select value={verdict} onChange={event => setVerdict(event.target.value)}><option value="CORRECT">Correct</option><option value="WRONG">Wrong</option><option value="NO_ANSWER">No answer / declined</option></select></label><label>Original spoken answer<textarea required={verdict !== 'NO_ANSWER'} maxLength={2000} value={answer} onChange={event => setAnswer(event.target.value)} /></label><label>Private host sheet reference<input required maxLength={200} value={reference} onChange={event => setReference(event.target.value)} /></label><label>Host record reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>{tied && <><label>Equal-time queue order (all buzzing team codes)<input required value={order} onChange={event => setOrder(event.target.value)} /></label><label>Private buzzer adjudication reference<input required maxLength={200} value={adjudication} onChange={event => setAdjudication(event.target.value)} /></label></>}<button>Record observed offline answer</button></fieldset>
    </form>}
    <p><a href={`/staff/scores?round=${desk.round_id}`}>Review Round 5 source scores after the round ends</a></p></section>
}

function Queue({ entries }: { entries: Entry[] }) {
  return entries.length ? <div className="buzzer-queue"><table><caption>Server-recorded buzzer order</caption><thead><tr><th>Position</th><th>Team</th><th>Server time (IST)</th></tr></thead><tbody>{entries.map(item => <tr key={item.id}><td>{item.position}</td><td>{item.team_code}<br /><small>{item.team_name} · {item.team_status}</small></td><td><time dateTime={item.received_at}>{serverTime(item.received_at)}</time><br /><small>{item.received_at} UTC</small></td></tr>)}</tbody></table></div> : <p>No teams have buzzed in this window.</p>
}

function Controls({ desk, refresh }: { desk: Desk; refresh: () => void }) {
  const [question, setQuestion] = useState('')
  const [reason, setReason] = useState('')
  const action = useStaffAction(`tth:buzzer-control:${desk.round_id}`, refresh)
  const current = desk.questions.find(item => String(item.id) === question) ?? desk.questions[0]
  const send = (operation: string) => action.send(`/api/staff/rounds/${desk.round_id}/buzzer/control`, { operation, reason, question_id: current?.id,
    expected_version: desk.control_version, expected_window_version: desk.window?.version ?? 0 })
  return <><StaffActionStatus action={action} />{desk.can_control && <section className="panel"><h2>Question buzzer controls</h2><fieldset disabled={action.disabled} className="form-stack"><label>Frozen question<select value={current?.id ?? ''} onChange={event => setQuestion(event.target.value)}>{desk.questions.map(item => <option key={item.id} value={item.id}>Stage {item.stage} · {item.public_id} · {item.version}</option>)}</select></label><label>Buzzer action reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><div className="button-row"><button disabled={!reason.trim() || !current || desk.state !== 'LIVE' || !!desk.window?.accepting} onClick={() => send('open')}>Open question buzzer</button><button className="secondary" disabled={!reason.trim() || !desk.window || !!desk.window.closed_at} onClick={() => send('close')}>Close buzzer and confirm order</button></div></fieldset><p>Close the window before calling the first team or opening another question. This waits for admitted presses and retains the complete order. Resetting opens a new window; previous presses remain evidence.</p>{!desk.questions.length && <p>Prepare and independently verify the five-stage questions, approve the rules and mark Round 5 READY in Django admin.</p>}</section>}
    <section className="panel"><h2>Current buzzer queue</h2>{desk.window && <p>Stage {desk.window.stage} · {desk.window.question_label} · window {desk.window.version} · {desk.window.accepting ? 'Open' : 'Closed or paused'}</p>}{desk.timestamp_tie ? <p role="alert">Equal server timestamps: {desk.first_team_codes.join(', ')}. Organizer review is required; team code does not break this tie.</p> : desk.first_team_codes.length ? <p role="status">{desk.order_final ? 'First team to answer offline' : 'Current earliest team — close the window to confirm'}: <strong>{desk.first_team_codes[0]}</strong></p> : null}<Queue entries={desk.entries} /></section>
    {desk.window && <HostAnswer key={desk.window.id} desk={desk} refresh={refresh} />}
    <section className="panel"><h2>Retained question windows</h2>{desk.history.map(item => <details key={item.window.id}><summary>Window {item.window.version} · stage {item.window.stage} · {item.window.question_label}</summary><p>Opened {serverTime(item.window.opened_at)}{item.window.closed_at && <> · closed {serverTime(item.window.closed_at)}</>}</p><Queue entries={item.entries} /></details>)}</section>
  </>
}

export function StaffBuzzer() {
  const [selected, setSelected] = useState('')
  const rounds = useQuery({ queryKey: ['staff-buzzer-rounds'], queryFn: ({ signal }) => getJson<{ rounds: { id: number; title: string; attempt_no: number; is_demo: boolean }[] }>('/api/staff/buzzer/rounds', signal), retry: false })
  const id = Number(selected) || rounds.data?.rounds[0]?.id || 0
  const desk = useQuery({ queryKey: ['staff-buzzer-desk', id], queryFn: ({ signal }) => getJson<Desk>(`/api/staff/rounds/${id}/buzzer`, signal), enabled: id > 0, retry: false, refetchInterval: 750, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return <section className="participant-page"><p className="eyebrow">ORGANIZER DESK</p><h1>Round 5 buzzer</h1><StaffNavigation /><p>Server timestamps determine answering priority. Phone/network delays receive no compensation. Questions and answers are presented offline.</p>{rounds.isError ? <><p role="alert">{rounds.error.message}</p><a href="/admin/login/?next=/staff/buzzer">Staff sign in</a></> : <label>Buzzer round<select value={id || ''} onChange={event => setSelected(event.target.value)}>{rounds.data?.rounds.map(item => <option key={item.id} value={item.id}>{item.title} · attempt {item.attempt_no}{item.is_demo ? ' · LOCAL DEMO' : ''}</option>)}</select></label>}{id === 0 && !rounds.isPending && !rounds.isError && <p>No BUZZER Round 5 attempt is configured.</p>}{desk.isError && <p role="alert">{desk.error.message}</p>}{desk.data && <Controls key={id} desk={desk.data} refresh={() => void desk.refetch()} />}</section>
}
