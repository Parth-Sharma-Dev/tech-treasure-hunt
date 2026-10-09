import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, getJson } from './api'

export type BuzzWindow = { id: number; version: number; stage: number; question_id: number; question_label: string; accepting: boolean; opened_at: string; closed_at: string | null }
export type BuzzReceipt = { id: string; window_id: number; received_at: string; admitted_at: string }
type Status = { round_id: number; team_code: string; state: string; eligible: boolean; eligibility_reason: string; window: BuzzWindow | null; own_press: BuzzReceipt | null; can_press: boolean }
type Pending = { action_id: string; window_id: number; team_code: string }

export function serverTime(value: string) {
  const base = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(value))
  const fraction = value.match(/\.(\d+)/)?.[1].padEnd(6, '0').slice(0, 6) ?? '000000'
  return `${base}.${fraction} IST`
}

function PressButton({ status, refresh }: { status: Status; refresh: () => void }) {
  const storageKey = `tth:buzzer:${status.round_id}:${status.team_code}`
  const [pending, setPending] = useState<Pending | null>(() => {
    try { const value = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null') as Pending | null
      return value?.team_code === status.team_code && typeof value.action_id === 'string' && Number.isInteger(value.window_id) ? value : null
    } catch { return null }
  })
  const sending = useRef(false)
  const csrf = useQuery({ queryKey: ['buzzer-csrf', status.round_id, status.team_code], queryFn: ({ signal }) => getJson<{ csrf_token: string }>('/api/auth/csrf', signal), staleTime: 30_000, retry: false })
  function clear() { sessionStorage.removeItem(storageKey); setPending(null) }
  const mutation = useMutation({ mutationFn: async ({ request, recover }: { request: Pending; recover: boolean }) => {
    if (recover) {
      try { return await getJson<{ press: BuzzReceipt }>(`/api/rounds/${status.round_id}/buzzer/presses/${request.action_id}`, AbortSignal.timeout(10_000)) }
      catch (error) { if (!(error instanceof ApiError && error.status === 404)) throw error }
    }
    // CSRF is prefetched before enabling the button; buzzing needs one network request.
    if (!csrf.data) throw new Error('Wait for the buzzer connection, then retry the saved press.')
    const response = await fetch(`/api/rounds/${status.round_id}/buzzer/press`, { method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10_000),
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': csrf.data.csrf_token },
      body: JSON.stringify({ action_id: request.action_id, window_id: request.window_id }) })
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-ID'), body?.error?.message, body?.error?.code)
    if (!body?.press) throw new Error('No acknowledgment received. Recover the saved press before continuing.')
    return body as { press: BuzzReceipt }
  }, onSuccess: () => { clear(); refresh() }, onError: error => {
    if (error instanceof ApiError && [400, 403, 409].includes(error.status) && error.code !== 'buzzer_transition') clear()
    if (error instanceof ApiError && error.status === 403) void csrf.refetch()
    refresh()
  }, onSettled: () => { sending.current = false } })
  function send(recover: boolean) {
    if (sending.current || !status.window && !pending) return
    const request = pending ?? { action_id: crypto.randomUUID(), window_id: status.window!.id, team_code: status.team_code }
    sessionStorage.setItem(storageKey, JSON.stringify(request)); setPending(request); sending.current = true
    mutation.mutate({ request, recover })
  }
  const receipt = status.own_press ?? (mutation.data && mutation.data.press.window_id === status.window?.id ? mutation.data.press : null)
  return <>
    <p>Server-recorded order decides who answers first. Keep your phone connected; network or phone delays are not compensated.</p>
    {status.window && <p className="eyebrow">STAGE {status.window.stage} · {status.window.question_label} · WINDOW {status.window.version}</p>}
    <button className="buzzer-button" disabled={!status.can_press || !!receipt || !!pending || mutation.isPending || !csrf.data} onClick={() => send(false)} aria-label="Press Round 5 buzzer">{mutation.isPending ? 'Sending…' : receipt ? 'Recorded' : 'BUZZ'}</button>
    {receipt && <p role="status">Your press is recorded at <time dateTime={receipt.received_at}>{serverTime(receipt.received_at)}</time>. Wait for the host to call your team.</p>}
    {!status.can_press && !status.own_press && <p role="status">{!status.eligible ? status.eligibility_reason : status.state === 'FROZEN' ? 'Round 5 is paused.' : ['ENDED', 'PROVISIONAL', 'FINALIZED'].includes(status.state) ? 'Round 5 has closed.' : 'Wait for the host to open the next question’s buzzer.'}</p>}
    {mutation.isError && <p role="alert">{mutation.error instanceof Error ? mutation.error.message : 'Connection unavailable.'}</p>}
    {csrf.isError && <p role="alert">The buzzer connection is unavailable. <button className="secondary" onClick={() => void csrf.refetch()}>Reconnect</button></p>}
    {pending && <section className="portal-notice"><p role="status">This press is awaiting confirmation. Recover the saved press before buzzing again.</p><button className="secondary" disabled={mutation.isPending || !csrf.data} onClick={() => send(true)}>Recover saved press</button></section>}
    <p>Answer aloud at the venue when the host gives your team the opportunity.</p>
  </>
}

export function Buzzer({ roundId }: { roundId: number }) {
  const query = useQuery({ queryKey: ['buzzer-status', roundId], queryFn: ({ signal }) => getJson<Status>(`/api/rounds/${roundId}/buzzer`, signal), retry: false, refetchInterval: 750, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always' })
  return <section className="panel buzzer-panel"><h2>Round 5 buzzer</h2>{query.isPending ? <p>Connecting to the buzzer…</p> : query.isError ? <><p role="alert">{query.error.message}</p>{query.error instanceof ApiError && query.error.status === 401 && <a href={`/login?next=${encodeURIComponent(location.pathname)}`}>Team sign in</a>}<button className="secondary" onClick={() => void query.refetch()}>Reconnect buzzer</button></> : <PressButton key={query.data.team_code} status={query.data} refresh={() => void query.refetch()} />}</section>
}
