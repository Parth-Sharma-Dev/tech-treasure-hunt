import { useState } from 'react'

type Proposal = { id: number; kind: string; maker_id: number; reason: string; payload: Record<string, unknown>; stale: boolean; reviewed: boolean }
export type PaperData = {
  play_mode: string
  paper_window: { official_start: string; official_end: string; assigned_desks: Record<string, string> } | null
  paper_proposals: Proposal[]
  paper_slips: { slip_number: string; team__code: string; mission__public_id: string; outcome: string; evaluated_at: string; active_elapsed_ms: number }[]
}
type Props = { preview: Partial<PaperData> & { state: string; control_version: number; actor_id: number; can_propose: boolean; can_close_incident: boolean; entries: { team_code: string; eligible: boolean }[]; missions?: { id: number; public_id: string; is_void: boolean }[] }; disabled: boolean; send: (data: Record<string, unknown>) => void }
const references = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean)

export function PaperDesk({ preview, disabled, send }: Props) {
  const [reason, setReason] = useState('')
  const [refs, setRefs] = useState('')
  const [clock, setClock] = useState('')
  const [isolation, setIsolation] = useState('')
  const [desks, setDesks] = useState<Record<string, string>>({})
  const [team, setTeam] = useState('')
  const [mission, setMission] = useState('')
  const [number, setNumber] = useState('')
  const [when, setWhen] = useState('')
  const [answer, setAnswer] = useState('')
  const [blocked, setBlocked] = useState(false)
  const window = preview.paper_window
  const missions = (preview.missions ?? []).filter(item => !item.is_void)
  const selectedTeam = team || Object.keys(window?.assigned_desks ?? {})[0] || ''
  const selectedMission = Number(mission || missions[0]?.id || 0)
  const base = { reason, evidence_refs: references(refs), expected_version: preview.control_version }
  return <section className="panel"><h2>Paper fallback and reconciliation</h2>
    <p>Pause online play first. A different verifier checks the clock, assigned desks and isolation of online writers. Paper activation permanently closes online scoring for this attempt.</p>
    {window && <><p>Official paper interval: {new Date(window.official_start).toLocaleString()} to {new Date(window.official_end).toLocaleString()}. Slip times below use this computer’s timezone.</p><p>Use numbered original slips and reconcile each team/mission chronologically. Only one evaluated answer per team/mission per 60 active seconds is allowed.</p></>}
    {preview.can_propose && preview.state === 'FROZEN' && preview.play_mode === 'ONLINE' && <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ ...base, action: 'propose', kind: 'ACTIVATE', assigned_desks: desks, clock_evidence: references(clock), writer_isolation_evidence: references(isolation) }) }}>
      <fieldset disabled={disabled}>{preview.entries.filter(item => item.eligible).map(item => <label key={item.team_code}>Paper desk for {item.team_code}<input required maxLength={100} value={desks[item.team_code] ?? ''} onChange={event => setDesks({ ...desks, [item.team_code]: event.target.value })} /></label>)}
      <label>Official clock evidence<textarea required value={clock} onChange={event => setClock(event.target.value)} /></label>
      <label>Online writer isolation evidence<textarea required value={isolation} onChange={event => setIsolation(event.target.value)} /></label>
      <label>Paper activation reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>Paper activation references<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label><button>Propose paper activation</button></fieldset>
    </form>}
    {window && preview.can_propose && ['LIVE', 'ENDED', 'PROVISIONAL'].includes(preview.state) && missions.length > 0 && <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ ...base, action: 'propose', kind: 'SLIP', team_code: selectedTeam, mission_id: selectedMission, slip_number: number, desk: window.assigned_desks[selectedTeam], evaluated_at: new Date(when).toISOString(), answer, blocked }); setAnswer('') }}>
      <fieldset disabled={disabled}><label>Paper team<select value={selectedTeam} onChange={event => setTeam(event.target.value)}>{Object.keys(window.assigned_desks).map(code => <option key={code}>{code}</option>)}</select></label>
      <label>Paper mission<select value={selectedMission} onChange={event => setMission(event.target.value)}>{missions.map(item => <option key={item.id} value={item.id}>{item.public_id}</option>)}</select></label>
      <label>Numbered slip<input required maxLength={64} value={number} onChange={event => setNumber(event.target.value)} /></label>
      <label>Official slip time<input required type="datetime-local" step="1" value={when} onChange={event => setWhen(event.target.value)} /></label>
      <label>Recorded four-digit answer<input required={!blocked} type="password" inputMode="numeric" pattern="[0-9]{4}" value={answer} onChange={event => setAnswer(event.target.value)} /></label>
      <label className="check-row"><input type="checkbox" checked={blocked} onChange={event => setBlocked(event.target.checked)} />This slip was blocked without evaluation.</label>
      <label>Slip reconciliation reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>Original slip evidence references<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label><button>Propose slip reconciliation</button></fieldset>
    </form>}
    {window && preview.can_propose && preview.state === 'LIVE' && <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ action: 'end', expected_version: preview.control_version, reason }) }}><fieldset disabled={disabled}><label>Reason for ending paper play<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><button>End paper play</button></fieldset></form>}
    {(preview.paper_proposals ?? []).map(item => <details key={item.id}><summary>Paper proposal {item.id} · {item.kind.toLowerCase()} · {item.reviewed ? 'reviewed' : item.stale ? 'stale' : 'awaiting review'}</summary><p>{item.reason}</p><pre className="paper-evidence">{JSON.stringify(item.payload, null, 2)}</pre>{!item.reviewed && item.maker_id !== preview.actor_id && preview.can_close_incident && <ReviewPaper proposal={item} disabled={disabled} send={send} />}</details>)}
    {(preview.paper_slips ?? []).length > 0 && <details><summary>Reconciled numbered slips</summary><ul>{preview.paper_slips?.map(item => <li key={item.slip_number}>{item.slip_number} · {item.team__code} · {item.mission__public_id} · {item.outcome} · {item.active_elapsed_ms / 1000} active seconds</li>)}</ul></details>}
  </section>
}

function ReviewPaper({ proposal, disabled, send }: { proposal: Proposal; disabled: boolean; send: Props['send'] }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ action: 'approve', proposal_id: proposal.id, reason, evidence_confirmed: confirmed }) }}><fieldset disabled={disabled}><label>Paper review reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I independently checked the original paper evidence and official timing.</label><button disabled={!confirmed || proposal.stale}>Approve paper proposal {proposal.id}</button><button type="button" className="secondary" disabled={!confirmed || !reason.trim()} onClick={() => send({ action: 'approve', proposal_id: proposal.id, reason, evidence_confirmed: confirmed, reject: true })}>Reject paper proposal {proposal.id}</button></fieldset></form>
}
