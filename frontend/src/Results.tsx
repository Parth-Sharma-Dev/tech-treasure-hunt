import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { pollInterval } from './RoundClock'

type Entry = { team_code: string; team_name: string; team_status: string; eligible: boolean; score: number; max_score: number; tie_time_ms: number | null; rank: number | null }
type Snapshot = { id: number; revision: number; status: string; entries: Entry[]; qualifier_codes: string[]; cut_count: number; published_at: string; appeal_deadline: string | null; supersedes: number | null; metadata: { publication_reason: string; tie_reason: string; open_material_incidents: number } }
type Preview = { round_id: number; title: string; number: number; attempt_no: number; state: string; control_version: number; evidence_digest: string; entries: Entry[]; cut_count: number; cutoff_tie: string[]; max_score: number; evidence_gaps: string[]; configuration_errors: string[]; finalization_blockers: string[]; appeal_deadline: string | null; actor_id: number; can_propose: boolean; can_approve: boolean; can_close_incident: boolean; proposals: Proposal[]; incidents: Incident[]; history: Snapshot[] }
type Proposal = { id: number; status: string; maker_id: number; maker_name: string; reason: string; stale: boolean; publication_id: number | null; payload: { qualifiers: string[]; preview: { entries: Entry[]; cut_count: number }; tie_order: string[]; tie_evidence: string[]; tie_reason: string } }
type Incident = { id: number; category: string; material: boolean; owner_id: number; affected_scope: { summary: string }; closed_at: string | null; decision: string; evidence_references: string[] }
type Action = { endpoint: 'publish' | 'incidents'; data: Record<string, unknown> }

export function dateLabel(value: string | null) {
  return value ? `${new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))} IST` : 'Not set'
}

function Standings({ entries, ownCode, qualifiers }: { entries: Entry[]; ownCode?: string; qualifiers?: string[] }) {
  return <div className="standings-scroll"><table className="standings"><caption>Round standings</caption><thead><tr><th scope="col">Rank</th><th scope="col">Team</th><th scope="col">Score</th><th scope="col">Last counted solve</th>{qualifiers && <th scope="col">Qualification</th>}</tr></thead><tbody>{entries.map(entry => <tr key={entry.team_code} className={entry.team_code === ownCode ? 'own-team' : ''}>
    <td>{entry.rank ?? '—'}</td><th scope="row">{entry.team_name}<small>{entry.team_code}{entry.team_code === ownCode ? ' · your team' : ''}{!entry.eligible ? ` · ${entry.team_status.toLowerCase()}` : ''}</small></th><td>{entry.score} / {entry.max_score}</td><td>{entry.tie_time_ms === null ? '—' : `${(entry.tie_time_ms / 1000).toFixed(3)} active seconds`}</td>{qualifiers && <td>{qualifiers.includes(entry.team_code) ? 'Qualified' : entry.eligible ? 'Not qualified' : 'Ineligible'}</td>}
  </tr>)}</tbody></table></div>
}

