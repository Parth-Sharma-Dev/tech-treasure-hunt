import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { RoundClock, pollInterval, stateLabels, type Clock } from './RoundClock'

type StaffRound = Clock & { title: string; number: number; attempt_no: number; is_demo: boolean }
type ActionRequest = { action: string; action_id: string; expected_version: number; reason: string; extension_ms: number }
const actionLabels: Record<string, string> = { open_lobby: 'Open lobby', start: 'Start round', freeze: 'Pause round', resume: 'Resume round', extend: 'Extend active budget', end: 'End round' }
const available: Record<string, string[]> = { READY: ['open_lobby'], LOBBY: ['start'], LIVE: ['freeze', 'extend', 'end'], FROZEN: ['resume', 'extend', 'end'] }

function loadPending(key: string): ActionRequest | null {
  try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as ActionRequest | null } catch { return null }
}

function Controls({ round, receivedAt, refresh }: { round: StaffRound; receivedAt: number; refresh: () => void }) {
  const actions = round.play_mode === 'ONLINE' ? available[round.state] ?? [] : []
  const storageKey = `tth:control:${round.round_id}`
  const [pending, setPending] = useState<ActionRequest | null>(() => loadPending(storageKey))
  const [action, setAction] = useState('')
  const [reason, setReason] = useState('')
  const [minutes, setMinutes] = useState('5')
  const selected = actions.includes(action) ? action : actions[0] ?? ''
  const mutation = useMutation({
    mutationFn: (request: ActionRequest) => postJson<Clock & { deadline_reached: boolean }>(`/api/staff/rounds/${round.round_id}/control`, request),
    onSuccess: () => { sessionStorage.removeItem(storageKey); setPending(null); setReason(''); refresh() },
    onError: error => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        sessionStorage.removeItem(storageKey); setPending(null); refresh()
      }
    },
  })
  function submit() {
    const request = pending ?? { action: selected, action_id: crypto.randomUUID(), expected_version: round.control_version, reason, extension_ms: selected === 'extend' ? Number(minutes) * 60_000 : 0 }
    sessionStorage.setItem(storageKey, JSON.stringify(request)); setPending(request); mutation.mutate(request)
  }
  return <section className="panel">
    <p className="eyebrow">ROUND {round.number} · ATTEMPT {round.attempt_no}{round.is_demo ? ' · LOCAL DEMO' : ''}</p>
    <h2>{round.title}</h2><p role="status">{stateLabels[round.state] ?? round.state}</p>
    <RoundClock clock={round} receivedAt={receivedAt} />
    <p className="muted">Control version {round.control_version}</p>
    {actions.length > 0 || pending ? <form className="form-stack" onSubmit={event => { event.preventDefault(); submit() }}>
      <label>Round action<select disabled={!!pending || mutation.isPending} value={pending?.action ?? selected} onChange={event => { setAction(event.target.value); mutation.reset() }}>
        {[...new Set([...actions, ...(pending ? [pending.action] : [])])].map(value => <option key={value} value={value}>{actionLabels[value]}</option>)}
      </select></label>
      {(pending?.action ?? selected) === 'extend' && <label>Extra active minutes<input type="number" min="1" max="1440" step="1" required disabled={!!pending} value={pending ? pending.extension_ms / 60_000 : minutes} onChange={event => setMinutes(event.target.value)} /></label>}
      <label>Reason<textarea required maxLength={2000} disabled={!!pending} value={pending?.reason ?? reason} onChange={event => setReason(event.target.value)} /></label>
      {(pending?.action ?? selected) === 'end' && <p>Ending closes play permanently for this attempt.</p>}
      {pending && !mutation.isPending && <p>Confirm this action’s outcome by retrying the same request. Its action ID is preserved across reloads.</p>}
      <button disabled={mutation.isPending}>{mutation.isPending ? 'Applying…' : pending ? 'Retry same action' : `Apply: ${actionLabels[selected]}`}</button>
    </form> : <p className="muted">{round.state === 'DRAFT' ? 'Prepare content and approve rules in Django admin before opening the lobby.' : 'No online round controls are available in this state.'}</p>}
    {mutation.isError && <p role="alert" className="error">{mutation.error.message}</p>}
    {mutation.isSuccess && <p role="status">{mutation.data.deadline_reached ? 'The deadline had passed. The round was ended at its cutoff.' : 'Action confirmed. Current state has been refreshed.'}</p>}
  </section>
}

export function StaffRounds() {
  const rounds = useQuery({ queryKey: ['staff-rounds'], queryFn: async ({ signal }) => {
    const data = await getJson<{ rounds: StaffRound[] }>('/api/staff/rounds', signal)
    return { ...data, receivedAt: performance.now() }
  }, retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return <section className="participant-page">
    <p className="eyebrow">ORGANIZER DESK</p><h1>Round controls</h1>
    <p className="muted">Start and pause play, extend the active budget, or close a round. Each confirmed action records your reason.</p>
    <a href="/admin/competition/round/">Content and approval in Django admin</a>
    {rounds.isPending ? <p>Loading rounds…</p> : rounds.isError ? <div className="panel"><p role="alert">{rounds.error.message}</p><a className="button" href="/admin/login/?next=/staff/rounds">Staff sign in</a><button className="secondary" onClick={() => void rounds.refetch()}>Refresh</button></div> : <div className="staff-grid">{rounds.data.rounds.map(round => <Controls key={round.round_id} round={round} receivedAt={rounds.data.receivedAt} refresh={() => void rounds.refetch()} />)}</div>}
  </section>
}
