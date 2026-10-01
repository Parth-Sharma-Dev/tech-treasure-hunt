export class ApiError extends Error {
  constructor(public readonly status: number, public readonly requestId: string | null, message = 'The request could not be completed.') {
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
    throw new ApiError(response.status, response.headers.get('X-Request-ID'), body?.error?.message)
  }
  return response.json() as Promise<T>
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const csrf = await getJson<{ csrf_token: string }>('/api/auth/csrf')
  const response = await fetch(path, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf.csrf_token, Accept: 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new ApiError(response.status, response.headers.get('X-Request-ID'), data?.error?.message)
  return data as T
}
