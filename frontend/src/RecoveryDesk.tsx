import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { postJson } from './api'

type Proposal = { id: number; maker_id: number; reason: string; reviewed: boolean; comparison: { missing: string[]; changed: string[]; additional: string[]; team_changes?: { team_id: number; kind: string; current?: string; checkpoint?: string }[] }; evidence_refs: string[] }
export type RecoveryData = { recovery_proposals: Proposal[] }
type Props = { preview: Partial<RecoveryData> & { round_id: number; number: number; state: string; control_version: number; actor_id: number; can_propose: boolean; can_close_incident: boolean }; disabled: boolean; send: (data: Record<string, unknown>) => void }

const roundExports: Record<number, [string, string][]> = {
  1: [['submissiondecision', 'decision'], ['paperslip', 'paper slip']],
  2: [['importbatch', 'original score batch'], ['scorerevision', 'reviewed score'], ['externalquestionvoid', 'question void']],
  3: [['codingtask', 'private task'], ['codingrevision', 'saved source'], ['codingsubmission', 'final submission'], ['codingjudgmentproposal', 'judging proposal'], ['codingjudgment', 'reviewed judgment'], ['codingworkstation', 'workstation']],
  4: [['importbatch', 'original faculty score batch'], ['scorerevision', 'reviewed score']],
  5: [['buzzerquestion', 'private final question'], ['buzzerwindow', 'buzzer window'], ['buzzerclosure', 'window closure'], ['buzzerpress', 'original press'], ['buzzeranswerevidence', 'host completion'], ['importbatch', 'original final score batch'], ['buzzerscorerevision', 'reviewed question ledger'], ['resultsnapshot', 'winner publication']],
}

export function RecoveryDesk({ preview, disabled, send }: Props) {
  const [bundle, setBundle] = useState('')
  const [fileError, setFileError] = useState('')
  const [reason, setReason] = useState('')
  const [refs, setRefs] = useState('')
  const [tokens, setTokens] = useState('')
  const verify = useMutation({ mutationFn: () => postJson<{ receipts: { decision_id?: string; status: string }[]; coverage_complete: boolean }>(`/api/staff/rounds/${preview.round_id}/receipts/verify`, { receipts: tokens.split('\n').map(value => value.trim()).filter(Boolean) }) })
  return <section className="panel"><h2>Evidence exports and recovery</h2>
    <p>Save private signed evidence separately from database backups. A signed inventory identifies records absent from an older restore; it cannot prove that no records existed after the checkpoint.</p>
    {preview.number === 5 && <p>Round 5 checkpoints bind original press and host completion times, reviewed question ledgers, winner history and the exact Round 1–4 carry-over results. Recover missing earlier rounds first. Reconciliation keeps windows closed and revokes team access; newer carry-over results require investigation.</p>}
    {['ENDED', 'PROVISIONAL', 'FINALIZED'].includes(preview.state) && <p><a href={`/api/staff/rounds/${preview.round_id}/exports/bundle`} download>Download signed round checkpoint</a></p>}
    <details><summary>Download evidence pages</summary><ul>{[...(roundExports[preview.number] ?? []), ['roundphase', 'clock'], ['facultyprofile', 'faculty directory'], ['rosterproposal', 'roster change']].map(([kind, label]) => <li key={kind}><a href={`/api/staff/rounds/${preview.round_id}/exports/${kind}?limit=200`} download>Download {label} evidence page</a></li>)}</ul><p>Each page contains at most 200 records. Follow its next cursor for further pages. Keep private source, tests and faculty score sheets with authorized reviewers.</p></details>
    {preview.can_propose && !['LIVE', 'FROZEN'].includes(preview.state) && <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ action: 'propose', signed_bundle: bundle, expected_version: preview.control_version, reason, evidence_refs: refs.split('\n').map(value => value.trim()).filter(Boolean) }) }}>
      <fieldset disabled={disabled}><label>Signed checkpoint file<input required type="file" accept=".json,application/json" onChange={async event => { setBundle(''); setFileError(''); const file = event.target.files?.[0]; if (!file) return; try { if (file.size > 10_000_000) throw new Error('Checkpoint file is too large.'); const data = JSON.parse(await file.text()); if (typeof data.signed_bundle !== 'string') throw new Error('Choose a signed round checkpoint JSON file.'); setBundle(data.signed_bundle) } catch (error) { setFileError(error instanceof Error ? error.message : 'Could not read the checkpoint file.') } }} /></label>
      <label>Recovery reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <label>Recovery evidence references<textarea required value={refs} onChange={event => setRefs(event.target.value)} /></label>
      <p>Stop all rounds in this cohort before proposing recovery. Recovery revokes shared team sessions and requires independent review. Withdrawn and disqualified teams keep their restrictions.</p>
      <button disabled={!bundle}>Propose checkpoint reconciliation</button></fieldset>
    </form>}
    {fileError && <p role="alert">{fileError}</p>}
    {(preview.recovery_proposals ?? []).map(item => <details key={item.id}><summary>Recovery {item.id} · {item.reviewed ? 'reconciled' : 'awaiting review'}</summary><p>{item.reason}</p><p>Missing: {item.comparison.missing.length} · Changed: {item.comparison.changed.length} · Additional: {item.comparison.additional.length}</p><pre className="paper-evidence">{JSON.stringify(item.comparison, null, 2)}</pre><ul>{item.evidence_refs.map((ref, index) => <li key={index}>{ref}</li>)}</ul>{!item.reviewed && item.maker_id !== preview.actor_id && preview.can_close_incident && <ReviewRecovery item={item} disabled={disabled} send={send} />}</details>)}
    {preview.number === 1 && <details><summary>Verify retained signed receipts</summary><form className="form-stack" onSubmit={event => { event.preventDefault(); verify.mutate() }}><label>Signed receipts (one token per line)<textarea required value={tokens} onChange={event => setTokens(event.target.value)} /></label><button disabled={verify.isPending}>Verify receipts</button></form>{verify.isError && <p role="alert">{verify.error.message}</p>}{verify.data && <><p role="status">{verify.data.coverage_complete ? 'Every supplied receipt matches its stored decision.' : 'Some receipts are invalid, conflicting or missing their stored decision. Record and resolve coverage gaps before finalization.'}</p><ul>{verify.data.receipts.map((item, index) => <li key={index}>{item.decision_id ?? 'Receipt'}: {item.status}</li>)}</ul></>}</details>}
  </section>
}

function ReviewRecovery({ item, disabled, send }: { item: Proposal; disabled: boolean; send: Props['send'] }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <form className="form-stack" onSubmit={event => { event.preventDefault(); send({ action: 'approve', proposal_id: item.id, reason, evidence_confirmed: confirmed }) }}><fieldset disabled={disabled}><label>Recovery review reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I checked the checkpoint, missing intervals, original sources, judging, clock, roster restrictions and session revocations.</label><button disabled={!confirmed}>Approve recovery {item.id}</button></fieldset></form>
}
