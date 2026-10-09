export class ApiError extends Error {
  constructor(public readonly status: number, public readonly requestId: string | null, message = 'The request could not be completed.', public readonly code?: string) {
    super(message)
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, response.headers.get('X-Request-ID'), body?.error?.message, body?.error?.code)
  }
  return response.json() as Promise<T>
}

export async function postJson<T>(path: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const csrf = await getJson<{ csrf_token: string }>('/api/auth/csrf')
  const response = await fetch(path, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { ...headers, 'Content-Type': 'application/json', 'X-CSRFToken': csrf.csrf_token, Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-ID'), data?.error?.message, data?.error?.code)
  if (data === null) throw new Error('The response could not be read. Check the outcome before retrying.')
  return data as T
}
