export class ApiError extends Error {
  constructor(public readonly status: number, public readonly requestId: string | null, message = 'The request could not be completed.', public readonly code?: string) {
    super(message)
  }
}

export function staffSignInRequired(error: unknown): boolean {
  return error instanceof ApiError && (error.code === 'staff_mfa_required' || error.code === 'staff_login_required')
}

function responseError(path: string, response: Response, body: { error?: { message?: string; code?: string } } | null): ApiError {
  const error = new ApiError(response.status, response.headers.get('X-Request-ID'), body?.error?.message, body?.error?.code)
  if (path.startsWith('/api/staff/') && staffSignInRequired(error)) window.dispatchEvent(new Event('tth:staff-sign-in-required'))
  return error
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
    throw responseError(path, response, body)
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
  if (!response.ok) throw responseError(path, response, data)
  if (data === null) throw new Error('The response could not be read. Check the outcome before retrying.')
  return data as T
}
