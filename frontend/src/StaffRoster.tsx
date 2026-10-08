import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getJson, postJson } from './api'
import { StaffActionStatus, StaffNavigation, useStaffAction } from './StaffAction'

type Row = { code: string; name: string; leader_name: string; member_count: number; roster_reference: string; status: string }
type Team = Row & { id: number; is_demo: boolean; session_version: number }
type Proposal = { id: number; maker_id: number; reason: string; payload: { is_demo: boolean; rows: Row[] }; reviewed: boolean }
type Desk = { actor_id: number; can_prepare: boolean; can_review: boolean; headers: string[]; teams: Team[]; proposals: Proposal[] }
const blank: Row = { code: '', name: '', leader_name: '', member_count: 3, roster_reference: '', status: 'ACTIVE' }

function ProposalReview({ proposal, desk, action }: { proposal: Proposal; desk: Desk; action: ReturnType<typeof useStaffAction> }) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <details className="panel"><summary>Roster proposal {proposal.id} · {proposal.payload.is_demo ? 'demo' : 'real'} · {proposal.reviewed ? 'reviewed' : 'pending'}</summary><p>{proposal.reason}</p><pre className="source-preview">{JSON.stringify(proposal.payload.rows, null, 2)}</pre>
    {!proposal.reviewed && (proposal.maker_id === desk.actor_id ? <p>A different verifier must review this roster.</p> : desk.can_review && <form className="form-stack" onSubmit={event => { event.preventDefault(); action.send('/api/staff/roster/change', { operation: 'review', proposal_id: proposal.id, reason, evidence_confirmed: confirmed }) }}><fieldset disabled={action.disabled}><label>Private roster review<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><label className="check-row"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />I independently verified the applications, membership and status decision.</label><button disabled={!confirmed}>Approve roster proposal {proposal.id}</button><button type="button" className="secondary" disabled={!reason.trim()} onClick={() => action.send('/api/staff/roster/change', { operation: 'review', proposal_id: proposal.id, reason, reject: true })}>Reject roster proposal {proposal.id}</button></fieldset></form>)}
  </details>
}

function CredentialForm({ team, refresh }: { team: Team; refresh: () => void }) {
  const [password, setPassword] = useState('')
  const [reason, setReason] = useState('')
  const mutation = useMutation({ mutationFn: (data: Record<string, unknown>) => postJson(`/api/staff/teams/${team.id}/credentials`, data), onSuccess: () => { setPassword(''); refresh() } })
  return <details><summary>Issue credentials for {team.code}</summary><form className="form-stack" onSubmit={event => { event.preventDefault(); mutation.mutate({ action_id: crypto.randomUUID(), reason, password, expected_version: team.session_version }) }}><fieldset disabled={mutation.isPending}><label>New team password<input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={password} onChange={event => setPassword(event.target.value)} /></label><label>Private access reason<input required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label><p>This revokes existing sessions. Give the credentials to the team through your approved organizer channel.</p><button>Issue team credentials</button></fieldset></form>{mutation.isError && <><p role="alert">{mutation.error.message}</p><button className="secondary" disabled={mutation.isPending} onClick={() => mutation.mutate(mutation.variables!)}>Retry credential action</button></>}{mutation.isSuccess && <p role="status">Credentials saved. Password cleared from this form.</p>}</details>
}

function Roster({ desk, refresh }: { desk: Desk; refresh: () => void }) {
  const action = useStaffAction(`tth:roster:${desk.actor_id}`, refresh)
  const [isDemo, setIsDemo] = useState(false)
  const [row, setRow] = useState<Row>(blank)
  const [csv, setCsv] = useState('')
  const [reason, setReason] = useState('')
  function propose(data: Record<string, unknown>) { action.send('/api/staff/roster/change', { operation: 'propose', is_demo: isDemo, reason, ...data }) }
  return <><StaffActionStatus action={action} />{desk.can_prepare && <section className="panel"><h2>Prepare a roster change</h2><p>Create and edit identities before the first round is released. Reviewed withdrawal and disqualification remain available later; they revoke team sessions and require qualification review after final publication.</p><fieldset disabled={action.disabled}><label>Cohort<select value={isDemo ? 'demo' : 'real'} onChange={event => setIsDemo(event.target.value === 'demo')}><option value="real">Real contest</option><option value="demo">Local demo</option></select></label><label>Private source or status reason<textarea required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <form className="form-stack" onSubmit={event => { event.preventDefault(); propose({ rows: [row] }) }}><label>Team code<input required maxLength={24} pattern="[A-Z0-9][A-Z0-9_-]*" value={row.code} onChange={event => setRow({ ...row, code: event.target.value })} /></label><label>Team name<input required maxLength={100} value={row.name} onChange={event => setRow({ ...row, name: event.target.value })} /></label><label>Leader name<input required maxLength={100} value={row.leader_name} onChange={event => setRow({ ...row, leader_name: event.target.value })} /></label><label>Member count<select value={row.member_count} onChange={event => setRow({ ...row, member_count: Number(event.target.value) })}><option value={3}>3</option><option value={4}>4</option></select></label><label>Roster evidence reference<input required maxLength={200} value={row.roster_reference} onChange={event => setRow({ ...row, roster_reference: event.target.value })} /></label><label>Team status<select value={row.status} onChange={event => setRow({ ...row, status: event.target.value })}>{['ACTIVE','WITHDRAWN','DISQUALIFIED'].map(status => <option key={status}>{status}</option>)}</select></label><button disabled={!reason.trim()}>Propose team change</button></form>
    <details><summary>Import roster CSV</summary><p>Columns: <code>{desk.headers.join(',')}</code>. The entire file is validated before proposal.</p><form className="form-stack" onSubmit={event => { event.preventDefault(); propose({ csv }) }}><label>Roster CSV<textarea required maxLength={1000000} value={csv} onChange={event => setCsv(event.target.value)} /></label><button disabled={!reason.trim()}>Validate and propose roster CSV</button></form></details></fieldset></section>}
    <section className="panel"><h2>Current teams</h2>{desk.teams.filter(team => team.is_demo === isDemo).map(team => <article className="portal-notice" key={team.id}><h3>{team.code} · {team.name}</h3><p>{team.status.toLowerCase()} · {team.member_count} members · leader {team.leader_name || 'not recorded'}</p>{desk.can_prepare && <><button className="secondary" disabled={action.disabled} onClick={() => setRow({ code: team.code, name: team.name, leader_name: team.leader_name, member_count: team.member_count, roster_reference: team.roster_reference, status: team.status })}>Edit or review status of {team.code}</button>{team.status === 'ACTIVE' && <CredentialForm team={team} refresh={refresh} />}</>}</article>)}</section>
    <h2>Roster review queue</h2>{desk.proposals.map(proposal => <ProposalReview key={proposal.id} proposal={proposal} desk={desk} action={action} />)}
  </>
}

export function StaffRoster() {
  const desk = useQuery({ queryKey: ['roster-desk'], queryFn: ({ signal }) => getJson<Desk>('/api/staff/roster', signal), retry: false })
  return <section className="participant-page"><p className="eyebrow">ORGANIZER WORKSPACE</p><h1>Team roster</h1><StaffNavigation /><p><button className="secondary" disabled={desk.isFetching} onClick={() => void desk.refetch()}>Refresh roster</button></p>{desk.isPending && <p>Loading roster…</p>}{desk.isError && <><p role="alert">{desk.error.message}</p><a className="button" href="/admin/login/?next=/staff/roster">Staff sign in</a></>}{desk.data && <Roster key={desk.data.actor_id} desk={desk.data} refresh={() => void desk.refetch()} />}</section>
}