export function PublishedResults() {
  const roundId = Number(location.pathname.split('/')[2])
  const results = useQuery({ queryKey: ['published-results', roundId], queryFn: ({ signal }) => getJson<{ title: string; attempt_no: number; current_attempt: boolean; own_team_code: string; snapshot: Snapshot | null; history: Snapshot[] }>(`/api/rounds/${roundId}/results`, signal), retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  if (results.isPending) return <section className="participant-page"><h1>Loading results…</h1></section>
  if (!results.data || (results.error instanceof ApiError && results.error.status === 401)) return <section className="participant-page narrow"><h1>Results unavailable</h1><p role="alert">{results.error?.message}</p><a className="button" href={`/login?next=${encodeURIComponent(location.pathname)}`}>Team sign in</a></section>
  const { snapshot, history, own_team_code: ownCode } = results.data
  return <section className="participant-page"><p className="eyebrow">{results.data.title} · ATTEMPT {results.data.attempt_no}</p><h1>Round results</h1><p><a href="/lobby">Return to lobby</a></p>
    {results.isError && <p role="alert">Refresh failed. Showing the last confirmed publication.</p>}
    {!snapshot ? <section className="panel"><h2>Results are not published yet</h2><p>Organizers are reviewing the round. Private previews and proposals are not shown here.</p></section> : <section className="panel">
      <h2>{snapshot.status === 'FINAL' ? 'Final results' : 'Provisional results'} · revision {snapshot.revision}</h2>
      <p>Published {dateLabel(snapshot.published_at)}</p>
      {results.data.current_attempt === false && <p>Historical results from an earlier attempt. Current progression follows the latest attempt’s final publication.</p>}
      {snapshot.status === 'PROVISIONAL' ? <><p>Qualification remains pending until final review.</p><p>Appeal deadline: <strong>{dateLabel(snapshot.appeal_deadline)}</strong>. Contact an organizer to register an appeal.</p></> : results.data.current_attempt === false ? <p>This publication records historical qualification; check the latest attempt for current access.</p> : <p role="status">{snapshot.qualifier_codes.includes(ownCode) ? 'Your team qualified for the next round.' : 'Your team did not qualify for the next round.'}</p>}
      {snapshot.metadata.publication_reason && <p>{snapshot.metadata.publication_reason}</p>}
      {!!snapshot.metadata.open_material_incidents && <p>At publication, {snapshot.metadata.open_material_incidents} material issue(s) were pending review.</p>}
      {snapshot.metadata.tie_reason && <p>Reserve-clue decision: {snapshot.metadata.tie_reason}</p>}
      {snapshot.supersedes && <p>This revision supersedes the previous publication. Earlier results remain in the history below.</p>}
      <Standings entries={snapshot.entries} ownCode={ownCode} qualifiers={snapshot.status === 'FINAL' ? snapshot.qualifier_codes : undefined} />
      <p className="muted">Rank uses score, then active time at the last counted solve. Zero-score teams remain tied; team-code display order does not break a competitive tie.</p>
    </section>}
    {history.length > 1 && <details className="panel"><summary>Publication history ({history.length} revisions)</summary>{history.map(item => <details key={item.id}><summary>Revision {item.revision} · {item.status.toLowerCase()} · {dateLabel(item.published_at)}</summary><p>{item.metadata.publication_reason}</p><Standings entries={item.entries} ownCode={ownCode} qualifiers={item.status === 'FINAL' ? item.qualifier_codes : undefined} /></details>)}</details>}
  </section>
}

function useResultAction(preview: Preview, refresh: () => void) {
  const key = `tth:results:${preview.actor_id}:${preview.round_id}`
  const [pending, setPending] = useState<Action | null>(() => { try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as Action | null } catch { return null } })
  const mutation = useMutation({ mutationFn: (request: Action) => postJson(`/api/staff/rounds/${preview.round_id}/${request.endpoint}`, request.data), onSuccess: () => { sessionStorage.removeItem(key); setPending(null); refresh() }, onError: error => {
    if (error instanceof ApiError && error.status >= 400 && error.status < 500) { sessionStorage.removeItem(key); setPending(null); refresh() }
  } })
  return { pending, mutation, disabled: !!pending || mutation.isPending, send: (endpoint: Action['endpoint'], data: Record<string, unknown>) => {
    const request = { endpoint, data: { ...data, action_id: crypto.randomUUID() } }
    sessionStorage.setItem(key, JSON.stringify(request)); setPending(request); mutation.mutate(request)
  } }
}
type ActionController = ReturnType<typeof useResultAction>

function Propose({ preview, action }: { preview: Preview; action: ActionController }) {
  const [status, setStatus] = useState('PROVISIONAL')
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [order, setOrder] = useState('')
  const [refs, setRefs] = useState('')
  const [tieReason, setTieReason] = useState('')
  const finalBlocked = preview.finalization_blockers.some(item => !item.includes('cutoff tie'))
  return <section className="panel"><h2>Propose a publication</h2><p>A second authorized reviewer must approve this proposal. This step does not publish results.</p>
    <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('publish', { action: 'propose', status, expected_version: preview.control_version, evidence_digest: preview.evidence_digest, reason, evidence_confirmed: confirmed, ...(status === 'FINAL' && preview.cutoff_tie.length > 0 ? { tie_order: order.split(',').map(value => value.trim()).filter(Boolean), tie_evidence: refs.split('\n').map(value => value.trim()).filter(Boolean), tie_reason: tieReason } : {}) }) }}>
      <fieldset disabled={action.disabled}><label>Publication type<select value={status} onChange={event => setStatus(event.target.value)}><option value="PROVISIONAL">Provisional results</option><option value="FINAL" disabled={finalBlocked}>Final results</option></select></label>
      <label>Public publication summary<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      {status === 'FINAL' && <><label className="check-row"><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I checked the roster, cut count, exclusions and evidence coverage.</label>{preview.cutoff_tie.length > 0 && <><p>Cutoff tie: {preview.cutoff_tie.join(', ')}. Use the supervised reserve-clue evidence; display order is not a tie-break.</p><label>Reserve-clue order (all tied team codes, comma separated)<input required value={order} onChange={event => setOrder(event.target.value)} /></label><label>Private reserve-clue evidence references (one per line)<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label><label>Public reserve-clue summary<textarea required maxLength={2000} value={tieReason} onChange={event => setTieReason(event.target.value)} /></label></>}</>}
      <button disabled={action.disabled || preview.evidence_gaps.length > 0 || preview.configuration_errors.length > 0 || (status === 'FINAL' && finalBlocked)}>Submit result proposal</button></fieldset>
    </form>
  </section>
}

