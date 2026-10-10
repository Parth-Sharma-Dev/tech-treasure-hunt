import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson, postJson } from './api'
import { pollInterval } from './RoundClock'
import { PaperDesk, type PaperData } from './PaperDesk'
import { RecoveryDesk, type RecoveryData } from './RecoveryDesk'
import { StaffNavigation } from './StaffAction'
import { serverTime } from './Buzzer'
import { answerCode } from './AnswerCode'

type Entry = { team_code: string; team_name: string; team_status: string; eligible: boolean; score: number; max_score: number; tie_time_ms: number | null; rank: number | null; stage_scores?: Record<string,number>; round5_score?: number; carry_over_score?: number; last_correct_at?: string | null; fully_correct_tasks?: number; final_submission_at?: string | null; official_finish_active_ms?: number | null; criterion_averages?: Record<string,string> | null }
type Snapshot = { id: number; revision: number; status: string; entries: Entry[]; qualifier_codes: string[]; cut_count: number; published_at: string; appeal_deadline: string | null; supersedes: number | null; metadata: { publication_reason: string; tie_reason: string; open_material_incidents: number; ranking_kind?: string; winner_codes?: string[]; winner_title?: string } }
type Preview = { ranking_kind?: string; round_id: number; title: string; number: number; attempt_no: number; state: string; control_version: number; evidence_digest: string; entries: Entry[]; cut_count: number; cutoff_tie: string[]; max_score: number; evidence_gaps: string[]; configuration_errors: string[]; finalization_blockers: string[]; appeal_deadline: string | null; actor_id: number; can_propose: boolean; can_approve: boolean; can_close_incident: boolean; proposals: Proposal[]; incidents: Incident[]; history: Snapshot[] }
type Proposal = { id: number; status: string; maker_id: number; maker_name: string; reason: string; stale: boolean; publication_id: number | null; payload: { qualifiers: string[]; preview: { entries: Entry[]; cut_count: number }; tie_order: string[]; tie_evidence: string[]; tie_reason: string } }
type Incident = { id: number; category: string; material: boolean; owner_id: number; affected_scope: { summary: string }; closed_at: string | null; decision: string; evidence_references: string[] }
type Action = { endpoint: 'publish' | 'incidents' | 'resolutions' | 'paper' | 'recovery'; data: Record<string, unknown> }
type Correction = { id: number; mission_id: number; correction_type: string; maker_id: number; reason: string; stale: boolean; resolution_id: number | null; payload: { public_summary: string; evidence_refs: string[] } }
type CorrectionPreview = Preview & Partial<PaperData> & Partial<RecoveryData> & { can_correct?: boolean; missions?: { id: number; public_id: string; is_void: boolean }[]; corrections?: Correction[] }

export function dateLabel(value: string | null) {
  return value ? `${new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))} IST` : 'Not set'
}

