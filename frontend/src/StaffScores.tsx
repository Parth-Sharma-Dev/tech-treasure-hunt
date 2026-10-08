import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJson } from './api'
import { StaffActionStatus, StaffNavigation, useStaffAction } from './StaffAction'

type Batch = { id: number; maker_id: number; schema_version: string; reason: string; preview: unknown[]; source_rows: unknown[]; dry_run_errors: { row?: number; team_code?: string; message: string }[]; committed_at: string | null; rejected: boolean }
type Void = { id: number; maker_id: number; question_id: string; reason: string; source_reference: string; reviewed?: boolean }
type Desk = { actor_id: number; can_prepare: boolean; can_review: boolean; round: { id: number; number: number; title: string; state: string; headers: string[]; schema: { version?: string; question_ids?: string[] } }; batches: Batch[]; void_proposals: Void[] }
type Action = ReturnType<typeof useStaffAction>

function Review({ batch, desk, action }: { batch: Batch; desk: Desk; action: Action }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <details className="panel"><summary>Batch {batch.id} · {batch.committed_at ? 'committed' : batch.rejected ? 'rejected' : batch.dry_run_errors.length ? 'invalid' : 'awaiting review'}</summary>
    <p>{batch.reason}</p>{batch.dry_run_errors.length > 0 && <ul>{batch.dry_run_errors.map((error, index) => <li key={index}>Row {error.row ?? error.team_code ?? '—'}: {error.message}</li>)}</ul>}
    <details><summary>Original private source rows</summary><pre className="source-preview">{JSON.stringify(batch.source_rows, null, 2)}</pre></details>
    <details><summary>Calculated preview</summary><pre className="source-preview">{JSON.stringify(batch.preview, null, 2)}</pre></details>
    {!batch.committed_at && !batch.rejected && (batch.maker_id === desk.actor_id ? <p>A different organizer must review this batch.</p> : desk.can_review && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send(`/api/staff/rounds/${desk.round.id}/imports/${batch.id}/commit`, { reason, evidence_confirmed: confirmed }) }}>
      <fieldset disabled={action.disabled}><label>Private review decision<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I checked every original score sheet, team, mark and tie metric.</label><button disabled={!confirmed || batch.dry_run_errors.length > 0}>Commit reviewed batch {batch.id}</button><button type="button" className="secondary" disabled={!reason.trim()} onClick={() => action.send(`/api/staff/rounds/${desk.round.id}/imports/${batch.id}/commit`, { reason, reject: true })}>Reject batch {batch.id}</button></fieldset>
    </form>)}
  </details>
}

function VoidReview({ proposal, desk, action }: { proposal: Void; desk: Desk; action: Action }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <details className="panel"><summary>Question void {proposal.id} · {proposal.question_id}{proposal.reviewed ? ' · reviewed' : ''}</summary><p>{proposal.reason}</p><p>{proposal.source_reference}</p>
    {!proposal.reviewed && (proposal.maker_id === desk.actor_id ? <p>A different organizer must review this question void.</p> : desk.can_review && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send(`/api/staff/rounds/${desk.round.id}/questions/void`, { operation: 'review', proposal_id: proposal.id, reason, evidence_confirmed: confirmed }) }}><fieldset disabled={action.disabled}><label>Private question review<textarea required value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />This faulty question must be removed for every team.</label><button disabled={!confirmed}>Approve global void {proposal.id}</button><button className="secondary" type="button" disabled={!reason.trim()} onClick={() => action.send(`/api/staff/rounds/${desk.round.id}/questions/void`, { operation: 'review', proposal_id: proposal.id, reason, reject: true })}>Reject question void {proposal.id}</button></fieldset></form>)}
  </details>
}

