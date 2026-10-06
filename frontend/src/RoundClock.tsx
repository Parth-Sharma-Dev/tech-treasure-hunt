import { useEffect, useState } from 'react'

export type Clock = {
  round_id: number
  state: string
  play_mode: string
  control_version: number
  server_time: string
  remaining_ms: number
  active_budget_ms: number
  active_elapsed_ms: number
  deadline_at: string | null
}

export const stateLabels: Record<string, string> = {
  DRAFT: 'Awaiting organizer approval', READY: 'Ready for the lobby',
  LOBBY: 'Waiting for the start', LIVE: 'Round live', FROZEN: 'Round paused',
  ENDED: 'Round ended', PROVISIONAL: 'Provisional results', FINALIZED: 'Results finalized',
}

export const pollInterval = () => 13_000 + Math.floor(Math.random() * 4_000)

export function RoundClock({ clock, receivedAt }: { clock: Clock; receivedAt: number }) {
  const [tick, setTick] = useState(() => performance.now())
  useEffect(() => {
    const interval = window.setInterval(() => setTick(performance.now()), 500)
    return () => window.clearInterval(interval)
  }, [])
  if (!['LIVE', 'FROZEN', 'ENDED'].includes(clock.state)) return null
  // Wall-clock changes on a phone must not affect the countdown. The server still
  // decides admission; this monotonic estimate is only a display between reads.
  const remaining = Math.max(0, clock.remaining_ms - (clock.state === 'LIVE' ? Math.max(0, tick - receivedAt) : 0))
  const seconds = Math.ceil(remaining / 1000)
  const time = `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
  return <div className="round-clock">
    <output aria-label="Round time remaining" aria-live="off" className="clock-time">{time}</output>
    <p className="muted">{clock.state === 'FROZEN' ? 'Paused · active time is stopped' : clock.state === 'ENDED' ? 'Play has ended' : remaining === 0 ? 'Time elapsed · awaiting server confirmation' : 'Active time remaining'}</p>
    {clock.state === 'LIVE' && clock.deadline_at && <small className="muted">Deadline: {new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(clock.deadline_at))} IST</small>}
  </div>
}