function Standings({ entries, ownCode, qualifiers, winners }: { entries: Entry[]; ownCode?: string; qualifiers?: string[]; winners?: string[] }) {
  if (entries.some(entry => entry.stage_scores)) return <div className="standings-scroll"><table className="standings"><caption>Event final standings</caption><thead><tr><th>Rank</th><th>Team</th><th>Carry-over</th>{[1,2,3,4,5].map(stage => <th key={stage}>Stage {stage}</th>)}<th>Round 5</th><th>Total score</th><th>Last correct completion</th>{winners && <th>Award</th>}</tr></thead><tbody>{entries.map(entry => <tr key={entry.team_code} className={entry.team_code === ownCode ? 'own-team' : ''}><td>{entry.rank ?? '—'}</td><th scope="row">{entry.team_name}<small>{entry.team_code}{entry.team_code === ownCode ? ' · your team' : ''}</small></th><td>{entry.carry_over_score}</td>{[1,2,3,4,5].map(stage => <td key={stage}>{entry.stage_scores?.[String(stage)] ?? 0}</td>)}<td>{entry.round5_score}</td><td>{entry.score} / {entry.max_score}</td><td>{entry.last_correct_at ? serverTime(entry.last_correct_at) : 'No correct Round 5 answer'}</td>{winners && <td>{winners.includes(entry.team_code) ? 'Winner' : entry.eligible ? 'Finalist' : 'Ineligible'}</td>}</tr>)}</tbody></table></div>
  const coding = entries.some(entry => entry.fully_correct_tasks !== undefined)
  const faculty = entries.some(entry => entry.criterion_averages != null)
  const finish = entries.some(entry => entry.official_finish_active_ms !== undefined)
  const criteria = ['technical','problem_solving','communication','coordination']
  return <div className="standings-scroll"><table className="standings"><caption>Round standings</caption><thead><tr><th scope="col">Rank</th><th scope="col">Team</th><th scope="col">Score</th>{coding && <th scope="col">Fully correct tasks</th>}{faculty ? criteria.map(field => <th scope="col" key={field}>{field.replaceAll('_',' ')} average</th>) : <th scope="col">{coding ? 'Final submission' : finish ? 'Recorded hand-in' : 'Last counted solve'}</th>}{qualifiers && <th scope="col">{faculty ? 'Green Card' : 'Qualification'}</th>}</tr></thead><tbody>{entries.map(entry => <tr key={entry.team_code} className={entry.team_code === ownCode ? 'own-team' : ''}>
    <td>{entry.rank ?? '—'}</td><th scope="row">{entry.team_name}<small>{entry.team_code}{entry.team_code === ownCode ? ' · your team' : ''}{!entry.eligible ? ` · ${entry.team_status.toLowerCase()}` : ''}</small></th><td>{entry.score} / {entry.max_score}</td>{coding && <td>{entry.fully_correct_tasks ?? 0}</td>}{faculty ? criteria.map(field => <td key={field}>{entry.criterion_averages?.[field] ?? '—'} / 10</td>) : <td>{coding ? entry.final_submission_at?.replace('T',' ').replace('+00:00',' UTC') ?? '—' : entry.tie_time_ms === null ? '—' : `${(entry.tie_time_ms / 1000).toFixed(3)} active seconds`}</td>}{qualifiers && <td>{qualifiers.includes(entry.team_code) ? faculty ? 'Awarded' : 'Qualified' : entry.eligible ? faculty ? 'Not awarded' : 'Not qualified' : 'Ineligible'}</td>}
  </tr>)}</tbody></table></div>
}

