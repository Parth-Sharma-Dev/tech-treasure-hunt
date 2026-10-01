export class ApiError extends Error {
  constructor(public readonly status: number, public readonly requestId: string | null) {
    super('The request could not be completed.')
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
    throw new ApiError(response.status, response.headers.get('X-Request-ID'))
  }
  return response.json() as Promise<T>
}
