import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { RoundClock, pollInterval, stateLabels, type Clock } from './RoundClock'
import { FallbackAccess, TeamProgress } from './Mission'

type Identity = {
  team: { code: string; name: string; member_count: number; status: string; is_demo: boolean }
  session: { active_count: number; max_active: number }
  rounds: { id: number; number: number; title: string; state: string; eligible: boolean; rules: Record<string, unknown> | null; clock: Clock }[]
}
function message(error: Error | null) { return error?.message ?? 'Please try again.' }

export function Login() {
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: () => postJson<{ return_to: string }>('/api/auth/login', {
      team_code: code, password, return_to: new URLSearchParams(location.search).get('next') ?? '/lobby',
    }),
    onSuccess: data => { setPassword(''); location.assign(data.return_to) },
  })
  return <section className="participant-page narrow">
    <p className="eyebrow">YOUR TEAM’S NEXT MOVE</p><h1>Team sign in</h1>
    <p className="muted">Use the credentials supplied by your organizers. Up to four browsers can join your team.</p>
    <form className="panel form-stack" onSubmit={event => { event.preventDefault(); login.mutate() }}>
      <label>Team code<input autoComplete="username" maxLength={24} required value={code} onChange={e => setCode(e.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" maxLength={256} required value={password} onChange={e => setPassword(e.target.value)} /></label>
      {login.isError && <p role="alert" className="error">{message(login.error)}</p>}
      <button disabled={login.isPending}>{login.isPending ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </section>
}

function Practice() {
  const [answer, setAnswer] = useState('')
  const clue = useQuery({ queryKey: ['practice'], queryFn: ({ signal }) => getJson<{ hint: string; symbol: string }>('/api/practice', signal), retry: false })
  const submit = useMutation({ mutationFn: () => postJson<{ outcome: string; keyword: string | null }>('/api/practice/submit', { answer }) })
  return <section className="panel"><p className="eyebrow">TRY THE FLOW</p><h2>Practice clue</h2>
    <p className="muted">Practice awards no points and does not count toward the competition.</p>
    {clue.isPending ? <p>Loading practice…</p> : clue.isError ? <p role="alert">{message(clue.error)}</p> : <>
      <p>{clue.data.symbol} {clue.data.hint}</p>
      <form className="form-stack" onSubmit={event => { event.preventDefault(); submit.mutate() }}>
        <label>Four-digit answer<input inputMode="numeric" pattern="[0-9]{4}" minLength={4} maxLength={4} required value={answer} onChange={e => { setAnswer(e.target.value); submit.reset() }} autoComplete="off" /></label>
        <button disabled={submit.isPending}>{submit.isPending ? 'Checking…' : 'Check practice answer'}</button>
      </form>
      {submit.isError && <p role="alert" className="error">{message(submit.error)}</p>}
      {submit.isSuccess && <p role="status">{submit.data.outcome === 'accepted' ? `Correct! Keyword: ${submit.data.keyword}. No points awarded.` : 'That answer is incorrect. Try again.'}</p>}
    </>}
  </section>
}

export function Lobby({ roundId }: { roundId?: number }) {
  const client = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: async ({ signal }) => {
    const identity = await getJson<Identity>('/api/me', signal)
    return { ...identity, receivedAt: performance.now() }
  }, retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  const logout = useMutation({ mutationFn: () => postJson('/api/auth/logout', {}), onSuccess: () => {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith('tth:')) sessionStorage.removeItem(key)
    client.clear(); location.assign('/')
  } })
  if (me.isPending) return <section className="participant-page"><h1>Opening your lobby…</h1></section>
  if (me.isError) return <section className="participant-page narrow"><h1>{me.error instanceof ApiError && me.error.status === 401 ? 'Sign in to continue' : 'Lobby unavailable'}</h1><p role="alert">{message(me.error)}</p><a className="button" href={`/login?next=${encodeURIComponent(location.pathname)}`}>Team sign in</a></section>
  const { team, session, rounds } = me.data
  const hunt = rounds.find(round => round.number === 1)
  if (roundId !== undefined && (!hunt || hunt.id !== roundId)) return <section className="participant-page"><h1>Round unavailable</h1><p>This round page is not available for your team. Open your dashboard for the current Round 1 attempt.</p><a href="/lobby">Return to round dashboard</a></section>
  const insideHunt = roundId !== undefined && hunt !== undefined
  return <section className="participant-page">
    <div className="lobby-heading"><div><p className="eyebrow">{team.is_demo ? 'LOCAL DEMO · ' : ''}{team.code}{insideHunt ? ' · ROUND 1' : ''}</p><h1>{insideHunt ? hunt.title : team.name}</h1></div><button className="secondary" disabled={logout.isPending} onClick={() => logout.mutate()}>Sign out</button></div>
    {logout.isError && <p role="alert" className="error">{message(logout.error)}</p>}
    <p className="muted">{team.member_count} members · {session.active_count} of {session.max_active} browser sessions active</p>
    {team.status !== 'ACTIVE' && <p role="alert">Your team is {team.status.toLowerCase()}. Contact an organizer for assistance.</p>}
    {insideHunt ? <>
      <p><a href="/lobby">Return to round dashboard</a></p>
      <section className="panel"><h2>Round status</h2><p role="status">{stateLabels[hunt.state] ?? hunt.state}</p><RoundClock clock={hunt.clock} receivedAt={me.data.receivedAt} />
        <p>{hunt.eligible ? 'Your team is eligible' : 'Contact an organizer to review your eligibility.'}</p>
        {hunt.rules && <details><summary>Approved rules</summary><dl>{Object.entries(hunt.rules).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></details>}
      </section>
      {team.status === 'ACTIVE' && <Practice />}
      {hunt.state !== 'DRAFT' && <TeamProgress roundId={hunt.id} />}
      {['ENDED', 'PROVISIONAL', 'FINALIZED'].includes(hunt.state) && <p><a href={`/rounds/${hunt.id}/results`}>View published results: {hunt.title}</a></p>}
      {team.status === 'ACTIVE' && hunt.eligible && hunt.state === 'LIVE' && hunt.clock.play_mode === 'ONLINE' ? <FallbackAccess /> : <p>{hunt.clock.play_mode === 'PAPER' ? 'Online scoring is closed. Follow your assigned paper desk’s instructions.' : 'New mission access and answers are available only during live Round 1 play. Existing mission links still let you check saved outcomes.'}</p>}
    </> : <section className="panel"><p className="eyebrow">THE PATH AHEAD</p><h2>Your rounds</h2><ol className="lobby-rounds">{rounds.map(round => <li key={round.id}><h3>{round.number}. {round.title}</h3><p>{round.number === 5 ? 'Details to be announced' : stateLabels[round.state] ?? round.state}</p>{round.number !== 5 && <><RoundClock clock={round.clock} receivedAt={me.data.receivedAt} /><p className="muted">{round.eligible ? 'Your team is eligible' : 'Eligibility awaits finalized results or organizer review'}</p></>}{round.number === 1 && <a className="button" href={`/rounds/${round.id}`}>Open Round 1</a>}</li>)}</ol></section>}
  </section>
}
