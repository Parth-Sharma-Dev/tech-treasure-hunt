import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ApiError, postJson } from './api'

type Request = { endpoint: string; data: Record<string, unknown> }

export function useStaffAction(key: string, refresh: () => void) {
  const [pending, setPending] = useState<Request | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(key) ?? 'null') as Request | null } catch { return null }
  })
  const mutation = useMutation({ mutationFn: (request: Request) => postJson(request.endpoint, request.data),
    onSuccess: () => { sessionStorage.removeItem(key); setPending(null); refresh() },
    onError: error => { if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
      sessionStorage.removeItem(key); setPending(null); refresh()
    } },
  })
  return { pending, mutation, disabled: !!pending || mutation.isPending,
    send: (endpoint: string, data: Record<string, unknown>) => {
      const request = { endpoint, data: { ...data, action_id: crypto.randomUUID() } }
      sessionStorage.setItem(key, JSON.stringify(request)); setPending(request); mutation.mutate(request)
    },
  }
}

export function StaffActionStatus({ action }: { action: ReturnType<typeof useStaffAction> }) {
  return <>{action.mutation.isError && <p role="alert">{action.mutation.error.message}</p>}
    {action.pending && <section className="panel"><p role="status">This action is awaiting confirmation. Retry the saved request to resolve its outcome.</p><button disabled={action.mutation.isPending} onClick={() => action.mutation.mutate(action.pending!)}>Retry saved action</button></section>}
  </>
}

export function StaffNavigation() {
  return <nav className="staff-navigation" aria-label="Staff workflows"><a href="/staff/rounds">Round controls</a><a href="/staff/results">Results and appeals</a><a href="/staff/coding">Coding lab</a><a href="/staff/scores">External scores</a><a href="/staff/roster">Team roster</a><a href="/admin/competition/facultyprofile/">Faculty profiles</a></nav>
}