export function PublishedResults() {
  const roundId = Number(location.pathname.split('/')[2])
  const results = useQuery({ queryKey: ['published-results', roundId], queryFn: ({ signal }) => getJson<{ title: string; attempt_no: number; current_attempt: boolean; qualification_active?: boolean; award_active?: boolean; own_team_code: string; snapshot: Snapshot | null; history: Snapshot[] }>(`/api/rounds/${roundId}/results`, signal), retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  if (results.isPending) return <section className="participant-page"><h1>Loading results…</h1></section>
  if (!results.data || (results.error instanceof ApiError && results.error.status === 401)) return <section className="participant-page narrow"><h1>Results unavailable</h1><p role="alert">{results.error?.message}</p><a className="button" href={`/login?next=${encodeURIComponent(location.pathname)}`}>Team sign in</a></section>
  const { snapshot, history, own_team_code: ownCode } = results.data
  const finale = snapshot?.metadata.ranking_kind === 'BUZZER_FINAL'
  return <section className="participant-page"><p className="eyebrow">{results.data.title} · ATTEMPT {results.data.attempt_no}</p><h1>Round results</h1><p><a href="/lobby">Return to lobby</a></p>
    {results.isError && <p role="alert">Refresh failed. Showing the last confirmed publication.</p>}
    {!snapshot ? <section className="panel"><h2>Results are not published yet</h2><p>Organizers are reviewing the round. Private previews and proposals are not shown here.</p></section> : <section className="panel">
      <h2>{snapshot.status === 'FINAL' ? 'Final results' : 'Provisional results'} · revision {snapshot.revision}</h2>
      <p>Published {dateLabel(snapshot.published_at)}</p>
      {results.data.current_attempt === false && <p>Historical results from an earlier attempt. Current progression follows the latest attempt’s final publication.</p>}
      {finale ? snapshot.status === 'PROVISIONAL' ? <><p>The event winner remains pending until final review.</p><p>Appeal deadline: <strong>{dateLabel(snapshot.appeal_deadline)}</strong>. Contact an organizer to register an appeal.</p></> : results.data.current_attempt === false ? <p>This is a historical event award; check the latest attempt.</p> : results.data.award_active === false ? <p role="status">The event award is under organizer review. Published history remains available.</p> : <><h3>{snapshot.metadata.winner_title ?? 'The Winner of Tech Treasure Hunt'}</h3><p role="status">{snapshot.metadata.winner_codes?.map(code => snapshot.entries.find(entry => entry.team_code === code)?.team_name ?? code).join(', ')}</p></> : snapshot.status === 'PROVISIONAL' ? <><p>Qualification remains pending until final review.</p><p>Appeal deadline: <strong>{dateLabel(snapshot.appeal_deadline)}</strong>. Contact an organizer to register an appeal.</p></> : results.data.current_attempt === false ? <p>This publication records historical qualification; check the latest attempt for current access.</p> : results.data.qualification_active === false ? <p role="status">Qualification is under organizer review. These published results remain available as evidence.</p> : <p role="status">{snapshot.metadata.ranking_kind === 'FACULTY' ? snapshot.qualifier_codes.includes(ownCode) ? 'Your team received a Green Card and qualified for Round 5. Open Round 5 from your dashboard.' : 'Your team did not receive a Green Card.' : snapshot.qualifier_codes.includes(ownCode) ? 'Your team qualified for the next round.' : 'Your team did not qualify for the next round.'}</p>}
      {snapshot.status === 'FINAL' && snapshot.metadata.ranking_kind === 'FACULTY' && snapshot.qualifier_codes.includes(ownCode) && results.data.current_attempt !== false && results.data.qualification_active !== false && <p><a href="/lobby">Round 5 information and buzzer on your dashboard</a></p>}
      {snapshot.metadata.publication_reason && <p>{snapshot.metadata.publication_reason}</p>}
      {!!snapshot.metadata.open_material_incidents && <p>At publication, {snapshot.metadata.open_material_incidents} material issue(s) were pending review.</p>}
      {snapshot.metadata.tie_reason && <p>Reserve-clue decision: {snapshot.metadata.tie_reason}</p>}
      {snapshot.supersedes && <p>This revision supersedes the previous publication. Earlier results remain in the history below.</p>}
      <Standings entries={snapshot.entries} ownCode={ownCode} qualifiers={snapshot.status === 'FINAL' && !finale ? snapshot.qualifier_codes : undefined} winners={snapshot.status === 'FINAL' && finale ? snapshot.metadata.winner_codes : undefined} />
      <p className="muted">{finale ? 'Total combines final scores from Rounds 1–4 and Round 5. Equal totals use the earlier host-confirmed completion of the last correct Round 5 question. Exact unresolved ties remain under review.' : snapshot.metadata.ranking_kind === 'FACULTY' ? 'Rank uses the weighted panel averages, then technical correctness, then problem-solving. A common reserve question resolves qualification ties.' : snapshot.metadata.ranking_kind === 'EXTERNAL_FINISH' ? 'Rank uses correct answers after reviewed global question voids, then earlier recorded hand-in time. A sealed reserve question resolves qualification ties.' : snapshot.entries.some(entry=>entry.fully_correct_tasks!==undefined) ? 'Rank uses score, then fully correct tasks, then earlier supervisor-confirmed final submission. Display order does not break an exact competitive tie.' : 'Rank uses score, then active time at the last counted solve. Zero-score teams remain tied; team-code display order does not break a competitive tie.'}</p>
    </section>}
    {history.length > 1 && <details className="panel"><summary>Publication history ({history.length} revisions)</summary>{history.map(item => <details key={item.id}><summary>Revision {item.revision} · {item.status.toLowerCase()} · {dateLabel(item.published_at)}</summary><p>{item.metadata.publication_reason}</p><Standings entries={item.entries} ownCode={ownCode} qualifiers={item.status === 'FINAL' && item.metadata.ranking_kind !== 'BUZZER_FINAL' ? item.qualifier_codes : undefined} winners={item.status === 'FINAL' && item.metadata.ranking_kind === 'BUZZER_FINAL' ? item.metadata.winner_codes : undefined} /></details>)}</details>}
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
    <details><summary>Review the proposed standings and evidence</summary><p>{proposal.payload.preview.entries.some(entry => entry.stage_scores) ? 'Winner count' : 'Cut count'}: {proposal.payload.preview.cut_count}. {proposal.payload.preview.entries.some(entry => entry.stage_scores) ? 'Final winner proposed' : 'Final qualifiers proposed'}: {proposal.payload.qualifiers.join(', ') || 'None'}</p><Standings entries={proposal.payload.preview.entries} /><p>Reserve-clue order: {proposal.payload.tie_order.join(', ') || 'Not required'}</p><p>{proposal.payload.tie_reason}</p><ul>{proposal.payload.tie_evidence.map(reference => <li key={reference}>{reference}</li>)}</ul></details>
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

function CorrectionDesk({ preview, action }: { preview: CorrectionPreview; action: ActionController }) {
  const [mission, setMission] = useState('')
  const [kind, setKind] = useState('ALTERNATE')
  const [answer, setAnswer] = useState('')
  const [reason, setReason] = useState('')
  const [summary, setSummary] = useState('')
  const [refs, setRefs] = useState('')
  const missions = (preview.missions ?? []).filter(item => !item.is_void)
  const selected = Number(mission || missions[0]?.id || 0)
  return <section className="panel"><h2>Reviewed score corrections</h2>
    <p>Alternate answers credit only answers that were originally evaluated. Voids remove current credit while preserving submissions and receipts.</p>
    {preview.can_correct && !['DRAFT', 'READY', 'LOBBY'].includes(preview.state) && missions.length > 0 && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('resolutions', { action: 'propose', correction_type: kind, mission_id: selected, expected_version: preview.control_version, reason, public_summary: summary, evidence_refs: refs.split('\n').map(value => value.trim()).filter(Boolean), ...(kind === 'ALTERNATE' ? { answer } : {}) }); setAnswer('') }}>
      <fieldset disabled={action.disabled}><label>Mission to correct<select value={selected} onChange={event => setMission(event.target.value)}>{missions.map(item => <option key={item.id} value={item.id}>{item.public_id}</option>)}</select></label>
      <label>Correction type<select value={kind} onChange={event => setKind(event.target.value)}><option value="ALTERNATE">Accept an alternate answer</option><option value="VOID">Void this mission</option></select></label>
      {kind === 'ALTERNATE' && <label>{preview.answer_format === 'six_ascii_alphanumeric' ? 'Alternate six-character answer' : 'Alternate four-digit answer'}<input type="password" inputMode={answerCode(preview.answer_format).inputMode} pattern={answerCode(preview.answer_format).pattern} required value={answer} onChange={event => setAnswer(event.target.value)} /></label>}
      <label>Private correction reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>Public correction summary<textarea required maxLength={2000} value={summary} onChange={event => setSummary(event.target.value)} /></label>
      <label>Private correction evidence (one reference per line)<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label>
      <button>Propose score correction</button></fieldset>
    </form>}
    {(preview.corrections ?? []).map(item => <details key={item.id}><summary>Correction {item.id} · {item.correction_type.toLowerCase()} · {item.resolution_id ? 'reviewed' : item.stale ? 'stale' : 'awaiting review'}</summary><p>{item.reason}</p><p>{item.payload.public_summary}</p><ul>{item.payload.evidence_refs.map((ref, index) => <li key={index}>{ref}</li>)}</ul>
      {!item.resolution_id && item.maker_id === preview.actor_id && <p>A different verifier must review this correction.</p>}
      {!item.resolution_id && item.maker_id !== preview.actor_id && preview.can_close_incident && <CorrectionReview item={item} preview={preview} action={action} />}
    </details>)}
  </section>
}

function CorrectionReview({ item, preview, action }: { item: Correction; preview: Preview; action: ActionController }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [supersession, setSupersession] = useState(false)
  const [impact, setImpact] = useState(false)
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('resolutions', { action: 'approve', proposal_id: item.id, reason, evidence_confirmed: confirmed, supersession_confirmed: supersession, progression_impact_confirmed: impact }) }}><fieldset disabled={action.disabled}>
    <label>Correction review reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I independently reviewed the correction and supporting evidence.</label>
    {preview.state === 'FINALIZED' && <><label className="check-row"><input type="checkbox" checked={supersession} onChange={event => setSupersession(event.target.checked)} />Supersede final results with provisional results and restart appeals.</label><label className="check-row"><input type="checkbox" checked={impact} onChange={event => setImpact(event.target.checked)} />Suspend dependent play and require review of any later-round qualification impact.</label></>}
    <button disabled={!confirmed || item.stale || (preview.state === 'FINALIZED' && (!supersession || !preview.can_approve))}>Approve correction {item.id}</button>
    <button type="button" className="secondary" disabled={!confirmed || !reason.trim()} onClick={() => action.send('resolutions', { action: 'approve', proposal_id: item.id, reason, evidence_confirmed: confirmed, reject: true })}>Reject correction {item.id}</button>
  </fieldset></form>
}