function Review({ proposal, preview, action }: { proposal: Proposal; preview: Preview; action: ActionController }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <section className="panel"><h3>Proposal {proposal.id} · {proposal.status.toLowerCase()}</h3><p>Prepared by {proposal.maker_name}. {proposal.reason}</p>
    <details><summary>Review the proposed standings and evidence</summary><p>Cut count: {proposal.payload.preview.cut_count}. Final qualifiers proposed: {proposal.payload.qualifiers.join(', ') || 'None'}</p><Standings entries={proposal.payload.preview.entries} /><p>Reserve-clue order: {proposal.payload.tie_order.join(', ') || 'Not required'}</p><p>{proposal.payload.tie_reason}</p><ul>{proposal.payload.tie_evidence.map(reference => <li key={reference}>{reference}</li>)}</ul></details>
    {proposal.publication_id ? <p>Published.</p> : proposal.stale ? <p>Evidence changed. This proposal is stale; a new proposal is required.</p> : proposal.maker_id === preview.actor_id ? <p>A different reviewer must approve this proposal.</p> : preview.can_approve && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('publish', { action: 'approve', proposal_id: proposal.id, reason, evidence_confirmed: confirmed }) }}>
      <fieldset disabled={action.disabled}><label>Public review summary<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I independently checked the standings, roster, cut and supporting evidence.</label><button>Approve and publish proposal {proposal.id}</button></fieldset>
    </form>}
  </section>
}

function IncidentDesk({ preview, action }: { preview: Preview; action: ActionController }) {
  const [reason, setReason] = useState('')
  const [category, setCategory] = useState('APPEAL')
  const [material, setMaterial] = useState(true)
  const [refs, setRefs] = useState('')
  return <section className="panel"><h2>Appeals and incidents</h2><p>Record organizer-received appeals or evidence gaps. Closing an incident does not change a score or override integrity checks.</p>
    {preview.can_propose && preview.state !== 'FINALIZED' && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('incidents', { action: 'open', category, material, reason, evidence_refs: refs.split('\n').map(value => value.trim()).filter(Boolean) }) }}>
      <fieldset disabled={action.disabled}><label>Incident category<select value={category} onChange={event => setCategory(event.target.value)}>{['APPEAL', 'EVIDENCE_GAP', 'SCORING', 'OTHER'].map(value => <option key={value}>{value}</option>)}</select></label><label>Private incident summary<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label>Private incident references (one per line)<textarea value={refs} onChange={event => setRefs(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={material} onChange={event => setMaterial(event.target.checked)} />Material issue — block final results until resolved.</label><button>Record incident</button></fieldset>
    </form>}
    {preview.incidents.map(incident => <details key={incident.id}><summary>Incident {incident.id} · {incident.category} · {incident.closed_at ? 'closed' : 'open'}{incident.material ? ' · material' : ''}</summary><p>{incident.affected_scope.summary}</p><ul>{incident.evidence_references.map((reference, index) => <li key={index}>{reference}</li>)}</ul>{incident.closed_at ? <p>{incident.decision}</p> : preview.can_close_incident && incident.owner_id !== preview.actor_id && preview.state !== 'FINALIZED' && <CloseIncident incident={incident} action={action} />}</details>)}
  </section>
}

function CloseIncident({ incident, action }: { incident: Incident; action: ActionController }) {
  const [reason, setReason] = useState('')
  const [refs, setRefs] = useState('')
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('incidents', { action: 'close', incident_id: incident.id, reason, evidence_refs: refs.split('\n').map(value => value.trim()).filter(Boolean) }) }}><fieldset disabled={action.disabled}><label>Private closure decision<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label>Closure evidence references (one per line)<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label><button>Verify and close incident {incident.id}</button></fieldset></form>
}