function Intake({ desk, refresh }: { desk: Desk; refresh: () => void }) {
  const action = useStaffAction(`tth:external:${desk.actor_id}:${desk.round.id}`, refresh)
  const [csv, setCsv] = useState('')
  const [reason, setReason] = useState('')
  const [rows, setRows] = useState<Record<string, string>[]>([Object.fromEntries(desk.round.headers.map(field => [field, '']))])
  const [question, setQuestion] = useState('')
  const [source, setSource] = useState('')
  const open = ['ENDED', 'PROVISIONAL'].includes(desk.round.state)
  function preview(data: Record<string, unknown>) {
    action.send(`/api/staff/rounds/${desk.round.id}/imports/validate`, { ...data, reason, schema_version: desk.round.schema.version })
  }
  return <><StaffActionStatus action={action} /><p><a href="/staff/results">Open the reviewed publication desk</a>. A source batch commit does not publish results.</p>
    {!open && <p>Score intake opens after the round ends and closes at final publication.</p>}
    {desk.can_prepare && open && <section className="panel"><h2>Prepare score evidence</h2><p>Schema {desk.round.schema.version ?? 'not configured'}. CSV columns: <code>{desk.round.headers.join(',')}</code></p><p>{desk.round.number === 2 ? 'Enter correct question IDs separated by | (empty for zero credit), and the volunteer-recorded hand-in time in active milliseconds.' : 'Enter one source row per assigned faculty member for each team. All three original criterion sheets are required; each mark is 0–10.'}</p>
      <fieldset disabled={action.disabled}><label>Private intake or correction reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
      <form className="form-stack" onSubmit={event => { event.preventDefault(); preview({ csv }) }}><label>CSV file<input type="file" accept=".csv,text/csv" onChange={event => { const file = event.target.files?.[0]; if (file && file.size <= 1000000) void file.text().then(setCsv); else if (file) setCsv('File exceeds the 1 MB limit.') }} /></label><label>CSV source<textarea maxLength={1000000} required value={csv} onChange={event => setCsv(event.target.value)} /></label><button disabled={!reason.trim()}>Dry-run CSV</button></form>
      <details><summary>Enter source rows manually</summary><form className="form-stack" onSubmit={event => { event.preventDefault(); preview({ rows }) }}>{rows.map((row, index) => <fieldset key={index}><legend>Source row {index + 1}</legend>{desk.round.headers.map(field => <label key={field}>{field.replaceAll('_', ' ')}<input required={field !== 'correct_question_ids'} value={row[field]} onChange={event => setRows(previous => previous.map((item, i) => i === index ? { ...item, [field]: event.target.value } : item))} /></label>)}{rows.length > 1 && <button className="secondary" type="button" onClick={() => setRows(previous => previous.filter((_, i) => i !== index))}>Remove row {index + 1}</button>}</fieldset>)}<button className="secondary" type="button" onClick={() => setRows(previous => [...previous, Object.fromEntries(desk.round.headers.map(field => [field, '']))])}>Add source row</button><button disabled={!reason.trim()}>Dry-run manual rows</button></form></details>
      {desk.round.number === 2 && <details><summary>Propose a faulty question void for every team</summary><form className="form-stack" onSubmit={event => { event.preventDefault(); action.send(`/api/staff/rounds/${desk.round.id}/questions/void`, { operation: 'propose', question_id: question, source_reference: source, reason }) }}><label>Released question<select required value={question} onChange={event => setQuestion(event.target.value)}><option value="">Select a question</option>{desk.round.schema.question_ids?.map(id => <option key={id}>{id}</option>)}</select></label><label>Private faulty-question evidence<input required maxLength={200} value={source} onChange={event => setSource(event.target.value)} /></label><button disabled={!reason.trim()}>Propose global question void</button></form></details>}</fieldset>
    </section>}
    <h2>Source batches</h2>{desk.batches.map(batch => <Review key={batch.id} batch={batch} desk={desk} action={action} />)}
    {desk.void_proposals.map(proposal => <VoidReview key={proposal.id} proposal={proposal} desk={desk} action={action} />)}
  </>
}

export function StaffScores() {
  const [selected, setSelected] = useState(new URLSearchParams(location.search).get('round') ?? '')
  const rounds = useQuery({ queryKey: ['external-rounds'], queryFn: ({ signal }) => getJson<{ rounds: { id: number; number: number; title: string; attempt_no: number }[] }>('/api/staff/results', signal), retry: false })
  const supported = rounds.data?.rounds.filter(round => [2,4].includes(round.number)) ?? []
  const id = Number(selected || supported[0]?.id || 0)
  const desk = useQuery({ queryKey: ['external-desk', id], queryFn: ({ signal }) => getJson<Desk>(`/api/staff/rounds/${id}/imports`, signal), enabled: id > 0, retry: false })
  return <section className="participant-page"><p className="eyebrow">ORGANIZER WORKSPACE</p><h1>External score desk</h1><StaffNavigation />
    {rounds.isError && <><p role="alert">{rounds.error.message}</p><a className="button" href="/admin/login/?next=/staff/scores">Staff sign in</a></>}<label>Round<select value={id || ''} onChange={event => setSelected(event.target.value)}>{supported.map(round => <option key={round.id} value={round.id}>Round {round.number} · {round.title} · attempt {round.attempt_no}</option>)}</select></label><p><button className="secondary" disabled={desk.isFetching} onClick={() => void desk.refetch()}>Refresh score desk</button></p>
    {desk.isPending && id > 0 && <p>Loading score evidence…</p>}{desk.isError && <p role="alert">{desk.error.message}</p>}{desk.data && <Intake key={`${desk.data.actor_id}:${id}`} desk={desk.data} refresh={() => void desk.refetch()} />}
  </section>
}