function ResultsDesk({ preview, refresh }: { preview: CorrectionPreview; refresh: () => void }) {
  const action = useResultAction(preview, refresh)
  return <><section className="panel"><h2>Private preview · {preview.title}</h2><p>Round {preview.number} · attempt {preview.attempt_no} · {preview.state.toLowerCase()}. {preview.number === 5 ? 'Winner count' : 'Advancement count'}: {preview.cut_count ?? 'not configured'}.</p><Standings entries={preview.entries} /><h3>Finalization checks</h3>{preview.finalization_blockers.length ? <ul>{preview.finalization_blockers.map(item => <li key={item}>{item}</li>)}</ul> : <p>Checks passed. Final publication still needs two independent reviews.</p>}{preview.appeal_deadline && <p>Current appeal deadline: {dateLabel(preview.appeal_deadline)}</p>}<button className="secondary" onClick={refresh}>Refresh results review</button></section>
    {action.pending && <section className="panel"><h2>Unconfirmed results action</h2><p>Your original request is saved in this browser session. Retry it to confirm the outcome without applying it twice.</p><button disabled={action.mutation.isPending} onClick={() => action.mutation.mutate(action.pending!)}>Retry same results action</button></section>}
    {action.mutation.isError && <p role="alert" className="error">{action.mutation.error.message}</p>}
    {action.mutation.isSuccess && <p role="status">Results action confirmed. The desk has been refreshed.</p>}
    {preview.can_propose && ['ENDED', 'PROVISIONAL'].includes(preview.state) && <Propose preview={preview} action={action} />}
    <section><h2 className="desk-section-title">Result proposals</h2>{preview.proposals.length ? preview.proposals.map(proposal => <Review key={proposal.id} proposal={proposal} preview={preview} action={action} />) : <p>No publication proposals yet.</p>}</section>
    <IncidentDesk preview={preview} action={action} />
    {preview.number === 1 && <CorrectionDesk preview={preview} action={action} />}
    {preview.number === 1 && <PaperDesk preview={preview} disabled={action.disabled} send={data => action.send('paper', data)} />}
    {[1, 2, 3, 4, 5].includes(preview.number) && <RecoveryDesk preview={preview} disabled={action.disabled} send={data => action.send('recovery', data)} />}
    {preview.history.length > 0 && <section className="panel"><h2>Published revisions</h2><ul>{preview.history.map(snapshot => <li key={snapshot.id}>Revision {snapshot.revision} · {snapshot.status.toLowerCase()} · {dateLabel(snapshot.published_at)}</li>)}</ul><a href={`/rounds/${preview.round_id}/results`}>Team results page (requires team sign-in)</a></section>}
  </>
}

