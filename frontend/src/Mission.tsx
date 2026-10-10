import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { answerCode } from './AnswerCode'
import { RoundClock, pollInterval, stateLabels, type Clock } from './RoundClock'

type MissionData = {
  answer_format?: string
  team_code: string; token: string; mission_id: string; round_id: number; clock: Clock
  opened: boolean; hint: string | null; symbol: string | null; completed: boolean; voided: boolean
  keyword: string | null; wrong_count: number; cooldown_remaining_ms: number
}
type Decision = { outcome: string; decision_id: string; keyword: string | null; points_awarded: number; receipt?: string; cooldown_remaining_ms: number }
type Pending = { key: string; answer: string }
const outcomes: Record<string, string> = {
  accepted: 'Correct! One point recorded.', incorrect: 'Incorrect answer. This attempt has been recorded.',
  already_completed: 'Your team has already completed this mission. No extra point was added.',
  paused: 'The round is paused. This attempt did not score.', late: 'This attempt reached the database after the deadline and did not score.',
  round_closed: 'The round is closed. This attempt did not score.', cooldown: 'Your mission cooldown is still active. This answer was not evaluated.',
  throttled: 'Your team’s shared answer allowance is temporarily exhausted. This answer was not evaluated.',
  not_opened: 'Open this mission before answering.', ineligible: 'Your team is not eligible to submit in this round.',
  mission_unavailable: 'This mission is unavailable.', paper_mode: 'Online answers are closed for paper play.',
  external_delivery: 'This round is externally judged. Native mission answers do not score.',
}

export function FallbackAccess() {
  const [code, setCode] = useState('')
  const open = useMutation({ mutationFn: () => postJson<{ token: string }>('/api/missions/open', { fallback_code: code }), onSuccess: data => location.assign(`/missions/${data.token}`) })
  return <section className="panel"><h2>Have a fallback code?</h2><p className="muted">Use the separate access code printed beside a mission QR. It is different from the answer code.</p>
    <form className="form-stack" onSubmit={event => { event.preventDefault(); open.mutate() }}><label>Mission fallback code<input maxLength={12} required autoComplete="off" value={code} onChange={event => setCode(event.target.value)} /></label><button disabled={open.isPending}>{open.isPending ? 'Opening…' : 'Open by fallback code'}</button></form>
    {open.isError && <p role="alert" className="error">{open.error.message}</p>}
  </section>
}

