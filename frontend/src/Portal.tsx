import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError, getJson } from './api'
import { FallbackAccess, TeamProgress } from './Mission'
import { RoundClock, pollInterval, stateLabels, type Clock } from './RoundClock'
import { dateLabel } from './Results'

type Notice = { id: number; title: string; body: string; published_at: string }
type Information = { summary?: string; venue?: string; scheduled_start?: string | null; scheduled_end?: string | null; instructions?: string; contacts?: { name: string; role: string; location?: string; channel?: string }[] }
export type PortalRound = { id: number; number: number; title: string; state: string; eligible: boolean; eligibility_reason: string; clock: Clock; information: Information; rules: Record<string, unknown> | null; announcements: Notice[]; earned_keywords: string[]; capabilities: { view_information: boolean; enter_activity: boolean; open_mission: boolean; instructions_visible: boolean; view_results: boolean; coding_supported?: boolean } }
const polling = { retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' as const }
const ruleNames: Record<string, string> = { allowed_tools: 'Allowed tools', movement_policy: 'Team movement', appeal_minutes: 'Appeal window', ranking_policy: 'Ranking', qualification_tie_policy: 'Qualification ties', paper_attempt_policy: 'Paper answers', points_per_mission: 'Points per mission', free_wrong_attempts: 'Wrong answers before cooldown', cooldown_seconds: 'Cooldown steps', team_answer_limit: 'Answers per shared window', team_answer_window_ms: 'Shared answer window' }
function ruleValue(key: string, value: unknown) {
  if (key === 'team_answer_window_ms' && typeof value === 'number') return `${value / 1000} seconds`
  if (key === 'appeal_minutes') return `${value} minutes`
  if (key === 'cooldown_seconds' && Array.isArray(value)) return value.map(item => `${item}s`).join(', ')
  return Array.isArray(value) ? value.join(', ') : String(value).replaceAll('_', ' ')
}

function Notices({ notices }: { notices: Notice[] }) {
  return notices.length ? <section className="panel"><h2>Organizer announcements</h2>{notices.map(item => <article className="portal-notice" key={item.id}><h3>{item.title}</h3><p className="portal-text">{item.body}</p><small className="muted">{dateLabel(item.published_at)}</small></article>)}</section> : null
}

function Schedule({ information }: { information: Information }) {
  return <dl className="portal-schedule"><div><dt>Venue</dt><dd>{information.venue || 'To be announced'}</dd></div><div><dt>Starts</dt><dd>{information.scheduled_start ? dateLabel(information.scheduled_start) : 'To be announced'}</dd></div>{information.scheduled_end && <div><dt>Ends</dt><dd>{dateLabel(information.scheduled_end)}</dd></div>}</dl>
}

export function ParticipantRounds() {
  const query = useQuery({ queryKey: ['portal-rounds'], queryFn: async ({ signal }) => ({ ...await getJson<{ rounds: PortalRound[]; announcements: Notice[] }>('/api/rounds', signal), receivedAt: performance.now() }), ...polling })
  if (query.isPending) return <p>Loading your rounds…</p>
  if (query.isError) return <div className="panel"><p role="alert">{query.error.message}</p><button className="secondary" onClick={() => void query.refetch()}>Refresh rounds</button></div>
  return <><Notices notices={query.data.announcements} /><h2>Your rounds</h2><div className="portal-grid">{query.data.rounds.map(round => <article className={`panel portal-card ${round.capabilities.enter_activity ? 'portal-active' : ''}`} key={round.id}>
    <p className="eyebrow">ROUND {round.number}</p><h3>{round.title}</h3><p>{round.number === 5 ? 'Details to be announced' : stateLabels[round.state] ?? round.state}</p>
    {round.number !== 5 && <><RoundClock clock={round.clock} receivedAt={query.data.receivedAt} /><p className="muted">{round.eligibility_reason}</p>{round.information.summary && <p className="portal-text">{round.information.summary}</p>}<Schedule information={round.information} /><a className="button" href={`/rounds/${round.id}`}>Open Round {round.number}</a>{round.capabilities.view_results && <p><a href={`/rounds/${round.id}/results`}>Published results</a></p>}</>}
  </article>)}</div></>
}

export function ParticipantRound({ roundId, practice }: { roundId: number; practice: ReactNode }) {
  const query = useQuery({ queryKey: ['portal-overview', roundId], queryFn: async ({ signal }) => ({ ...await getJson<PortalRound>(`/api/rounds/${roundId}/overview`, signal), receivedAt: performance.now() }), ...polling })
  if (query.isPending) return <p>Loading round information…</p>
  if (query.isError) return <section className="panel"><h2>Round unavailable</h2><p role="alert">{query.error.message}</p><a href={query.error instanceof ApiError && query.error.status === 401 ? `/login?next=${encodeURIComponent(location.pathname)}` : '/lobby'}>{query.error instanceof ApiError && query.error.status === 401 ? 'Team sign in' : 'Return to round dashboard'}</a></section>
  const round = query.data
  return <><p><a href="/lobby">Return to round dashboard</a></p><Notices notices={round.announcements} />
    <section className="panel"><h2>Round status</h2><p role="status">{stateLabels[round.state] ?? round.state}</p><RoundClock clock={round.clock} receivedAt={round.receivedAt} /><p>{round.eligibility_reason}</p>{round.information.summary && <p className="portal-text">{round.information.summary}</p>}<Schedule information={round.information} /></section>
    {round.information.instructions && <section className="panel"><h2>Participant instructions</h2><p className="portal-text">{round.information.instructions}</p></section>}
    {round.rules && <section className="panel"><details><summary>Approved rules</summary><dl>{Object.entries(round.rules).map(([key, value]) => <div key={key}><dt>{ruleNames[key] ?? key.replaceAll('_', ' ')}</dt><dd>{ruleValue(key, value)}</dd></div>)}</dl></details></section>}
    <section className="panel"><h2>Approved contacts</h2>{round.information.contacts?.length ? <><p>Contact the organizers or faculty listed here for this round.</p><div className="portal-grid">{round.information.contacts.map((contact, index) => <article key={index}><h3>{contact.name}</h3><p>{contact.role}</p>{contact.location && <p>{contact.location}</p>}{contact.channel && <p className="portal-text">{contact.channel}</p>}</article>)}</div></> : <p>Contact details will be announced by the organizers.</p>}</section>
    {round.number === 1 ? <>{practice}{round.state !== 'DRAFT' && <TeamProgress roundId={round.id} />}{round.capabilities.open_mission ? <FallbackAccess /> : <p>{round.clock.play_mode === 'PAPER' ? 'Online scoring is closed. Follow your assigned paper desk’s instructions.' : 'New mission access and answers are available only during live Round 1 play. Existing mission links still let you check saved outcomes.'}</p>}</> : <section className="panel"><h2>Round activity</h2>{round.capabilities.enter_activity ? <p>{round.number === 2 ? 'Follow the announced quiz and puzzle instructions at the venue. Reviewed results will be published here.' : round.number === 3 ? 'Follow your supervisor’s Python and C competition instructions. Submission details will be announced by the supervisor.' : 'Follow the interview schedule and contact only the approved contest faculty listed above.'}</p> : <p>{!round.eligible ? round.eligibility_reason : round.state === 'FROZEN' ? 'Activity is paused. Wait for the organizers to resume it.' : ['ENDED', 'PROVISIONAL', 'FINALIZED'].includes(round.state) ? 'This activity has closed. Published results remain available.' : 'Activity opens when the organizers start this round.'}</p>}</section>}
    {!!round.earned_keywords.length && <section className="panel"><h2>Your Round 1 keywords</h2><p>{round.earned_keywords.join(' · ')}</p><p className="muted">Keep these for Round 2. They do not award bonus points.</p></section>}
    {round.capabilities.coding_supported && round.eligible && round.state!=='DRAFT' && <p><a className="button" href={`/rounds/${round.id}/coding`}>Open coding workspace</a></p>}
    {round.capabilities.view_results && <p><a href={`/rounds/${round.id}/results`}>View published results: {round.title}</a></p>}
  </>
}