function RoundReview({ roundId }: { roundId: number }) {
  const preview = useQuery({ queryKey: ['result-preview', roundId], queryFn: ({ signal }) => getJson<CorrectionPreview>(`/api/staff/rounds/${roundId}/results`, signal), retry: false, refetchInterval: pollInterval, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return preview.isPending ? <p>Loading review…</p> : preview.isError ? <p role="alert">{preview.error.message}</p> : <ResultsDesk key={`${roundId}:${preview.data.actor_id}`} preview={preview.data} refresh={() => void preview.refetch()} />
}

export function StaffResults() {
  const [selected, setSelected] = useState(new URLSearchParams(location.search).get('round') ?? '')
  const rounds = useQuery({ queryKey: ['result-rounds'], queryFn: ({ signal }) => getJson<{ rounds: { id: number; number: number; attempt_no: number; title: string; state: string; is_demo: boolean }[] }>('/api/staff/results', signal), retry: false })
  const selectedId = Number(selected || rounds.data?.rounds.find(round => ['ENDED', 'PROVISIONAL'].includes(round.state))?.id || rounds.data?.rounds[0]?.id || 0)
  return <section className="participant-page"><p className="eyebrow">ORGANIZER DESK</p><h1>Results review</h1><StaffNavigation /><p className="muted">Review round standings, publish provisional results, record appeals and independently verify final qualifiers.</p><p><a href="/admin/">Django admin</a></p>
    {rounds.isPending ? <p>Loading rounds…</p> : rounds.isError ? <section className="panel"><p role="alert">{rounds.error.message}</p><a className="button" href="/admin/login/?next=/staff/results">Staff sign in</a></section> : <><label>Round to review<select value={selectedId} onChange={event => setSelected(event.target.value)}>{rounds.data.rounds.map(round => <option key={round.id} value={round.id}>Round {round.number} · attempt {round.attempt_no} · {round.title}{round.is_demo ? ' · LOCAL DEMO' : ''}</option>)}</select></label>{selectedId > 0 ? <RoundReview key={selectedId} roundId={selectedId} /> : <p>No rounds configured.</p>}</>}
  </section>
}