function ResultsDesk({ preview, refresh }: { preview: Preview; refresh: () => void }) {
  const action = useResultAction(preview, refresh)
  return <><section className="panel"><h2>Private preview · {preview.title}</h2><p>Round {preview.number} · attempt {preview.attempt_no} · {preview.state.toLowerCase()}. Advancement count: {preview.cut_count ?? 'not configured'}.</p><Standings entries={preview.entries} /><h3>Finalization checks</h3>{preview.finalization_blockers.length ? <ul>{preview.finalization_blockers.map(item => <li key={item}>{item}</li>)}</ul> : <p>Checks passed. Final publication still needs two independent reviews.</p>}{preview.appeal_deadline && <p>Current appeal deadline: {dateLabel(preview.appeal_deadline)}</p>}<button className="secondary" onClick={refresh}>Refresh results review</button></section>
    {action.pending && <section className="panel"><h2>Unconfirmed results action</h2><p>Your original request is saved in this browser session. Retry it to confirm the outcome without applying it twice.</p><button disabled={action.mutation.isPending} onClick={() => action.mutation.mutate(action.pending!)}>Retry same results action</button></section>}
    {action.mutation.isError && <p role="alert" className="error">{action.mutation.error.message}</p>}
    {action.mutation.isSuccess && <p role="status">Results action confirmed. The desk has been refreshed.</p>}
    {preview.can_propose && ['ENDED', 'PROVISIONAL'].includes(preview.state) && <Propose preview={preview} action={action} />}
    <section><h2 className="desk-section-title">Result proposals</h2>{preview.proposals.length ? preview.proposals.map(proposal => <Review key={proposal.id} proposal={proposal} preview={preview} action={action} />) : <p>No publication proposals yet.</p>}</section>
    <IncidentDesk preview={preview} action={action} />
    {preview.history.length > 0 && <section className="panel"><h2>Published revisions</h2><ul>{preview.history.map(snapshot => <li key={snapshot.id}>Revision {snapshot.revision} · {snapshot.status.toLowerCase()} · {dateLabel(snapshot.published_at)}</li>)}</ul><a href={`/rounds/${preview.round_id}/results`}>Team results page (requires team sign-in)</a></section>}
  </>
}

function RoundReview({ roundId }: { roundId: number }) {
  const preview = useQuery({ queryKey: ['result-preview', roundId], queryFn: ({ signal }) => getJson<Preview>(`/api/staff/rounds/${roundId}/results`, signal), retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return preview.isPending ? <p>Loading review…</p> : preview.isError ? <p role="alert">{preview.error.message}</p> : <ResultsDesk key={`${roundId}:${preview.data.actor_id}`} preview={preview.data} refresh={() => void preview.refetch()} />
}

export function StaffResults() {
  const [selected, setSelected] = useState(new URLSearchParams(location.search).get('round') ?? '')
  const rounds = useQuery({ queryKey: ['result-rounds'], queryFn: ({ signal }) => getJson<{ rounds: { id: number; number: number; attempt_no: number; title: string; state: string; is_demo: boolean }[] }>('/api/staff/results', signal), retry: false })
  const selectedId = Number(selected || rounds.data?.rounds.find(round => ['ENDED', 'PROVISIONAL'].includes(round.state))?.id || rounds.data?.rounds[0]?.id || 0)
  return <section className="participant-page"><p className="eyebrow">ORGANIZER DESK</p><h1>Results review</h1><p className="muted">Review Round 1 standings, publish provisional results, record appeals and independently verify final qualifiers.</p><p><a href="/staff/rounds">Round controls</a> · <a href="/admin/">Django admin</a></p>
    {rounds.isPending ? <p>Loading rounds…</p> : rounds.isError ? <section className="panel"><p role="alert">{rounds.error.message}</p><a className="button" href="/admin/login/?next=/staff/results">Staff sign in</a></section> : <><label>Round to review<select value={selectedId} onChange={event => setSelected(event.target.value)}>{rounds.data.rounds.map(round => <option key={round.id} value={round.id}>Round {round.number} · attempt {round.attempt_no} · {round.title}{round.is_demo ? ' · LOCAL DEMO' : ''}</option>)}</select></label>{selectedId > 0 ? <RoundReview key={selectedId} roundId={selectedId} /> : <p>No rounds configured.</p>}</>}
  </section>
}