export function TeamProgress({ roundId }: { roundId: number }) {
  const progress = useQuery({ queryKey: ['progress', roundId], queryFn: ({ signal }) => getJson<{ score: number; completions: { mission_id: string; keyword: string; voided: boolean }[] }>(`/api/rounds/${roundId}/state`, signal), retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return <section className="panel"><h2>Your team’s progress</h2>
    {progress.isPending ? <p>Loading current score…</p> : progress.isError ? <p role="alert">Current score unavailable. {progress.error.message}</p> : <><p className="score-line">Current score: <strong>{progress.data.score}</strong></p><ul>{progress.data.completions.map(item => <li key={item.mission_id}>{item.mission_id}: {item.keyword}{item.voided ? ' · voided, no current credit' : ''}</li>)}</ul></>}
    <a href="/api/me/receipts" download="treasure-hunt-receipts.json">Save accepted receipts</a>
  </section>
}

function Attempt({ mission }: { mission: MissionData }) {
  const code = answerCode(mission.answer_format)
  const client = useQueryClient()
  const storageKey = `tth:attempt:${mission.team_code}:${mission.token}`
  const [pending, setPending] = useState<Pending | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(storageKey) ?? 'null') as Pending | null } catch { return null }
  })
  const [answer, setAnswer] = useState('')
  const mutation = useMutation({
    mutationFn: async ({ request, recover }: { request: Pending; recover: boolean }) => {
      if (recover) {
        const status = await getJson<{ status: string; decision: Decision | null }>(`/api/rounds/${mission.round_id}/attempts/${request.key}`)
        if (status.status === 'recorded' && status.decision) return status.decision
      }
      return postJson<Decision>(`/api/missions/${mission.token}/submit`, { answer: request.answer }, { 'Idempotency-Key': request.key })
    },
    onSuccess: () => {
      sessionStorage.removeItem(storageKey); setPending(null); setAnswer('')
      void client.invalidateQueries({ queryKey: ['mission', mission.token] })
      void client.invalidateQueries({ queryKey: ['progress', mission.round_id] })
    },
  })
  function submit() {
    const request = pending ?? { key: crypto.randomUUID(), answer }
    const recover = pending !== null
    sessionStorage.setItem(storageKey, JSON.stringify(request)); setPending(request)
    mutation.mutate({ request, recover })
  }
  const available = mission.clock.state === 'LIVE' && mission.clock.play_mode === 'ONLINE' && !mission.completed && !mission.voided && mission.cooldown_remaining_ms === 0
  return <section className="panel"><h2>Your answer</h2>
    {mission.completed && <p>Your team completed this mission. Keyword: <strong>{mission.keyword}</strong>{mission.voided ? ' · mission voided, no current credit' : ''}</p>}
    {mission.cooldown_remaining_ms > 0 && <p>Cooldown: {Math.ceil(mission.cooldown_remaining_ms / 1000)} active seconds remaining at the last server check. Pauses do not consume it.</p>}
    {pending ? <p>Outcome unconfirmed. Check the saved attempt before sending another answer.</p> : !available && !mission.completed && <p>Answers are available during live online play after any cooldown ends.</p>}
    {(available || pending) && <form className="form-stack" onSubmit={event => { event.preventDefault(); submit() }}><label>{mission.answer_format === 'six_ascii_alphanumeric' ? code.label : 'Four-digit mission answer'}<input required pattern={code.pattern} minLength={code.length} maxLength={code.length} inputMode={code.inputMode} autoComplete="off" disabled={!!pending || mutation.isPending} value={pending?.answer ?? answer} onChange={event => { setAnswer(event.target.value); mutation.reset() }} /></label><button disabled={mutation.isPending}>{mutation.isPending ? 'Confirming…' : pending ? 'Check saved attempt' : 'Submit mission answer'}</button></form>}
    {mutation.isError && <p role="alert" className="error">{mutation.error.message} Your attempt ID is preserved for recovery.</p>}
    {mutation.isSuccess && <div role="status"><p>{outcomes[mutation.data.outcome] ?? mutation.data.outcome}</p>{mutation.data.keyword && <p>Earned keyword: {mutation.data.keyword}</p>}</div>}
  </section>
}

export function Mission() {
  const token = location.pathname.slice('/missions/'.length)
  const client = useQueryClient()
  const mission = useQuery({ queryKey: ['mission', token], queryFn: async ({ signal }) => {
    const data = await getJson<MissionData>(`/api/missions/${token}`, signal)
    return { ...data, receivedAt: performance.now() }
  }, retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  const open = useMutation({ mutationFn: () => postJson<MissionData>('/api/missions/open', { token }), onSuccess: () => void client.invalidateQueries({ queryKey: ['mission', token] }) })
  if (mission.isPending) return <section className="participant-page"><h1>Loading mission…</h1></section>
  if (mission.isError) return <section className="participant-page narrow"><h1>{mission.error instanceof ApiError && mission.error.status === 401 ? 'Sign in to continue' : 'Mission unavailable'}</h1><p role="alert">{mission.error.message}</p><a className="button" href={`/login?next=${encodeURIComponent(location.pathname)}`}>Team sign in</a><p><a href="/lobby">Return to lobby</a></p></section>
  const data = mission.data
  return <section className="participant-page"><p className="eyebrow">{data.team_code} · {data.mission_id}</p><h1>Follow the clue.</h1><p>{stateLabels[data.clock.state]}</p><RoundClock clock={data.clock} receivedAt={data.receivedAt} /><a href="/lobby">Return to lobby</a>
    {!data.opened ? <section className="panel"><h2>Open this mission</h2><p>Opening records access for your team. A QR link does not prove physical presence.</p><button disabled={open.isPending || data.clock.state !== 'LIVE' || data.clock.play_mode !== 'ONLINE' || data.voided} onClick={() => open.mutate()}>{open.isPending ? 'Opening…' : 'Open mission'}</button>{open.isError && <p role="alert">{open.error.message}</p>}</section> : <><section className="panel"><h2>Your clue</h2><p>{data.symbol} {data.hint}</p></section><Attempt mission={data} /></>}
    <TeamProgress roundId={data.round_id} />
  </section>
}
